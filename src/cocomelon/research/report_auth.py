from __future__ import annotations

import hashlib
import json
import sqlite3
from decimal import Decimal, InvalidOperation

from cocomelon.research.contracts import ResearchCandidateState
from cocomelon.research.metrics import compute_checkpoint_risk_metrics
from cocomelon.research.provenance import load_sealed_admitted_batch_provenance
from cocomelon.research.sequential import (
    DEFAULT_SEQUENTIAL_RESEARCH_POLICY,
    evaluate_checkpoint,
)

DAY_MS = 86_400_000


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _decimal_string(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise ValueError(f"stored research observation {field} is invalid")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"stored research observation {field} is invalid") from exc
    if not result.is_finite():
        raise ValueError(f"stored research observation {field} is invalid")
    return result


def _int_value(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"stored research observation {field} is invalid")
    return value


def _load_observations(
    connection: sqlite3.Connection,
    *,
    candidate_id: str,
) -> tuple[dict[str, object], ...]:
    table = connection.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = 'research_trade_observations'
        """
    ).fetchone()
    if table is None:
        return ()
    rows = connection.execute(
        """
        SELECT payload_json
        FROM research_trade_observations
        WHERE candidate_id = ?
        ORDER BY closed_at_ms, trade_id
        """,
        (candidate_id,),
    ).fetchall()
    observations: list[dict[str, object]] = []
    for row in rows:
        payload = json.loads(str(row["payload_json"]))
        if not isinstance(payload, dict) or not all(isinstance(key, str) for key in payload):
            raise ValueError("stored research observation is invalid")
        observations.append(payload)
    return tuple(observations)


def assert_checkpoint_report_backed_by_observations(
    connection: sqlite3.Connection,
    *,
    candidate_id: str,
    report_id: str,
    payload: dict[str, object],
    state: ResearchCandidateState,
) -> None:
    unsigned_payload = dict(payload)
    embedded_report_id = unsigned_payload.pop("report_id", None)
    authenticated_report_id = hashlib.sha256(
        _canonical_json(unsigned_payload).encode("utf-8")
    ).hexdigest()
    if report_id != authenticated_report_id:
        raise ValueError("checkpoint report id does not authenticate payload")
    if embedded_report_id is not None and embedded_report_id != report_id:
        raise ValueError("checkpoint report id does not authenticate payload")

    observations = _load_observations(connection, candidate_id=candidate_id)
    net_r_values = tuple(
        _decimal_string(observation.get("net_r"), "net_r") for observation in observations
    )
    closed_days = {
        _int_value(observation.get("closed_at_ms"), "closed_at_ms") // DAY_MS
        for observation in observations
    }
    risk_metrics = compute_checkpoint_risk_metrics(observations)
    batch_ids, source_ids = load_sealed_admitted_batch_provenance(
        connection,
        candidate_id=candidate_id,
    )

    reason_codes_value = payload.get("reason_codes", [])
    if not isinstance(reason_codes_value, list) or not all(
        isinstance(reason, str) for reason in reason_codes_value
    ):
        raise ValueError("checkpoint report reason_codes is invalid")
    reason_codes = tuple(reason_codes_value)
    operational_failure = "operational_failure" in reason_codes
    hard_risk_failure = "hard_risk_failure" in reason_codes
    checkpoint = evaluate_checkpoint(
        net_r_values=net_r_values,
        closed_trade_days=len(closed_days),
        operational_failure=operational_failure,
        hard_risk_failure=hard_risk_failure,
        policy=DEFAULT_SEQUENTIAL_RESEARCH_POLICY,
    )

    expected = {
        "candidate_state": checkpoint.candidate_state.value,
        "checkpoint_state": checkpoint.checkpoint_state.value,
        "closed_trade_count": checkpoint.trade_count,
        "closed_trade_days": checkpoint.closed_trade_days,
        "posterior_probability_positive": (
            None
            if checkpoint.posterior_probability_positive is None
            else str(checkpoint.posterior_probability_positive)
        ),
        "policy_digest": checkpoint.policy_digest,
        "reason_codes": list(checkpoint.reason_codes),
        "realized_closed_trade_max_drawdown_fraction": (
            None
            if risk_metrics.realized_closed_trade_max_drawdown_fraction is None
            else str(risk_metrics.realized_closed_trade_max_drawdown_fraction)
        ),
        "max_realized_planned_risk_utilization": (
            None
            if risk_metrics.max_realized_planned_risk_utilization is None
            else str(risk_metrics.max_realized_planned_risk_utilization)
        ),
        "batch_ids": list(batch_ids),
        "source_ids": list(source_ids),
    }
    for field, expected_value in expected.items():
        if payload.get(field) != expected_value:
            raise ValueError(
                f"checkpoint report is not reproducible from immutable observations/provenance: {field}"
            )
    if checkpoint.candidate_state is not state:
        raise ValueError(
            "checkpoint report is not reproducible from immutable observations/provenance: state"
        )
