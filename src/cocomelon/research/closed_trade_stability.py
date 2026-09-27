from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from statistics import median
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry

ZERO: Final = Decimal("0")
ROLLING_WINDOWS: Final = (5, 10)
CHRONOLOGICAL_BLOCKS: Final = 4
MIN_TRADES_PER_BLOCK: Final = 10
MIN_CLOSED_TRADES_FOR_REVIEW: Final = (
    CHRONOLOGICAL_BLOCKS * MIN_TRADES_PER_BLOCK
)


def _ordered(
    trades: Sequence[TradeJournalEntry],
) -> tuple[TradeJournalEntry, ...]:
    return tuple(
        sorted(
            trades,
            key=lambda trade: (
                trade.closed_at_ms,
                trade.opened_at_ms,
                trade.trade_id,
            ),
        )
    )


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


def _summary(
    trades: Sequence[TradeJournalEntry],
) -> dict[str, object]:
    items = tuple(trades)
    count = len(items)
    net_pnl = sum((trade.net_pnl for trade in items), ZERO)
    total_r = sum((trade.net_r for trade in items), ZERO)
    pf = _profit_factor(items)
    median_r = (
        None
        if not items
        else Decimal(str(median([trade.net_r for trade in items])))
    )
    return {
        "trades": count,
        "wins": sum(1 for trade in items if trade.net_pnl > ZERO),
        "losses": sum(1 for trade in items if trade.net_pnl < ZERO),
        "breakeven": sum(
            1 for trade in items if trade.net_pnl == ZERO
        ),
        "net_pnl": str(net_pnl),
        "mean_net_r": (
            None
            if count == 0
            else str(total_r / Decimal(count))
        ),
        "median_net_r": (
            None if median_r is None else str(median_r)
        ),
        "profit_factor": None if pf is None else str(pf),
        "positive_net_pnl": net_pnl > ZERO,
        "positive_mean_net_r": total_r > ZERO,
        "first_closed_at_ms": (
            None if not items else items[0].closed_at_ms
        ),
        "last_closed_at_ms": (
            None if not items else items[-1].closed_at_ms
        ),
    }


def _rolling(
    trades: tuple[TradeJournalEntry, ...],
    size: int,
) -> dict[str, object]:
    windows = tuple(
        trades[index : index + size]
        for index in range(0, len(trades) - size + 1)
    )
    summaries = tuple(_summary(window) for window in windows)
    positive_pnl = sum(
        1
        for item in summaries
        if item["positive_net_pnl"] is True
    )
    positive_r = sum(
        1
        for item in summaries
        if item["positive_mean_net_r"] is True
    )

    if not summaries:
        return {
            "window_size": size,
            "window_count": 0,
            "latest": None,
            "positive_pnl_windows": 0,
            "positive_mean_r_windows": 0,
            "positive_pnl_fraction": None,
            "positive_mean_r_fraction": None,
            "worst_mean_net_r": None,
            "best_mean_net_r": None,
            "worst_net_pnl": None,
            "best_net_pnl": None,
        }

    mean_rs = tuple(
        Decimal(str(item["mean_net_r"]))
        for item in summaries
        if item["mean_net_r"] is not None
    )
    pnls = tuple(
        Decimal(str(item["net_pnl"]))
        for item in summaries
    )
    count = len(summaries)
    return {
        "window_size": size,
        "window_count": count,
        "latest": summaries[-1],
        "positive_pnl_windows": positive_pnl,
        "positive_mean_r_windows": positive_r,
        "positive_pnl_fraction": str(
            Decimal(positive_pnl) / Decimal(count)
        ),
        "positive_mean_r_fraction": str(
            Decimal(positive_r) / Decimal(count)
        ),
        "worst_mean_net_r": str(min(mean_rs)),
        "best_mean_net_r": str(max(mean_rs)),
        "worst_net_pnl": str(min(pnls)),
        "best_net_pnl": str(max(pnls)),
    }


def _chronological_blocks(
    trades: tuple[TradeJournalEntry, ...],
) -> tuple[dict[str, object], ...]:
    if not trades:
        return ()
    quotient, remainder = divmod(
        len(trades),
        CHRONOLOGICAL_BLOCKS,
    )
    blocks: list[dict[str, object]] = []
    start = 0
    for index in range(CHRONOLOGICAL_BLOCKS):
        count = quotient + (1 if index < remainder else 0)
        stop = start + count
        block = trades[start:stop]
        payload = _summary(block)
        payload["block"] = index + 1
        blocks.append(payload)
        start = stop
    return tuple(blocks)


def closed_trade_stability(
    trades: Sequence[TradeJournalEntry],
) -> dict[str, object]:
    items = _ordered(trades)
    blocks = _chronological_blocks(items)
    full_blocks = tuple(
        block
        for block in blocks
        if int(block["trades"]) >= MIN_TRADES_PER_BLOCK
    )
    all_blocks_positive_pnl = (
        len(full_blocks) == CHRONOLOGICAL_BLOCKS
        and all(
            block["positive_net_pnl"] is True
            for block in full_blocks
        )
    )
    all_blocks_positive_mean_r = (
        len(full_blocks) == CHRONOLOGICAL_BLOCKS
        and all(
            block["positive_mean_net_r"] is True
            for block in full_blocks
        )
    )
    ready = (
        len(items) >= MIN_CLOSED_TRADES_FOR_REVIEW
        and len(full_blocks) == CHRONOLOGICAL_BLOCKS
    )

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "definition": (
            "chronological_closed_trade_net_economics"
        ),
        "closed_trades": len(items),
        "overall": _summary(items),
        "rolling": {
            str(size): _rolling(items, size)
            for size in ROLLING_WINDOWS
        },
        "chronological_blocks": list(blocks),
        "stability": {
            "all_full_blocks_positive_net_pnl": (
                all_blocks_positive_pnl
            ),
            "all_full_blocks_positive_mean_net_r": (
                all_blocks_positive_mean_r
            ),
            "full_blocks": len(full_blocks),
        },
        "readiness": {
            "min_closed_trades": (
                MIN_CLOSED_TRADES_FOR_REVIEW
            ),
            "chronological_blocks": CHRONOLOGICAL_BLOCKS,
            "min_trades_per_block": MIN_TRADES_PER_BLOCK,
            "missing_closed_trades": max(
                0,
                MIN_CLOSED_TRADES_FOR_REVIEW - len(items),
            ),
            "ready_for_review": ready,
        },
    }
