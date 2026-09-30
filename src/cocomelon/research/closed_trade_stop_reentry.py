from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.strategy import Direction

ZERO: Final = Decimal("0")
STOP_EXIT_REASON: Final = "MARK_STOP_TRIGGERED"
FIVE_MINUTES_MS: Final = 5 * 60 * 1_000
THIRTY_MINUTES_MS: Final = 30 * 60 * 1_000
TWO_HOURS_MS: Final = 120 * 60 * 1_000


def _summary(
    trades: Sequence[TradeJournalEntry],
) -> dict[str, object]:
    values = tuple(trades)
    net_pnl = sum((trade.net_pnl for trade in values), ZERO)
    net_r = sum((trade.net_r for trade in values), ZERO)
    return {
        "trades": len(values),
        "wins": sum(1 for trade in values if trade.net_pnl > ZERO),
        "losses": sum(1 for trade in values if trade.net_pnl < ZERO),
        "breakeven": sum(
            1 for trade in values if trade.net_pnl == ZERO
        ),
        "net_pnl": str(net_pnl),
        "mean_net_pnl": (
            None
            if not values
            else str(net_pnl / Decimal(len(values)))
        ),
        "net_r": str(net_r),
        "mean_net_r": (
            None
            if not values
            else str(net_r / Decimal(len(values)))
        ),
    }


def _gap_bucket(gap_ms: int) -> str:
    if gap_ms <= FIVE_MINUTES_MS:
        return "0-5m"
    if gap_ms <= THIRTY_MINUTES_MS:
        return "5-30m"
    if gap_ms <= TWO_HOURS_MS:
        return "30-120m"
    return "120m+"


def _robustness(
    trades: tuple[TradeJournalEntry, ...],
) -> dict[str, object]:
    deltas = tuple(-trade.net_pnl for trade in trades)
    total = sum(deltas, ZERO)
    leave_one_out = tuple(total - delta for delta in deltas)
    minimum = min(leave_one_out, default=ZERO)
    return {
        "total_delta_trade_contribution_pnl": str(total),
        "leave_one_trade_out_min_delta_pnl": str(minimum),
        "positive_after_removing_any_one_trade": (
            len(deltas) >= 2 and minimum > ZERO
        ),
    }


def _window_summary(
    reentries: tuple[
        tuple[TradeJournalEntry, int, TradeJournalEntry, int], ...
    ],
    *,
    max_gap_ms: int,
) -> dict[str, object]:
    blocked = tuple(
        trade
        for trade, gap_ms, _prior, _streak in reentries
        if gap_ms <= max_gap_ms
    )
    blocked_net_pnl = sum(
        (trade.net_pnl for trade in blocked),
        ZERO,
    )
    return {
        "max_gap_ms": max_gap_ms,
        "blocked_trades": len(blocked),
        "blocked_winners": sum(
            1 for trade in blocked if trade.net_pnl > ZERO
        ),
        "blocked_losses": sum(
            1 for trade in blocked if trade.net_pnl < ZERO
        ),
        "blocked_breakeven": sum(
            1 for trade in blocked if trade.net_pnl == ZERO
        ),
        "blocked_net_pnl": str(blocked_net_pnl),
        "blocked_mean_net_r": (
            None
            if not blocked
            else str(
                sum((trade.net_r for trade in blocked), ZERO)
                / Decimal(len(blocked))
            )
        ),
        "delta_trade_contribution_pnl": str(-blocked_net_pnl),
        "robustness": _robustness(blocked),
    }


def _market_robustness(
    trades: tuple[TradeJournalEntry, ...],
) -> dict[str, object]:
    by_market: dict[str, Decimal] = {}
    for trade in trades:
        market = trade.market.canonical
        by_market[market] = (
            by_market.get(market, ZERO) - trade.net_pnl
        )
    total = sum(by_market.values(), ZERO)
    leave_one_out = tuple(
        total - delta for delta in by_market.values()
    )
    minimum = min(leave_one_out, default=ZERO)
    return {
        "market_count": len(by_market),
        "leave_one_market_out_min_delta_pnl": str(minimum),
        "positive_after_removing_any_one_market": (
            len(by_market) >= 2 and minimum > ZERO
        ),
    }


def _streak_threshold_summary(
    values: tuple[tuple[TradeJournalEntry, int], ...],
    *,
    min_prior_losing_stops: int,
) -> dict[str, object]:
    blocked = tuple(
        trade
        for trade, streak in values
        if streak >= min_prior_losing_stops
    )
    blocked_net_pnl = sum(
        (trade.net_pnl for trade in blocked),
        ZERO,
    )
    return {
        "min_prior_losing_stops": min_prior_losing_stops,
        "blocked_trades": len(blocked),
        "blocked_winners": sum(
            1 for trade in blocked if trade.net_pnl > ZERO
        ),
        "blocked_losses": sum(
            1 for trade in blocked if trade.net_pnl < ZERO
        ),
        "blocked_breakeven": sum(
            1 for trade in blocked if trade.net_pnl == ZERO
        ),
        "blocked_net_pnl": str(blocked_net_pnl),
        "blocked_net_r": str(
            sum((trade.net_r for trade in blocked), ZERO)
        ),
        "delta_trade_contribution_pnl": str(-blocked_net_pnl),
        "robustness": _robustness(blocked),
        "market_robustness": _market_robustness(blocked),
    }


def closed_trade_stop_reentry_summary(
    trades: Sequence[TradeJournalEntry],
) -> dict[str, object]:
    ordered = tuple(
        sorted(
            trades,
            key=lambda trade: (
                trade.opened_at_ms,
                trade.closed_at_ms,
                trade.trade_id,
            ),
        )
    )
    history: dict[
        tuple[str, Direction],
        list[TradeJournalEntry],
    ] = {}
    reentries: list[
        tuple[TradeJournalEntry, int, TradeJournalEntry, int]
    ] = []
    streak_values: list[tuple[TradeJournalEntry, int]] = []
    fresh_or_reset: list[TradeJournalEntry] = []

    for trade in ordered:
        key = (trade.market.canonical, trade.direction)
        prior_trades = history.setdefault(key, [])
        completed = tuple(
            prior
            for prior in prior_trades
            if prior.closed_at_ms <= trade.opened_at_ms
        )
        previous = (
            None
            if not completed
            else max(
                completed,
                key=lambda prior: (
                    prior.closed_at_ms,
                    prior.opened_at_ms,
                    prior.trade_id,
                ),
            )
        )
        completed_ordered = tuple(
            sorted(
                completed,
                key=lambda prior: (
                    prior.closed_at_ms,
                    prior.opened_at_ms,
                    prior.trade_id,
                ),
            )
        )
        prior_losing_stop_streak = 0
        for prior in reversed(completed_ordered):
            if (
                prior.exit_reason == STOP_EXIT_REASON
                and prior.net_pnl < ZERO
            ):
                prior_losing_stop_streak += 1
                continue
            break
        streak_values.append(
            (trade, prior_losing_stop_streak)
        )
        if (
            previous is not None
            and previous.exit_reason == STOP_EXIT_REASON
            and previous.net_pnl < ZERO
        ):
            reentries.append(
                (
                    trade,
                    trade.opened_at_ms - previous.closed_at_ms,
                    previous,
                    prior_losing_stop_streak,
                )
            )
        else:
            fresh_or_reset.append(trade)
        prior_trades.append(trade)

    reentry_values = tuple(reentries)
    reentry_trades = tuple(
        trade
        for trade, _gap_ms, _previous, _streak in reentry_values
    )
    fresh_values = tuple(fresh_or_reset)

    by_gap_bucket: dict[str, dict[str, object]] = {}
    for bucket in ("0-5m", "5-30m", "30-120m", "120m+"):
        cohort = tuple(
            trade
            for trade, gap_ms, _previous, _streak in reentry_values
            if _gap_bucket(gap_ms) == bucket
        )
        by_gap_bucket[bucket] = _summary(cohort)

    reentry_by_direction = {
        direction.value: _summary(
            tuple(
                trade
                for trade, _gap_ms, _previous, _streak in reentry_values
                if trade.direction is direction
            )
        )
        for direction in (Direction.LONG, Direction.SHORT)
    }
    reentry_markets = sorted(
        {trade.market.canonical for trade in reentry_trades}
    )
    reentry_by_market = {
        market: _summary(
            tuple(
                trade
                for trade in reentry_trades
                if trade.market.canonical == market
            )
        )
        for market in reentry_markets
    }

    reentry_summary = _summary(reentry_trades)
    fresh_summary = _summary(fresh_values)
    resolved_streak_values = tuple(streak_values)
    by_prior_losing_stop_streak = {
        "0": _summary(
            tuple(
                trade
                for trade, streak in resolved_streak_values
                if streak == 0
            )
        ),
        "1": _summary(
            tuple(
                trade
                for trade, streak in resolved_streak_values
                if streak == 1
            )
        ),
        "2": _summary(
            tuple(
                trade
                for trade, streak in resolved_streak_values
                if streak == 2
            )
        ),
        "3+": _summary(
            tuple(
                trade
                for trade, streak in resolved_streak_values
                if streak >= 3
            )
        ),
    }
    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "descriptive_only": True,
        "changes_readiness_gate": False,
        "claim_scope": (
            "closed_trade_same_market_same_side_after_losing_stop"
        ),
        "closed_trades": len(ordered),
        "reentry_trades": len(reentry_trades),
        "fresh_or_reset_trades": len(fresh_values),
        "reentry_wins": reentry_summary["wins"],
        "reentry_losses": reentry_summary["losses"],
        "reentry_net_pnl": reentry_summary["net_pnl"],
        "reentry_mean_net_r": reentry_summary["mean_net_r"],
        "fresh_or_reset_wins": fresh_summary["wins"],
        "fresh_or_reset_losses": fresh_summary["losses"],
        "fresh_or_reset_net_pnl": fresh_summary["net_pnl"],
        "fresh_or_reset_mean_net_r": fresh_summary["mean_net_r"],
        "by_gap_bucket": by_gap_bucket,
        "reentry_by_direction": reentry_by_direction,
        "reentry_by_market": reentry_by_market,
        "by_prior_losing_stop_streak": (
            by_prior_losing_stop_streak
        ),
        "skip_after_prior_losing_stops": {
            "after_1": _streak_threshold_summary(
                resolved_streak_values,
                min_prior_losing_stops=1,
            ),
            "after_2": _streak_threshold_summary(
                resolved_streak_values,
                min_prior_losing_stops=2,
            ),
            "after_3": _streak_threshold_summary(
                resolved_streak_values,
                min_prior_losing_stops=3,
            ),
        },
        "skip_windows": {
            "within_5m": _window_summary(
                reentry_values,
                max_gap_ms=FIVE_MINUTES_MS,
            ),
            "within_30m": _window_summary(
                reentry_values,
                max_gap_ms=THIRTY_MINUTES_MS,
            ),
            "within_120m": _window_summary(
                reentry_values,
                max_gap_ms=TWO_HOURS_MS,
            ),
        },
    }
