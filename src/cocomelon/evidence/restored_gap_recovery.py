"""Recover only *named* checkpoint gaps on accepted, fresh public WS evidence.

This observer owns no trading decisions. A checkpoint's anonymous legacy
outages have no source identity and can never enter its recovery set.
"""
from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path

from cocomelon.domain.candle_intervals import CANDLE_INTERVAL_MS
from cocomelon.domain.stream import DataGap, StreamEvent, StreamKind
from cocomelon.hyperliquid.ws_protocol import SOURCE as MAINNET_WS_SOURCE
from cocomelon.hyperliquid.ws_supervisor import event_stream_id

GapSink = Callable[[DataGap], Awaitable[None]]
WitnessSink = Callable[[StreamEvent, DataGap, int], Awaitable[None]]
GapIntervals = Mapping[str, Sequence[tuple[int, int | None]]]
WITNESS_FILENAME = "named-gap-recovery-witnesses.jsonl"
ROTATION_WITNESS_FILENAME = "in-session-gap-recovery-witnesses.jsonl"


def append_restored_named_gap_witness(
    path: str | Path,
    *,
    event: StreamEvent,
    gap: DataGap,
    checkpoint_ms: int,
) -> None:
    """Fsynced event proof, not a claim that a later gap write succeeded.

    The deferred auditor must independently intersect this witness with
    the persisted closed source interval before reporting a verified closure.
    """
    received_ms = int(event.receive_time.timestamp() * 1_000)
    payload = {
        "definition": "post_handoff_named_ws_recovery_witness_v1",
        "checkpoint_last_available_at_ms": checkpoint_ms,
        "stream_id": gap.stream_id,
        "gap_start_ms": gap.started_ms,
        "witness_receive_ms": received_ms,
        "witness_exchange_ms": event.exchange_time_ms,
        "witness_event_key": event.event_key,
        "witness_event_source": event.source,
        "observed_event_before_gap_closure": True,
        "independently_verified_checkpoint_closure": False,
        "historical_price_reconstruction": False,
        "research_only": True,
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        ) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def append_in_session_rotation_gap_witness(
    path: str | Path,
    *,
    event: StreamEvent,
    gap: DataGap,
    checkpoint_ms: int,
) -> None:
    """Fsync proof of a post-rotation *accepted* event before exact gap close.

    Distinct from a predecessor-checkpoint recovery receipt: no signed state
    has certified this live watchlist rotation. An on-disk witness is not
    permission to erase missing ticks or bypass the forward-data gap gates.
    """
    received_ms = int(event.receive_time.timestamp() * 1_000)
    if (
        event.source != MAINNET_WS_SOURCE
        or event_stream_id(event) != gap.stream_id
        or not (0 <= gap.started_ms < checkpoint_ms < received_ms)
    ):
        raise ValueError("invalid in-session source recovery witness")
    payload = {
        "definition": "post_rotation_named_ws_recovery_witness_v1",
        "rotation_checkpoint_ms": checkpoint_ms,
        "stream_id": gap.stream_id,
        "gap_start_ms": gap.started_ms,
        "witness_receive_ms": received_ms,
        "witness_exchange_ms": event.exchange_time_ms,
        "witness_event_key": event.event_key,
        "witness_event_source": event.source,
        "observed_event_before_gap_closure": True,
        "independently_verified_checkpoint_closure": False,
        "historical_price_reconstruction": False,
        "research_only": True,
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
            + "\n"
        )
        handle.flush()
        os.fsync(handle.fileno())


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
        recovery_reason: str = "recovered_after_handoff_witness",
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
        if recovery_reason not in {
            "recovered_after_handoff_witness",
            "recovered_after_rotation_witness",
        }:
            raise ValueError("invalid named source recovery reason")
        self._recovery_reason = recovery_reason
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
        if event.kind is StreamKind.CANDLE:
            # Hyperliquid WS candle exchange_time_ms is the OPEN of its
            # interval, not the arrival timestamp. A valid current 15m
            # candle can be hundreds of seconds old under the ordinary
            # L2 book-age ceiling. Verify the candle's exact time window
            # and source identity instead; an old completed candle MUST
            # NOT cure a missing-feed interval merely because it arrived.
            payload = event.payload
            period = payload.get("interval")
            start = payload.get("start_ms")
            end = payload.get("end_ms")
            duration = (
                CANDLE_INTERVAL_MS.get(period)
                if isinstance(period, str) else None
            )
            if (
                duration is None
                or type(start) is not int
                or type(end) is not int
                or start < 0
                or exchange_ms != start
                or end - start not in (duration - 1, duration)
                or not start <= received_ms <= end + self._max_exchange_age_ms
            ):
                return ()
        else:
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
                reason=self._recovery_reason,
            )
            for start in sorted(starts)
        )

    async def accept_recorded_event(
        self,
        event: StreamEvent,
        *,
        observed_at_ms: int,
        gap_sink: GapSink,
        witness_sink: WitnessSink | None = None,
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
                # Record the real accepted source event *before* the gap
                # closes. A witness alone is not a verified recovery:
                # deferred audit checks the exact checkpoint afterwards.
                if witness_sink is not None:
                    await witness_sink(event, gap, self._checkpoint_ms)
                await gap_sink(gap)
                self._open[gap.stream_id].remove(gap.started_ms)
                if not self._open[gap.stream_id]:
                    del self._open[gap.stream_id]
                count += 1
            return count

def rotation_named_gap_recovery(
    *,
    market_gaps: GapIntervals,
    global_gaps: GapIntervals,
    checkpoint_ms: int,
    max_exchange_age_ms: int,
    earlier_observers: Sequence[RestoredNamedGapRecovery],
) -> RestoredNamedGapRecovery | None:
    """Reseed ONLY unclaimed, exact open starts at a live supervisor rotation.

    A newly subscribed WebSocket group can be fully ready while the replaced
    mux still has an unclosed source gap. Group readiness alone may NOT close
    an interval. Capture those exact durable starts before switching and wait
    for a distinct, actually accepted post-rotation source event to prove its
    recovery. Existing restored/rotation observers retain their own starts;
    overlap must not double-emit a gap closure.
    """
    claimed: dict[str, set[int]] = {}
    for observer in earlier_observers:
        for stream_id, starts in observer.pending_named_starts.items():
            claimed.setdefault(stream_id, set()).update(starts)

    def unclaimed(
        intervals_by_stream: GapIntervals,
    ) -> dict[str, tuple[tuple[int, int | None], ...]]:
        selected: dict[str, tuple[tuple[int, int | None], ...]] = {}
        for stream_id, intervals in intervals_by_stream.items():
            pending = tuple(
                (start, None)
                for start, end in intervals
                if end is None
                and 0 <= start < checkpoint_ms
                and start not in claimed.get(stream_id, set())
            )
            if pending:
                selected[stream_id] = pending
        return selected

    remaining_market = unclaimed(market_gaps)
    remaining_global = unclaimed(global_gaps)
    if not remaining_market and not remaining_global:
        return None
    return RestoredNamedGapRecovery(
        market_gaps=remaining_market,
        global_gaps=remaining_global,
        checkpoint_ms=checkpoint_ms,
        max_exchange_age_ms=max_exchange_age_ms,
        recovery_reason="recovered_after_rotation_witness",
    )


