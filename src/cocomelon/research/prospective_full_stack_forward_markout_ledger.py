from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final, cast

from cocomelon.domain.strategy import Direction
from cocomelon.research.prospective_combined_entry_filter import (
    ProspectiveCombinedEntryFilterState,
    prospective_combined_block_reason,
)
from cocomelon.research.prospective_full_stack_forward_markout import (
    MIN_ADMIT_SETTLED_PER_HORIZON,
    MIN_BLOCK_SETTLED_PER_HORIZON,
    MIN_LONG_SETTLED_PER_HORIZON,
    MIN_MARKETS_PER_HORIZON,
    MIN_SETTLED_PER_HORIZON,
    MIN_SHORT_SETTLED_PER_HORIZON,
)
from cocomelon.research.prospective_momentum_band_entry import (
    MAX_SIGNED_DAY_RETURN,
    MIN_SIGNED_RETURN_1H,
    ProspectiveMomentumBandEntryState,
)
from cocomelon.research.prospective_momentum_band_forward_markout import (
    FORWARD_HORIZONS_MS,
    MAX_MARK_LAG_MS,
)
from cocomelon.research.prospective_two_strike_stop_filter import (
    STRIKE_THRESHOLD,
    ProspectiveTwoStrikeStopFilterState,
)

LEDGER_SCHEMA_VERSION: Final = 1
LEDGER_KIND: Final = "prospective-full-stack-forward-markout-ledger-v1"
STACK_ID: Final = "combined+two_strike+momentum"
TERMINAL_STATUSES: Final = frozenset({"settled", "stale"})
PENDING_STATUSES: Final = frozenset({"pending", "missing_path"})
ZERO: Final = Decimal("0")


class ProspectiveFullStackForwardMarkoutLedgerError(RuntimeError):
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
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            f"{key} must be a non-empty string"
        )
    return value


def _required_int(raw: dict[str, object], key: str) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            f"{key} must be an integer"
        )
    return value


def _decimal_string(
    value: object,
    *,
    field: str,
) -> str:
    if not isinstance(value, str):
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            f"{field} must be a decimal string"
        )
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            f"{field} must be a decimal string"
        ) from exc
    if not parsed.is_finite():
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            f"{field} must be finite"
        )
    return value


def _optional_decimal_string(
    value: object,
    *,
    field: str,
) -> str | None:
    if value is None:
        return None
    return _decimal_string(value, field=field)


def _optional_string(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            f"{field} must be null or a non-empty string"
        )
    return value


def _optional_int(value: object, *, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            f"{field} must be null or an integer"
        )
    return value


def _row_identity(row: dict[str, object]) -> tuple[int, str]:
    return (
        cast(int, row["timestamp_ms"]),
        cast(str, row["opportunity_id"]),
    )


def _canonical_markout(
    raw: object,
    *,
    opportunity_timestamp_ms: int,
    horizon_ms: int,
    terminal_only: bool,
) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            "markout must be an object"
        )
    status = _required_string(raw, "status")
    if status not in TERMINAL_STATUSES | PENDING_STATUSES:
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            f"unsupported markout status: {status}"
        )
    if terminal_only and status not in TERMINAL_STATUSES:
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            "immutable full-stack markout row is not terminal"
        )

    target_at_ms = _required_int(raw, "target_at_ms")
    if target_at_ms != opportunity_timestamp_ms + horizon_ms:
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            "markout target does not match fixed horizon"
        )
    observed_at_ms = raw.get("observed_at_ms")
    observation_lag_ms = raw.get("observation_lag_ms")
    mark_px = raw.get("mark_px")
    directional_return = raw.get("directional_return")

    if status in PENDING_STATUSES:
        if any(
            value is not None
            for value in (
                observed_at_ms,
                observation_lag_ms,
                mark_px,
                directional_return,
            )
        ):
            raise ProspectiveFullStackForwardMarkoutLedgerError(
                "pending markout contains terminal evidence"
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
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            "terminal markout timestamp is invalid"
        )
    if (
        isinstance(observation_lag_ms, bool)
        or not isinstance(observation_lag_ms, int)
        or observation_lag_ms != observed_at_ms - target_at_ms
    ):
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            "terminal markout lag does not reconcile"
        )
    parsed_mark = Decimal(
        _decimal_string(mark_px, field="mark_px")
    )
    if parsed_mark <= ZERO:
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            "terminal mark price must be positive"
        )
    if status == "settled":
        if observation_lag_ms > MAX_MARK_LAG_MS:
            raise ProspectiveFullStackForwardMarkoutLedgerError(
                "settled markout exceeds maximum lag"
            )
        parsed_return = _decimal_string(
            directional_return,
            field="directional_return",
        )
    else:
        if observation_lag_ms <= MAX_MARK_LAG_MS:
            raise ProspectiveFullStackForwardMarkoutLedgerError(
                "stale markout does not exceed maximum lag"
            )
        if directional_return is not None:
            raise ProspectiveFullStackForwardMarkoutLedgerError(
                "stale markout must not carry directional return"
            )
        parsed_return = None
    return {
        "status": status,
        "target_at_ms": target_at_ms,
        "observed_at_ms": observed_at_ms,
        "observation_lag_ms": observation_lag_ms,
        "mark_px": str(parsed_mark),
        "directional_return": parsed_return,
    }


def _validate_momentum_fields(
    *,
    decision: str,
    reason: str,
    prior_strikes: int,
    signed_return_1h: str | None,
    signed_day_return: str | None,
) -> None:
    if reason == "nonzero_strike_bypass":
        if (
            prior_strikes <= 0
            or decision != "ADMIT"
            or signed_return_1h is not None
            or signed_day_return is not None
        ):
            raise ProspectiveFullStackForwardMarkoutLedgerError(
                "momentum bypass evidence is inconsistent"
            )
        return
    if reason not in {"momentum_band", "momentum_band_pass"}:
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            "momentum reason is unsupported"
        )
    if (
        prior_strikes != 0
        or signed_return_1h is None
        or signed_day_return is None
    ):
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            "momentum-band evidence is incomplete"
        )
    should_block = (
        Decimal(signed_return_1h) < MIN_SIGNED_RETURN_1H
        or Decimal(signed_day_return) > MAX_SIGNED_DAY_RETURN
    )
    expected_decision = "BLOCK" if should_block else "ADMIT"
    expected_reason = (
        "momentum_band" if should_block else "momentum_band_pass"
    )
    if decision != expected_decision or reason != expected_reason:
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            "momentum decision does not match frozen thresholds"
        )


def _canonical_row(
    raw: object,
    *,
    overlap_started_at_ms: int,
    terminal_only: bool,
) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            "ledger row must be an object"
        )
    opportunity_id = _required_string(raw, "opportunity_id")
    timestamp_ms = _required_int(raw, "timestamp_ms")
    if timestamp_ms < overlap_started_at_ms:
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            "full-stack markout row predates common clean start"
        )
    market = _required_string(raw, "market")
    direction = _required_string(raw, "direction")
    if direction not in {"long", "short"}:
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            "row direction must be long or short"
        )
    direction_enum = Direction(direction)
    lead_strategy = _required_string(raw, "lead_strategy")
    rank_ordinal = _required_int(raw, "rank_ordinal")
    rank_age_ms = _required_int(raw, "rank_age_ms")
    if rank_ordinal <= 0 or rank_age_ms < 0:
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            "rank evidence is invalid"
        )
    combined_reason = _optional_string(
        raw.get("combined_block_reason"),
        field="combined_block_reason",
    )
    expected_combined_reason = prospective_combined_block_reason(
        direction=direction_enum,
        lead_strategy=lead_strategy,
        ordinal=rank_ordinal,
    )
    if combined_reason != expected_combined_reason:
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            "combined decision does not match frozen rule"
        )

    two_strike_prior_strikes = _required_int(
        raw,
        "two_strike_prior_strikes",
    )
    if two_strike_prior_strikes < 0:
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            "two-strike prior strikes must be non-negative"
        )
    stack_decision = _required_string(raw, "stack_decision")
    if stack_decision not in {"ADMIT", "BLOCK"}:
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            "stack decision must be ADMIT or BLOCK"
        )
    block_layer = _required_string(raw, "block_layer")
    if block_layer not in {
        "combined",
        "two_strike",
        "momentum",
        "none",
    }:
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            "full-stack block layer is unsupported"
        )

    momentum_decision = _optional_string(
        raw.get("momentum_decision"),
        field="momentum_decision",
    )
    momentum_reason = _optional_string(
        raw.get("momentum_reason"),
        field="momentum_reason",
    )
    momentum_prior_strikes = _optional_int(
        raw.get("momentum_prior_strikes"),
        field="momentum_prior_strikes",
    )
    signed_return_1h = _optional_decimal_string(
        raw.get("signed_return_1h"),
        field="signed_return_1h",
    )
    signed_day_return = _optional_decimal_string(
        raw.get("signed_day_return"),
        field="signed_day_return",
    )

    if expected_combined_reason is not None:
        expected_stack = "BLOCK"
        expected_layer = "combined"
        if any(
            value is not None
            for value in (
                momentum_decision,
                momentum_reason,
                momentum_prior_strikes,
                signed_return_1h,
                signed_day_return,
            )
        ):
            raise ProspectiveFullStackForwardMarkoutLedgerError(
                "combined-blocked row contains downstream momentum evidence"
            )
    elif two_strike_prior_strikes >= STRIKE_THRESHOLD:
        expected_stack = "BLOCK"
        expected_layer = "two_strike"
        if any(
            value is not None
            for value in (
                momentum_decision,
                momentum_reason,
                momentum_prior_strikes,
                signed_return_1h,
                signed_day_return,
            )
        ):
            raise ProspectiveFullStackForwardMarkoutLedgerError(
                "two-strike-blocked row contains momentum evidence"
            )
    else:
        if (
            momentum_decision is None
            or momentum_reason is None
            or momentum_prior_strikes is None
        ):
            raise ProspectiveFullStackForwardMarkoutLedgerError(
                "momentum-evaluated row is missing evidence"
            )
        _validate_momentum_fields(
            decision=momentum_decision,
            reason=momentum_reason,
            prior_strikes=momentum_prior_strikes,
            signed_return_1h=signed_return_1h,
            signed_day_return=signed_day_return,
        )
        expected_stack = momentum_decision
        expected_layer = (
            "momentum" if momentum_decision == "BLOCK" else "none"
        )
    if stack_decision != expected_stack or block_layer != expected_layer:
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            "stack decision does not match frozen layer ordering"
        )

    raw_markouts = raw.get("markouts")
    if not isinstance(raw_markouts, dict):
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            "row markouts must be an object"
        )
    expected_keys = {str(value) for value in FORWARD_HORIZONS_MS}
    if set(raw_markouts) != expected_keys:
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            "row markout horizons drift"
        )
    markouts = {
        str(horizon_ms): _canonical_markout(
            raw_markouts[str(horizon_ms)],
            opportunity_timestamp_ms=timestamp_ms,
            horizon_ms=horizon_ms,
            terminal_only=terminal_only,
        )
        for horizon_ms in FORWARD_HORIZONS_MS
    }
    return {
        "opportunity_id": opportunity_id,
        "timestamp_ms": timestamp_ms,
        "market": market,
        "direction": direction,
        "lead_strategy": lead_strategy,
        "rank_ordinal": rank_ordinal,
        "rank_age_ms": rank_age_ms,
        "combined_block_reason": combined_reason,
        "two_strike_prior_strikes": two_strike_prior_strikes,
        "momentum_decision": momentum_decision,
        "momentum_reason": momentum_reason,
        "momentum_prior_strikes": momentum_prior_strikes,
        "signed_return_1h": signed_return_1h,
        "signed_day_return": signed_day_return,
        "stack_decision": stack_decision,
        "block_layer": block_layer,
        "markouts": markouts,
    }


def _canonical_rows(
    raw: object,
    *,
    overlap_started_at_ms: int,
) -> tuple[dict[str, object], ...]:
    if not isinstance(raw, (list, tuple)):
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            "ledger rows must be a list"
        )
    rows = tuple(
        _canonical_row(
            row,
            overlap_started_at_ms=overlap_started_at_ms,
            terminal_only=True,
        )
        for row in raw
    )
    identities = tuple(_row_identity(row) for row in rows)
    if len(identities) != len(set(identities)):
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            "duplicate full-stack markout row identity"
        )
    ids = tuple(cast(str, row["opportunity_id"]) for row in rows)
    if len(ids) != len(set(ids)):
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            "duplicate full-stack opportunity id"
        )
    return tuple(sorted(rows, key=_row_identity))


def _rows_sha256(rows: tuple[dict[str, object], ...]) -> str:
    payload = "\n".join(_canonical_json(row) for row in rows)
    if payload:
        payload += "\n"
    return _sha256_text(payload)


def _spread(
    values: Sequence[tuple[str, str, Decimal]],
) -> Decimal | None:
    admits = tuple(v for d, _m, v in values if d == "ADMIT")
    blocks = tuple(v for d, _m, v in values if d == "BLOCK")
    if not admits or not blocks:
        return None
    return (
        sum(admits, ZERO) / Decimal(len(admits))
        - sum(blocks, ZERO) / Decimal(len(blocks))
    )


def _horizon_summary(
    rows: tuple[dict[str, object], ...],
    *,
    horizon_ms: int,
    integrity_clean: bool,
) -> dict[str, object]:
    key = str(horizon_ms)
    settled: list[tuple[str, str, str, Decimal]] = []
    stale = 0
    for row in rows:
        markouts = cast(dict[str, dict[str, object]], row["markouts"])
        markout = markouts[key]
        if markout["status"] == "stale":
            stale += 1
            continue
        value = Decimal(cast(str, markout["directional_return"]))
        settled.append(
            (
                cast(str, row["stack_decision"]),
                cast(str, row["market"]),
                cast(str, row["direction"]),
                value,
            )
        )
    admits = tuple(item for item in settled if item[0] == "ADMIT")
    blocks = tuple(item for item in settled if item[0] == "BLOCK")
    admit_mean = (
        None
        if not admits
        else sum((item[3] for item in admits), ZERO)
        / Decimal(len(admits))
    )
    block_mean = (
        None
        if not blocks
        else sum((item[3] for item in blocks), ZERO)
        / Decimal(len(blocks))
    )
    simple = tuple(
        (decision, market, value)
        for decision, market, _direction, value in settled
    )
    full_spread = _spread(simple)
    leave_one = tuple(
        candidate
        for index in range(len(simple))
        if (
            candidate := _spread(simple[:index] + simple[index + 1 :])
        )
        is not None
    )
    markets = tuple(sorted({item[1] for item in settled}))
    leave_market = tuple(
        candidate
        for market in markets
        if (
            candidate := _spread(
                tuple(item for item in simple if item[1] != market)
            )
        )
        is not None
    )
    long_count = sum(item[2] == "long" for item in settled)
    short_count = sum(item[2] == "short" for item in settled)
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
        and full_spread is not None
        and admit_mean > ZERO
        and block_mean < ZERO
        and full_spread > ZERO
    )
    opportunity_robust = (
        len(leave_one) == len(simple)
        and bool(leave_one)
        and min(leave_one) > ZERO
    )
    market_robust = (
        len(leave_market) == len(markets)
        and bool(leave_market)
        and min(leave_market) > ZERO
    )
    return {
        "horizon_ms": horizon_ms,
        "terminal_opportunities": len(rows),
        "settled_opportunities": len(settled),
        "stale_opportunities": stale,
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
        "admit_minus_block_mean_return": (
            None if full_spread is None else str(full_spread)
        ),
        "leave_one_opportunity_min_spread": (
            None if not leave_one else str(min(leave_one))
        ),
        "leave_one_market_min_spread": (
            None if not leave_market else str(min(leave_market))
        ),
        "block_layer_counts": dict(
            sorted(
                Counter(
                    cast(str, row["block_layer"])
                    for row in rows
                    if row["stack_decision"] == "BLOCK"
                ).items()
            )
        ),
        "review_readiness": {
            "ready_for_early_evidence_review": (
                integrity_clean
                and sample_complete
                and separation_positive
                and opportunity_robust
                and market_robust
            ),
            "integrity_clean": integrity_clean,
            "sample_complete": sample_complete,
            "separation_positive": separation_positive,
            "single_opportunity_robust": opportunity_robust,
            "single_market_robust": market_robust,
            "min_settled_opportunities": MIN_SETTLED_PER_HORIZON,
            "min_admit_settled": MIN_ADMIT_SETTLED_PER_HORIZON,
            "min_block_settled": MIN_BLOCK_SETTLED_PER_HORIZON,
            "min_long_settled": MIN_LONG_SETTLED_PER_HORIZON,
            "min_short_settled": MIN_SHORT_SETTLED_PER_HORIZON,
            "min_markets": MIN_MARKETS_PER_HORIZON,
            "changes_closed_trade_readiness_gate": False,
        },
    }


def _summary(
    rows: tuple[dict[str, object], ...],
    *,
    pending_opportunity_count: int,
    integrity_clean: bool,
) -> dict[str, object]:
    return {
        "terminal_opportunity_count": len(rows),
        "pending_opportunity_count": pending_opportunity_count,
        "integrity_clean": integrity_clean,
        "stack_admitted_terminal": sum(
            row["stack_decision"] == "ADMIT" for row in rows
        ),
        "stack_blocked_terminal": sum(
            row["stack_decision"] == "BLOCK" for row in rows
        ),
        "block_layer_counts": dict(
            sorted(
                Counter(
                    cast(str, row["block_layer"])
                    for row in rows
                ).items()
            )
        ),
        "horizons": {
            str(horizon_ms): _horizon_summary(
                rows,
                horizon_ms=horizon_ms,
                integrity_clean=integrity_clean,
            )
            for horizon_ms in FORWARD_HORIZONS_MS
        },
    }


def _state_bundle(
    combined: ProspectiveCombinedEntryFilterState,
    two_strike: ProspectiveTwoStrikeStopFilterState,
    momentum: ProspectiveMomentumBandEntryState,
) -> dict[str, object]:
    return {
        "combined": combined.payload(),
        "two_strike": two_strike.payload(),
        "momentum": momentum.payload(),
    }


def _validate_state_bundle(
    raw: object,
) -> tuple[
    ProspectiveCombinedEntryFilterState,
    ProspectiveTwoStrikeStopFilterState,
    ProspectiveMomentumBandEntryState,
]:
    if not isinstance(raw, dict):
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            "full-stack state bundle must be an object"
        )
    try:
        combined = ProspectiveCombinedEntryFilterState.from_payload(
            raw.get("combined")
        )
        two_strike = ProspectiveTwoStrikeStopFilterState.from_payload(
            raw.get("two_strike")
        )
        momentum = ProspectiveMomentumBandEntryState.from_payload(
            raw.get("momentum")
        )
    except (ValueError, RuntimeError) as exc:
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            "full-stack state bundle is invalid"
        ) from exc
    return combined, two_strike, momentum


def validate_full_stack_forward_markout_ledger(
    raw: object,
) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            "full-stack markout ledger must be an object"
        )
    if raw.get("schema_version") != LEDGER_SCHEMA_VERSION:
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            "full-stack markout ledger schema is unsupported"
        )
    if raw.get("kind") != LEDGER_KIND:
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            "full-stack markout ledger kind is unsupported"
        )
    if raw.get("candidate_stack") != STACK_ID:
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            "full-stack candidate stack drift"
        )
    combined, two_strike, momentum = _validate_state_bundle(
        raw.get("states")
    )
    overlap_started_at_ms = _required_int(
        raw,
        "overlap_started_at_ms",
    )
    if overlap_started_at_ms != max(
        combined.started_at_ms,
        two_strike.started_at_ms,
        momentum.started_at_ms,
    ):
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            "full-stack markout clean start drift"
        )
    if raw.get("forward_horizons_ms") != list(FORWARD_HORIZONS_MS):
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            "full-stack markout horizon drift"
        )
    if raw.get("max_mark_lag_ms") != MAX_MARK_LAG_MS:
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            "full-stack markout lag contract drift"
        )
    rows = _canonical_rows(
        raw.get("rows"),
        overlap_started_at_ms=overlap_started_at_ms,
    )
    if raw.get("row_count") != len(rows):
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            "full-stack markout row count mismatch"
        )
    if raw.get("rows_sha256") != _rows_sha256(rows):
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            "full-stack markout row digest mismatch"
        )
    pending = _required_int(raw, "pending_opportunity_count")
    if pending < 0:
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            "full-stack markout pending count is invalid"
        )
    history = raw.get("source_history")
    if not isinstance(history, list):
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            "full-stack markout source history must be a list"
        )
    integrity_clean = all(
        isinstance(item, dict)
        and item.get("integrity_clean") is True
        for item in history
    )
    if raw.get("summary") != _summary(
        rows,
        pending_opportunity_count=pending,
        integrity_clean=integrity_clean,
    ):
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            "full-stack markout summary does not reconcile"
        )
    if (
        raw.get("research_only") is not True
        or raw.get("execution_authority") is not False
        or raw.get("promotion_authority") is not False
        or raw.get("changes_readiness_gate") is not False
        or raw.get("changes_closed_trade_readiness_gate") is not False
    ):
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            "full-stack markout ledger authority drift"
        )
    expected_digest = _sha256_text(
        _canonical_json(_digest_payload(raw))
    )
    if raw.get("ledger_sha256") != expected_digest:
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            "full-stack markout ledger digest mismatch"
        )
    return {**raw, "rows": rows}


def load_full_stack_forward_markout_ledger(
    path: str | Path,
) -> dict[str, object]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            "full-stack markout ledger file is invalid"
        ) from exc
    return validate_full_stack_forward_markout_ledger(raw)


def _source_rows(
    summary: object,
    combined: ProspectiveCombinedEntryFilterState,
    two_strike: ProspectiveTwoStrikeStopFilterState,
    momentum: ProspectiveMomentumBandEntryState,
) -> tuple[tuple[dict[str, object], ...], int, int, bool]:
    if not isinstance(summary, dict):
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            "full-stack forward-markout summary must be an object"
        )
    if summary.get("enabled") is not True or summary.get("error") is not None:
        raise ProspectiveFullStackForwardMarkoutLedgerError(
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
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            "full-stack forward-markout source authority drift"
        )
    if summary.get("candidate_stack") != STACK_ID:
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            "full-stack forward-markout candidate drift"
        )
    overlap_started_at_ms = _required_int(
        summary,
        "overlap_started_at_ms",
    )
    expected_overlap = max(
        combined.started_at_ms,
        two_strike.started_at_ms,
        momentum.started_at_ms,
    )
    if overlap_started_at_ms != expected_overlap:
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            "full-stack forward-markout clean start drift"
        )
    for key, expected in (
        ("combined_started_at_ms", combined.started_at_ms),
        ("two_strike_started_at_ms", two_strike.started_at_ms),
        ("momentum_started_at_ms", momentum.started_at_ms),
        ("forward_horizons_ms", list(FORWARD_HORIZONS_MS)),
        ("max_mark_lag_ms", MAX_MARK_LAG_MS),
    ):
        if summary.get(key) != expected:
            raise ProspectiveFullStackForwardMarkoutLedgerError(
                f"full-stack forward-markout metadata drift: {key}"
            )
    raw_rows = summary.get("rows")
    if not isinstance(raw_rows, list):
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            "full-stack forward-markout rows must be a list"
        )
    evaluated = _required_int(
        summary,
        "stack_risk_approved_evaluated",
    )
    if evaluated != len(raw_rows):
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            "full-stack evaluated count does not reconcile"
        )

    terminal: list[dict[str, object]] = []
    pending = 0
    for raw_row in raw_rows:
        row = _canonical_row(
            raw_row,
            overlap_started_at_ms=overlap_started_at_ms,
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
                    row,
                    overlap_started_at_ms=overlap_started_at_ms,
                    terminal_only=True,
                )
            )
        else:
            pending += 1
    canonical = _canonical_rows(
        terminal,
        overlap_started_at_ms=overlap_started_at_ms,
    )
    return (
        canonical,
        pending,
        overlap_started_at_ms,
        summary.get("integrity_clean") is True,
    )


def update_full_stack_forward_markout_ledger(
    summary: object,
    combined: ProspectiveCombinedEntryFilterState,
    two_strike: ProspectiveTwoStrikeStopFilterState,
    momentum: ProspectiveMomentumBandEntryState,
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

    (
        source_rows,
        pending_count,
        overlap_started_at_ms,
        source_integrity_clean,
    ) = _source_rows(
        summary,
        combined,
        two_strike,
        momentum,
    )
    states = _state_bundle(combined, two_strike, momentum)
    previous_rows: tuple[dict[str, object], ...] = ()
    history: list[object] = []
    prior_ledger_sha256: str | None = None

    if previous is not None:
        validated = validate_full_stack_forward_markout_ledger(previous)
        for key, expected in (
            ("candidate_stack", STACK_ID),
            ("states", states),
            ("overlap_started_at_ms", overlap_started_at_ms),
            ("forward_horizons_ms", list(FORWARD_HORIZONS_MS)),
            ("max_mark_lag_ms", MAX_MARK_LAG_MS),
        ):
            if validated.get(key) != expected:
                raise ProspectiveFullStackForwardMarkoutLedgerError(
                    f"full-stack markout metadata drift: {key}"
                )
        raw_history = validated.get("source_history")
        if not isinstance(raw_history, list):
            raise ProspectiveFullStackForwardMarkoutLedgerError(
                "full-stack source history is invalid"
            )
        for item in raw_history:
            if not isinstance(item, dict):
                raise ProspectiveFullStackForwardMarkoutLedgerError(
                    "full-stack source history entry is invalid"
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
                    raise ProspectiveFullStackForwardMarkoutLedgerError(
                        "duplicate full-stack source artifact drift"
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
                raise ProspectiveFullStackForwardMarkoutLedgerError(
                    "previous terminal full-stack markout row disappeared"
                )
            if current != old:
                raise ProspectiveFullStackForwardMarkoutLedgerError(
                    "previous terminal full-stack markout row changed"
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
            "pending_opportunity_count": pending_count,
            "integrity_clean": source_integrity_clean,
            "rows_sha256": _rows_sha256(rows),
        }
    )
    cumulative_integrity_clean = all(
        isinstance(item, dict)
        and item.get("integrity_clean") is True
        for item in history
    )
    payload: dict[str, object] = {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "kind": LEDGER_KIND,
        "candidate_stack": STACK_ID,
        "states": states,
        "overlap_started_at_ms": overlap_started_at_ms,
        "forward_horizons_ms": list(FORWARD_HORIZONS_MS),
        "max_mark_lag_ms": MAX_MARK_LAG_MS,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_readiness_gate": False,
        "changes_closed_trade_readiness_gate": False,
        "prior_ledger_sha256": prior_ledger_sha256,
        "row_count": len(rows),
        "previous_row_count": len(previous_rows),
        "new_row_count": len(new_rows),
        "pending_opportunity_count": pending_count,
        "rows_sha256": _rows_sha256(rows),
        "source_history": history,
        "summary": _summary(
            rows,
            pending_opportunity_count=pending_count,
            integrity_clean=cumulative_integrity_clean,
        ),
        "rows": rows,
    }
    payload["ledger_sha256"] = _sha256_text(
        _canonical_json(_digest_payload(payload))
    )
    return payload
