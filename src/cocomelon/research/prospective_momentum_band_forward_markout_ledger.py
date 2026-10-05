from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final, cast

from cocomelon.research.prospective_momentum_band_entry import (
    EMBARGO_MS,
    MAX_SIGNED_DAY_RETURN,
    MIN_SIGNED_RETURN_1H,
    ProspectiveMomentumBandEntryState,
)
from cocomelon.research.prospective_momentum_band_forward_markout import (
    FORWARD_HORIZONS_MS,
    MAX_MARK_LAG_MS,
)

LEDGER_SCHEMA_VERSION: Final = 1
LEDGER_KIND: Final = "prospective-momentum-band-forward-markout-ledger-v1"
TERMINAL_STATUSES: Final = frozenset({"settled", "stale"})
PENDING_STATUSES: Final = frozenset({"pending", "missing_path"})
MIN_SETTLED_PER_HORIZON: Final = 20
MIN_ADMIT_SETTLED_PER_HORIZON: Final = 5
MIN_BLOCK_SETTLED_PER_HORIZON: Final = 5
MIN_LONG_SETTLED_PER_HORIZON: Final = 5
MIN_SHORT_SETTLED_PER_HORIZON: Final = 5
MIN_MARKETS_PER_HORIZON: Final = 4
ZERO: Final = Decimal("0")


class ProspectiveMomentumBandForwardMarkoutLedgerError(RuntimeError):
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
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            f"{key} must be a non-empty string"
        )
    return value


def _required_int(raw: dict[str, object], key: str) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            f"{key} must be an integer"
        )
    return value


def _decimal_string(
    value: object,
    *,
    field: str,
) -> str:
    if not isinstance(value, str):
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            f"{field} must be a decimal string"
        )
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            f"{field} must be a decimal string"
        ) from exc
    if not parsed.is_finite():
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
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
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            "markout must be an object"
        )
    status = _required_string(raw, "status")
    supported = TERMINAL_STATUSES | PENDING_STATUSES
    if status not in supported:
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            f"unsupported markout status: {status}"
        )
    if terminal_only and status not in TERMINAL_STATUSES:
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            "immutable markout row contains a non-terminal horizon"
        )

    target_at_ms = _required_int(raw, "target_at_ms")
    expected_target = opportunity_timestamp_ms + horizon_ms
    if target_at_ms != expected_target:
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
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
            raise ProspectiveMomentumBandForwardMarkoutLedgerError(
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
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            "terminal markout observed timestamp is invalid"
        )
    if (
        isinstance(observation_lag_ms, bool)
        or not isinstance(observation_lag_ms, int)
        or observation_lag_ms != observed_at_ms - target_at_ms
    ):
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            "terminal markout lag does not reconcile"
        )
    parsed_mark = Decimal(
        _decimal_string(mark_px, field="mark_px")
    )
    if parsed_mark <= ZERO:
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            "terminal mark price must be positive"
        )

    if status == "settled":
        if observation_lag_ms > MAX_MARK_LAG_MS:
            raise ProspectiveMomentumBandForwardMarkoutLedgerError(
                "settled markout exceeds maximum lag"
            )
        parsed_return = _decimal_string(
            directional_return,
            field="directional_return",
        )
    else:
        if observation_lag_ms <= MAX_MARK_LAG_MS:
            raise ProspectiveMomentumBandForwardMarkoutLedgerError(
                "stale markout does not exceed maximum lag"
            )
        if directional_return is not None:
            raise ProspectiveMomentumBandForwardMarkoutLedgerError(
                "stale markout must not carry a directional return"
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


def _canonical_row(
    raw: object,
    *,
    overlap_started_at_ms: int,
    terminal_only: bool,
) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            "ledger row must be an object"
        )
    opportunity_id = _required_string(raw, "opportunity_id")
    timestamp_ms = _required_int(raw, "timestamp_ms")
    if timestamp_ms < overlap_started_at_ms:
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            "momentum markout row predates common clean start"
        )
    market = _required_string(raw, "market")
    direction = _required_string(raw, "direction")
    if direction not in {"long", "short"}:
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            "row direction must be long or short"
        )
    lead_strategy = _required_string(raw, "lead_strategy")
    rank_ordinal = _required_int(raw, "rank_ordinal")
    rank_age_ms = _required_int(raw, "rank_age_ms")
    two_strike_prior_strikes = _required_int(
        raw,
        "two_strike_prior_strikes",
    )
    if (
        rank_ordinal <= 0
        or rank_age_ms < 0
        or two_strike_prior_strikes < 0
    ):
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            "rank or strike metadata is invalid"
        )

    decision = _required_string(raw, "momentum_decision")
    if decision not in {"ADMIT", "BLOCK"}:
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            "momentum decision must be ADMIT or BLOCK"
        )
    reason = _required_string(raw, "momentum_reason")
    if reason not in {
        "momentum_band",
        "momentum_band_pass",
        "nonzero_strike_bypass",
    }:
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            "momentum reason is unsupported"
        )
    prior_strikes = _required_int(raw, "momentum_prior_strikes")
    if prior_strikes < 0:
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            "momentum prior strikes must be non-negative"
        )
    signed_return_1h = _optional_decimal_string(
        raw.get("signed_return_1h"),
        field="signed_return_1h",
    )
    signed_day_return = _optional_decimal_string(
        raw.get("signed_day_return"),
        field="signed_day_return",
    )
    if reason == "nonzero_strike_bypass":
        if (
            prior_strikes <= 0
            or decision != "ADMIT"
            or signed_return_1h is not None
            or signed_day_return is not None
        ):
            raise ProspectiveMomentumBandForwardMarkoutLedgerError(
                "nonzero-strike momentum bypass is inconsistent"
            )
    else:
        if (
            prior_strikes != 0
            or signed_return_1h is None
            or signed_day_return is None
        ):
            raise ProspectiveMomentumBandForwardMarkoutLedgerError(
                "momentum-band row is missing frozen feature evidence"
            )
        should_block = (
            Decimal(signed_return_1h) < MIN_SIGNED_RETURN_1H
            or Decimal(signed_day_return) > MAX_SIGNED_DAY_RETURN
        )
        expected_reason = (
            "momentum_band" if should_block else "momentum_band_pass"
        )
        expected_decision = "BLOCK" if should_block else "ADMIT"
        if reason != expected_reason or decision != expected_decision:
            raise ProspectiveMomentumBandForwardMarkoutLedgerError(
                "momentum decision does not match frozen thresholds"
            )

    raw_markouts = raw.get("markouts")
    if not isinstance(raw_markouts, dict):
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            "row markouts must be an object"
        )
    expected_keys = {str(value) for value in FORWARD_HORIZONS_MS}
    if set(raw_markouts) != expected_keys:
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            "row markout horizons do not match frozen horizons"
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
        "two_strike_prior_strikes": two_strike_prior_strikes,
        "momentum_decision": decision,
        "momentum_reason": reason,
        "momentum_prior_strikes": prior_strikes,
        "signed_return_1h": signed_return_1h,
        "signed_day_return": signed_day_return,
        "markouts": markouts,
    }


def _canonical_rows(
    raw: object,
    *,
    overlap_started_at_ms: int,
) -> tuple[dict[str, object], ...]:
    if not isinstance(raw, (list, tuple)):
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
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
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            "duplicate momentum markout row identity"
        )
    ids = tuple(cast(str, row["opportunity_id"]) for row in rows)
    if len(ids) != len(set(ids)):
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            "duplicate momentum markout opportunity id"
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
        raw_return = cast(str, markout["directional_return"])
        settled.append(
            (
                cast(str, row["momentum_decision"]),
                cast(str, row["market"]),
                cast(str, row["direction"]),
                Decimal(raw_return),
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
            candidate := _spread(
                simple[:index] + simple[index + 1 :]
            )
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
            "missing_settled_opportunities": max(
                0,
                MIN_SETTLED_PER_HORIZON - len(settled),
            ),
            "missing_admit_settled": max(
                0,
                MIN_ADMIT_SETTLED_PER_HORIZON - len(admits),
            ),
            "missing_block_settled": max(
                0,
                MIN_BLOCK_SETTLED_PER_HORIZON - len(blocks),
            ),
            "missing_long_settled": max(
                0,
                MIN_LONG_SETTLED_PER_HORIZON - long_count,
            ),
            "missing_short_settled": max(
                0,
                MIN_SHORT_SETTLED_PER_HORIZON - short_count,
            ),
            "missing_markets": max(
                0,
                MIN_MARKETS_PER_HORIZON - len(markets),
            ),
            "changes_closed_trade_readiness_gate": False,
        },
    }


def _post_integrity_miss_summary(
    rows: tuple[dict[str, object], ...],
    *,
    overlap_started_at_ms: int,
    boundary_known: bool,
    last_miss_at_ms: int | None,
) -> dict[str, object]:
    if not boundary_known:
        return {
            "boundary_known": False,
            "last_miss_at_ms": None,
            "started_at_ms": None,
            "terminal_opportunity_count": 0,
            "all_horizons_ready_for_early_evidence_review": False,
            "horizons": {},
            "changes_closed_trade_readiness_gate": False,
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
    horizons = {
        str(horizon_ms): _horizon_summary(
            clean_rows,
            horizon_ms=horizon_ms,
            integrity_clean=True,
        )
        for horizon_ms in FORWARD_HORIZONS_MS
    }
    all_ready = all(
        cast(dict[str, object], item["review_readiness"])[
            "ready_for_early_evidence_review"
        ]
        is True
        for item in horizons.values()
    )
    return {
        "boundary_known": True,
        "last_miss_at_ms": last_miss_at_ms,
        "started_at_ms": started_at_ms,
        "terminal_opportunity_count": len(clean_rows),
        "all_horizons_ready_for_early_evidence_review": all_ready,
        "horizons": horizons,
        "changes_closed_trade_readiness_gate": False,
    }


def _summary(
    rows: tuple[dict[str, object], ...],
    *,
    pending_opportunity_count: int,
    integrity_clean: bool,
    include_post_integrity_readiness: bool = True,
    overlap_started_at_ms: int | None = None,
    integrity_boundary_known: bool = False,
    integrity_last_miss_at_ms: int | None = None,
) -> dict[str, object]:
    horizons = {
        str(horizon_ms): _horizon_summary(
            rows,
            horizon_ms=horizon_ms,
            integrity_clean=integrity_clean,
        )
        for horizon_ms in FORWARD_HORIZONS_MS
    }
    result: dict[str, object] = {
        "terminal_opportunity_count": len(rows),
        "pending_opportunity_count": pending_opportunity_count,
        "integrity_clean": integrity_clean,
        "momentum_admitted_terminal": sum(
            row["momentum_decision"] == "ADMIT" for row in rows
        ),
        "momentum_blocked_terminal": sum(
            row["momentum_decision"] == "BLOCK" for row in rows
        ),
        "horizons": horizons,
    }
    if not include_post_integrity_readiness:
        return result
    if overlap_started_at_ms is None:
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            "post-integrity cohort requires overlap start"
        )

    cumulative_ready = all(
        cast(dict[str, object], item["review_readiness"])[
            "ready_for_early_evidence_review"
        ]
        is True
        for item in horizons.values()
    )
    post_integrity = _post_integrity_miss_summary(
        rows,
        overlap_started_at_ms=overlap_started_at_ms,
        boundary_known=integrity_boundary_known,
        last_miss_at_ms=integrity_last_miss_at_ms,
    )
    post_ready = (
        post_integrity[
            "all_horizons_ready_for_early_evidence_review"
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

    result["all_horizons_ready_for_early_evidence_review"] = (
        cumulative_ready
    )
    result["post_integrity_miss"] = post_integrity
    result[
        "effective_all_horizons_ready_for_early_evidence_review"
    ] = effective_ready
    result["effective_integrity_scope"] = effective_scope
    return result


def _validate_metadata(
    raw: dict[str, object],
) -> ProspectiveMomentumBandEntryState:
    if raw.get("schema_version") != LEDGER_SCHEMA_VERSION:
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            "momentum markout ledger schema is unsupported"
        )
    if raw.get("kind") != LEDGER_KIND:
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            "momentum markout ledger kind is unsupported"
        )
    frozen_at_ms = _required_int(raw, "frozen_at_ms")
    candidate_id = _required_string(raw, "candidate_id")
    try:
        state = ProspectiveMomentumBandEntryState(
            frozen_at_ms=frozen_at_ms,
            candidate_id=candidate_id,
        )
    except ValueError as exc:
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            str(exc)
        ) from exc
    if raw.get("started_at_ms") != state.started_at_ms:
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            "momentum markout ledger clean start drift"
        )
    if raw.get("embargo_ms") != EMBARGO_MS:
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            "momentum markout ledger embargo drift"
        )
    if raw.get("rule") != state.payload()["rule"]:
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            "momentum markout ledger rule drift"
        )
    overlap_started_at_ms = _required_int(
        raw,
        "overlap_started_at_ms",
    )
    if overlap_started_at_ms < state.started_at_ms:
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            "momentum markout overlap predates candidate clean start"
        )
    if raw.get("forward_horizons_ms") != list(FORWARD_HORIZONS_MS):
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            "momentum markout horizons drift"
        )
    if raw.get("max_mark_lag_ms") != MAX_MARK_LAG_MS:
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            "momentum markout lag contract drift"
        )
    return state


def validate_momentum_forward_markout_ledger(
    raw: object,
) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            "momentum markout ledger must be an object"
        )
    _validate_metadata(raw)
    overlap_started_at_ms = _required_int(
        raw,
        "overlap_started_at_ms",
    )
    rows = _canonical_rows(
        raw.get("rows"),
        overlap_started_at_ms=overlap_started_at_ms,
    )
    if raw.get("row_count") != len(rows):
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            "momentum markout row count mismatch"
        )
    if raw.get("rows_sha256") != _rows_sha256(rows):
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            "momentum markout row digest mismatch"
        )
    pending = _required_int(raw, "pending_opportunity_count")
    if pending < 0:
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            "momentum markout pending count is invalid"
        )
    history = raw.get("source_history")
    if not isinstance(history, list):
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            "momentum markout source history must be a list"
        )
    integrity_clean = all(
        isinstance(item, dict)
        and item.get("integrity_clean") is True
        for item in history
    )
    latest_boundary_known = False
    latest_last_miss: int | None = None
    if history:
        latest_history = history[-1]
        if not isinstance(latest_history, dict):
            raise ProspectiveMomentumBandForwardMarkoutLedgerError(
                "latest momentum markout source history is invalid"
            )
        latest_boundary_known = (
            latest_history.get("integrity_boundary_known") is True
            or (
                "integrity_boundary_known" not in latest_history
                and latest_history.get("integrity_clean") is True
            )
        )
        raw_last_miss = latest_history.get("integrity_last_miss_at_ms")
        if raw_last_miss is not None and (
            isinstance(raw_last_miss, bool)
            or not isinstance(raw_last_miss, int)
        ):
            raise ProspectiveMomentumBandForwardMarkoutLedgerError(
                "latest momentum integrity miss boundary is invalid"
            )
        latest_last_miss = cast(int | None, raw_last_miss)

    expected_current = _summary(
        rows,
        pending_opportunity_count=pending,
        integrity_clean=integrity_clean,
        overlap_started_at_ms=overlap_started_at_ms,
        integrity_boundary_known=latest_boundary_known,
        integrity_last_miss_at_ms=latest_last_miss,
    )
    expected_legacy = _summary(
        rows,
        pending_opportunity_count=pending,
        integrity_clean=integrity_clean,
        include_post_integrity_readiness=False,
    )
    if raw.get("summary") not in (expected_current, expected_legacy):
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            "momentum markout summary does not reconcile"
        )
    if (
        raw.get("research_only") is not True
        or raw.get("execution_authority") is not False
        or raw.get("promotion_authority") is not False
        or raw.get("changes_readiness_gate") is not False
    ):
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            "momentum markout ledger authority drift"
        )
    expected_digest = _sha256_text(
        _canonical_json(_digest_payload(raw))
    )
    if raw.get("ledger_sha256") != expected_digest:
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            "momentum markout ledger digest mismatch"
        )
    return {**raw, "rows": rows}


def load_momentum_forward_markout_ledger(
    path: str | Path,
) -> dict[str, object]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            "momentum markout ledger file is invalid"
        ) from exc
    return validate_momentum_forward_markout_ledger(raw)


def _source_rows(
    summary: object,
    state: ProspectiveMomentumBandEntryState,
) -> tuple[
    tuple[dict[str, object], ...],
    int,
    int,
    bool,
    bool,
    int | None,
]:
    if not isinstance(summary, dict):
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            "momentum forward-markout summary must be an object"
        )
    if summary.get("enabled") is not True or summary.get("error") is not None:
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            "momentum forward-markout source is not cleanly enabled"
        )
    if (
        summary.get("research_only") is not True
        or summary.get("execution_authority") is not False
        or summary.get("promotion_authority") is not False
        or summary.get("descriptive_only") is not True
        or summary.get("changes_readiness_gate") is not False
    ):
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            "momentum forward-markout source authority drift"
        )
    if summary.get("candidate_id") != state.candidate_id:
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            "momentum forward-markout candidate drift"
        )
    overlap_started_at_ms = _required_int(
        summary,
        "overlap_started_at_ms",
    )
    if overlap_started_at_ms < state.started_at_ms:
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            "momentum forward-markout overlap predates clean start"
        )
    if summary.get("forward_horizons_ms") != list(FORWARD_HORIZONS_MS):
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            "momentum forward-markout horizon drift"
        )
    if summary.get("max_mark_lag_ms") != MAX_MARK_LAG_MS:
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            "momentum forward-markout lag drift"
        )
    raw_rows = summary.get("rows")
    if not isinstance(raw_rows, list):
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            "momentum forward-markout rows must be a list"
        )
    evaluated = _required_int(
        summary,
        "base_stack_risk_approved_evaluated",
    )
    if evaluated != len(raw_rows):
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            "momentum forward-markout evaluated count does not reconcile"
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
    integrity_clean = summary.get("integrity_clean") is True
    boundary_known = (
        "integrity_last_miss_at_ms" in summary
        or integrity_clean
    )
    raw_last_miss = summary.get("integrity_last_miss_at_ms")
    if raw_last_miss is not None and (
        isinstance(raw_last_miss, bool)
        or not isinstance(raw_last_miss, int)
    ):
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            "momentum forward-markout integrity boundary is invalid"
        )
    return (
        canonical,
        pending,
        overlap_started_at_ms,
        integrity_clean,
        boundary_known,
        cast(int | None, raw_last_miss),
    )


def update_momentum_forward_markout_ledger(
    summary: object,
    state: ProspectiveMomentumBandEntryState,
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
        source_integrity_boundary_known,
        source_integrity_last_miss_at_ms,
    ) = _source_rows(summary, state)
    previous_rows: tuple[dict[str, object], ...] = ()
    history: list[object] = []
    prior_ledger_sha256: str | None = None

    if previous is not None:
        validated = validate_momentum_forward_markout_ledger(previous)
        for key, expected in (
            ("candidate_id", state.candidate_id),
            ("frozen_at_ms", state.frozen_at_ms),
            ("started_at_ms", state.started_at_ms),
            ("embargo_ms", EMBARGO_MS),
            ("rule", state.payload()["rule"]),
            ("overlap_started_at_ms", overlap_started_at_ms),
            ("forward_horizons_ms", list(FORWARD_HORIZONS_MS)),
            ("max_mark_lag_ms", MAX_MARK_LAG_MS),
        ):
            if validated.get(key) != expected:
                raise ProspectiveMomentumBandForwardMarkoutLedgerError(
                    f"momentum markout metadata drift: {key}"
                )
        raw_history = validated.get("source_history")
        if not isinstance(raw_history, list):
            raise ProspectiveMomentumBandForwardMarkoutLedgerError(
                "momentum markout source history is invalid"
            )
        for item in raw_history:
            if not isinstance(item, dict):
                raise ProspectiveMomentumBandForwardMarkoutLedgerError(
                    "momentum markout source history entry is invalid"
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
                    raise ProspectiveMomentumBandForwardMarkoutLedgerError(
                        "duplicate momentum markout source artifact drift"
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
                raise ProspectiveMomentumBandForwardMarkoutLedgerError(
                    "previous terminal momentum markout row disappeared"
                )
            if current != old:
                raise ProspectiveMomentumBandForwardMarkoutLedgerError(
                    "previous terminal momentum markout row changed"
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
            "integrity_boundary_known": (
                source_integrity_boundary_known
            ),
            "integrity_last_miss_at_ms": (
                source_integrity_last_miss_at_ms
            ),
            "rows_sha256": _rows_sha256(rows),
        }
    )
    cumulative_integrity_clean = all(
        isinstance(item, dict)
        and item.get("integrity_clean") is True
        for item in history
    )
    latest_history = history[-1]
    if not isinstance(latest_history, dict):
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            "latest momentum markout source history is invalid"
        )
    latest_boundary_known = (
        latest_history.get("integrity_boundary_known") is True
        or (
            "integrity_boundary_known" not in latest_history
            and latest_history.get("integrity_clean") is True
        )
    )
    latest_last_miss = latest_history.get("integrity_last_miss_at_ms")
    if latest_last_miss is not None and (
        isinstance(latest_last_miss, bool)
        or not isinstance(latest_last_miss, int)
    ):
        raise ProspectiveMomentumBandForwardMarkoutLedgerError(
            "latest momentum integrity miss boundary is invalid"
        )

    payload: dict[str, object] = {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "kind": LEDGER_KIND,
        "candidate_id": state.candidate_id,
        "frozen_at_ms": state.frozen_at_ms,
        "started_at_ms": state.started_at_ms,
        "embargo_ms": EMBARGO_MS,
        "rule": state.payload()["rule"],
        "overlap_started_at_ms": overlap_started_at_ms,
        "forward_horizons_ms": list(FORWARD_HORIZONS_MS),
        "max_mark_lag_ms": MAX_MARK_LAG_MS,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_readiness_gate": False,
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
            overlap_started_at_ms=overlap_started_at_ms,
            integrity_boundary_known=latest_boundary_known,
            integrity_last_miss_at_ms=cast(
                int | None,
                latest_last_miss,
            ),
        ),
        "rows": rows,
    }
    payload["ledger_sha256"] = _sha256_text(
        _canonical_json(_digest_payload(payload))
    )
    return payload
