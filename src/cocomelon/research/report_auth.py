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
ZERO = Decimal("0")


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


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def _load_observations(
    connection: sqlite3.Connection,
    *,
    candidate_id: str,
) -> tuple[dict[str, object], ...]:
    if not _table_exists(connection, "research_trade_observations"):
        return ()
    total_row = connection.execute(
        "SELECT COUNT(*) FROM research_trade_observations WHERE candidate_id = ?",
        (candidate_id,),
    ).fetchone()
    total = 0 if total_row is None else int(total_row[0])
    if not _table_exists(connection, "research_batch_attestations"):
        if total:
            raise ValueError(
                "checkpoint report is not reproducible from immutable observations/provenance"
            )
        return ()
    rows = connection.execute(
        """
        SELECT o.payload_json
        FROM research_trade_observations AS o
        JOIN research_batches AS b
          ON b.batch_id = o.batch_id AND b.candidate_id = o.candidate_id
        JOIN research_batch_attestations AS a
          ON a.batch_id = o.batch_id AND a.candidate_id = o.candidate_id
        WHERE o.candidate_id = ? AND b.status = 'admitted'
        ORDER BY o.closed_at_ms, o.trade_id
        """,
        (candidate_id,),
    ).fetchall()
    if total != len(rows):
        raise ValueError(
            "checkpoint report is not reproducible from immutable observations/provenance"
        )
    observations: list[dict[str, object]] = []
    for row in rows:
        payload = json.loads(str(row["payload_json"]))
        if not isinstance(payload, dict) or not all(isinstance(key, str) for key in payload):
            raise ValueError("stored research observation is invalid")
        observations.append(payload)
    return tuple(observations)


def _configured_risk_per_trade(
    connection: sqlite3.Connection,
    *,
    candidate_id: str,
    required: bool,
) -> Decimal | None:
    row = connection.execute(
        "SELECT risk_config_json FROM research_candidates WHERE candidate_id = ?",
        (candidate_id,),
    ).fetchone()
    if row is None:
        raise ValueError("checkpoint candidate is missing")
    try:
        raw = json.loads(str(row["risk_config_json"]))
    except json.JSONDecodeError as exc:
        raise ValueError("checkpoint candidate risk config is invalid") from exc
    value = raw.get("risk_per_trade") if isinstance(raw, dict) else None
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise ValueError("checkpoint candidate risk_per_trade is invalid")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("checkpoint candidate risk_per_trade is invalid") from exc
    if not result.is_finite() or result <= ZERO:
        raise ValueError("checkpoint candidate risk_per_trade is invalid")
    return result


def _attested_health(
    connection: sqlite3.Connection,
    *,
    candidate_id: str,
) -> tuple[bool, bool]:
    if not _table_exists(connection, "research_batch_attestations"):
        return False, False
    rows = connection.execute(
        """
        SELECT a.operational_failure, a.hard_risk_failure
        FROM research_batch_attestations AS a
        JOIN research_batches AS b ON b.batch_id = a.batch_id
        WHERE a.candidate_id = ? AND b.status = 'admitted'
        """,
        (candidate_id,),
    ).fetchall()
    return (
        any(bool(int(row["operational_failure"])) for row in rows),
        any(bool(int(row["hard_risk_failure"])) for row in rows),
    )


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
    configured_risk = _configured_risk_per_trade(
        connection,
        candidate_id=candidate_id,
        required=bool(observations),
    )
    risk_metrics = compute_checkpoint_risk_metrics(
        observations,
        configured_risk_per_trade=configured_risk,
    )
    batch_ids, source_ids = load_sealed_admitted_batch_provenance(
        connection,
        candidate_id=candidate_id,
    )
    operational_failure, hard_risk_failure = _attested_health(
        connection,
        candidate_id=candidate_id,
    )

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
            message = (
                "checkpoint report is not reproducible from immutable "
                f"observations/provenance: {field}"
            )
            raise ValueError(message)
    if checkpoint.candidate_state is not state:
        raise ValueError(
            "checkpoint report is not reproducible from immutable observations/provenance: state"
        )
