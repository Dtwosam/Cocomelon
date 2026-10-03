from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final, cast

from cocomelon.research.prospective_momentum_band_forward_markout import (
    FORWARD_HORIZONS_MS,
)
from cocomelon.research.prospective_risk_rejected_forward_markout_ledger import (
    MIN_REASON_LONG_SETTLED_PER_HORIZON,
    MIN_REASON_MARKETS_PER_HORIZON,
    MIN_REASON_SHORT_SETTLED_PER_HORIZON,
    MIN_REASON_STACK_ADMIT_SETTLED_PER_HORIZON,
)

LEDGER_SCHEMA_VERSION: Final = 1
LEDGER_KIND: Final = "prospective-risk-rejected-stop-path-ledger-v1"
CLAIM_SCOPE: Final = "observed_mark_stop_crossing_only"
ZERO: Final = Decimal("0")

RESOLVED_STATUSES: Final = frozenset(
    {
        "observed_stop_crossing",
        "observed_path_survivor",
        "missing_stop",
        "unsupported_horizon",
        "markout_stale",
        "markout_unsupported_horizon",
        "no_causal_marks",
    }
)
PENDING_STATUSES: Final = frozenset(
    {
        "missing_path",
        "markout_pending",
        "markout_missing_path",
    }
)


class RiskRejectedStopPathLedgerError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _digest_payload(payload: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in payload.items()
        if key != "ledger_sha256"
    }


def _required_string(raw: dict[str, object], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RiskRejectedStopPathLedgerError(
            f"{key} must be a non-empty string"
        )
    return value


def _required_int(raw: dict[str, object], key: str) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise RiskRejectedStopPathLedgerError(
            f"{key} must be an integer"
        )
    return value


def _optional_string(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise RiskRejectedStopPathLedgerError(
            f"{field} must be a non-empty string or null"
        )
    return value


def _optional_decimal_string(
    value: object,
    *,
    field: str,
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise RiskRejectedStopPathLedgerError(
            f"{field} must be a decimal string or null"
        )
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise RiskRejectedStopPathLedgerError(
            f"{field} must be a decimal string or null"
        ) from exc
    if not parsed.is_finite():
        raise RiskRejectedStopPathLedgerError(
            f"{field} must be finite"
        )
    return value


def _risk_reasons(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise RiskRejectedStopPathLedgerError(
            "risk reasons must be an array"
        )
    values = tuple(value)
    if not values or not all(
        isinstance(item, str) and item.strip() for item in values
    ):
        raise RiskRejectedStopPathLedgerError(
            "risk reasons must be non-empty strings"
        )
    return tuple(sorted(set(cast(tuple[str, ...], values))))


def _canonical_stop_horizon(
    raw: object,
    *,
    timestamp_ms: int,
    horizon_ms: int,
) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise RiskRejectedStopPathLedgerError(
            "stop-path horizon must be an object"
        )
    status = _required_string(raw, "status")
    if status not in RESOLVED_STATUSES | PENDING_STATUSES:
        raise RiskRejectedStopPathLedgerError(
            f"unsupported stop-path status: {status}"
        )
    target = _required_int(raw, "target_at_ms")
    if target != timestamp_ms + horizon_ms:
        raise RiskRejectedStopPathLedgerError(
            "stop-path target does not match fixed horizon"
        )
    count = _required_int(raw, "observed_mark_count")
    if count < 0:
        raise RiskRejectedStopPathLedgerError(
            "observed mark count must be non-negative"
        )

    crossed = raw.get("stop_crossed")
    survived = raw.get("survived_observed_marks_to_horizon")
    first_at = raw.get("first_stop_cross_at_ms")
    first_px = raw.get("first_stop_cross_mark_px")
    time_to_stop = raw.get("time_to_stop_ms")

    if status == "observed_stop_crossing":
        if crossed is not True or survived is not False or count <= 0:
            raise RiskRejectedStopPathLedgerError(
                "stop crossing flags are invalid"
            )
        if (
            isinstance(first_at, bool)
            or not isinstance(first_at, int)
            or first_at <= timestamp_ms
            or first_at > target
        ):
            raise RiskRejectedStopPathLedgerError(
                "stop crossing timestamp is invalid"
            )
        parsed_px = _optional_decimal_string(
            first_px,
            field="first_stop_cross_mark_px",
        )
        if parsed_px is None or Decimal(parsed_px) <= ZERO:
            raise RiskRejectedStopPathLedgerError(
                "stop crossing mark must be positive"
            )
        if (
            isinstance(time_to_stop, bool)
            or not isinstance(time_to_stop, int)
            or time_to_stop != first_at - timestamp_ms
        ):
            raise RiskRejectedStopPathLedgerError(
                "stop crossing duration is invalid"
            )
    elif status == "observed_path_survivor":
        if crossed is not False or survived is not True or count <= 0:
            raise RiskRejectedStopPathLedgerError(
                "stop survivor flags are invalid"
            )
        if any(
            value is not None
            for value in (first_at, first_px, time_to_stop)
        ):
            raise RiskRejectedStopPathLedgerError(
                "stop survivor contains crossing evidence"
            )
        parsed_px = None
    else:
        if crossed is not None or survived is not None:
            raise RiskRejectedStopPathLedgerError(
                "unresolved stop path has resolved flags"
            )
        if any(
            value is not None
            for value in (first_at, first_px, time_to_stop)
        ):
            raise RiskRejectedStopPathLedgerError(
                "unresolved stop path has crossing evidence"
            )
        parsed_px = None

    return {
        "status": status,
        "target_at_ms": target,
        "observed_mark_count": count,
        "stop_crossed": crossed,
        "first_stop_cross_at_ms": first_at,
        "first_stop_cross_mark_px": parsed_px,
        "time_to_stop_ms": time_to_stop,
        "survived_observed_marks_to_horizon": survived,
    }


def _canonical_stop_path(
    raw: object,
    *,
    timestamp_ms: int,
) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise RiskRejectedStopPathLedgerError(
            "stop path must be an object"
        )
    if raw.get("claim_scope") != CLAIM_SCOPE:
        raise RiskRejectedStopPathLedgerError(
            "stop-path claim scope drift"
        )
    stop = _optional_decimal_string(
        raw.get("original_stop_price"),
        field="original_stop_price",
    )
    entry = _optional_decimal_string(
        raw.get("entry_reference_price"),
        field="entry_reference_price",
    )
    if entry is None or Decimal(entry) <= ZERO:
        raise RiskRejectedStopPathLedgerError(
            "entry reference must be positive"
        )
    if stop is not None and Decimal(stop) <= ZERO:
        raise RiskRejectedStopPathLedgerError(
            "original stop must be positive"
        )
    if (
        raw.get("changes_execution") is not False
        or raw.get("changes_risk_limits") is not False
        or raw.get("changes_candidate_readiness") is not False
    ):
        raise RiskRejectedStopPathLedgerError(
            "stop-path authority drift"
        )

    raw_horizons = raw.get("horizons")
    if not isinstance(raw_horizons, dict):
        raise RiskRejectedStopPathLedgerError(
            "stop-path horizons must be an object"
        )
    expected = {str(value) for value in FORWARD_HORIZONS_MS}
    if set(raw_horizons) != expected:
        raise RiskRejectedStopPathLedgerError(
            "stop-path horizon set drift"
        )
    horizons = {
        str(horizon_ms): _canonical_stop_horizon(
            raw_horizons[str(horizon_ms)],
            timestamp_ms=timestamp_ms,
            horizon_ms=horizon_ms,
        )
        for horizon_ms in FORWARD_HORIZONS_MS
    }
    return {
        "claim_scope": CLAIM_SCOPE,
        "original_stop_price": stop,
        "entry_reference_price": entry,
        "horizons": horizons,
        "changes_execution": False,
        "changes_risk_limits": False,
        "changes_candidate_readiness": False,
    }


def _canonical_row(
    raw: object,
    *,
    overlap_started_at_ms: int,
    terminal_only: bool,
) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise RiskRejectedStopPathLedgerError(
            "stop-path row must be an object"
        )
    timestamp_ms = _required_int(raw, "timestamp_ms")
    if timestamp_ms < overlap_started_at_ms:
        raise RiskRejectedStopPathLedgerError(
            "stop-path row predates common stack start"
        )
    if raw.get("baseline_risk_approved") is not False:
        raise RiskRejectedStopPathLedgerError(
            "stop-path ledger accepts risk-rejected rows only"
        )
    direction = _required_string(raw, "direction")
    if direction not in {"long", "short"}:
        raise RiskRejectedStopPathLedgerError(
            "direction must be long or short"
        )
    decision = _required_string(raw, "stack_decision")
    if decision not in {"ADMIT", "BLOCK"}:
        raise RiskRejectedStopPathLedgerError(
            "stack decision must be ADMIT or BLOCK"
        )
    layer = _required_string(raw, "block_layer")
    if layer not in {"none", "combined", "two_strike", "momentum"}:
        raise RiskRejectedStopPathLedgerError(
            "block layer is unsupported"
        )
    if (
        (decision == "ADMIT" and layer != "none")
        or (decision == "BLOCK" and layer == "none")
    ):
        raise RiskRejectedStopPathLedgerError(
            "stack decision and block layer do not reconcile"
        )
    stop_path_raw = raw.get("long_trend_carveout_stop_path")
    if stop_path_raw is None:
        stop_path_raw = raw.get("stop_path")
    stop_path = _canonical_stop_path(
        stop_path_raw,
        timestamp_ms=timestamp_ms,
    )
    statuses = {
        cast(str, item["status"])
        for item in cast(
            dict[str, dict[str, object]],
            stop_path["horizons"],
        ).values()
    }
    if terminal_only and not statuses <= RESOLVED_STATUSES:
        raise RiskRejectedStopPathLedgerError(
            "immutable stop-path row contains pending horizon"
        )

    return {
        "opportunity_id": _required_string(raw, "opportunity_id"),
        "timestamp_ms": timestamp_ms,
        "market": _required_string(raw, "market"),
        "direction": direction,
        "lead_strategy": _required_string(raw, "lead_strategy"),
        "baseline_risk_approved": False,
        "baseline_risk_reason_codes": list(
            _risk_reasons(raw.get("baseline_risk_reason_codes"))
        ),
        "stack_decision": decision,
        "block_layer": layer,
        "combined_block_reason": _optional_string(
            raw.get("combined_block_reason"),
            field="combined_block_reason",
        ),
        "stop_path": stop_path,
    }


def _row_identity(row: dict[str, object]) -> tuple[int, str]:
    return (
        cast(int, row["timestamp_ms"]),
        cast(str, row["opportunity_id"]),
    )


def _canonical_rows(
    raw: object,
    *,
    overlap_started_at_ms: int,
) -> tuple[dict[str, object], ...]:
    if not isinstance(raw, (list, tuple)):
        raise RiskRejectedStopPathLedgerError(
            "ledger rows must be a list"
        )
    rows = tuple(
        _canonical_row(
            item,
            overlap_started_at_ms=overlap_started_at_ms,
            terminal_only=True,
        )
        for item in raw
    )
    identities = tuple(_row_identity(row) for row in rows)
    if len(identities) != len(set(identities)):
        raise RiskRejectedStopPathLedgerError(
            "duplicate stop-path row identity"
        )
    ids = tuple(cast(str, row["opportunity_id"]) for row in rows)
    if len(ids) != len(set(ids)):
        raise RiskRejectedStopPathLedgerError(
            "duplicate stop-path opportunity id"
        )
    return tuple(sorted(rows, key=_row_identity))


def _rows_sha256(rows: Sequence[dict[str, object]]) -> str:
    payload = "\n".join(_canonical_json(row) for row in rows)
    if payload:
        payload += "\n"
    return _sha256_text(payload)


def _median_int(values: Sequence[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) // 2


def _bucket_summary(
    rows: Sequence[dict[str, object]],
    *,
    horizon_key: str,
) -> dict[str, object]:
    evaluated = 0
    crossings = 0
    survivors = 0
    times: list[int] = []
    markets: set[str] = set()
    for row in rows:
        stop_path = cast(dict[str, object], row["stop_path"])
        horizons = cast(
            dict[str, dict[str, object]],
            stop_path["horizons"],
        )
        item = horizons[horizon_key]
        status = cast(str, item["status"])
        if status not in {
            "observed_stop_crossing",
            "observed_path_survivor",
        }:
            continue
        evaluated += 1
        markets.add(cast(str, row["market"]))
        if status == "observed_stop_crossing":
            crossings += 1
            raw_time = item["time_to_stop_ms"]
            if isinstance(raw_time, int) and not isinstance(raw_time, bool):
                times.append(raw_time)
        else:
            survivors += 1
    return {
        "evaluable": evaluated,
        "crossings": crossings,
        "survivors": survivors,
        "crossing_fraction": (
            None
            if evaluated == 0
            else str(Decimal(crossings) / Decimal(evaluated))
        ),
        "median_time_to_stop_ms": _median_int(times),
        "market_count": len(markets),
    }


def _horizon_summary(
    rows: Sequence[dict[str, object]],
    *,
    horizon_ms: int,
) -> dict[str, object]:
    key = str(horizon_ms)
    statuses: Counter[str] = Counter()
    for row in rows:
        stop_path = cast(dict[str, object], row["stop_path"])
        horizons = cast(
            dict[str, dict[str, object]],
            stop_path["horizons"],
        )
        statuses[cast(str, horizons[key]["status"])] += 1

    by_layer: dict[str, dict[str, object]] = {}
    layers = sorted({cast(str, row["block_layer"]) for row in rows})
    for layer in layers:
        by_layer[layer] = _bucket_summary(
            tuple(row for row in rows if row["block_layer"] == layer),
            horizon_key=key,
        )

    by_combined_reason: dict[str, dict[str, object]] = {}
    reasons = sorted(
        {
            cast(str, row["combined_block_reason"])
            for row in rows
            if row["combined_block_reason"] is not None
        }
    )
    for reason in reasons:
        by_combined_reason[reason] = _bucket_summary(
            tuple(
                row
                for row in rows
                if row["combined_block_reason"] == reason
            ),
            horizon_key=key,
        )

    return {
        "horizon_ms": horizon_ms,
        "terminal_opportunities": len(rows),
        "status_counts": dict(sorted(statuses.items())),
        "overall": _bucket_summary(rows, horizon_key=key),
        "by_block_layer": by_layer,
        "by_combined_reason": by_combined_reason,
        "claim_scope": CLAIM_SCOPE,
        "changes_execution": False,
        "changes_risk_limits": False,
        "changes_candidate_readiness": False,
    }


def _survival_margin(
    rows: Sequence[dict[str, object]],
    *,
    horizon_key: str,
) -> int | None:
    survivors = 0
    crossings = 0
    evaluated = 0
    for row in rows:
        stop_path = cast(dict[str, object], row["stop_path"])
        horizons = cast(
            dict[str, dict[str, object]],
            stop_path["horizons"],
        )
        status = cast(str, horizons[horizon_key]["status"])
        if status == "observed_path_survivor":
            survivors += 1
            evaluated += 1
        elif status == "observed_stop_crossing":
            crossings += 1
            evaluated += 1
    if evaluated == 0:
        return None
    return survivors - crossings


def _risk_budget_stop_readiness(
    rows: Sequence[dict[str, object]],
    *,
    integrity_clean: bool,
) -> dict[str, object]:
    stack_admit_rows = tuple(
        row for row in rows if row["stack_decision"] == "ADMIT"
    )
    reasons = sorted(
        {
            reason
            for row in stack_admit_rows
            for reason in cast(
                list[str],
                row["baseline_risk_reason_codes"],
            )
        }
    )
    by_reason: dict[str, dict[str, object]] = {}
    ready_reasons: list[str] = []

    for reason in reasons:
        reason_rows = tuple(
            row
            for row in stack_admit_rows
            if reason
            in cast(list[str], row["baseline_risk_reason_codes"])
        )
        horizons: dict[str, dict[str, object]] = {}
        reason_ready = True
        for horizon_ms in FORWARD_HORIZONS_MS:
            key = str(horizon_ms)
            evaluable: list[dict[str, object]] = []
            survivors = 0
            crossings = 0
            for row in reason_rows:
                stop_path = cast(dict[str, object], row["stop_path"])
                path_horizons = cast(
                    dict[str, dict[str, object]],
                    stop_path["horizons"],
                )
                status = cast(str, path_horizons[key]["status"])
                if status == "observed_path_survivor":
                    survivors += 1
                    evaluable.append(row)
                elif status == "observed_stop_crossing":
                    crossings += 1
                    evaluable.append(row)

            markets = {
                cast(str, row["market"]) for row in evaluable
            }
            long_count = sum(
                row["direction"] == "long" for row in evaluable
            )
            short_count = sum(
                row["direction"] == "short" for row in evaluable
            )
            coverage_complete = (
                bool(reason_rows)
                and len(evaluable) == len(reason_rows)
            )
            sample_complete = (
                len(evaluable)
                >= MIN_REASON_STACK_ADMIT_SETTLED_PER_HORIZON
                and len(markets) >= MIN_REASON_MARKETS_PER_HORIZON
                and long_count >= MIN_REASON_LONG_SETTLED_PER_HORIZON
                and short_count >= MIN_REASON_SHORT_SETTLED_PER_HORIZON
            )
            survivor_majority = survivors > crossings

            leave_one_margins = tuple(
                margin
                for index in range(len(evaluable))
                if (
                    margin := _survival_margin(
                        tuple(
                            evaluable[:index]
                            + evaluable[index + 1 :]
                        ),
                        horizon_key=key,
                    )
                )
                is not None
            )
            opportunity_robust = (
                len(leave_one_margins) == len(evaluable)
                and bool(leave_one_margins)
                and min(leave_one_margins) > 0
            )

            leave_market_margins = tuple(
                margin
                for market in sorted(markets)
                if (
                    margin := _survival_margin(
                        tuple(
                            row
                            for row in evaluable
                            if row["market"] != market
                        ),
                        horizon_key=key,
                    )
                )
                is not None
            )
            market_robust = (
                len(leave_market_margins) == len(markets)
                and bool(leave_market_margins)
                and min(leave_market_margins) > 0
            )
            ready = (
                integrity_clean
                and coverage_complete
                and sample_complete
                and survivor_majority
                and opportunity_robust
                and market_robust
            )
            reason_ready = reason_ready and ready
            horizons[key] = {
                "evaluable": len(evaluable),
                "survivors": survivors,
                "crossings": crossings,
                "survival_margin": survivors - crossings,
                "market_count": len(markets),
                "long_evaluable": long_count,
                "short_evaluable": short_count,
                "coverage_complete": coverage_complete,
                "sample_complete": sample_complete,
                "survivor_majority": survivor_majority,
                "leave_one_opportunity_min_survival_margin": (
                    None
                    if not leave_one_margins
                    else min(leave_one_margins)
                ),
                "leave_one_market_min_survival_margin": (
                    None
                    if not leave_market_margins
                    else min(leave_market_margins)
                ),
                "single_opportunity_robust": opportunity_robust,
                "single_market_robust": market_robust,
                "ready_for_risk_budget_stop_investigation": ready,
            }
        if reason_ready and horizons:
            ready_reasons.append(reason)
        by_reason[reason] = {
            "ready_for_risk_budget_stop_investigation": (
                reason_ready and bool(horizons)
            ),
            "horizons": horizons,
        }

    return {
        "scope": "risk_rejected_stack_admit_stop_survival_only",
        "ready_reasons": ready_reasons,
        "min_evaluable_per_horizon": (
            MIN_REASON_STACK_ADMIT_SETTLED_PER_HORIZON
        ),
        "min_markets_per_horizon": MIN_REASON_MARKETS_PER_HORIZON,
        "min_long_evaluable_per_horizon": (
            MIN_REASON_LONG_SETTLED_PER_HORIZON
        ),
        "min_short_evaluable_per_horizon": (
            MIN_REASON_SHORT_SETTLED_PER_HORIZON
        ),
        "by_reason": by_reason,
        "changes_risk_limits": False,
        "changes_execution": False,
        "changes_candidate_readiness": False,
    }


def _summary(
    rows: Sequence[dict[str, object]],
    *,
    pending_opportunity_count: int,
    integrity_clean: bool,
    include_risk_budget_stop_readiness: bool = True,
) -> dict[str, object]:
    row_values = tuple(rows)
    block_layers = Counter(
        cast(str, row["block_layer"]) for row in row_values
    )
    risk_reasons: Counter[str] = Counter()
    for row in row_values:
        risk_reasons.update(
            cast(list[str], row["baseline_risk_reason_codes"])
        )
    result: dict[str, object] = {
        "terminal_opportunity_count": len(row_values),
        "pending_opportunity_count": pending_opportunity_count,
        "integrity_clean": integrity_clean,
        "block_layer_counts": dict(sorted(block_layers.items())),
        "risk_reason_counts": dict(sorted(risk_reasons.items())),
        "horizons": {
            str(horizon_ms): _horizon_summary(
                row_values,
                horizon_ms=horizon_ms,
            )
            for horizon_ms in FORWARD_HORIZONS_MS
        },
        "claim_scope": CLAIM_SCOPE,
        "changes_execution": False,
        "changes_risk_limits": False,
        "changes_candidate_readiness": False,
    }
    if include_risk_budget_stop_readiness:
        result["risk_budget_stop_investigation"] = (
            _risk_budget_stop_readiness(
                row_values,
                integrity_clean=integrity_clean,
            )
        )
    return result


def _validate_metadata(raw: dict[str, object]) -> int:
    if raw.get("schema_version") != LEDGER_SCHEMA_VERSION:
        raise RiskRejectedStopPathLedgerError(
            "stop-path ledger schema is unsupported"
        )
    if raw.get("kind") != LEDGER_KIND:
        raise RiskRejectedStopPathLedgerError(
            "stop-path ledger kind is unsupported"
        )
    overlap = _required_int(raw, "overlap_started_at_ms")
    if raw.get("forward_horizons_ms") != list(FORWARD_HORIZONS_MS):
        raise RiskRejectedStopPathLedgerError(
            "stop-path ledger horizons drift"
        )
    if raw.get("claim_scope") != CLAIM_SCOPE:
        raise RiskRejectedStopPathLedgerError(
            "stop-path ledger claim scope drift"
        )
    return overlap


def validate_risk_rejected_stop_path_ledger(
    raw: object,
) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise RiskRejectedStopPathLedgerError(
            "stop-path ledger must be an object"
        )
    overlap = _validate_metadata(raw)
    rows = _canonical_rows(
        raw.get("rows"),
        overlap_started_at_ms=overlap,
    )
    if raw.get("row_count") != len(rows):
        raise RiskRejectedStopPathLedgerError(
            "stop-path row count mismatch"
        )
    if raw.get("rows_sha256") != _rows_sha256(rows):
        raise RiskRejectedStopPathLedgerError(
            "stop-path rows digest mismatch"
        )
    pending = _required_int(raw, "pending_opportunity_count")
    if pending < 0:
        raise RiskRejectedStopPathLedgerError(
            "pending opportunity count is invalid"
        )
    history = raw.get("source_history")
    if not isinstance(history, list):
        raise RiskRejectedStopPathLedgerError(
            "source history must be a list"
        )
    integrity_clean = all(
        isinstance(item, dict)
        and item.get("integrity_clean") is True
        for item in history
    )
    current_summary = _summary(
        rows,
        pending_opportunity_count=pending,
        integrity_clean=integrity_clean,
    )
    legacy_summary = _summary(
        rows,
        pending_opportunity_count=pending,
        integrity_clean=integrity_clean,
        include_risk_budget_stop_readiness=False,
    )
    if raw.get("summary") not in (current_summary, legacy_summary):
        raise RiskRejectedStopPathLedgerError(
            "stop-path summary does not reconcile"
        )
    if (
        raw.get("research_only") is not True
        or raw.get("execution_authority") is not False
        or raw.get("promotion_authority") is not False
        or raw.get("changes_risk_limits") is not False
        or raw.get("changes_candidate_readiness") is not False
    ):
        raise RiskRejectedStopPathLedgerError(
            "stop-path ledger authority drift"
        )
    expected = _sha256_text(_canonical_json(_digest_payload(raw)))
    if raw.get("ledger_sha256") != expected:
        raise RiskRejectedStopPathLedgerError(
            "stop-path ledger digest mismatch"
        )
    return {**raw, "rows": rows}


def load_risk_rejected_stop_path_ledger(
    path: str | Path,
) -> dict[str, object]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RiskRejectedStopPathLedgerError(
            "stop-path ledger file is invalid"
        ) from exc
    return validate_risk_rejected_stop_path_ledger(raw)


def _source_rows(
    summary: object,
) -> tuple[
    tuple[dict[str, object], ...],
    int,
    int,
    bool,
]:
    if not isinstance(summary, dict):
        raise RiskRejectedStopPathLedgerError(
            "full-stack source must be an object"
        )
    if summary.get("enabled") is not True or summary.get("error") is not None:
        raise RiskRejectedStopPathLedgerError(
            "full-stack source is not cleanly enabled"
        )
    if (
        summary.get("research_only") is not True
        or summary.get("execution_authority") is not False
        or summary.get("promotion_authority") is not False
        or summary.get("descriptive_only") is not True
        or summary.get("changes_readiness_gate") is not False
        or summary.get("changes_closed_trade_readiness_gate") is not False
    ):
        raise RiskRejectedStopPathLedgerError(
            "full-stack source authority drift"
        )
    overlap = _required_int(summary, "overlap_started_at_ms")
    candidate = summary.get("risk_rejected_long_trend_carveout")
    if not isinstance(candidate, dict):
        raise RiskRejectedStopPathLedgerError(
            "source predates stop-path overlay"
        )
    overlay = candidate.get("stop_path_overlay")
    if not isinstance(overlay, dict):
        raise RiskRejectedStopPathLedgerError(
            "source predates stop-path overlay"
        )
    if (
        overlay.get("enabled") is not True
        or overlay.get("claim_scope") != CLAIM_SCOPE
        or overlay.get("changes_execution") is not False
        or overlay.get("changes_risk_limits") is not False
        or overlay.get("changes_candidate_readiness") is not False
    ):
        raise RiskRejectedStopPathLedgerError(
            "source stop-path overlay contract drift"
        )
    raw_rows = summary.get("risk_rejected_rows")
    if not isinstance(raw_rows, list):
        raise RiskRejectedStopPathLedgerError(
            "risk-rejected source rows must be a list"
        )
    evaluated = _required_int(summary, "risk_rejected_stack_evaluated")
    if evaluated != len(raw_rows):
        raise RiskRejectedStopPathLedgerError(
            "risk-rejected evaluated count does not reconcile"
        )

    terminal: list[dict[str, object]] = []
    pending = 0
    for raw_row in raw_rows:
        row = _canonical_row(
            raw_row,
            overlap_started_at_ms=overlap,
            terminal_only=False,
        )
        stop_path = cast(dict[str, object], row["stop_path"])
        horizons = cast(
            dict[str, dict[str, object]],
            stop_path["horizons"],
        )
        statuses = {
            cast(str, item["status"])
            for item in horizons.values()
        }
        if statuses <= RESOLVED_STATUSES:
            terminal.append(
                _canonical_row(
                    row,
                    overlap_started_at_ms=overlap,
                    terminal_only=True,
                )
            )
        else:
            pending += 1

    rows = _canonical_rows(
        terminal,
        overlap_started_at_ms=overlap,
    )
    integrity_clean = summary.get("risk_rejected_integrity_clean") is True
    return rows, pending, overlap, integrity_clean


def update_risk_rejected_stop_path_ledger(
    summary: object,
    *,
    previous: dict[str, object] | None,
    source_paper_run_id: int,
    source_paper_run_attempt: int,
    source_artifact_name: str,
    source_artifact_digest: str,
) -> dict[str, object]:
    if source_paper_run_id <= 0 or source_paper_run_attempt <= 0:
        raise ValueError("source paper run identity must be positive")
    if not source_artifact_name.strip():
        raise ValueError("source artifact name must not be empty")
    if not source_artifact_digest.startswith("sha256:"):
        raise ValueError("source artifact digest must be sha256")

    source_rows, pending, overlap, source_integrity = _source_rows(summary)
    previous_rows: tuple[dict[str, object], ...] = ()
    history: list[object] = []
    prior_ledger_sha256: str | None = None

    if previous is not None:
        validated = validate_risk_rejected_stop_path_ledger(previous)
        if validated.get("overlap_started_at_ms") != overlap:
            raise RiskRejectedStopPathLedgerError(
                "stop-path overlap start drift"
            )
        raw_history = validated.get("source_history")
        if not isinstance(raw_history, list):
            raise RiskRejectedStopPathLedgerError(
                "stop-path source history is invalid"
            )
        for item in raw_history:
            if not isinstance(item, dict):
                raise RiskRejectedStopPathLedgerError(
                    "stop-path source history entry is invalid"
                )
            if (
                item.get("paper_run_id") == source_paper_run_id
                and item.get("paper_run_attempt")
                == source_paper_run_attempt
            ):
                if (
                    item.get("artifact_name") != source_artifact_name
                    or item.get("artifact_digest") != source_artifact_digest
                ):
                    raise RiskRejectedStopPathLedgerError(
                        "duplicate stop-path source artifact drift"
                    )
                return validated
        previous_rows = cast(
            tuple[dict[str, object], ...],
            validated["rows"],
        )
        history = list(raw_history)
        prior_ledger_sha256 = cast(str, validated["ledger_sha256"])
        current_by_id = {
            cast(str, row["opportunity_id"]): row
            for row in source_rows
        }
        for old in previous_rows:
            opportunity_id = cast(str, old["opportunity_id"])
            current = current_by_id.get(opportunity_id)
            if current is None:
                raise RiskRejectedStopPathLedgerError(
                    "previous terminal stop-path row disappeared"
                )
            if current != old:
                raise RiskRejectedStopPathLedgerError(
                    "previous terminal stop-path row changed"
                )

    old_ids = {
        cast(str, row["opportunity_id"])
        for row in previous_rows
    }
    new_rows = tuple(
        row
        for row in source_rows
        if cast(str, row["opportunity_id"]) not in old_ids
    )
    rows = previous_rows + new_rows
    history.append(
        {
            "paper_run_id": source_paper_run_id,
            "paper_run_attempt": source_paper_run_attempt,
            "artifact_name": source_artifact_name,
            "artifact_digest": source_artifact_digest,
            "terminal_row_count": len(rows),
            "new_terminal_row_count": len(new_rows),
            "pending_opportunity_count": pending,
            "integrity_clean": source_integrity,
            "rows_sha256": _rows_sha256(rows),
        }
    )
    cumulative_integrity = all(
        isinstance(item, dict)
        and item.get("integrity_clean") is True
        for item in history
    )

    payload: dict[str, object] = {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "kind": LEDGER_KIND,
        "overlap_started_at_ms": overlap,
        "forward_horizons_ms": list(FORWARD_HORIZONS_MS),
        "claim_scope": CLAIM_SCOPE,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_risk_limits": False,
        "changes_candidate_readiness": False,
        "prior_ledger_sha256": prior_ledger_sha256,
        "row_count": len(rows),
        "previous_row_count": len(previous_rows),
        "new_row_count": len(new_rows),
        "pending_opportunity_count": pending,
        "rows_sha256": _rows_sha256(rows),
        "source_history": history,
        "summary": _summary(
            rows,
            pending_opportunity_count=pending,
            integrity_clean=cumulative_integrity,
        ),
        "rows": rows,
    }
    payload["ledger_sha256"] = _sha256_text(
        _canonical_json(_digest_payload(payload))
    )
    return payload
