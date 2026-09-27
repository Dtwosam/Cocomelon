from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.research.learning_clean_review_dossier import (
    PROMOTION_REQUIREMENTS,
)
from cocomelon.research.learning_shadow_admission import (
    MAX_MARKET_POSITIVE_PNL_FRACTION,
    MAX_PAPER_DRAWDOWN_FRACTION,
    MAX_SEVEN_DAY_POSITIVE_PNL_FRACTION,
    MIN_CLOSED_MAINNET_PAPER_TRADES,
    MIN_PROFIT_FACTOR,
    MIN_SHADOW_CALENDAR_DAYS,
)

ZERO: Final = Decimal("0")
DAY_MS: Final = 86_400_000
SEVEN_DAYS_MS: Final = 7 * DAY_MS


class ContinuousPaperPromotionGuardError(RuntimeError):
    pass


def _profit_factor(
    trades: Sequence[TradeJournalEntry],
) -> Decimal | None:
    winners = sum(
        (trade.net_pnl for trade in trades if trade.net_pnl > ZERO),
        ZERO,
    )
    losers = -sum(
        (trade.net_pnl for trade in trades if trade.net_pnl < ZERO),
        ZERO,
    )
    if losers == ZERO:
        return None
    if winners == ZERO:
        return ZERO
    return winners / losers


def _positive_concentration(
    trades: Sequence[TradeJournalEntry],
    *,
    grouping: str,
) -> Decimal | None:
    grouped: dict[object, Decimal] = defaultdict(lambda: ZERO)
    for trade in trades:
        if grouping == "market":
            key: object = trade.market.canonical
        elif grouping == "seven_day":
            key = trade.closed_at_ms // SEVEN_DAYS_MS
        else:
            raise ValueError(f"unsupported grouping: {grouping}")
        grouped[key] += trade.net_pnl

    positive = tuple(value for value in grouped.values() if value > ZERO)
    if not positive:
        return None
    denominator = sum(positive, ZERO)
    if denominator <= ZERO:
        return None
    return max(positive) / denominator


def _gate(
    requirement: str,
    *,
    status: str,
    observed: object,
    required: object,
    reason: str,
) -> dict[str, object]:
    if status not in {
        "pass",
        "fail",
        "collecting",
        "external_required",
        "not_authorized",
    }:
        raise ValueError("unsupported promotion gate status")
    return {
        "requirement": requirement,
        "status": status,
        "observed": observed,
        "required": required,
        "reason": reason,
    }


def _sampled_drawdown(
    raw: object,
) -> Mapping[str, object]:
    if not isinstance(raw, dict):
        raise ContinuousPaperPromotionGuardError(
            "drawdown payload must be an object"
        )
    sampled = raw.get("sampled_account")
    if not isinstance(sampled, dict):
        raise ContinuousPaperPromotionGuardError(
            "sampled drawdown payload is missing"
        )
    return sampled


def continuous_paper_promotion_guard(
    trades: Sequence[TradeJournalEntry],
    drawdown_payload: object,
    *,
    timestamp_ms: int,
    execution_healthy: bool,
    execution_reason_codes: Sequence[str],
) -> dict[str, object]:
    if timestamp_ms < 0:
        raise ValueError("timestamp_ms must be non-negative")
    sampled = _sampled_drawdown(drawdown_payload)
    started_at_ms = sampled.get("started_at_ms")
    observation_count = sampled.get("observation_count")
    restore_error = sampled.get("state_restore_error")
    if isinstance(started_at_ms, bool) or not isinstance(
        started_at_ms,
        int,
    ):
        raise ContinuousPaperPromotionGuardError(
            "drawdown started_at_ms must be an integer"
        )
    if isinstance(observation_count, bool) or not isinstance(
        observation_count,
        int,
    ):
        raise ContinuousPaperPromotionGuardError(
            "drawdown observation_count must be an integer"
        )
    if restore_error is not None and not isinstance(restore_error, str):
        raise ContinuousPaperPromotionGuardError(
            "drawdown restore error must be null or string"
        )
    if timestamp_ms < started_at_ms:
        raise ContinuousPaperPromotionGuardError(
            "promotion timestamp precedes evaluation start"
        )

    eligible = tuple(
        trade
        for trade in trades
        if trade.opened_at_ms >= started_at_ms
    )
    closed_count = len(eligible)
    shadow_days = (
        0
        if observation_count == 0
        else (
            timestamp_ms // DAY_MS
            - started_at_ms // DAY_MS
            + 1
        )
    )
    total_net_pnl = sum(
        (trade.net_pnl for trade in eligible),
        ZERO,
    )
    total_net_r = sum(
        (trade.net_r for trade in eligible),
        ZERO,
    )
    mean_net_r = (
        None
        if not eligible
        else total_net_r / Decimal(closed_count)
    )
    profit_factor = _profit_factor(eligible)
    market_concentration = _positive_concentration(
        eligible,
        grouping="market",
    )
    seven_day_concentration = _positive_concentration(
        eligible,
        grouping="seven_day",
    )

    raw_drawdown = sampled.get("max_drawdown_fraction")
    max_drawdown: Decimal | None = None
    if raw_drawdown is not None:
        max_drawdown = Decimal(str(raw_drawdown))
        if not max_drawdown.is_finite() or max_drawdown < ZERO:
            raise ContinuousPaperPromotionGuardError(
                "sampled maximum drawdown must be non-negative"
            )

    gates: list[dict[str, object]] = []

    gates.append(
        _gate(
            "closed_mainnet_paper_trades",
            status=(
                "pass"
                if closed_count >= MIN_CLOSED_MAINNET_PAPER_TRADES
                else "collecting"
            ),
            observed=closed_count,
            required=MIN_CLOSED_MAINNET_PAPER_TRADES,
            reason=(
                "counted only from the drawdown-complete evaluation start"
            ),
        )
    )
    gates.append(
        _gate(
            "shadow_calendar_days",
            status=(
                "pass"
                if shadow_days >= MIN_SHADOW_CALENDAR_DAYS
                else "collecting"
            ),
            observed=shadow_days,
            required=MIN_SHADOW_CALENDAR_DAYS,
            reason=(
                "UTC calendar-day lower bound from the durable evaluation start"
            ),
        )
    )
    expectancy_pass = (
        mean_net_r is not None
        and mean_net_r > ZERO
        and total_net_pnl > ZERO
    )
    gates.append(
        _gate(
            "positive_net_expectancy_after_costs",
            status=(
                "collecting"
                if mean_net_r is None
                else ("pass" if expectancy_pass else "fail")
            ),
            observed={
                "net_pnl": str(total_net_pnl),
                "mean_net_r": (
                    None if mean_net_r is None else str(mean_net_r)
                ),
            },
            required={
                "net_pnl": ">0",
                "mean_net_r": ">0",
            },
            reason=(
                "journal net PnL already includes realized execution costs "
                "and funding"
            ),
        )
    )
    gates.append(
        _gate(
            "positive_untouched_oos",
            status="external_required",
            observed=None,
            required="positive untouched OOS evidence",
            reason=(
                "continuous paper runtime cannot self-certify untouched OOS"
            ),
        )
    )
    gates.append(
        _gate(
            "walk_forward_stability",
            status="external_required",
            observed=None,
            required="stable walk-forward evidence",
            reason=(
                "continuous paper runtime cannot self-certify walk-forward "
                "stability"
            ),
        )
    )
    gates.append(
        _gate(
            "profit_factor",
            status=(
                "collecting"
                if profit_factor is None
                else (
                    "pass"
                    if profit_factor >= MIN_PROFIT_FACTOR
                    else "fail"
                )
            ),
            observed=(
                None if profit_factor is None else str(profit_factor)
            ),
            required=str(MIN_PROFIT_FACTOR),
            reason=(
                "profit factor is unavailable until at least one loss exists"
                if profit_factor is None
                else "net closed-trade profit factor"
            ),
        )
    )
    drawdown_ready = (
        observation_count > 0
        and restore_error is None
        and max_drawdown is not None
    )
    gates.append(
        _gate(
            "maximum_paper_drawdown",
            status=(
                "collecting"
                if not drawdown_ready
                else (
                    "pass"
                    if max_drawdown <= MAX_PAPER_DRAWDOWN_FRACTION
                    else "fail"
                )
            ),
            observed=(
                None if max_drawdown is None else str(max_drawdown)
            ),
            required=f"<={MAX_PAPER_DRAWDOWN_FRACTION}",
            reason=(
                "requires uninterrupted durable sampled account-equity coverage"
            ),
        )
    )
    gates.append(
        _gate(
            "market_concentration",
            status=(
                "collecting"
                if market_concentration is None
                else (
                    "pass"
                    if market_concentration
                    <= MAX_MARKET_POSITIVE_PNL_FRACTION
                    else "fail"
                )
            ),
            observed=(
                None
                if market_concentration is None
                else str(market_concentration)
            ),
            required=f"<={MAX_MARKET_POSITIVE_PNL_FRACTION}",
            reason="share of positive grouped net PnL from the top market",
        )
    )
    gates.append(
        _gate(
            "seven_day_concentration",
            status=(
                "collecting"
                if seven_day_concentration is None
                else (
                    "pass"
                    if seven_day_concentration
                    <= MAX_SEVEN_DAY_POSITIVE_PNL_FRACTION
                    else "fail"
                )
            ),
            observed=(
                None
                if seven_day_concentration is None
                else str(seven_day_concentration)
            ),
            required=f"<={MAX_SEVEN_DAY_POSITIVE_PNL_FRACTION}",
            reason=(
                "share of positive grouped net PnL from the top seven-day bucket"
            ),
        )
    )
    gates.append(
        _gate(
            "risk_invariants",
            status=(
                "fail"
                if not execution_healthy
                else "external_required"
            ),
            observed={
                "current_execution_healthy": execution_healthy,
                "current_reason_codes": list(execution_reason_codes),
            },
            required="zero unresolved risk-invariant violations",
            reason=(
                "current health can prove a failure, but cannot certify the "
                "full historical invariant ledger"
            ),
        )
    )
    gates.append(
        _gate(
            "recovery_reconciliation",
            status="external_required",
            observed=None,
            required="successful restart/recovery/reconciliation evidence",
            reason=(
                "must be attested by dedicated recovery evidence, not inferred "
                "from one live heartbeat"
            ),
        )
    )
    gates.append(
        _gate(
            "explicit_live_authorization",
            status="not_authorized",
            observed=False,
            required="explicit user authorization and capital amount",
            reason=(
                "continuous paper runtime has no authority to grant live "
                "promotion"
            ),
        )
    )

    expected_order = tuple(
        key for key, _description in PROMOTION_REQUIREMENTS
    )
    actual_order = tuple(
        str(item["requirement"]) for item in gates
    )
    if actual_order != expected_order:
        raise ContinuousPaperPromotionGuardError(
            "promotion gate order drifted from source of truth"
        )

    all_observable_numeric_pass = all(
        item["status"] == "pass"
        for item in gates
        if item["requirement"]
        in {
            "closed_mainnet_paper_trades",
            "shadow_calendar_days",
            "positive_net_expectancy_after_costs",
            "profit_factor",
            "maximum_paper_drawdown",
            "market_concentration",
            "seven_day_concentration",
        }
    )
    blocked = tuple(
        str(item["requirement"])
        for item in gates
        if item["status"] != "pass"
    )
    return {
        "observability_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "live_orders": False,
        "evaluation_start_ms": started_at_ms,
        "eligible_closed_trades": closed_count,
        "shadow_calendar_days_lower_bound": shadow_days,
        "all_observable_numeric_gates_pass": (
            all_observable_numeric_pass
        ),
        "live_promotion_ready": False,
        "blocked_requirements": list(blocked),
        "gates": gates,
    }
