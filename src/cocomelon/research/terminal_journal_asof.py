"""Conservative as-of projections from the original terminal-only paper journal.

This is a RESEARCH-ONLY input filter. A finalized trade must not contribute
its historical opening to an opportunity evaluated before that finalization.

A terminal-only journal cannot certify an earlier open was observed. When
such a trade overlaps an opportunity, callers must flag research integrity
dirty even though they use the conservative closed-as-of projection.
"""
from __future__ import annotations

from collections.abc import Sequence

from cocomelon.domain.journal import TradeJournalEntry


def terminal_trades_known_at(
    trades: Sequence[TradeJournalEntry],
    *,
    timestamp_ms: int,
) -> tuple[TradeJournalEntry, ...]:
    """Use only original terminal records finalized by the query clock."""
    return tuple(
        trade for trade in trades if trade.closed_at_ms <= timestamp_ms
    )


def future_finalized_open_exposure(
    trades: Sequence[TradeJournalEntry],
    *,
    timestamp_ms: int,
    overlap_started_at_ms: int,
    market: str,
    direction: str,
) -> bool:
    """Potential online-open provenance gap; never grant readiness when true."""
    return any(
        trade.opened_at_ms >= overlap_started_at_ms
        and trade.opened_at_ms < timestamp_ms
        and trade.closed_at_ms > timestamp_ms
        and trade.market.canonical == market
        and trade.direction.value == direction
        for trade in trades
    )
