from __future__ import annotations

import hashlib
import json
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final, cast

from cocomelon.research.prospective_momentum_band_forward_markout import (
    FORWARD_HORIZONS_MS,
    MAX_MARK_LAG_MS,
)

LEDGER_SCHEMA_VERSION: Final = 1
LEDGER_KIND: Final = "prospective-risk-rejected-forward-markout-ledger-v1"
TERMINAL_STATUSES: Final = frozenset(
    {"settled", "stale", "unsupported_horizon"}
)
PENDING_STATUSES: Final = frozenset({"pending", "missing_path"})
ZERO: Final = Decimal("0")
MIN_REASON_STACK_ADMIT_SETTLED_PER_HORIZON: Final = 12
MIN_REASON_MARKETS_PER_HORIZON: Final = 4
MIN_REASON_LONG_SETTLED_PER_HORIZON: Final = 3
MIN_REASON_SHORT_SETTLED_PER_HORIZON: Final = 3


class ProspectiveRiskRejectedForwardMarkoutLedgerError(RuntimeError):
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
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            f"{key} must be a non-empty string"
        )
    return value


def _required_int(raw: dict[str, object], key: str) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            f"{key} must be an integer"
        )
    return value


def _decimal_string(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            f"{field} must be a decimal string"
        )
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            f"{field} must be a decimal string"
        ) from exc
    if not parsed.is_finite():
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
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


def _required_reasons(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            "baseline risk reasons must be an array"
        )
    reasons = tuple(value)
    if not reasons or not all(
        isinstance(reason, str) and reason.strip()
        for reason in reasons
    ):
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            "baseline risk reasons must be non-empty strings"
        )
    return tuple(sorted(set(cast(tuple[str, ...], reasons))))


def _canonical_markout(
    raw: object,
    *,
    opportunity_timestamp_ms: int,
    horizon_ms: int,
    terminal_only: bool,
) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            "markout must be an object"
        )
    status = _required_string(raw, "status")
    supported = TERMINAL_STATUSES | PENDING_STATUSES
    if status not in supported:
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            f"unsupported markout status: {status}"
        )
    if terminal_only and status not in TERMINAL_STATUSES:
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            "immutable rejected-opportunity row contains pending horizon"
        )
    target_at_ms = _required_int(raw, "target_at_ms")
    if target_at_ms != opportunity_timestamp_ms + horizon_ms:
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            "markout target does not match fixed horizon"
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
            raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
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
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            "terminal markout observed timestamp is invalid"
        )
    if (
        isinstance(lag_ms, bool)
        or not isinstance(lag_ms, int)
        or lag_ms != observed_at_ms - target_at_ms
    ):
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            "terminal markout lag does not reconcile"
        )
    parsed_mark = Decimal(_decimal_string(mark_px, field="mark_px"))
    if parsed_mark <= ZERO:
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            "terminal mark price must be positive"
        )
    if status == "settled":
        if lag_ms > MAX_MARK_LAG_MS:
            raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
                "settled markout exceeds maximum lag"
            )
        parsed_return = _decimal_string(
            directional_return,
            field="directional_return",
        )
    else:
        if lag_ms <= MAX_MARK_LAG_MS:
            raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
                "stale markout does not exceed maximum lag"
            )
        if directional_return is not None:
            raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
                "stale markout must not carry directional return"
            )
        parsed_return = None

    return {
        "status": status,
        "target_at_ms": target_at_ms,
        "observed_at_ms": observed_at_ms,
        "observation_lag_ms": lag_ms,
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
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            "ledger row must be an object"
        )
    opportunity_id = _required_string(raw, "opportunity_id")
    timestamp_ms = _required_int(raw, "timestamp_ms")
    if timestamp_ms < overlap_started_at_ms:
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            "risk-rejected markout row predates common start"
        )
    market = _required_string(raw, "market")
    direction = _required_string(raw, "direction")
    if direction not in {"long", "short"}:
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            "row direction must be long or short"
        )
    lead_strategy = _required_string(raw, "lead_strategy")
    rank_ordinal = _required_int(raw, "rank_ordinal")
    rank_age_ms = _required_int(raw, "rank_age_ms")
    prior_strikes = _required_int(raw, "two_strike_prior_strikes")
    if rank_ordinal <= 0 or rank_age_ms < 0 or prior_strikes < 0:
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            "rank or strike metadata is invalid"
        )
    if raw.get("baseline_risk_approved") is not False:
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            "risk-rejected row must be baseline-risk rejected"
        )
    reasons = _required_reasons(raw.get("baseline_risk_reason_codes"))

    stack_decision = _required_string(raw, "stack_decision")
    if stack_decision not in {"ADMIT", "BLOCK"}:
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            "stack decision must be ADMIT or BLOCK"
        )
    block_layer = _required_string(raw, "block_layer")
    if block_layer not in {"none", "combined", "two_strike", "momentum"}:
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            "stack block layer is unsupported"
        )
    if (
        (stack_decision == "ADMIT" and block_layer != "none")
        or (stack_decision == "BLOCK" and block_layer == "none")
    ):
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            "stack decision and block layer do not reconcile"
        )

    combined_reason = raw.get("combined_block_reason")
    if combined_reason is not None and not isinstance(
        combined_reason,
        str,
    ):
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            "combined block reason must be string or null"
        )
    momentum_decision = raw.get("momentum_decision")
    momentum_reason = raw.get("momentum_reason")
    if momentum_decision is not None and momentum_decision not in {
        "ADMIT",
        "BLOCK",
    }:
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            "momentum decision is invalid"
        )
    if momentum_reason is not None and not isinstance(
        momentum_reason,
        str,
    ):
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            "momentum reason must be string or null"
        )
    momentum_prior_strikes = raw.get("momentum_prior_strikes")
    if (
        momentum_prior_strikes is not None
        and (
            isinstance(momentum_prior_strikes, bool)
            or not isinstance(momentum_prior_strikes, int)
            or momentum_prior_strikes < 0
        )
    ):
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            "momentum prior strikes must be non-negative or null"
        )
    signed_return_1h = _optional_decimal_string(
        raw.get("signed_return_1h"),
        field="signed_return_1h",
    )
    signed_day_return = _optional_decimal_string(
        raw.get("signed_day_return"),
        field="signed_day_return",
    )

    raw_markouts = raw.get("markouts")
    if not isinstance(raw_markouts, dict):
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            "row markouts must be an object"
        )
    expected_keys = {str(value) for value in FORWARD_HORIZONS_MS}
    if set(raw_markouts) != expected_keys:
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
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
        "baseline_risk_approved": False,
        "baseline_risk_reason_codes": list(reasons),
        "combined_block_reason": combined_reason,
        "two_strike_prior_strikes": prior_strikes,
        "momentum_decision": momentum_decision,
        "momentum_reason": momentum_reason,
        "momentum_prior_strikes": momentum_prior_strikes,
        "signed_return_1h": signed_return_1h,
        "signed_day_return": signed_day_return,
        "stack_decision": stack_decision,
        "block_layer": block_layer,
        "markouts": markouts,
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
    terminal_only: bool,
) -> tuple[dict[str, object], ...]:
    if not isinstance(raw, (list, tuple)):
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            "ledger rows must be a list"
        )
    rows = tuple(
        _canonical_row(
            row,
            overlap_started_at_ms=overlap_started_at_ms,
            terminal_only=terminal_only,
        )
        for row in raw
    )
    identities = tuple(_row_identity(row) for row in rows)
    if len(identities) != len(set(identities)):
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            "duplicate risk-rejected row identity"
        )
    ids = tuple(cast(str, row["opportunity_id"]) for row in rows)
    if len(ids) != len(set(ids)):
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            "duplicate risk-rejected opportunity id"
        )
    return tuple(sorted(rows, key=_row_identity))


def _rows_sha256(rows: tuple[dict[str, object], ...]) -> str:
    payload = "\n".join(_canonical_json(row) for row in rows)
    if payload:
        payload += "\n"
    return _sha256_text(payload)


def _mean(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return sum(values, ZERO) / Decimal(len(values))


def _mean_robustness(
    settled: tuple[tuple[str, Decimal], ...],
) -> dict[str, object]:
    values = tuple(value for _market, value in settled)
    full = _mean(values)
    leave_one = tuple(
        _mean(values[:index] + values[index + 1 :])
        for index in range(len(values))
    )
    leave_one_values = tuple(
        value for value in leave_one if value is not None
    )
    markets = tuple(sorted({market for market, _value in settled}))
    leave_market = tuple(
        _mean(
            tuple(
                value
                for item_market, value in settled
                if item_market != market
            )
        )
        for market in markets
    )
    leave_market_values = tuple(
        value for value in leave_market if value is not None
    )
    return {
        "mean_directional_return": (
            None if full is None else str(full)
        ),
        "leave_one_opportunity_min_mean": (
            None
            if not leave_one_values
            else str(min(leave_one_values))
        ),
        "positive_after_removing_any_one_opportunity": (
            len(values) >= 2
            and len(leave_one_values) == len(values)
            and min(leave_one_values) > ZERO
        ),
        "leave_one_market_min_mean": (
            None
            if not leave_market_values
            else str(min(leave_market_values))
        ),
        "positive_after_removing_any_one_market": (
            len(markets) >= 2
            and len(leave_market_values) == len(markets)
            and min(leave_market_values) > ZERO
        ),
    }


def _risk_reason_investigation_readiness(
    rows: tuple[dict[str, object], ...],
    *,
    integrity_clean: bool,
) -> dict[str, object]:
    reasons = tuple(
        sorted(
            {
                reason
                for row in rows
                for reason in cast(
                    list[str],
                    row["baseline_risk_reason_codes"],
                )
            }
        )
    )
    by_reason: dict[str, dict[str, object]] = {}
    ready_reasons: list[str] = []

    for reason in reasons:
        horizons: dict[str, dict[str, object]] = {}
        all_horizons_ready = True
        for horizon_ms in FORWARD_HORIZONS_MS:
            key = str(horizon_ms)
            settled: list[tuple[dict[str, object], Decimal]] = []
            for row in rows:
                if row["stack_decision"] != "ADMIT":
                    continue
                if reason not in cast(
                    list[str],
                    row["baseline_risk_reason_codes"],
                ):
                    continue
                markouts = cast(
                    dict[str, dict[str, object]],
                    row["markouts"],
                )
                markout = markouts[key]
                if markout["status"] != "settled":
                    continue
                settled.append(
                    (
                        row,
                        Decimal(
                            cast(
                                str,
                                markout["directional_return"],
                            )
                        ),
                    )
                )

            market_values = tuple(
                (cast(str, row["market"]), value)
                for row, value in settled
            )
            robustness = _mean_robustness(market_values)
            markets = {
                cast(str, row["market"])
                for row, _value in settled
            }
            long_count = sum(
                row["direction"] == "long"
                for row, _value in settled
            )
            short_count = sum(
                row["direction"] == "short"
                for row, _value in settled
            )
            settled_count = len(settled)
            mean_raw = robustness["mean_directional_return"]
            mean_positive = (
                isinstance(mean_raw, str)
                and Decimal(mean_raw) > ZERO
            )
            opportunity_robust = (
                robustness[
                    "positive_after_removing_any_one_opportunity"
                ]
                is True
            )
            market_robust = (
                robustness[
                    "positive_after_removing_any_one_market"
                ]
                is True
            )
            sample_complete = (
                settled_count
                >= MIN_REASON_STACK_ADMIT_SETTLED_PER_HORIZON
                and len(markets) >= MIN_REASON_MARKETS_PER_HORIZON
                and long_count
                >= MIN_REASON_LONG_SETTLED_PER_HORIZON
                and short_count
                >= MIN_REASON_SHORT_SETTLED_PER_HORIZON
            )
            horizon_ready = (
                integrity_clean
                and sample_complete
                and mean_positive
                and opportunity_robust
                and market_robust
            )
            all_horizons_ready = (
                all_horizons_ready and horizon_ready
            )
            horizons[key] = {
                "horizon_ms": horizon_ms,
                "stack_admit_settled": settled_count,
                "market_count": len(markets),
                "long_settled": long_count,
                "short_settled": short_count,
                "mean_directional_return": mean_raw,
                "leave_one_opportunity_min_mean": robustness[
                    "leave_one_opportunity_min_mean"
                ],
                "leave_one_market_min_mean": robustness[
                    "leave_one_market_min_mean"
                ],
                "sample_complete": sample_complete,
                "mean_positive": mean_positive,
                "single_opportunity_robust": opportunity_robust,
                "single_market_robust": market_robust,
                "integrity_clean": integrity_clean,
                "ready_for_investigation": horizon_ready,
                "missing_stack_admit_settled": max(
                    0,
                    MIN_REASON_STACK_ADMIT_SETTLED_PER_HORIZON
                    - settled_count,
                ),
                "missing_markets": max(
                    0,
                    MIN_REASON_MARKETS_PER_HORIZON
                    - len(markets),
                ),
                "missing_long_settled": max(
                    0,
                    MIN_REASON_LONG_SETTLED_PER_HORIZON
                    - long_count,
                ),
                "missing_short_settled": max(
                    0,
                    MIN_REASON_SHORT_SETTLED_PER_HORIZON
                    - short_count,
                ),
            }

        if all_horizons_ready:
            ready_reasons.append(reason)
        by_reason[reason] = {
            "ready_for_risk_budget_investigation": (
                all_horizons_ready
            ),
            "horizons": horizons,
        }

    return {
        "review_only": True,
        "decision_scope": "risk_rejected_stack_admit_only",
        "changes_risk_limits": False,
        "changes_candidate_readiness": False,
        "execution_authority": False,
        "promotion_authority": False,
        "min_stack_admit_settled_per_horizon": (
            MIN_REASON_STACK_ADMIT_SETTLED_PER_HORIZON
        ),
        "min_markets_per_horizon": MIN_REASON_MARKETS_PER_HORIZON,
        "min_long_settled_per_horizon": (
            MIN_REASON_LONG_SETTLED_PER_HORIZON
        ),
        "min_short_settled_per_horizon": (
            MIN_REASON_SHORT_SETTLED_PER_HORIZON
        ),
        "integrity_clean": integrity_clean,
        "ready_reasons": ready_reasons,
        "by_reason": by_reason,
    }


def _horizon_summary(
    rows: tuple[dict[str, object], ...],
    *,
    horizon_ms: int,
    include_block_layer_attribution: bool = True,
) -> dict[str, object]:
    key = str(horizon_ms)
    settled: list[tuple[dict[str, object], Decimal]] = []
    status_counts: Counter[str] = Counter()
    by_reason_values: dict[str, list[tuple[str, Decimal]]] = {}
    by_reason_opportunities: Counter[str] = Counter()
    by_block_layer_values: dict[
        str, list[tuple[str, Decimal]]
    ] = {}
    by_block_layer_opportunities: Counter[str] = Counter()

    for row in rows:
        reasons = cast(list[str], row["baseline_risk_reason_codes"])
        for reason in reasons:
            by_reason_opportunities[reason] += 1
        if row["stack_decision"] == "BLOCK":
            by_block_layer_opportunities[
                cast(str, row["block_layer"])
            ] += 1
        markouts = cast(dict[str, dict[str, object]], row["markouts"])
        markout = markouts[key]
        status = cast(str, markout["status"])
        status_counts[status] += 1
        if status != "settled":
            continue
        raw_return = cast(str, markout["directional_return"])
        value = Decimal(raw_return)
        settled.append((row, value))
        for reason in reasons:
            by_reason_values.setdefault(reason, []).append(
                (cast(str, row["market"]), value)
            )
        if row["stack_decision"] == "BLOCK":
            by_block_layer_values.setdefault(
                cast(str, row["block_layer"]),
                [],
            ).append((cast(str, row["market"]), value))

    admitted = tuple(
        (cast(str, row["market"]), value)
        for row, value in settled
        if row["stack_decision"] == "ADMIT"
    )
    blocked = tuple(
        (cast(str, row["market"]), value)
        for row, value in settled
        if row["stack_decision"] == "BLOCK"
    )
    all_values = tuple(
        (cast(str, row["market"]), value)
        for row, value in settled
    )
    by_reason: dict[str, dict[str, object]] = {}
    for reason in sorted(by_reason_opportunities):
        values = tuple(by_reason_values.get(reason, ()))
        returns = tuple(value for _market, value in values)
        admit_values = tuple(
            value
            for row, value in settled
            if reason
            in cast(list[str], row["baseline_risk_reason_codes"])
            and row["stack_decision"] == "ADMIT"
        )
        by_reason[reason] = {
            "opportunities": by_reason_opportunities[reason],
            "settled": len(values),
            "positive": sum(value > ZERO for value in returns),
            "negative": sum(value < ZERO for value in returns),
            "flat": sum(value == ZERO for value in returns),
            "mean_directional_return": (
                None
                if not returns
                else str(_mean(returns))
            ),
            "stack_admit_settled": len(admit_values),
            "stack_admit_mean_directional_return": (
                None
                if not admit_values
                else str(_mean(admit_values))
            ),
        }

    result: dict[str, object] = {
        "horizon_ms": horizon_ms,
        "terminal_opportunities": len(rows),
        "settled_opportunities": len(settled),
        "status_counts": dict(sorted(status_counts.items())),
        "stack_admit_settled": len(admitted),
        "stack_block_settled": len(blocked),
        "stack_admit": _mean_robustness(admitted),
        "stack_block_mean_directional_return": (
            None
            if not blocked
            else str(_mean(tuple(value for _market, value in blocked)))
        ),
        "overall": _mean_robustness(all_values),
        "long_settled": sum(
            row["direction"] == "long" for row, _value in settled
        ),
        "short_settled": sum(
            row["direction"] == "short" for row, _value in settled
        ),
        "market_count": len(
            {
                cast(str, row["market"])
                for row, _value in settled
            }
        ),
        "by_risk_reason": by_reason,
        "descriptive_only": True,
        "changes_risk_limits": False,
        "changes_candidate_readiness": False,
    }
    if include_block_layer_attribution:
        by_block_layer: dict[str, dict[str, object]] = {}
        for layer in sorted(by_block_layer_opportunities):
            values = tuple(by_block_layer_values.get(layer, ()))
            returns = tuple(value for _market, value in values)
            by_block_layer[layer] = {
                "opportunities": by_block_layer_opportunities[layer],
                "settled": len(values),
                "positive": sum(value > ZERO for value in returns),
                "negative": sum(value < ZERO for value in returns),
                "flat": sum(value == ZERO for value in returns),
                "mean_directional_return": (
                    None if not returns else str(_mean(returns))
                ),
                "market_count": len(
                    {market for market, _value in values}
                ),
            }
        result["by_block_layer"] = by_block_layer
    return result


def _summary(
    rows: tuple[dict[str, object], ...],
    *,
    pending_opportunity_count: int,
    integrity_clean: bool,
    include_investigation_readiness: bool = True,
    include_block_layer_attribution: bool = True,
) -> dict[str, object]:
    reason_counts: Counter[str] = Counter()
    for row in rows:
        reason_counts.update(
            cast(list[str], row["baseline_risk_reason_codes"])
        )
    block_layer_counts: Counter[str] = Counter(
        cast(str, row["block_layer"])
        for row in rows
        if row["stack_decision"] == "BLOCK"
    )
    result: dict[str, object] = {
        "terminal_opportunity_count": len(rows),
        "pending_opportunity_count": pending_opportunity_count,
        "integrity_clean": integrity_clean,
        "stack_admitted_terminal": sum(
            row["stack_decision"] == "ADMIT" for row in rows
        ),
        "stack_blocked_terminal": sum(
            row["stack_decision"] == "BLOCK" for row in rows
        ),
        "risk_reason_counts": dict(sorted(reason_counts.items())),
        "horizons": {
            str(horizon_ms): _horizon_summary(
                rows,
                horizon_ms=horizon_ms,
                include_block_layer_attribution=(
                    include_block_layer_attribution
                ),
            )
            for horizon_ms in FORWARD_HORIZONS_MS
        },
    }
    if include_block_layer_attribution:
        result["stack_block_layer_counts"] = dict(
            sorted(block_layer_counts.items())
        )
    if include_investigation_readiness:
        result["risk_budget_investigation_readiness"] = (
            _risk_reason_investigation_readiness(
                rows,
                integrity_clean=integrity_clean,
            )
        )
    return result


def _validate_metadata(raw: dict[str, object]) -> None:
    if raw.get("schema_version") != LEDGER_SCHEMA_VERSION:
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            "risk-rejected markout ledger schema is unsupported"
        )
    if raw.get("kind") != LEDGER_KIND:
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            "risk-rejected markout ledger kind is unsupported"
        )
    if raw.get("candidate_stack") != "combined+two_strike+momentum":
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            "risk-rejected candidate stack drift"
        )
    overlap = _required_int(raw, "overlap_started_at_ms")
    starts = (
        _required_int(raw, "combined_started_at_ms"),
        _required_int(raw, "two_strike_started_at_ms"),
        _required_int(raw, "momentum_started_at_ms"),
    )
    if overlap != max(starts):
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            "risk-rejected overlap start does not reconcile"
        )
    if raw.get("forward_horizons_ms") != list(FORWARD_HORIZONS_MS):
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            "risk-rejected markout horizons drift"
        )
    if raw.get("max_mark_lag_ms") != MAX_MARK_LAG_MS:
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            "risk-rejected markout lag contract drift"
        )


def validate_risk_rejected_forward_markout_ledger(
    raw: object,
) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            "risk-rejected markout ledger must be an object"
        )
    _validate_metadata(raw)
    overlap = _required_int(raw, "overlap_started_at_ms")
    rows = _canonical_rows(
        raw.get("rows"),
        overlap_started_at_ms=overlap,
        terminal_only=True,
    )
    if raw.get("row_count") != len(rows):
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            "risk-rejected markout row count mismatch"
        )
    if raw.get("rows_sha256") != _rows_sha256(rows):
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            "risk-rejected markout row digest mismatch"
        )
    pending = _required_int(raw, "pending_opportunity_count")
    if pending < 0:
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            "risk-rejected pending count is invalid"
        )
    history = raw.get("source_history")
    if not isinstance(history, list):
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            "risk-rejected source history must be a list"
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
    pre_layer_summary = _summary(
        rows,
        pending_opportunity_count=pending,
        integrity_clean=integrity_clean,
        include_block_layer_attribution=False,
    )
    pre_readiness_summary = _summary(
        rows,
        pending_opportunity_count=pending,
        integrity_clean=integrity_clean,
        include_investigation_readiness=False,
    )
    legacy_summary = _summary(
        rows,
        pending_opportunity_count=pending,
        integrity_clean=integrity_clean,
        include_investigation_readiness=False,
        include_block_layer_attribution=False,
    )
    if raw.get("summary") not in (
        current_summary,
        pre_layer_summary,
        pre_readiness_summary,
        legacy_summary,
    ):
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            "risk-rejected markout summary does not reconcile"
        )
    if (
        raw.get("research_only") is not True
        or raw.get("execution_authority") is not False
        or raw.get("promotion_authority") is not False
        or raw.get("changes_risk_limits") is not False
        or raw.get("changes_candidate_readiness") is not False
    ):
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            "risk-rejected markout ledger authority drift"
        )
    expected = _sha256_text(
        _canonical_json(_digest_payload(raw))
    )
    if raw.get("ledger_sha256") != expected:
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            "risk-rejected markout ledger digest mismatch"
        )
    return {**raw, "rows": rows}


def load_risk_rejected_forward_markout_ledger(
    path: str | Path,
) -> dict[str, object]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            "risk-rejected markout ledger file is invalid"
        ) from exc
    return validate_risk_rejected_forward_markout_ledger(raw)


def _source_rows(
    summary: object,
) -> tuple[
    tuple[dict[str, object], ...],
    int,
    tuple[int, int, int, int],
    bool,
]:
    if not isinstance(summary, dict):
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            "full-stack forward-markout summary must be an object"
        )
    if summary.get("enabled") is not True or summary.get("error") is not None:
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
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
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            "full-stack forward-markout source authority drift"
        )
    if summary.get("candidate_stack") != "combined+two_strike+momentum":
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            "full-stack candidate stack drift"
        )
    metadata = (
        _required_int(summary, "overlap_started_at_ms"),
        _required_int(summary, "combined_started_at_ms"),
        _required_int(summary, "two_strike_started_at_ms"),
        _required_int(summary, "momentum_started_at_ms"),
    )
    if metadata[0] != max(metadata[1:]):
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            "full-stack overlap start does not reconcile"
        )
    if summary.get("forward_horizons_ms") != list(FORWARD_HORIZONS_MS):
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            "full-stack forward horizons drift"
        )
    if summary.get("max_mark_lag_ms") != MAX_MARK_LAG_MS:
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            "full-stack markout lag drift"
        )
    raw_rows = summary.get("risk_rejected_rows")
    if not isinstance(raw_rows, list):
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            "risk-rejected source rows must be a list"
        )
    evaluated = _required_int(summary, "risk_rejected_stack_evaluated")
    if evaluated != len(raw_rows):
        raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
            "risk-rejected evaluated count does not reconcile"
        )
    canonical_all = _canonical_rows(
        raw_rows,
        overlap_started_at_ms=metadata[0],
        terminal_only=False,
    )
    terminal: list[dict[str, object]] = []
    pending = 0
    for row in canonical_all:
        markouts = cast(dict[str, dict[str, object]], row["markouts"])
        statuses = {
            cast(str, markout["status"])
            for markout in markouts.values()
        }
        if statuses <= TERMINAL_STATUSES:
            terminal.append(
                _canonical_row(
                    row,
                    overlap_started_at_ms=metadata[0],
                    terminal_only=True,
                )
            )
        else:
            pending += 1
    integrity_clean = summary.get("risk_rejected_integrity_clean") is True
    return (
        _canonical_rows(
            terminal,
            overlap_started_at_ms=metadata[0],
            terminal_only=True,
        ),
        pending,
        metadata,
        integrity_clean,
    )


def update_risk_rejected_forward_markout_ledger(
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

    source_rows, pending, metadata, source_integrity = _source_rows(
        summary
    )
    (
        overlap_started_at_ms,
        combined_started_at_ms,
        two_strike_started_at_ms,
        momentum_started_at_ms,
    ) = metadata

    previous_rows: tuple[dict[str, object], ...] = ()
    history: list[object] = []
    prior_ledger_sha256: str | None = None

    if previous is not None:
        validated = validate_risk_rejected_forward_markout_ledger(
            previous
        )
        for key, expected in (
            ("candidate_stack", "combined+two_strike+momentum"),
            ("overlap_started_at_ms", overlap_started_at_ms),
            ("combined_started_at_ms", combined_started_at_ms),
            ("two_strike_started_at_ms", two_strike_started_at_ms),
            ("momentum_started_at_ms", momentum_started_at_ms),
            ("forward_horizons_ms", list(FORWARD_HORIZONS_MS)),
            ("max_mark_lag_ms", MAX_MARK_LAG_MS),
        ):
            if validated.get(key) != expected:
                raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
                    f"risk-rejected markout metadata drift: {key}"
                )
        raw_history = validated.get("source_history")
        if not isinstance(raw_history, list):
            raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
                "risk-rejected source history is invalid"
            )
        for item in raw_history:
            if not isinstance(item, dict):
                raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
                    "risk-rejected source history entry is invalid"
                )
            if (
                item.get("paper_run_id") == source_paper_run_id
                and item.get("paper_run_attempt")
                == source_paper_run_attempt
            ):
                if (
                    item.get("artifact_name") != source_artifact_name
                    or item.get("artifact_digest")
                    != source_artifact_digest
                ):
                    raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
                        "duplicate risk-rejected source artifact drift"
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
                raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
                    "previous terminal risk-rejected row disappeared"
                )
            if current != old:
                raise ProspectiveRiskRejectedForwardMarkoutLedgerError(
                    "previous terminal risk-rejected row changed"
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
        "candidate_stack": "combined+two_strike+momentum",
        "overlap_started_at_ms": overlap_started_at_ms,
        "combined_started_at_ms": combined_started_at_ms,
        "two_strike_started_at_ms": two_strike_started_at_ms,
        "momentum_started_at_ms": momentum_started_at_ms,
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
