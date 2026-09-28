from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from decimal import Decimal
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry

ZERO: Final = Decimal("0")
TEMPORAL_BLOCKS: Final = 4
MIN_TRADES_PER_FULL_BLOCK: Final = 5


class ProspectiveFilterRobustnessError(RuntimeError):
    pass


def _contribution(
    trade: TradeJournalEntry,
    blocked: bool,
) -> Decimal:
    return -trade.net_pnl if blocked else ZERO


def prospective_filter_robustness(
    items: Sequence[tuple[TradeJournalEntry, bool]],
) -> dict[str, object]:
    values = tuple(items)
    ids = tuple(trade.trade_id for trade, _ in values)
    if len(set(ids)) != len(ids):
        raise ProspectiveFilterRobustnessError(
            "filter robustness contains duplicate trade ids"
        )

    contributions = tuple(
        (trade, _contribution(trade, blocked))
        for trade, blocked in values
    )
    nonzero = tuple(
        (trade, value)
        for trade, value in contributions
        if value != ZERO
    )
    total = sum((value for _, value in contributions), ZERO)
    abs_total = sum((abs(value) for _, value in nonzero), ZERO)

    largest_trade = (
        None
        if not nonzero
        else max(
            nonzero,
            key=lambda item: (
                abs(item[1]),
                item[0].closed_at_ms,
                item[0].trade_id,
            ),
        )
    )
    leave_one_trade_out = tuple(
        total - value
        for _, value in nonzero
    )

    market_contribution: dict[str, Decimal] = defaultdict(
        lambda: ZERO
    )
    for trade, value in contributions:
        market_contribution[trade.market.canonical] += value
    nonzero_markets = {
        market: value
        for market, value in market_contribution.items()
        if value != ZERO
    }
    abs_market_total = sum(
        (abs(value) for value in nonzero_markets.values()),
        ZERO,
    )
    largest_market = (
        None
        if not nonzero_markets
        else max(
            nonzero_markets.items(),
            key=lambda item: (abs(item[1]), item[0]),
        )
    )
    leave_one_market_out = tuple(
        total - value
        for value in nonzero_markets.values()
    )

    ordered = tuple(
        sorted(
            contributions,
            key=lambda item: (
                item[0].closed_at_ms,
                item[0].opened_at_ms,
                item[0].trade_id,
            ),
        )
    )
    quotient, remainder = divmod(
        len(ordered),
        TEMPORAL_BLOCKS,
    )
    blocks: list[dict[str, object]] = []
    start = 0
    for index in range(TEMPORAL_BLOCKS):
        count = quotient + (1 if index < remainder else 0)
        stop = start + count
        block = ordered[start:stop]
        start = stop
        if not block:
            continue
        delta = sum((value for _, value in block), ZERO)
        blocked_count = sum(
            1 for _, value in block if value != ZERO
        )
        blocks.append(
            {
                "block": index + 1,
                "trades": len(block),
                "blocked_trades": blocked_count,
                "first_closed_at_ms": block[0][0].closed_at_ms,
                "last_closed_at_ms": block[-1][0].closed_at_ms,
                "delta_trade_contribution_pnl": str(delta),
                "positive_delta": delta > ZERO,
            }
        )

    def is_full_block(block: dict[str, object]) -> bool:
        count = block.get("trades")
        return (
            isinstance(count, int)
            and not isinstance(count, bool)
            and count >= MIN_TRADES_PER_FULL_BLOCK
        )

    full_blocks = tuple(
        block
        for block in blocks
        if is_full_block(block)
    )
    positive_full_blocks = sum(
        1
        for block in full_blocks
        if block["positive_delta"] is True
    )

    return {
        "descriptive_only": True,
        "changes_readiness_gate": False,
        "attributed_trades": len(values),
        "nonzero_blocked_contributions": len(nonzero),
        "markets_with_nonzero_blocked_contribution": len(
            nonzero_markets
        ),
        "total_delta_trade_contribution_pnl": str(total),
        "largest_abs_trade_contribution": (
            None
            if largest_trade is None
            else str(largest_trade[1])
        ),
        "largest_abs_trade_market": (
            None
            if largest_trade is None
            else largest_trade[0].market.canonical
        ),
        "largest_abs_trade_share": (
            None
            if largest_trade is None or abs_total == ZERO
            else str(abs(largest_trade[1]) / abs_total)
        ),
        "leave_one_trade_out_min_delta": (
            None
            if not leave_one_trade_out
            else str(min(leave_one_trade_out))
        ),
        "positive_after_any_single_trade_removed": (
            None
            if len(nonzero) < 2
            else min(leave_one_trade_out) > ZERO
        ),
        "largest_abs_market": (
            None
            if largest_market is None
            else largest_market[0]
        ),
        "largest_abs_market_contribution": (
            None
            if largest_market is None
            else str(largest_market[1])
        ),
        "largest_abs_market_share": (
            None
            if largest_market is None or abs_market_total == ZERO
            else str(abs(largest_market[1]) / abs_market_total)
        ),
        "leave_one_market_out_min_delta": (
            None
            if not leave_one_market_out
            else str(min(leave_one_market_out))
        ),
        "positive_after_any_single_market_removed": (
            None
            if len(nonzero_markets) < 2
            else min(leave_one_market_out) > ZERO
        ),
        "temporal": {
            "chronological_blocks": blocks,
            "configured_blocks": TEMPORAL_BLOCKS,
            "min_trades_per_full_block": (
                MIN_TRADES_PER_FULL_BLOCK
            ),
            "full_blocks": len(full_blocks),
            "positive_full_blocks": positive_full_blocks,
            "all_full_blocks_positive": (
                len(full_blocks) == TEMPORAL_BLOCKS
                and positive_full_blocks == TEMPORAL_BLOCKS
            ),
        },
    }
