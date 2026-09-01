from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from decimal import Decimal, InvalidOperation, localcontext

from cocomelon.domain.strategy import Direction
from cocomelon.evaluation.metrics import AUTHORITATIVE_CONTEXT
from cocomelon.research.contracts import ResearchCandidateState
from cocomelon.research.metrics import compute_checkpoint_risk_metrics
from cocomelon.research.provenance import load_sealed_admitted_batch_provenance
from cocomelon.research.sequential import (
    DEFAULT_SEQUENTIAL_RESEARCH_POLICY,
    evaluate_checkpoint,
)

DAY_MS = 86_400_000
ZERO = Decimal("0")
TOUCHED_NON_PROMOTIONAL_LABEL = "TOUCHED / NON-PROMOTIONAL"


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


def _string_value(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"stored research observation {field} is invalid")
    return value


def _reason_codes(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise ValueError("stored research observation reason_codes is invalid")
    return tuple(value)


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def _validate_declared_batch_ids(payload: dict[str, object]) -> tuple[str, ...]:
    raw = payload.get("batch_ids")
    if not isinstance(raw, list) or not raw:
        raise ValueError("checkpoint report requires attested batch provenance")
    if not all(isinstance(item, str) and item.strip() for item in raw):
        raise ValueError("checkpoint report batch_ids are invalid")
    batch_ids = tuple(raw)
    if len(set(batch_ids)) != len(batch_ids):
        raise ValueError("checkpoint report batch_ids are not unique")
    return batch_ids


def _validated_scoped_provenance(
    connection: sqlite3.Connection,
    *,
    candidate_id: str,
    batch_ids: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if not batch_ids:
        raise ValueError("checkpoint report requires attested batch provenance")
    if not _table_exists(connection, "research_batch_seals") or not _table_exists(
        connection, "research_batch_attestations"
    ):
        raise ValueError("checkpoint report requires attested batch provenance")
    placeholders = ", ".join("?" for _ in batch_ids)
    rows = connection.execute(
        f"""
        SELECT b.batch_id, b.source_id
        FROM research_batches AS b
        INNER JOIN research_batch_seals AS s
          ON s.batch_id = b.batch_id AND s.candidate_id = b.candidate_id
        INNER JOIN research_batch_attestations AS a
          ON a.batch_id = b.batch_id AND a.candidate_id = b.candidate_id
        WHERE b.candidate_id = ?
          AND b.status = 'admitted'
          AND b.batch_id IN ({placeholders})
        ORDER BY b.batch_id, b.source_id
        """,
        (candidate_id, *batch_ids),
    ).fetchall()
    canonical_batch_ids = tuple(str(row["batch_id"]) for row in rows)
    if len(canonical_batch_ids) != len(batch_ids) or set(canonical_batch_ids) != set(batch_ids):
        raise ValueError("checkpoint report batch provenance is not sealed and attested")
    source_ids = tuple(sorted({str(row["source_id"]) for row in rows}))
    return canonical_batch_ids, source_ids


def _expected_attested_sample_identities(
    connection: sqlite3.Connection,
    *,
    candidate_id: str,
    batch_ids: tuple[str, ...] | None = None,
) -> set[tuple[str, str, str]]:
    if not _table_exists(connection, "research_batch_attestations"):
        return set()
    scope = ""
    parameters: tuple[object, ...] = (candidate_id,)
    if batch_ids is not None:
        placeholders = ", ".join("?" for _ in batch_ids)
        scope = f" AND a.batch_id IN ({placeholders})"
        parameters = (candidate_id, *batch_ids)
    rows = connection.execute(
        f"""
        SELECT a.batch_id, a.sample_identities_json
        FROM research_batch_attestations AS a
        JOIN research_batches AS b
          ON b.batch_id = a.batch_id AND b.candidate_id = a.candidate_id
        WHERE a.candidate_id = ? AND b.status = 'admitted'{scope}
        ORDER BY a.batch_id
        """,
        parameters,
    ).fetchall()
    expected: set[tuple[str, str, str]] = set()
    for row in rows:
        batch_id = str(row["batch_id"])
        decoded = json.loads(str(row["sample_identities_json"]))
        if not isinstance(decoded, list):
            raise ValueError("stored research batch sample identities are invalid")
        for identity in decoded:
            if (
                not isinstance(identity, list)
                or len(identity) != 2
                or not all(isinstance(item, str) and item for item in identity)
            ):
                raise ValueError("stored research batch sample identities are invalid")
            item = (batch_id, identity[0], identity[1])
            if item in expected:
                raise ValueError("stored research batch sample identities are not unique")
            expected.add(item)
    return expected


def _load_observations(
    connection: sqlite3.Connection,
    *,
    candidate_id: str,
    batch_ids: tuple[str, ...] | None = None,
) -> tuple[dict[str, object], ...]:
    if not _table_exists(connection, "research_trade_observations"):
        if _expected_attested_sample_identities(
            connection,
            candidate_id=candidate_id,
            batch_ids=batch_ids,
        ):
            raise ValueError(
                "checkpoint report is not reproducible from complete attested observations"
            )
        return ()

    observation_scope = ""
    observation_parameters: tuple[object, ...] = (candidate_id,)
    if batch_ids is not None:
        placeholders = ", ".join("?" for _ in batch_ids)
        observation_scope = f" AND batch_id IN ({placeholders})"
        observation_parameters = (candidate_id, *batch_ids)
    total_row = connection.execute(
        f"""
        SELECT COUNT(*)
        FROM research_trade_observations
        WHERE candidate_id = ?{observation_scope}
        """,
        observation_parameters,
    ).fetchone()
    total = 0 if total_row is None else int(total_row[0])
    if not _table_exists(connection, "research_batch_attestations"):
        if total:
            raise ValueError(
                "checkpoint report is not reproducible from immutable observations/provenance"
            )
        return ()

    joined_scope = ""
    joined_parameters: tuple[object, ...] = (candidate_id,)
    if batch_ids is not None:
        placeholders = ", ".join("?" for _ in batch_ids)
        joined_scope = f" AND o.batch_id IN ({placeholders})"
        joined_parameters = (candidate_id, *batch_ids)
    rows = connection.execute(
        f"""
        SELECT o.batch_id, o.trade_id, o.sample_id, o.payload_json
        FROM research_trade_observations AS o
        JOIN research_batches AS b
          ON b.batch_id = o.batch_id AND b.candidate_id = o.candidate_id
        JOIN research_batch_attestations AS a
          ON a.batch_id = o.batch_id AND a.candidate_id = o.candidate_id
        WHERE o.candidate_id = ? AND b.status = 'admitted'{joined_scope}
        ORDER BY o.closed_at_ms, o.trade_id
        """,
        joined_parameters,
    ).fetchall()
    if total != len(rows):
        raise ValueError(
            "checkpoint report is not reproducible from immutable observations/provenance"
        )

    actual: set[tuple[str, str, str]] = set()
    for row in rows:
        values = (row["batch_id"], row["trade_id"], row["sample_id"])
        if not all(isinstance(item, str) and item for item in values):
            raise ValueError("stored research observation identity is invalid")
        actual.add((str(values[0]), str(values[1]), str(values[2])))
    expected = _expected_attested_sample_identities(
        connection,
        candidate_id=candidate_id,
        batch_ids=batch_ids,
    )
    if actual != expected:
        raise ValueError(
            "checkpoint report is not reproducible from complete attested observations"
        )

    observations: list[dict[str, object]] = []
    for row in rows:
        payload = json.loads(str(row["payload_json"]))
        if not isinstance(payload, dict) or not all(isinstance(key, str) for key in payload):
            raise ValueError("stored research observation is invalid")
        observations.append(payload)
    return tuple(observations)


def _candidate_identity(
    connection: sqlite3.Connection,
    *,
    candidate_id: str,
) -> dict[str, str]:
    row = connection.execute(
        """
        SELECT family_id, config_digest, code_revision,
               execution_config_json, risk_config_json
        FROM research_candidates
        WHERE candidate_id = ?
        """,
        (candidate_id,),
    ).fetchone()
    if row is None:
        raise ValueError("checkpoint candidate is missing")
    return {
        "family_id": str(row["family_id"]),
        "config_digest": str(row["config_digest"]),
        "code_revision": str(row["code_revision"]),
        "execution_config_json": str(row["execution_config_json"]),
        "risk_config_json": str(row["risk_config_json"]),
    }


def _configured_risk_per_trade(
    connection: sqlite3.Connection,
    *,
    candidate_id: str,
    required: bool,
) -> Decimal | None:
    identity = _candidate_identity(connection, candidate_id=candidate_id)
    try:
        raw = json.loads(identity["risk_config_json"])
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
    batch_ids: tuple[str, ...] | None = None,
) -> tuple[bool, bool]:
    if not _table_exists(connection, "research_batch_attestations"):
        return False, False
    scope = ""
    parameters: tuple[object, ...] = (candidate_id,)
    if batch_ids is not None:
        placeholders = ", ".join("?" for _ in batch_ids)
        scope = f" AND a.batch_id IN ({placeholders})"
        parameters = (candidate_id, *batch_ids)
    rows = connection.execute(
        f"""
        SELECT a.operational_failure, a.hard_risk_failure
        FROM research_batch_attestations AS a
        JOIN research_batches AS b ON b.batch_id = a.batch_id
        WHERE a.candidate_id = ? AND b.status = 'admitted'{scope}
        """,
        parameters,
    ).fetchall()
    return (
        any(bool(int(row["operational_failure"])) for row in rows),
        any(bool(int(row["hard_risk_failure"])) for row in rows),
    )


def _assert_checkpoint_report_backed_by_observations(
    connection: sqlite3.Connection,
    *,
    candidate_id: str,
    report_id: str,
    payload: dict[str, object],
    state: ResearchCandidateState,
    batch_scope: tuple[str, ...] | None,
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

    if batch_scope is None:
        batch_ids, source_ids = load_sealed_admitted_batch_provenance(
            connection,
            candidate_id=candidate_id,
        )
    else:
        batch_ids, source_ids = _validated_scoped_provenance(
            connection,
            candidate_id=candidate_id,
            batch_ids=batch_scope,
        )
    if not batch_ids:
        raise ValueError("checkpoint report requires attested batch provenance")

    observations = _load_observations(
        connection,
        candidate_id=candidate_id,
        batch_ids=None if batch_scope is None else batch_ids,
    )
    identity = _candidate_identity(connection, candidate_id=candidate_id)
    net_r_values = tuple(
        _decimal_string(observation.get("net_r"), "net_r") for observation in observations
    )
    net_pnl_values = tuple(
        _decimal_string(observation.get("net_pnl"), "net_pnl")
        for observation in observations
    )
    fee_values = tuple(
        _decimal_string(observation.get("fees"), "fees") for observation in observations
    )
    funding_values = tuple(
        _decimal_string(observation.get("funding_cash_pnl"), "funding_cash_pnl")
        for observation in observations
    )
    slippage_values = tuple(
        _decimal_string(observation.get("slippage_amount"), "slippage_amount")
        for observation in observations
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
    operational_failure, hard_risk_failure = _attested_health(
        connection,
        candidate_id=candidate_id,
        batch_ids=None if batch_scope is None else batch_ids,
    )

    with localcontext(AUTHORITATIVE_CONTEXT):
        net_pnl = sum(net_pnl_values, start=ZERO)
        total_net_r = sum(net_r_values, start=ZERO)
        total_fees = sum(fee_values, start=ZERO)
        funding_cash_pnl = sum(funding_values, start=ZERO)
        total_slippage = sum(slippage_values, start=ZERO)
        mean_net_r = (
            None if not observations else total_net_r / Decimal(len(observations))
        )

    market_counts = Counter(
        _string_value(observation.get("market"), "market") for observation in observations
    )
    exit_reason_counts: Counter[str] = Counter()
    for observation in observations:
        exit_reason_counts.update(_reason_codes(observation.get("reason_codes")))
    long_count = sum(
        _string_value(observation.get("direction"), "direction") == Direction.LONG.value
        for observation in observations
    )
    short_count = sum(
        _string_value(observation.get("direction"), "direction") == Direction.SHORT.value
        for observation in observations
    )

    checkpoint = evaluate_checkpoint(
        net_r_values=net_r_values,
        closed_trade_days=len(closed_days),
        operational_failure=operational_failure,
        hard_risk_failure=hard_risk_failure,
        policy=DEFAULT_SEQUENTIAL_RESEARCH_POLICY,
    )

    expected: dict[str, object] = {
        "label": TOUCHED_NON_PROMOTIONAL_LABEL,
        "candidate_id": candidate_id,
        "family_id": identity["family_id"],
        "config_digest": identity["config_digest"],
        "code_revision": identity["code_revision"],
        "execution_config_json": identity["execution_config_json"],
        "risk_config_json": identity["risk_config_json"],
        "batch_ids": list(batch_ids),
        "source_ids": list(source_ids),
        "closed_trade_count": checkpoint.trade_count,
        "closed_trade_days": checkpoint.closed_trade_days,
        "net_pnl": str(net_pnl),
        "mean_net_r": None if mean_net_r is None else str(mean_net_r),
        "total_fees": str(total_fees),
        "funding_cash_pnl": str(funding_cash_pnl),
        "total_slippage_amount": str(total_slippage),
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
        "long_count": long_count,
        "short_count": short_count,
        "market_trade_counts": [list(item) for item in sorted(market_counts.items())],
        "exit_reason_counts": [list(item) for item in sorted(exit_reason_counts.items())],
        "checkpoint_state": checkpoint.checkpoint_state.value,
        "candidate_state": checkpoint.candidate_state.value,
        "posterior_probability_positive": (
            None
            if checkpoint.posterior_probability_positive is None
            else str(checkpoint.posterior_probability_positive)
        ),
        "policy_digest": checkpoint.policy_digest,
        "reason_codes": list(checkpoint.reason_codes),
    }
    if set(unsigned_payload) != set(expected):
        raise ValueError("checkpoint report fields do not match canonical report payload")
    for field, expected_value in expected.items():
        if unsigned_payload.get(field) != expected_value:
            raise ValueError(
                "checkpoint report is not reproducible from immutable "
                f"observations/provenance: {field}"
            )
    if checkpoint.candidate_state is not state:
        raise ValueError(
            "checkpoint report is not reproducible from immutable observations/provenance: state"
        )


def assert_checkpoint_report_backed_by_observations(
    connection: sqlite3.Connection,
    *,
    candidate_id: str,
    report_id: str,
    payload: dict[str, object],
    state: ResearchCandidateState,
) -> None:
    _assert_checkpoint_report_backed_by_observations(
        connection,
        candidate_id=candidate_id,
        report_id=report_id,
        payload=payload,
        state=state,
        batch_scope=None,
    )


def assert_historical_checkpoint_report_backed_by_observations(
    connection: sqlite3.Connection,
    *,
    candidate_id: str,
    report_id: str,
    payload: dict[str, object],
    state: ResearchCandidateState,
) -> None:
    batch_scope = _validate_declared_batch_ids(payload)
    _assert_checkpoint_report_backed_by_observations(
        connection,
        candidate_id=candidate_id,
        report_id=report_id,
        payload=payload,
        state=state,
        batch_scope=batch_scope,
    )
