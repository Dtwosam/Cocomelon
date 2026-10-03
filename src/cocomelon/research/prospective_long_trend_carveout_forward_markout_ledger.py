from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final, cast

from cocomelon.research.prospective_full_stack_forward_markout import (
    LONG_TREND_CARVEOUT_CANDIDATE_ID,
)
from cocomelon.research.prospective_momentum_band_forward_markout import (
    FORWARD_HORIZONS_MS,
    MAX_MARK_LAG_MS,
)

LEDGER_SCHEMA_VERSION: Final = 1
LEDGER_KIND: Final = "prospective-long-trend-carveout-fast-markout-ledger-v1"
TERMINAL_STATUSES: Final = frozenset(
    {"settled", "stale", "unsupported_horizon"}
)
PENDING_STATUSES: Final = frozenset({"pending", "missing_path"})
ZERO: Final = Decimal("0")

MIN_SETTLED_PER_HORIZON: Final = 20
MIN_ADMIT_SETTLED_PER_HORIZON: Final = 5
MIN_BLOCK_SETTLED_PER_HORIZON: Final = 5
MIN_LONG_SETTLED_PER_HORIZON: Final = 5
MIN_SHORT_SETTLED_PER_HORIZON: Final = 5
MIN_MARKETS_PER_HORIZON: Final = 4
MIN_REOPENED_LONG_TREND_SETTLED_PER_HORIZON: Final = 10
MIN_REOPENED_LONG_TREND_MARKETS_PER_HORIZON: Final = 4


class ProspectiveLongTrendCarveoutLedgerError(RuntimeError):
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
        raise ProspectiveLongTrendCarveoutLedgerError(
            f"{key} must be a non-empty string"
        )
    return value


def _required_int(raw: dict[str, object], key: str) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProspectiveLongTrendCarveoutLedgerError(
            f"{key} must be an integer"
        )
    return value


def _optional_string(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ProspectiveLongTrendCarveoutLedgerError(
            f"{field} must be a non-empty string or null"
        )
    return value


def _optional_int(value: object, *, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProspectiveLongTrendCarveoutLedgerError(
            f"{field} must be an integer or null"
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
        raise ProspectiveLongTrendCarveoutLedgerError(
            f"{field} must be a decimal string or null"
        )
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ProspectiveLongTrendCarveoutLedgerError(
            f"{field} must be a decimal string or null"
        ) from exc
    if not parsed.is_finite():
        raise ProspectiveLongTrendCarveoutLedgerError(
            f"{field} must be finite"
        )
    return value


def _risk_reasons(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ProspectiveLongTrendCarveoutLedgerError(
            "baseline risk reasons must be an array"
        )
    values = tuple(value)
    if not values or not all(
        isinstance(item, str) and item.strip() for item in values
    ):
        raise ProspectiveLongTrendCarveoutLedgerError(
            "baseline risk reasons must be non-empty strings"
        )
    return tuple(sorted(set(cast(tuple[str, ...], values))))


def _canonical_markout(
    raw: object,
    *,
    timestamp_ms: int,
    horizon_ms: int,
    terminal_only: bool,
) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ProspectiveLongTrendCarveoutLedgerError(
            "markout must be an object"
        )
    status = _required_string(raw, "status")
    if status not in TERMINAL_STATUSES | PENDING_STATUSES:
        raise ProspectiveLongTrendCarveoutLedgerError(
            f"unsupported markout status: {status}"
        )
    if terminal_only and status not in TERMINAL_STATUSES:
        raise ProspectiveLongTrendCarveoutLedgerError(
            "immutable carveout row contains pending horizon"
        )
    target_at_ms = _required_int(raw, "target_at_ms")
    if target_at_ms != timestamp_ms + horizon_ms:
        raise ProspectiveLongTrendCarveoutLedgerError(
            "markout target does not match frozen horizon"
        )

    observed_at_ms = raw.get("observed_at_ms")
    lag_ms = raw.get("observation_lag_ms")
    mark_px = raw.get("mark_px")
    directional_return = raw.get("directional_return")
    if status in PENDING_STATUSES or status == "unsupported_horizon":
        if any(
            value is not None
            for value in (
                observed_at_ms,
                lag_ms,
                mark_px,
                directional_return,
            )
        ):
            raise ProspectiveLongTrendCarveoutLedgerError(
                "non-observed markout contains terminal evidence"
            )
        return {
            "status": status,
            "target_at_ms": target_at_ms,
            "observed_at_ms": None,
            "observation_lag_ms": None,
            "mark_px": None,
            "directional_return": None,
        }

    if (
        isinstance(observed_at_ms, bool)
        or not isinstance(observed_at_ms, int)
        or observed_at_ms < target_at_ms
    ):
        raise ProspectiveLongTrendCarveoutLedgerError(
            "terminal markout timestamp is invalid"
        )
    if (
        isinstance(lag_ms, bool)
        or not isinstance(lag_ms, int)
        or lag_ms != observed_at_ms - target_at_ms
    ):
        raise ProspectiveLongTrendCarveoutLedgerError(
            "terminal markout lag does not reconcile"
        )
    parsed_mark = _optional_decimal_string(mark_px, field="mark_px")
    if parsed_mark is None or Decimal(parsed_mark) <= ZERO:
        raise ProspectiveLongTrendCarveoutLedgerError(
            "terminal mark price must be positive"
        )
    if status == "settled":
        if lag_ms > MAX_MARK_LAG_MS:
            raise ProspectiveLongTrendCarveoutLedgerError(
                "settled markout exceeds maximum lag"
            )
        parsed_return = _optional_decimal_string(
            directional_return,
            field="directional_return",
        )
        if parsed_return is None:
            raise ProspectiveLongTrendCarveoutLedgerError(
                "settled markout is missing directional return"
            )
    else:
        if lag_ms <= MAX_MARK_LAG_MS:
            raise ProspectiveLongTrendCarveoutLedgerError(
                "stale markout does not exceed maximum lag"
            )
        if directional_return is not None:
            raise ProspectiveLongTrendCarveoutLedgerError(
                "stale markout must not carry directional return"
            )
        parsed_return = None

    return {
        "status": status,
        "target_at_ms": target_at_ms,
        "observed_at_ms": observed_at_ms,
        "observation_lag_ms": lag_ms,
        "mark_px": parsed_mark,
        "directional_return": parsed_return,
    }


def _canonical_stop_path(
    raw: object,
    *,
    timestamp_ms: int,
) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ProspectiveLongTrendCarveoutLedgerError(
            "carveout stop path must be an object"
        )
    if raw.get("claim_scope") != "observed_mark_stop_crossing_only":
        raise ProspectiveLongTrendCarveoutLedgerError(
            "carveout stop path claim scope drift"
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
        raise ProspectiveLongTrendCarveoutLedgerError(
            "carveout stop path entry reference must be positive"
        )
    if stop is not None and Decimal(stop) <= ZERO:
        raise ProspectiveLongTrendCarveoutLedgerError(
            "carveout stop path stop must be positive"
        )
    if (
        raw.get("changes_execution") is not False
        or raw.get("changes_risk_limits") is not False
        or raw.get("changes_candidate_readiness") is not False
    ):
        raise ProspectiveLongTrendCarveoutLedgerError(
            "carveout stop path authority drift"
        )

    raw_horizons = raw.get("horizons")
    if not isinstance(raw_horizons, dict):
        raise ProspectiveLongTrendCarveoutLedgerError(
            "carveout stop path horizons must be an object"
        )
    expected = {str(value) for value in FORWARD_HORIZONS_MS}
    if set(raw_horizons) != expected:
        raise ProspectiveLongTrendCarveoutLedgerError(
            "carveout stop path horizon drift"
        )
    unresolved = {
        "missing_stop",
        "missing_path",
        "unsupported_horizon",
        "markout_pending",
        "markout_stale",
        "markout_missing_path",
        "markout_unsupported_horizon",
        "no_causal_marks",
    }
    horizons: dict[str, dict[str, object]] = {}
    for horizon_ms in FORWARD_HORIZONS_MS:
        key = str(horizon_ms)
        item = raw_horizons[key]
        if not isinstance(item, dict):
            raise ProspectiveLongTrendCarveoutLedgerError(
                "carveout stop path horizon must be an object"
            )
        status = _required_string(item, "status")
        target = _required_int(item, "target_at_ms")
        if target != timestamp_ms + horizon_ms:
            raise ProspectiveLongTrendCarveoutLedgerError(
                "carveout stop path target drift"
            )
        count = _required_int(item, "observed_mark_count")
        if count < 0:
            raise ProspectiveLongTrendCarveoutLedgerError(
                "carveout stop path mark count is invalid"
            )
        crossed = item.get("stop_crossed")
        survived = item.get("survived_observed_marks_to_horizon")
        first_at = item.get("first_stop_cross_at_ms")
        first_px = item.get("first_stop_cross_mark_px")
        time_to_stop = item.get("time_to_stop_ms")

        if status == "observed_stop_crossing":
            if crossed is not True or survived is not False or count <= 0:
                raise ProspectiveLongTrendCarveoutLedgerError(
                    "carveout stop crossing flags are invalid"
                )
            if (
                isinstance(first_at, bool)
                or not isinstance(first_at, int)
                or first_at <= timestamp_ms
                or first_at > target
            ):
                raise ProspectiveLongTrendCarveoutLedgerError(
                    "carveout stop crossing timestamp is invalid"
                )
            parsed_px = _optional_decimal_string(
                first_px,
                field="first_stop_cross_mark_px",
            )
            if parsed_px is None or Decimal(parsed_px) <= ZERO:
                raise ProspectiveLongTrendCarveoutLedgerError(
                    "carveout stop crossing mark is invalid"
                )
            if (
                isinstance(time_to_stop, bool)
                or not isinstance(time_to_stop, int)
                or time_to_stop != first_at - timestamp_ms
            ):
                raise ProspectiveLongTrendCarveoutLedgerError(
                    "carveout stop crossing duration is invalid"
                )
        elif status == "observed_path_survivor":
            if crossed is not False or survived is not True or count <= 0:
                raise ProspectiveLongTrendCarveoutLedgerError(
                    "carveout stop survivor flags are invalid"
                )
            if any(
                value is not None
                for value in (first_at, first_px, time_to_stop)
            ):
                raise ProspectiveLongTrendCarveoutLedgerError(
                    "carveout stop survivor contains crossing evidence"
                )
            parsed_px = None
        elif status in unresolved:
            if crossed is not None or survived is not None:
                raise ProspectiveLongTrendCarveoutLedgerError(
                    "unresolved carveout stop path has resolved flags"
                )
            if any(
                value is not None
                for value in (first_at, first_px, time_to_stop)
            ):
                raise ProspectiveLongTrendCarveoutLedgerError(
                    "unresolved carveout stop path has crossing evidence"
                )
            parsed_px = None
        else:
            raise ProspectiveLongTrendCarveoutLedgerError(
                f"unsupported carveout stop path status: {status}"
            )

        horizons[key] = {
            "status": status,
            "target_at_ms": target,
            "observed_mark_count": count,
            "stop_crossed": crossed,
            "first_stop_cross_at_ms": first_at,
            "first_stop_cross_mark_px": parsed_px,
            "time_to_stop_ms": time_to_stop,
            "survived_observed_marks_to_horizon": survived,
        }

    return {
        "claim_scope": "observed_mark_stop_crossing_only",
        "original_stop_price": stop,
        "entry_reference_price": entry,
        "horizons": horizons,
        "changes_execution": False,
        "changes_risk_limits": False,
        "changes_candidate_readiness": False,
    }


def _validate_transition(
    *,
    combined_reason: str | None,
    original_decision: str,
    original_layer: str,
    carveout_decision: str,
    carveout_layer: str,
) -> None:
    if original_decision not in {"ADMIT", "BLOCK"}:
        raise ProspectiveLongTrendCarveoutLedgerError(
            "original stack decision is invalid"
        )
    if original_layer not in {
        "none",
        "combined",
        "two_strike",
        "momentum",
    }:
        raise ProspectiveLongTrendCarveoutLedgerError(
            "original stack block layer is invalid"
        )
    if carveout_decision not in {"ADMIT", "BLOCK"}:
        raise ProspectiveLongTrendCarveoutLedgerError(
            "carveout decision is invalid"
        )
    if carveout_layer not in {
        "none",
        "rank_above_10",
        "two_strike",
        "momentum",
    }:
        raise ProspectiveLongTrendCarveoutLedgerError(
            "carveout block layer is invalid"
        )
    if (
        (carveout_decision == "ADMIT" and carveout_layer != "none")
        or (
            carveout_decision == "BLOCK"
            and carveout_layer == "none"
        )
    ):
        raise ProspectiveLongTrendCarveoutLedgerError(
            "carveout decision and block layer do not reconcile"
        )

    if combined_reason == "long_trend":
        if original_decision != "BLOCK" or original_layer != "combined":
            raise ProspectiveLongTrendCarveoutLedgerError(
                "long-trend source did not originate at combined block"
            )
        if carveout_layer == "rank_above_10":
            raise ProspectiveLongTrendCarveoutLedgerError(
                "pure long-trend carveout cannot become a rank block"
            )
        return
    if combined_reason in {
        "rank_above_10",
        "long_trend_and_rank_above_10",
    }:
        if (
            original_decision != "BLOCK"
            or original_layer != "combined"
            or carveout_decision != "BLOCK"
            or carveout_layer != "rank_above_10"
        ):
            raise ProspectiveLongTrendCarveoutLedgerError(
                "rank block changed under long-trend carveout"
            )
        return
    if original_layer == "combined":
        raise ProspectiveLongTrendCarveoutLedgerError(
            "combined block is missing a supported reason"
        )
    if (
        carveout_decision != original_decision
        or carveout_layer != original_layer
    ):
        raise ProspectiveLongTrendCarveoutLedgerError(
            "non-combined decision changed under carveout"
        )


def _canonical_row(
    raw: object,
    *,
    overlap_started_at_ms: int,
    terminal_only: bool,
) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ProspectiveLongTrendCarveoutLedgerError(
            "carveout row must be an object"
        )
    timestamp_ms = _required_int(raw, "timestamp_ms")
    if timestamp_ms < overlap_started_at_ms:
        raise ProspectiveLongTrendCarveoutLedgerError(
            "carveout row predates common stack start"
        )
    if raw.get("baseline_risk_approved") is not False:
        raise ProspectiveLongTrendCarveoutLedgerError(
            "carveout ledger accepts risk-rejected rows only"
        )
    reasons = _risk_reasons(raw.get("baseline_risk_reason_codes"))
    direction = _required_string(raw, "direction")
    if direction not in {"long", "short"}:
        raise ProspectiveLongTrendCarveoutLedgerError(
            "row direction must be long or short"
        )
    original_decision_raw = raw.get("stack_decision")
    if original_decision_raw is None:
        original_decision_raw = raw.get("original_stack_decision")
    if (
        not isinstance(original_decision_raw, str)
        or not original_decision_raw.strip()
    ):
        raise ProspectiveLongTrendCarveoutLedgerError(
            "original stack decision must be a non-empty string"
        )
    original_decision = original_decision_raw

    original_layer_raw = raw.get("block_layer")
    if original_layer_raw is None:
        original_layer_raw = raw.get("original_block_layer")
    if (
        not isinstance(original_layer_raw, str)
        or not original_layer_raw.strip()
    ):
        raise ProspectiveLongTrendCarveoutLedgerError(
            "original block layer must be a non-empty string"
        )
    original_layer = original_layer_raw
    combined_reason = _optional_string(
        raw.get("combined_block_reason"),
        field="combined_block_reason",
    )
    candidate_id = raw.get("long_trend_carveout_candidate_id")
    if candidate_id is None:
        candidate_id = raw.get("candidate_id")
    if candidate_id != LONG_TREND_CARVEOUT_CANDIDATE_ID:
        raise ProspectiveLongTrendCarveoutLedgerError(
            "long-trend carveout candidate identity drift"
        )
    carveout_decision_raw = raw.get(
        "long_trend_carveout_decision"
    )
    if carveout_decision_raw is None:
        carveout_decision_raw = raw.get("carveout_decision")
    if (
        not isinstance(carveout_decision_raw, str)
        or not carveout_decision_raw.strip()
    ):
        raise ProspectiveLongTrendCarveoutLedgerError(
            "carveout decision must be a non-empty string"
        )
    carveout_decision = carveout_decision_raw

    carveout_layer_raw = raw.get(
        "long_trend_carveout_block_layer"
    )
    if carveout_layer_raw is None:
        carveout_layer_raw = raw.get("carveout_block_layer")
    if (
        not isinstance(carveout_layer_raw, str)
        or not carveout_layer_raw.strip()
    ):
        raise ProspectiveLongTrendCarveoutLedgerError(
            "carveout block layer must be a non-empty string"
        )
    carveout_layer = carveout_layer_raw
    _validate_transition(
        combined_reason=combined_reason,
        original_decision=original_decision,
        original_layer=original_layer,
        carveout_decision=carveout_decision,
        carveout_layer=carveout_layer,
    )

    ordinal = _required_int(raw, "rank_ordinal")
    rank_age_ms = _required_int(raw, "rank_age_ms")
    prior_two_strikes = _required_int(raw, "two_strike_prior_strikes")
    if ordinal <= 0 or rank_age_ms < 0 or prior_two_strikes < 0:
        raise ProspectiveLongTrendCarveoutLedgerError(
            "rank or strike lineage is invalid"
        )

    momentum_decision_raw = raw.get(
        "long_trend_carveout_momentum_decision"
    )
    if momentum_decision_raw is None:
        momentum_decision_raw = raw.get(
            "carveout_momentum_decision"
        )
    momentum_decision = _optional_string(
        momentum_decision_raw,
        field="carveout_momentum_decision",
    )
    if momentum_decision not in {None, "ADMIT", "BLOCK"}:
        raise ProspectiveLongTrendCarveoutLedgerError(
            "carveout momentum decision is invalid"
        )
    momentum_reason_raw = raw.get(
        "long_trend_carveout_momentum_reason"
    )
    if momentum_reason_raw is None:
        momentum_reason_raw = raw.get(
            "carveout_momentum_reason"
        )
    momentum_reason = _optional_string(
        momentum_reason_raw,
        field="carveout_momentum_reason",
    )
    momentum_prior_raw = raw.get(
        "long_trend_carveout_momentum_prior_strikes"
    )
    if momentum_prior_raw is None:
        momentum_prior_raw = raw.get(
            "carveout_momentum_prior_strikes"
        )
    momentum_prior = _optional_int(
        momentum_prior_raw,
        field="carveout_momentum_prior_strikes",
    )
    if momentum_prior is not None and momentum_prior < 0:
        raise ProspectiveLongTrendCarveoutLedgerError(
            "carveout momentum prior strikes must be non-negative"
        )

    raw_markouts = raw.get("markouts")
    if not isinstance(raw_markouts, dict):
        raise ProspectiveLongTrendCarveoutLedgerError(
            "row markouts must be an object"
        )
    expected_keys = {str(value) for value in FORWARD_HORIZONS_MS}
    if set(raw_markouts) != expected_keys:
        raise ProspectiveLongTrendCarveoutLedgerError(
            "row markout horizons do not match frozen horizons"
        )
    markouts = {
        str(horizon_ms): _canonical_markout(
            raw_markouts[str(horizon_ms)],
            timestamp_ms=timestamp_ms,
            horizon_ms=horizon_ms,
            terminal_only=terminal_only,
        )
        for horizon_ms in FORWARD_HORIZONS_MS
    }

    row = {
        "opportunity_id": _required_string(raw, "opportunity_id"),
        "timestamp_ms": timestamp_ms,
        "market": _required_string(raw, "market"),
        "direction": direction,
        "lead_strategy": _required_string(raw, "lead_strategy"),
        "rank_ordinal": ordinal,
        "rank_age_ms": rank_age_ms,
        "baseline_risk_approved": False,
        "baseline_risk_reason_codes": list(reasons),
        "combined_block_reason": combined_reason,
        "two_strike_prior_strikes": prior_two_strikes,
        "original_stack_decision": original_decision,
        "original_block_layer": original_layer,
        "candidate_id": LONG_TREND_CARVEOUT_CANDIDATE_ID,
        "carveout_decision": carveout_decision,
        "carveout_block_layer": carveout_layer,
        "carveout_momentum_decision": momentum_decision,
        "carveout_momentum_reason": momentum_reason,
        "carveout_momentum_prior_strikes": momentum_prior,
        "carveout_signed_return_1h": _optional_decimal_string(
            (
                raw.get("long_trend_carveout_signed_return_1h")
                if "long_trend_carveout_signed_return_1h" in raw
                else raw.get("carveout_signed_return_1h")
            ),
            field="carveout_signed_return_1h",
        ),
        "carveout_signed_day_return": _optional_decimal_string(
            (
                raw.get("long_trend_carveout_signed_day_return")
                if "long_trend_carveout_signed_day_return" in raw
                else raw.get("carveout_signed_day_return")
            ),
            field="carveout_signed_day_return",
        ),
        "markouts": markouts,
    }
    raw_stop_path = raw.get("long_trend_carveout_stop_path")
    if raw_stop_path is None and "stop_path" in raw:
        raw_stop_path = raw.get("stop_path")
    if raw_stop_path is not None:
        row["stop_path"] = _canonical_stop_path(
            raw_stop_path,
            timestamp_ms=timestamp_ms,
        )
    return row


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
        raise ProspectiveLongTrendCarveoutLedgerError(
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
        raise ProspectiveLongTrendCarveoutLedgerError(
            "duplicate carveout row identity"
        )
    ids = tuple(cast(str, row["opportunity_id"]) for row in rows)
    if len(ids) != len(set(ids)):
        raise ProspectiveLongTrendCarveoutLedgerError(
            "duplicate carveout opportunity id"
        )
    return tuple(sorted(rows, key=_row_identity))


def _rows_sha256(rows: Sequence[dict[str, object]]) -> str:
    payload = "\n".join(_canonical_json(row) for row in rows)
    if payload:
        payload += "\n"
    return _sha256_text(payload)


def _mean(values: Sequence[Decimal]) -> Decimal | None:
    if not values:
        return None
    return sum(values, ZERO) / Decimal(len(values))


def _median_int(values: Sequence[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) // 2


def _mean_robustness(
    values: Sequence[tuple[str, Decimal]],
) -> dict[str, object]:
    items = tuple(values)
    returns = tuple(value for _market, value in items)
    mean_value = _mean(returns)
    leave_one = tuple(
        candidate
        for index in range(len(items))
        if (
            candidate := _mean(
                tuple(
                    value
                    for _market, value in (
                        items[:index] + items[index + 1 :]
                    )
                )
            )
        )
        is not None
    )
    markets = tuple(sorted({market for market, _value in items}))
    leave_market = tuple(
        candidate
        for market in markets
        if (
            candidate := _mean(
                tuple(
                    value
                    for item_market, value in items
                    if item_market != market
                )
            )
        )
        is not None
    )
    return {
        "mean_directional_return": (
            None if mean_value is None else str(mean_value)
        ),
        "leave_one_opportunity_min_mean": (
            None if not leave_one else str(min(leave_one))
        ),
        "positive_after_removing_any_one_opportunity": (
            len(leave_one) == len(items)
            and bool(leave_one)
            and min(leave_one) > ZERO
        ),
        "leave_one_market_min_mean": (
            None if not leave_market else str(min(leave_market))
        ),
        "positive_after_removing_any_one_market": (
            len(leave_market) == len(markets)
            and bool(leave_market)
            and min(leave_market) > ZERO
        ),
    }


def _spread(
    values: Sequence[tuple[str, str, Decimal]],
) -> Decimal | None:
    admits = tuple(
        value
        for decision, _market, value in values
        if decision == "ADMIT"
    )
    blocks = tuple(
        value
        for decision, _market, value in values
        if decision == "BLOCK"
    )
    admit_mean = _mean(admits)
    block_mean = _mean(blocks)
    if admit_mean is None or block_mean is None:
        return None
    return admit_mean - block_mean


def _spread_robustness(
    values: Sequence[tuple[str, str, Decimal]],
) -> dict[str, object]:
    items = tuple(values)
    full = _spread(items)
    leave_one = tuple(
        candidate
        for index in range(len(items))
        if (
            candidate := _spread(
                items[:index] + items[index + 1 :]
            )
        )
        is not None
    )
    markets = tuple(
        sorted({market for _decision, market, _value in items})
    )
    leave_market = tuple(
        candidate
        for market in markets
        if (
            candidate := _spread(
                tuple(item for item in items if item[1] != market)
            )
        )
        is not None
    )
    return {
        "admit_minus_block_mean_return": (
            None if full is None else str(full)
        ),
        "leave_one_opportunity_min_spread": (
            None if not leave_one else str(min(leave_one))
        ),
        "positive_after_removing_any_one_opportunity": (
            len(leave_one) == len(items)
            and bool(leave_one)
            and min(leave_one) > ZERO
        ),
        "leave_one_market_min_spread": (
            None if not leave_market else str(min(leave_market))
        ),
        "positive_after_removing_any_one_market": (
            len(leave_market) == len(markets)
            and bool(leave_market)
            and min(leave_market) > ZERO
        ),
    }


def _is_reopened_long_trend(row: dict[str, object]) -> bool:
    return (
        row["combined_block_reason"] == "long_trend"
        and row["original_stack_decision"] == "BLOCK"
        and row["original_block_layer"] == "combined"
        and row["carveout_decision"] == "ADMIT"
    )


def _reopened_exit_timing_summary(
    rows: Sequence[dict[str, object]],
) -> dict[str, object]:
    complete: list[tuple[str, dict[int, Decimal]]] = []
    for row in rows:
        if not _is_reopened_long_trend(row):
            continue
        markouts = cast(dict[str, dict[str, object]], row["markouts"])
        values: dict[int, Decimal] = {}
        for horizon_ms in FORWARD_HORIZONS_MS:
            markout = markouts[str(horizon_ms)]
            if markout["status"] != "settled":
                break
            raw_return = markout["directional_return"]
            if not isinstance(raw_return, str):
                raise ProspectiveLongTrendCarveoutLedgerError(
                    "settled markout is missing directional return"
                )
            values[horizon_ms] = Decimal(raw_return)
        else:
            complete.append((cast(str, row["market"]), values))

    five_ms, fifteen_ms, sixty_ms = FORWARD_HORIZONS_MS
    five_vs_sixty = tuple(
        (market, values[five_ms] - values[sixty_ms])
        for market, values in complete
    )
    fifteen_vs_sixty = tuple(
        (market, values[fifteen_ms] - values[sixty_ms])
        for market, values in complete
    )
    five_vs_fifteen = tuple(
        (market, values[five_ms] - values[fifteen_ms])
        for market, values in complete
    )

    best_horizon_counts: Counter[str] = Counter()
    best_horizon_ties = 0
    early_exit_preferred = 0
    sixty_min_preferred = 0
    early_vs_sixty_ties = 0
    for _market, values in complete:
        best_value = max(values.values())
        best_horizons = tuple(
            horizon_ms
            for horizon_ms, value in values.items()
            if value == best_value
        )
        if len(best_horizons) == 1:
            best_horizon_counts[str(best_horizons[0])] += 1
        else:
            best_horizon_ties += 1

        best_early = max(values[five_ms], values[fifteen_ms])
        if best_early > values[sixty_ms]:
            early_exit_preferred += 1
        elif values[sixty_ms] > best_early:
            sixty_min_preferred += 1
        else:
            early_vs_sixty_ties += 1

    return {
        "claim_scope": "fixed_markout_exit_timing_only",
        "evaluable_opportunities": len(complete),
        "market_count": len({market for market, _values in complete}),
        "best_horizon_counts": dict(
            sorted(best_horizon_counts.items())
        ),
        "best_horizon_ties": best_horizon_ties,
        "early_exit_preferred_count": early_exit_preferred,
        "sixty_min_preferred_count": sixty_min_preferred,
        "early_vs_sixty_tie_count": early_vs_sixty_ties,
        "five_min_minus_sixty_min": _mean_robustness(
            five_vs_sixty
        ),
        "fifteen_min_minus_sixty_min": _mean_robustness(
            fifteen_vs_sixty
        ),
        "five_min_minus_fifteen_min": _mean_robustness(
            five_vs_fifteen
        ),
        "changes_execution": False,
        "changes_risk_limits": False,
        "changes_candidate_readiness": False,
    }


def _horizon_summary(
    rows: Sequence[dict[str, object]],
    *,
    horizon_ms: int,
    integrity_clean: bool,
    include_stop_path: bool = True,
    include_stop_readiness: bool = True,
) -> dict[str, object]:
    key = str(horizon_ms)
    settled: list[tuple[dict[str, object], Decimal]] = []
    statuses: Counter[str] = Counter()
    for row in rows:
        markouts = cast(dict[str, dict[str, object]], row["markouts"])
        markout = markouts[key]
        status = cast(str, markout["status"])
        statuses[status] += 1
        if status != "settled":
            continue
        raw_return = markout["directional_return"]
        if not isinstance(raw_return, str):
            raise ProspectiveLongTrendCarveoutLedgerError(
                "settled markout is missing directional return"
            )
        settled.append((row, Decimal(raw_return)))

    admits = tuple(
        (cast(str, row["market"]), value)
        for row, value in settled
        if row["carveout_decision"] == "ADMIT"
    )
    blocks = tuple(
        (cast(str, row["market"]), value)
        for row, value in settled
        if row["carveout_decision"] == "BLOCK"
    )
    spread_values = tuple(
        (
            cast(str, row["carveout_decision"]),
            cast(str, row["market"]),
            value,
        )
        for row, value in settled
    )
    reopened = tuple(
        (cast(str, row["market"]), value)
        for row, value in settled
        if (
            row["combined_block_reason"] == "long_trend"
            and row["original_stack_decision"] == "BLOCK"
            and row["original_block_layer"] == "combined"
            and row["carveout_decision"] == "ADMIT"
        )
    )
    admit_returns = tuple(value for _market, value in admits)
    block_returns = tuple(value for _market, value in blocks)
    admit_mean = _mean(admit_returns)
    block_mean = _mean(block_returns)
    spread_robustness = _spread_robustness(spread_values)
    reopened_robustness = _mean_robustness(reopened)
    long_count = sum(
        row["direction"] == "long" for row, _value in settled
    )
    short_count = sum(
        row["direction"] == "short" for row, _value in settled
    )
    markets = {
        cast(str, row["market"]) for row, _value in settled
    }
    reopened_markets = {market for market, _value in reopened}
    stop_evaluable = 0
    stop_crossings = 0
    stop_survivors = 0
    stop_cross_times: list[int] = []
    if include_stop_path:
        for row, _value in settled:
            if not (
                row["combined_block_reason"] == "long_trend"
                and row["original_stack_decision"] == "BLOCK"
                and row["original_block_layer"] == "combined"
                and row["carveout_decision"] == "ADMIT"
            ):
                continue
            raw_stop_path = row.get("stop_path")
            if not isinstance(raw_stop_path, dict):
                continue
            raw_horizons = raw_stop_path.get("horizons")
            if not isinstance(raw_horizons, dict):
                continue
            stop_item = raw_horizons.get(key)
            if not isinstance(stop_item, dict):
                continue
            stop_status = stop_item.get("status")
            if stop_status not in {
                "observed_stop_crossing",
                "observed_path_survivor",
            }:
                continue
            stop_evaluable += 1
            if stop_status == "observed_stop_crossing":
                stop_crossings += 1
                raw_time = stop_item.get("time_to_stop_ms")
                if isinstance(raw_time, int) and not isinstance(
                    raw_time, bool
                ):
                    stop_cross_times.append(raw_time)
            else:
                stop_survivors += 1

    sample_complete = (
        len(settled) >= MIN_SETTLED_PER_HORIZON
        and len(admits) >= MIN_ADMIT_SETTLED_PER_HORIZON
        and len(blocks) >= MIN_BLOCK_SETTLED_PER_HORIZON
        and long_count >= MIN_LONG_SETTLED_PER_HORIZON
        and short_count >= MIN_SHORT_SETTLED_PER_HORIZON
        and len(markets) >= MIN_MARKETS_PER_HORIZON
    )
    separation_positive = (
        admit_mean is not None
        and block_mean is not None
        and admit_mean > ZERO
        and block_mean < ZERO
        and cast(str | None, spread_robustness[
            "admit_minus_block_mean_return"
        ])
        is not None
        and Decimal(
            cast(
                str,
                spread_robustness["admit_minus_block_mean_return"],
            )
        )
        > ZERO
    )
    spread_robust = (
        spread_robustness[
            "positive_after_removing_any_one_opportunity"
        ]
        is True
        and spread_robustness[
            "positive_after_removing_any_one_market"
        ]
        is True
    )
    reopened_complete = (
        len(reopened)
        >= MIN_REOPENED_LONG_TREND_SETTLED_PER_HORIZON
        and len(reopened_markets)
        >= MIN_REOPENED_LONG_TREND_MARKETS_PER_HORIZON
    )
    reopened_positive = (
        reopened_robustness["mean_directional_return"] is not None
        and Decimal(
            cast(
                str,
                reopened_robustness["mean_directional_return"],
            )
        )
        > ZERO
    )
    reopened_robust = (
        reopened_robustness[
            "positive_after_removing_any_one_opportunity"
        ]
        is True
        and reopened_robustness[
            "positive_after_removing_any_one_market"
        ]
        is True
    )
    stop_path_complete = (
        stop_evaluable == len(reopened)
        and bool(reopened)
    )
    stop_survivor_majority = (
        stop_evaluable > 0
        and stop_survivors > stop_crossings
    )
    ready = (
        integrity_clean
        and sample_complete
        and separation_positive
        and spread_robust
        and reopened_complete
        and reopened_positive
        and reopened_robust
        and (
            not include_stop_readiness
            or (
                stop_path_complete
                and stop_survivor_majority
            )
        )
    )

    readiness: dict[str, object] = {
        "ready_for_execution_shadow_investigation": ready,
        "integrity_clean": integrity_clean,
        "sample_complete": sample_complete,
        "separation_positive": separation_positive,
        "spread_robust": spread_robust,
        "reopened_sample_complete": reopened_complete,
        "reopened_mean_positive": reopened_positive,
        "reopened_robust": reopened_robust,
        "min_settled": MIN_SETTLED_PER_HORIZON,
        "min_admit_settled": MIN_ADMIT_SETTLED_PER_HORIZON,
        "min_block_settled": MIN_BLOCK_SETTLED_PER_HORIZON,
        "min_long_settled": MIN_LONG_SETTLED_PER_HORIZON,
        "min_short_settled": MIN_SHORT_SETTLED_PER_HORIZON,
        "min_markets": MIN_MARKETS_PER_HORIZON,
        "min_reopened_long_trend_settled": (
            MIN_REOPENED_LONG_TREND_SETTLED_PER_HORIZON
        ),
        "min_reopened_long_trend_markets": (
            MIN_REOPENED_LONG_TREND_MARKETS_PER_HORIZON
        ),
        "changes_execution": False,
        "changes_risk_limits": False,
        "changes_candidate_readiness": False,
    }
    if include_stop_readiness:
        readiness.update(
            {
                "stop_path_complete_for_reopened_sample": (
                    stop_path_complete
                ),
                "stop_survivor_majority": stop_survivor_majority,
                "stop_evaluable": stop_evaluable,
                "stop_crossings": stop_crossings,
                "stop_survivors": stop_survivors,
            }
        )

    result: dict[str, object] = {
        "horizon_ms": horizon_ms,
        "terminal_opportunities": len(rows),
        "settled_opportunities": len(settled),
        "status_counts": dict(sorted(statuses.items())),
        "admit_settled": len(admits),
        "block_settled": len(blocks),
        "long_settled": long_count,
        "short_settled": short_count,
        "market_count": len(markets),
        "admit_mean_directional_return": (
            None if admit_mean is None else str(admit_mean)
        ),
        "block_mean_directional_return": (
            None if block_mean is None else str(block_mean)
        ),
        "spread_robustness": spread_robustness,
        "reopened_long_trend_settled": len(reopened),
        "reopened_long_trend_market_count": len(reopened_markets),
        "reopened_long_trend": reopened_robustness,
        "investigation_readiness": readiness,
    }
    if include_stop_path:
        result["reopened_long_trend_stop_path"] = {
            "claim_scope": "observed_mark_stop_crossing_only",
            "evaluable": stop_evaluable,
            "crossings": stop_crossings,
            "survivors": stop_survivors,
            "crossing_fraction": (
                None
                if stop_evaluable == 0
                else str(
                    Decimal(stop_crossings)
                    / Decimal(stop_evaluable)
                )
            ),
            "median_time_to_stop_ms": _median_int(stop_cross_times),
            "changes_execution": False,
            "changes_risk_limits": False,
            "changes_candidate_readiness": False,
        }
    return result


def _post_integrity_miss_summary(
    rows: Sequence[dict[str, object]],
    *,
    overlap_started_at_ms: int,
    boundary_known: bool,
    last_miss_at_ms: int | None,
    include_stop_path: bool,
    include_stop_readiness: bool,
    include_exit_timing: bool,
) -> dict[str, object]:
    if not boundary_known:
        return {
            "boundary_known": False,
            "last_miss_at_ms": None,
            "started_at_ms": None,
            "terminal_opportunity_count": 0,
            "all_horizons_ready_for_execution_shadow_investigation": False,
            "horizons": {},
            "changes_execution": False,
            "changes_risk_limits": False,
            "changes_candidate_readiness": False,
        }

    started_at_ms = (
        overlap_started_at_ms
        if last_miss_at_ms is None
        else last_miss_at_ms + 1
    )
    clean_rows = tuple(
        row
        for row in rows
        if cast(int, row["timestamp_ms"]) >= started_at_ms
    )
    clean_summary = _summary(
        clean_rows,
        pending_opportunity_count=0,
        integrity_clean=True,
        include_stop_path=include_stop_path,
        include_stop_readiness=include_stop_readiness,
        include_exit_timing=include_exit_timing,
        include_post_integrity_readiness=False,
    )
    return {
        "boundary_known": True,
        "last_miss_at_ms": last_miss_at_ms,
        "started_at_ms": started_at_ms,
        "terminal_opportunity_count": len(clean_rows),
        "all_horizons_ready_for_execution_shadow_investigation": (
            clean_summary[
                "all_horizons_ready_for_execution_shadow_investigation"
            ]
        ),
        "horizons": clean_summary["horizons"],
        "changes_execution": False,
        "changes_risk_limits": False,
        "changes_candidate_readiness": False,
    }


def _summary(
    rows: Sequence[dict[str, object]],
    *,
    pending_opportunity_count: int,
    integrity_clean: bool,
    include_stop_path: bool = True,
    include_stop_readiness: bool = True,
    include_exit_timing: bool = True,
    include_post_integrity_readiness: bool = True,
    overlap_started_at_ms: int | None = None,
    integrity_boundary_known: bool = False,
    integrity_last_miss_at_ms: int | None = None,
) -> dict[str, object]:
    row_values = tuple(rows)
    decisions = Counter(
        cast(str, row["carveout_decision"]) for row in row_values
    )
    layers = Counter(
        cast(str, row["carveout_block_layer"]) for row in row_values
    )
    changed = sum(
        row["carveout_decision"] != row["original_stack_decision"]
        or row["carveout_block_layer"] != row["original_block_layer"]
        for row in row_values
    )
    reopened = sum(
        row["combined_block_reason"] == "long_trend"
        and row["original_stack_decision"] == "BLOCK"
        and row["original_block_layer"] == "combined"
        and row["carveout_decision"] == "ADMIT"
        for row in row_values
    )
    horizons = {
        str(horizon_ms): _horizon_summary(
            row_values,
            horizon_ms=horizon_ms,
            integrity_clean=integrity_clean,
            include_stop_path=include_stop_path,
            include_stop_readiness=include_stop_readiness,
        )
        for horizon_ms in FORWARD_HORIZONS_MS
    }
    cumulative_ready = all(
        cast(dict[str, object], item["investigation_readiness"])[
            "ready_for_execution_shadow_investigation"
        ]
        is True
        for item in horizons.values()
    )
    result: dict[str, object] = {
        "terminal_opportunity_count": len(row_values),
        "pending_opportunity_count": pending_opportunity_count,
        "integrity_clean": integrity_clean,
        "carveout_admitted_terminal": decisions["ADMIT"],
        "carveout_blocked_terminal": decisions["BLOCK"],
        "carveout_block_layer_counts": dict(sorted(layers.items())),
        "changed_decision_or_layer_terminal": changed,
        "reopened_long_trend_terminal": reopened,
        "all_horizons_ready_for_execution_shadow_investigation": (
            cumulative_ready
        ),
        "horizons": horizons,
    }
    if include_exit_timing:
        result["reopened_long_trend_exit_timing"] = (
            _reopened_exit_timing_summary(row_values)
        )
    if include_post_integrity_readiness:
        if overlap_started_at_ms is None:
            raise ProspectiveLongTrendCarveoutLedgerError(
                "post-integrity cohort requires overlap start"
            )
        post_integrity = _post_integrity_miss_summary(
            row_values,
            overlap_started_at_ms=overlap_started_at_ms,
            boundary_known=integrity_boundary_known,
            last_miss_at_ms=integrity_last_miss_at_ms,
            include_stop_path=include_stop_path,
            include_stop_readiness=include_stop_readiness,
            include_exit_timing=include_exit_timing,
        )
        post_ready = (
            post_integrity[
                "all_horizons_ready_for_execution_shadow_investigation"
            ]
            is True
        )
        effective_ready = cumulative_ready or post_ready
        if cumulative_ready:
            effective_scope = "cumulative"
        elif post_ready:
            effective_scope = "post_integrity_miss"
        else:
            effective_scope = "none"
        result["post_integrity_miss"] = post_integrity
        result[
            "effective_all_horizons_ready_for_execution_shadow_investigation"
        ] = effective_ready
        result["effective_integrity_scope"] = effective_scope
    return result


def _validate_metadata(raw: dict[str, object]) -> int:
    if raw.get("schema_version") != LEDGER_SCHEMA_VERSION:
        raise ProspectiveLongTrendCarveoutLedgerError(
            "carveout ledger schema is unsupported"
        )
    if raw.get("kind") != LEDGER_KIND:
        raise ProspectiveLongTrendCarveoutLedgerError(
            "carveout ledger kind is unsupported"
        )
    if raw.get("candidate_id") != LONG_TREND_CARVEOUT_CANDIDATE_ID:
        raise ProspectiveLongTrendCarveoutLedgerError(
            "carveout ledger candidate drift"
        )
    overlap = _required_int(raw, "overlap_started_at_ms")
    if raw.get("forward_horizons_ms") != list(FORWARD_HORIZONS_MS):
        raise ProspectiveLongTrendCarveoutLedgerError(
            "carveout ledger horizons drift"
        )
    if raw.get("max_mark_lag_ms") != MAX_MARK_LAG_MS:
        raise ProspectiveLongTrendCarveoutLedgerError(
            "carveout ledger max mark lag drift"
        )
    return overlap


def validate_long_trend_carveout_ledger(
    raw: object,
) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ProspectiveLongTrendCarveoutLedgerError(
            "carveout ledger must be an object"
        )
    overlap = _validate_metadata(raw)
    rows = _canonical_rows(
        raw.get("rows"),
        overlap_started_at_ms=overlap,
    )
    if raw.get("row_count") != len(rows):
        raise ProspectiveLongTrendCarveoutLedgerError(
            "carveout row count mismatch"
        )
    if raw.get("rows_sha256") != _rows_sha256(rows):
        raise ProspectiveLongTrendCarveoutLedgerError(
            "carveout rows digest mismatch"
        )
    pending = _required_int(raw, "pending_opportunity_count")
    if pending < 0:
        raise ProspectiveLongTrendCarveoutLedgerError(
            "pending opportunity count is invalid"
        )
    history = raw.get("source_history")
    if not isinstance(history, list):
        raise ProspectiveLongTrendCarveoutLedgerError(
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
    pre_exit_timing_summary = _summary(
        rows,
        pending_opportunity_count=pending,
        integrity_clean=integrity_clean,
        include_exit_timing=False,
    )
    pre_stop_readiness_with_timing_summary = _summary(
        rows,
        pending_opportunity_count=pending,
        integrity_clean=integrity_clean,
        include_stop_readiness=False,
    )
    pre_stop_readiness_summary = _summary(
        rows,
        pending_opportunity_count=pending,
        integrity_clean=integrity_clean,
        include_stop_readiness=False,
        include_exit_timing=False,
    )
    pre_stop_path_with_timing_summary = _summary(
        rows,
        pending_opportunity_count=pending,
        integrity_clean=integrity_clean,
        include_stop_path=False,
        include_stop_readiness=False,
    )
    legacy_summary = _summary(
        rows,
        pending_opportunity_count=pending,
        integrity_clean=integrity_clean,
        include_stop_path=False,
        include_stop_readiness=False,
        include_exit_timing=False,
    )
    if raw.get("summary") not in (
        current_summary,
        pre_exit_timing_summary,
        pre_stop_readiness_with_timing_summary,
        pre_stop_readiness_summary,
        pre_stop_path_with_timing_summary,
        legacy_summary,
    ):
        raise ProspectiveLongTrendCarveoutLedgerError(
            "carveout summary does not reconcile"
        )
    if (
        raw.get("research_only") is not True
        or raw.get("execution_authority") is not False
        or raw.get("promotion_authority") is not False
        or raw.get("changes_risk_limits") is not False
        or raw.get("changes_candidate_readiness") is not False
    ):
        raise ProspectiveLongTrendCarveoutLedgerError(
            "carveout ledger authority drift"
        )
    expected = _sha256_text(_canonical_json(_digest_payload(raw)))
    if raw.get("ledger_sha256") != expected:
        raise ProspectiveLongTrendCarveoutLedgerError(
            "carveout ledger digest mismatch"
        )
    return {**raw, "rows": rows}


def load_long_trend_carveout_ledger(
    path: str | Path,
) -> dict[str, object]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProspectiveLongTrendCarveoutLedgerError(
            "carveout ledger file is invalid"
        ) from exc
    return validate_long_trend_carveout_ledger(raw)


def _source_rows(
    summary: object,
) -> tuple[
    tuple[dict[str, object], ...],
    int,
    int,
    int,
    bool,
    bool,
    int | None,
]:
    if not isinstance(summary, dict):
        raise ProspectiveLongTrendCarveoutLedgerError(
            "full-stack forward-markout summary must be an object"
        )
    if summary.get("enabled") is not True or summary.get("error") is not None:
        raise ProspectiveLongTrendCarveoutLedgerError(
            "full-stack forward-markout source is not cleanly enabled"
        )
    if (
        summary.get("research_only") is not True
        or summary.get("execution_authority") is not False
        or summary.get("promotion_authority") is not False
        or summary.get("descriptive_only") is not True
        or summary.get("changes_readiness_gate") is not False
        or summary.get("changes_closed_trade_readiness_gate") is not False
    ):
        raise ProspectiveLongTrendCarveoutLedgerError(
            "full-stack source authority drift"
        )
    overlap = _required_int(summary, "overlap_started_at_ms")
    candidate = summary.get("risk_rejected_long_trend_carveout")
    if not isinstance(candidate, dict):
        raise ProspectiveLongTrendCarveoutLedgerError(
            "source predates long-trend carveout shadow"
        )
    if candidate.get("candidate_id") != LONG_TREND_CARVEOUT_CANDIDATE_ID:
        raise ProspectiveLongTrendCarveoutLedgerError(
            "source carveout candidate identity drift"
        )
    if (
        candidate.get("research_only") is not True
        or candidate.get("execution_authority") is not False
        or candidate.get("promotion_authority") is not False
        or candidate.get("descriptive_only") is not True
        or candidate.get("changes_readiness_gate") is not False
        or candidate.get("changes_closed_trade_readiness_gate") is not False
    ):
        raise ProspectiveLongTrendCarveoutLedgerError(
            "source carveout authority drift"
        )
    integrity = candidate.get("integrity_clean")
    if not isinstance(integrity, bool):
        raise ProspectiveLongTrendCarveoutLedgerError(
            "source carveout integrity flag is invalid"
        )
    boundary_key = (
        "risk_rejected_long_trend_carveout_integrity_last_miss_at_ms"
    )
    boundary_known = boundary_key in summary or integrity is True
    raw_last_miss = summary.get(boundary_key)
    if raw_last_miss is not None and (
        isinstance(raw_last_miss, bool)
        or not isinstance(raw_last_miss, int)
    ):
        raise ProspectiveLongTrendCarveoutLedgerError(
            "source carveout integrity boundary is invalid"
        )

    raw_rows = summary.get("risk_rejected_rows")
    if not isinstance(raw_rows, list):
        raise ProspectiveLongTrendCarveoutLedgerError(
            "risk-rejected source rows must be a list"
        )
    terminal: list[dict[str, object]] = []
    pending = 0
    unevaluable = 0
    current_format = 0
    for raw_row in raw_rows:
        if not isinstance(raw_row, dict):
            raise ProspectiveLongTrendCarveoutLedgerError(
                "risk-rejected source row must be an object"
            )
        if (
            raw_row.get("long_trend_carveout_candidate_id")
            != LONG_TREND_CARVEOUT_CANDIDATE_ID
        ):
            raise ProspectiveLongTrendCarveoutLedgerError(
                "source row predates carveout lineage"
            )
        current_format += 1
        if raw_row.get("long_trend_carveout_decision") not in {
            "ADMIT",
            "BLOCK",
        }:
            unevaluable += 1
            continue
        row = _canonical_row(
            raw_row,
            overlap_started_at_ms=overlap,
            terminal_only=False,
        )
        markouts = cast(dict[str, dict[str, object]], row["markouts"])
        statuses = {
            cast(str, markout["status"])
            for markout in markouts.values()
        }
        if statuses <= TERMINAL_STATUSES:
            terminal.append(
                _canonical_row(
                    raw_row,
                    overlap_started_at_ms=overlap,
                    terminal_only=True,
                )
            )
        else:
            pending += 1

    if candidate.get("evaluated") != current_format - unevaluable:
        raise ProspectiveLongTrendCarveoutLedgerError(
            "source carveout evaluated count does not reconcile"
        )
    return (
        _canonical_rows(
            terminal,
            overlap_started_at_ms=overlap,
        ),
        pending,
        unevaluable,
        overlap,
        integrity,
        boundary_known,
        cast(int | None, raw_last_miss),
    )


def update_long_trend_carveout_ledger(
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

    source_rows, pending, unevaluable, overlap, source_integrity = (
        _source_rows(summary)
    )
    previous_rows: tuple[dict[str, object], ...] = ()
    history: list[object] = []
    prior_ledger_sha256: str | None = None

    if previous is not None:
        validated = validate_long_trend_carveout_ledger(previous)
        if validated.get("overlap_started_at_ms") != overlap:
            raise ProspectiveLongTrendCarveoutLedgerError(
                "carveout overlap start drift"
            )
        raw_history = validated.get("source_history")
        if not isinstance(raw_history, list):
            raise ProspectiveLongTrendCarveoutLedgerError(
                "previous source history is invalid"
            )
        for item in raw_history:
            if not isinstance(item, dict):
                raise ProspectiveLongTrendCarveoutLedgerError(
                    "previous source history entry is invalid"
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
                    raise ProspectiveLongTrendCarveoutLedgerError(
                        "duplicate source artifact drift"
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
                raise ProspectiveLongTrendCarveoutLedgerError(
                    "previous terminal carveout row disappeared"
                )
            if current != old:
                raise ProspectiveLongTrendCarveoutLedgerError(
                    "previous terminal carveout row changed"
                )

    previous_ids = {
        cast(str, row["opportunity_id"]) for row in previous_rows
    }
    new_rows = tuple(
        row
        for row in source_rows
        if cast(str, row["opportunity_id"]) not in previous_ids
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
            "unevaluable_opportunity_count": unevaluable,
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
        "candidate_id": LONG_TREND_CARVEOUT_CANDIDATE_ID,
        "overlap_started_at_ms": overlap,
        "forward_horizons_ms": list(FORWARD_HORIZONS_MS),
        "max_mark_lag_ms": MAX_MARK_LAG_MS,
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
        "unevaluable_opportunity_count": unevaluable,
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
