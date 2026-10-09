"""Recover only *named* checkpoint gaps on accepted, fresh public WS evidence.

This observer owns no trading decisions. A checkpoint's anonymous legacy
outages have no source identity and can never enter its recovery set.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence

from cocomelon.domain.stream import DataGap, StreamEvent, StreamKind
from cocomelon.hyperliquid.ws_protocol import SOURCE as MAINNET_WS_SOURCE
from cocomelon.hyperliquid.ws_supervisor import event_stream_id

GapSink = Callable[[DataGap], Awaitable[None]]
GapIntervals = Mapping[str, Sequence[tuple[int, int | None]]]


class RestoredNamedGapRecovery:
    """Carry forward exact named starts until genuine new events prove recovery.

    A source is not healed by worker bootstrap, a reused checkpoint, a
    different feed, or a stale/failed event. The caller must *first* persist
    the normalized WebSocket event, then call accept_recorded_event.
    """

    def __init__(
        self,
        *,
        market_gaps: GapIntervals,
        global_gaps: GapIntervals,
        checkpoint_ms: int,
        max_exchange_age_ms: int,
        max_delivery_lag_ms: int = 30_000,
    ) -> None:
        if (
            type(checkpoint_ms) is not int or checkpoint_ms < 0
            or type(max_exchange_age_ms) is not int
            or max_exchange_age_ms <= 0
            or type(max_delivery_lag_ms) is not int
            or max_delivery_lag_ms <= 0
        ):
            raise ValueError("invalid restored named source recovery limits")
        if set(market_gaps) & set(global_gaps):
            raise ValueError("named source appears in both checkpoint scopes")
        self._lock = asyncio.Lock()
        self._checkpoint_ms = checkpoint_ms
        self._max_exchange_age_ms = max_exchange_age_ms
        self._max_delivery_lag_ms = max_delivery_lag_ms
        self._open: dict[str, set[int]] = {
            stream_id: {
                start for start, ended in intervals if ended is None
            }
            for scope in (market_gaps, global_gaps)
            for stream_id, intervals in scope.items()
        }
        self._open = {
            stream_id: starts for stream_id, starts in self._open.items()
            if starts
        }

    @property
    def pending_named_starts(self) -> dict[str, tuple[int, ...]]:
        return {
            stream_id: tuple(sorted(starts))
            for stream_id, starts in sorted(self._open.items())
        }

    def _fresh_recovery_gaps(
        self, event: StreamEvent, *, observed_at_ms: int,
    ) -> tuple[DataGap, ...]:
        if type(observed_at_ms) is not int or observed_at_ms < 0:
            raise ValueError("observed_at_ms must be nonnegative integer")
        if event.source != MAINNET_WS_SOURCE:
            return ()
        stream_id = event_stream_id(event)
        starts = self._open.get(stream_id)
        if not starts:
            return ()
        received_ms = int(event.receive_time.timestamp() * 1_000)
        if (
            received_ms <= self._checkpoint_ms
            or observed_at_ms < received_ms
            or observed_at_ms - received_ms > self._max_delivery_lag_ms
            or any(start >= received_ms for start in starts)
        ):
            return ()
        exchange_ms = event.exchange_time_ms
        if event.kind is StreamKind.L2_BOOK and exchange_ms is None:
            return ()
        if exchange_ms is not None and not (
            0 <= received_ms - exchange_ms < self._max_exchange_age_ms
        ):
            return ()
        return tuple(
            DataGap(
                stream_id=stream_id,
                started_ms=start,
                ended_ms=received_ms,
                reason="recovered_after_handoff_witness",
            )
            for start in sorted(starts)
        )

    async def accept_recorded_event(
        self,
        event: StreamEvent,
        *,
        observed_at_ms: int,
        gap_sink: GapSink,
    ) -> int:
        """Commit recovery receipts, never remove a start on failed persistence.

        This must be called only AFTER the normalized event's durable paper
        pipeline write has returned successfully. The returned count covers
        source starts, not certified historical trades or recovered prices.
        """
        async with self._lock:
            count = 0
            for gap in self._fresh_recovery_gaps(
                event, observed_at_ms=observed_at_ms,
            ):
                await gap_sink(gap)
                self._open[gap.stream_id].remove(gap.started_ms)
                if not self._open[gap.stream_id]:
                    del self._open[gap.stream_id]
                count += 1
            return count
