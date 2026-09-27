from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from decimal import Decimal
from statistics import median
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry

ZERO: Final = Decimal("0")
MIN_CLOSED_TRADES_FOR_REVIEW: Final = 30


def _profit_factor(
    trades: Sequence[TradeJournalEntry],
) -> Decimal | None:
    gross_profit = sum(
        (trade.net_pnl for trade in trades if trade.net_pnl > ZERO),
        ZERO,
    )
    gross_loss_abs = -sum(
        (trade.net_pnl for trade in trades if trade.net_pnl < ZERO),
        ZERO,
    )
    if gross_loss_abs == ZERO:
        return None
    if gross_profit == ZERO:
        return ZERO
    return gross_profit / gross_loss_abs


def _median_net_r(
    trades: Sequence[TradeJournalEntry],
) -> Decimal | None:
    if not trades:
        return None
    return Decimal(str(median([trade.net_r for trade in trades])))


def _scenario(
    trades: tuple[TradeJournalEntry, ...],
    *,
    removed: tuple[TradeJournalEntry, ...],
) -> dict[str, object]:
    removed_ids = {trade.trade_id for trade in removed}
    remaining = tuple(
        trade for trade in trades if trade.trade_id not in removed_ids
    )
    net_pnl = sum((trade.net_pnl for trade in remaining), ZERO)
    net_r = sum((trade.net_r for trade in remaining), ZERO)
    pf = _profit_factor(remaining)
    return {
        "remaining_trades": len(remaining),
        "removed_trade_count": len(removed),
        "removed_trade_ids": [trade.trade_id for trade in removed],
        "removed_net_pnl": str(
            sum((trade.net_pnl for trade in removed), ZERO)
        ),
        "net_pnl": str(net_pnl),
        "mean_net_r": (
            None
            if not remaining
            else str(net_r / Decimal(len(remaining)))
        ),
        "median_net_r": (
            None
            if not remaining
            else str(_median_net_r(remaining))
        ),
        "profit_factor": None if pf is None else str(pf),
        "positive_net_pnl": net_pnl > ZERO,
    }


def closed_trade_robustness(
    trades: Sequence[TradeJournalEntry],
) -> dict[str, object]:
    items = tuple(trades)
    ordered_winners = tuple(
        sorted(
            (
                trade
                for trade in items
                if trade.net_pnl > ZERO
            ),
            key=lambda trade: (
                trade.net_pnl,
                trade.net_r,
                trade.closed_at_ms,
                trade.trade_id,
            ),
            reverse=True,
        )
    )
    gross_profit = sum(
        (trade.net_pnl for trade in ordered_winners),
        ZERO,
    )
    net_pnl = sum((trade.net_pnl for trade in items), ZERO)
    top_one = ordered_winners[:1]
    top_two = ordered_winners[:2]
    top_one_pnl = sum((trade.net_pnl for trade in top_one), ZERO)
    top_two_pnl = sum((trade.net_pnl for trade in top_two), ZERO)

    remove_best_one = _scenario(items, removed=top_one)
    remove_best_two = _scenario(items, removed=top_two)

    market_groups: dict[str, list[TradeJournalEntry]] = defaultdict(list)
    for trade in items:
        market_groups[trade.market.canonical].append(trade)
    market_net_pnl = {
        market: sum(
            (trade.net_pnl for trade in trades_for_market),
            ZERO,
        )
        for market, trades_for_market in market_groups.items()
    }
    positive_market_net_pnl = {
        market: pnl
        for market, pnl in market_net_pnl.items()
        if pnl > ZERO
    }
    positive_market_total = sum(
        positive_market_net_pnl.values(),
        ZERO,
    )
    top_positive_market = (
        None
        if not positive_market_net_pnl
        else max(
            positive_market_net_pnl,
            key=lambda market: (
                positive_market_net_pnl[market],
                market,
            ),
        )
    )
    top_positive_market_trades = (
        ()
        if top_positive_market is None
        else tuple(market_groups[top_positive_market])
    )
    top_positive_market_pnl = (
        None
        if top_positive_market is None
        else positive_market_net_pnl[top_positive_market]
    )
    remove_top_positive_market = _scenario(
        items,
        removed=top_positive_market_trades,
    )

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "closed_trades": len(items),
        "net_pnl": str(net_pnl),
        "gross_profit": str(gross_profit),
        "median_net_r": (
            None
            if not items
            else str(_median_net_r(items))
        ),
        "largest_winner_net_pnl": (
            None
            if not ordered_winners
            else str(ordered_winners[0].net_pnl)
        ),
        "largest_winner_net_r": (
            None
            if not ordered_winners
            else str(ordered_winners[0].net_r)
        ),
        "largest_winner_trade_id": (
            None
            if not ordered_winners
            else ordered_winners[0].trade_id
        ),
        "top_one_winner_share_of_gross_profit": (
            None
            if gross_profit == ZERO
            else str(top_one_pnl / gross_profit)
        ),
        "top_two_winner_share_of_gross_profit": (
            None
            if gross_profit == ZERO
            else str(top_two_pnl / gross_profit)
        ),
        "top_positive_market": top_positive_market,
        "top_positive_market_net_pnl": (
            None
            if top_positive_market_pnl is None
            else str(top_positive_market_pnl)
        ),
        "top_positive_market_trade_count": len(
            top_positive_market_trades
        ),
        "top_positive_market_share_of_positive_market_pnl": (
            None
            if top_positive_market_pnl is None
            or positive_market_total == ZERO
            else str(
                top_positive_market_pnl
                / positive_market_total
            )
        ),
        "remove_best_one": remove_best_one,
        "remove_best_two": remove_best_two,
        "remove_top_positive_market": remove_top_positive_market,
        "positive_pnl_survives_remove_best_one": bool(
            remove_best_one["positive_net_pnl"]
        ),
        "positive_pnl_survives_remove_best_two": bool(
            remove_best_two["positive_net_pnl"]
        ),
        "positive_pnl_survives_remove_top_positive_market": bool(
            remove_top_positive_market["positive_net_pnl"]
        ),
        "readiness": {
            "min_closed_trades": MIN_CLOSED_TRADES_FOR_REVIEW,
            "missing_closed_trades": max(
                0,
                MIN_CLOSED_TRADES_FOR_REVIEW - len(items),
            ),
            "ready_for_review": (
                len(items) >= MIN_CLOSED_TRADES_FOR_REVIEW
            ),
        },
    }
