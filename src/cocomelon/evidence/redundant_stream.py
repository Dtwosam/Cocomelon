from __future__ import annotations

import asyncio
import hashlib
import json
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable, Mapping
from time import perf_counter

from cocomelon.domain.stream import DataGap, StreamEvent, StreamKind
from cocomelon.hyperliquid.ws_supervisor import event_stream_id

EventSink = Callable[[StreamEvent], Awaitable[None]]
GapSink = Callable[[DataGap], Awaitable[None]]


class RedundantStreamMux:
    """Merge redundant normalized public streams without hiding true data loss.

    One lane is active per stream while the other continuously buffers normalized
    events. A lane-local disconnect or stale-stream gap switches that stream to
    a proven healthy standby while unrelated streams can remain on the same lane.
    The standby backfills events the active lane did not emit. A durable gap is
    forwarded
    whenever no lane has demonstrated continuous coverage for the stream.

    Supervisors send every subscription before they begin receiving messages. The
    first normalized event from a lane therefore proves that the whole websocket
    session completed its subscription phase, so that lane can cover any sibling
    subscription until a disconnect revokes session readiness. Per-stream recovery
    gaps remain authoritative after a disconnect.
    """

    def __init__(
        self,
        *,
        event_sink: EventSink,
        gap_sink: GapSink,
        lane_count: int = 2,
        buffer_size: int = 8192,
        dedup_size: int = 16384,
        receive_only_duplicate_window_ms: int = 1_000,
        defer_all_mids_aggregate_recovery: bool = False,
    ) -> None:
        if lane_count < 2:
            raise ValueError("lane_count must be at least two")
        if buffer_size <= 0:
            raise ValueError("buffer_size must be positive")
        if dedup_size <= 0:
            raise ValueError("dedup_size must be positive")
        if receive_only_duplicate_window_ms < 0:
            raise ValueError("receive_only_duplicate_window_ms must be non-negative")
        self._event_sink = event_sink
        self._gap_sink = gap_sink
        self._lane_count = lane_count
        self._buffer_size = buffer_size
        self._dedup_size = dedup_size
        self._receive_only_duplicate_window_ms = receive_only_duplicate_window_ms
        # Opt-in only for production supervisors with an authenticated
        # complete-frame acknowledgement callback. Standalone mux callers
        # preserve the old per-event recovery contract.
        self._defer_all_mids_aggregate_recovery = (
            defer_all_mids_aggregate_recovery
        )
        self._all_mids_pending_witnesses: dict[tuple[int, str], int] = {}
        self._active: dict[str, int] = {}
        self._buffers: dict[tuple[int, str], deque[StreamEvent]] = defaultdict(deque)
        self._lane_gap_starts: dict[str, dict[int, int]] = defaultdict(dict)
        self._observed_lanes: dict[str, set[int]] = defaultdict(set)
        self._session_ready_lanes: set[int] = set()
        self._aggregate_gap_starts: dict[str, int] = {}
        # A failed/cancelled durable OPEN write must block all subsequent
        # observations of this stream until its original gap is recorded.
        # This is a bounded subset of currently open gaps, not a retry queue
        # with fabricated timestamps or replacement source records.
        self._uncommitted_aggregate_gap_opens: set[str] = set()
        # Preserve the exact first recovery witness across a failed or
        # cancelled downstream CLOSE. A later event cannot move the
        # original boundary forward or be admitted before this is written.
        self._uncommitted_aggregate_gap_closes: dict[str, DataGap] = {}
        # A recovered notification alone is not a replayable price event.
        # Require an actually accepted normalized event from the healed lane.
        self._recovery_witness_lanes: dict[str, set[int]] = defaultdict(set)
        self._seen_keys: dict[str, set[str]] = defaultdict(set)
        self._seen_queues: dict[str, deque[str]] = defaultdict(deque)
        self._last_emitted: dict[str, StreamEvent] = {}
        self._failover_count = 0
        # Both WebSocket supervisors invoke this mux from independent tasks.
        # A downstream sink can yield: without an ingress lock another lane
        # can switch/drain a buffer while a prior emit has not yet committed
        # _last_emitted or its event key. Preserve actual callback order and
        # never reorder/repair the timestamps in the original events.
        self._ingress_lock = asyncio.Lock()
        self._ingress_active_waiters = 0
        self._ingress_peak_waiters = 0
        self._ingress_contended_calls = 0
        self._ingress_completed_calls = 0
        self._ingress_failed_calls = 0
        self._ingress_max_wait_ms = 0
        self._ingress_max_hold_ms = 0

    def ingress_diagnostics(self) -> dict[str, int | bool]:
        """Volatile, negative-only latency evidence; never gap authority."""
        return {
            "serialization_enabled": True,
            "completed_calls": self._ingress_completed_calls,
            "failed_calls": self._ingress_failed_calls,
            "uncommitted_aggregate_gap_open_count": len(
                self._uncommitted_aggregate_gap_opens
            ),
            "uncommitted_aggregate_gap_close_count": len(
                self._uncommitted_aggregate_gap_closes
            ),
            "contended_calls": self._ingress_contended_calls,
            "active_waiters": self._ingress_active_waiters,
            "peak_waiters": self._ingress_peak_waiters,
            "max_lock_wait_ms": self._ingress_max_wait_ms,
            "max_lock_hold_ms": self._ingress_max_hold_ms,
            "source_gap_or_paper_promotion_authority": False,
        }

    async def _serialize_ingress(
        self, lane: int, message: StreamEvent | DataGap,
    ) -> None:
        # Monotonic process durations only. Do not substitute them for
        # original venue exchange or socket receive clocks.
        started = perf_counter()
        if self._ingress_lock.locked():
            self._ingress_contended_calls += 1
        self._ingress_active_waiters += 1
        self._ingress_peak_waiters = max(
            self._ingress_peak_waiters, self._ingress_active_waiters
        )
        try:
            async with self._ingress_lock:
                self._ingress_max_wait_ms = max(
                    self._ingress_max_wait_ms,
                    max(0, int((perf_counter() - started) * 1000)),
                )
                held_at = perf_counter()
                try:
                    if isinstance(message, DataGap):
                        await self._on_gap_serialized(lane, message)
                    else:
                        await self._on_event_serialized(lane, message)
                except Exception:
                    # Preserve the actual sink exception and all prior
                    # immutable source-gap failure semantics.
                    self._ingress_failed_calls += 1
                    raise
                else:
                    self._ingress_completed_calls += 1
                finally:
                    self._ingress_max_hold_ms = max(
                        self._ingress_max_hold_ms,
                        max(0, int((perf_counter() - held_at) * 1000)),
                    )
        finally:
            self._ingress_active_waiters -= 1

    @property
    def failover_count(self) -> int:
        return self._failover_count

    def active_lane(self, stream_id: str) -> int:
        if not stream_id.strip():
            raise ValueError("stream_id must not be empty")
        return self._active.get(stream_id, 0)

    def _require_lane(self, lane: int) -> None:
        if lane < 0 or lane >= self._lane_count:
            raise ValueError("lane is outside configured redundant lane range")

    @staticmethod
    def _receive_ms(event: StreamEvent) -> int:
        return int(event.receive_time.timestamp() * 1_000)

    @staticmethod
    def _semantic_signature(event: StreamEvent) -> str:
        payload: Mapping[str, object] = event.payload
        encoded = json.dumps(
            {
                "kind": event.kind.value,
                "market": event.market.canonical,
                "payload": payload,
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _remember_key(self, stream_id: str, event_key: str) -> None:
        keys = self._seen_keys[stream_id]
        if event_key in keys:
            return
        queue = self._seen_queues[stream_id]
        keys.add(event_key)
        queue.append(event_key)
        while len(queue) > self._dedup_size:
            keys.discard(queue.popleft())

    def _is_duplicate(self, stream_id: str, event: StreamEvent) -> bool:
        if event.event_key in self._seen_keys[stream_id]:
            return True
        previous = self._last_emitted.get(stream_id)
        if (
            previous is not None
            and previous.exchange_time_ms is None
            and event.exchange_time_ms is None
            and self._semantic_signature(previous) == self._semantic_signature(event)
            and abs(self._receive_ms(event) - self._receive_ms(previous))
            <= self._receive_only_duplicate_window_ms
        ):
            return True
        return False

    def _is_older_than_last_emitted(self, stream_id: str, event: StreamEvent) -> bool:
        previous = self._last_emitted.get(stream_id)
        if previous is None:
            return False
        if previous.exchange_time_ms is not None and event.exchange_time_ms is not None:
            return event.exchange_time_ms < previous.exchange_time_ms
        if previous.exchange_time_ms is None and event.exchange_time_ms is None:
            # A single normalized websocket message can contain distinct
            # context updates with the EXACT same original receive_time.
            # Equality is not evidence of an old packet: event-key and
            # semantic payload duplicate guards run immediately afterward.
            # Only strictly older observed times can be rejected here.
            return event.receive_time < previous.receive_time
        return False

    async def _emit_candidate(self, stream_id: str, event: StreamEvent) -> bool:
        if self._is_older_than_last_emitted(stream_id, event):
            return False
        if self._is_duplicate(stream_id, event):
            return False
        await self._event_sink(event)
        self._last_emitted[stream_id] = event
        self._remember_key(stream_id, event.event_key)
        return True

    def _buffer(self, lane: int, stream_id: str, event: StreamEvent) -> None:
        buffer = self._buffers[(lane, stream_id)]
        buffer.append(event)
        while len(buffer) > self._buffer_size:
            buffer.popleft()

    def _lane_is_available(self, stream_id: str, lane: int) -> bool:
        return (
            lane in self._session_ready_lanes
            and lane not in self._lane_gap_starts[stream_id]
        )

    async def _drain_active_buffer(self, stream_id: str) -> None:
        """Resume exact standby backfill before any newer same-stream input.

        An interrupted sink inside _switch has already made the standby
        active, but its first unacknowledged original event remains at the
        head of the buffer. Retrying an incoming event directly would skip
        the older backlog. The original head is removed only after its
        downstream event sink acknowledges the write (or rejects it as an
        already admitted duplicate). Failure/cancellation is propagated.
        """
        lane = self.active_lane(stream_id)
        if not self._lane_is_available(stream_id, lane):
            return
        buffer = self._buffers[(lane, stream_id)]
        while buffer:
            original = buffer[0]
            delivered = await self._emit_candidate(stream_id, original)
            if delivered:
                self._remember_recovery_witness(
                    stream_id, lane, original,
                )
            buffer.popleft()

    async def _switch(self, stream_id: str, lane: int) -> None:
        if not self._lane_is_available(stream_id, lane):
            return
        current = self.active_lane(stream_id)
        if current == lane:
            # This lane might still hold original data from a previously
            # failed/cancelled transition; never treat it as caught up.
            await self._drain_active_buffer(stream_id)
            return
        self._active[stream_id] = lane
        self._failover_count += 1
        await self._drain_active_buffer(stream_id)

    def _remember_recovery_witness(
        self, stream_id: str, lane: int, event: StreamEvent,
    ) -> None:
        gap_start = self._aggregate_gap_starts.get(stream_id)
        original_received_ms = self._receive_ms(event)
        if gap_start is None or original_received_ms < gap_start:
            return
        self._recovery_witness_lanes[stream_id].add(lane)
        if (
            self._defer_all_mids_aggregate_recovery
            and event.kind is StreamKind.ALL_MIDS
        ):
            key = (lane, stream_id)
            self._all_mids_pending_witnesses.setdefault(
                key, original_received_ms,
            )

    def _available_lane(self, stream_id: str, *, excluding: int) -> int | None:
        for lane in range(self._lane_count):
            if lane != excluding and self._lane_is_available(stream_id, lane):
                return lane
        return None

    def _has_any_available_lane(self, stream_id: str) -> bool:
        return any(
            self._lane_is_available(stream_id, lane)
            for lane in range(self._lane_count)
        )

    async def _persist_uncommitted_aggregate_gap_open(
        self, stream_id: str,
    ) -> None:
        if stream_id not in self._uncommitted_aggregate_gap_opens:
            return
        # Retry the SAME original aggregate gap start, with the SAME
        # stream ID. If the sink still fails, propagate its failure BEFORE
        # any new input is emitted or a recovered closure can be reported.
        # A partial downstream commit is conservatively at-least-once:
        # no receipt is silently declared successful after an exception.
        started_ms = self._aggregate_gap_starts[stream_id]
        await self._gap_sink(
            DataGap(
                stream_id=stream_id,
                started_ms=started_ms,
                ended_ms=None,
                reason="redundant_disconnect",
            )
        )
        self._uncommitted_aggregate_gap_opens.remove(stream_id)

    async def _open_aggregate_gap_if_needed(
        self,
        stream_id: str,
        *,
        started_ms: int,
    ) -> None:
        if self._has_any_available_lane(stream_id):
            return
        if stream_id in self._aggregate_gap_starts:
            return
        starts = self._lane_gap_starts[stream_id]
        aggregate_start = max(starts.values(), default=started_ms)
        self._aggregate_gap_starts[stream_id] = aggregate_start
        for key in tuple(self._all_mids_pending_witnesses):
            if key[1] == stream_id:
                self._all_mids_pending_witnesses.pop(key, None)
        self._uncommitted_aggregate_gap_opens.add(stream_id)
        self._recovery_witness_lanes.pop(stream_id, None)
        await self._persist_uncommitted_aggregate_gap_open(stream_id)

    async def _persist_uncommitted_aggregate_gap_close(
        self, stream_id: str,
    ) -> None:
        recovered = self._uncommitted_aggregate_gap_closes.get(stream_id)
        if recovered is None:
            return
        # At-least-once under uncertain sink acknowledgement. Always retry
        # the IDENTICAL original close (start AND end) before processing any
        # later event, gap, or lane transition on this aggregate stream.
        await self._gap_sink(recovered)
        self._uncommitted_aggregate_gap_closes.pop(stream_id, None)
        self._aggregate_gap_starts.pop(stream_id, None)
        self._recovery_witness_lanes.pop(stream_id, None)
        for key in tuple(self._all_mids_pending_witnesses):
            if key[1] == stream_id:
                self._all_mids_pending_witnesses.pop(key, None)

    async def _close_aggregate_gap_if_needed(
        self,
        stream_id: str,
        *,
        recovered_ms: int,
    ) -> None:
        # If an earlier write was interrupted, do not replace its end with
        # this later witness. This call can also directly retry that write.
        if stream_id in self._uncommitted_aggregate_gap_closes:
            await self._persist_uncommitted_aggregate_gap_close(stream_id)
            return
        started_ms = self._aggregate_gap_starts.get(stream_id)
        if started_ms is None:
            return
        if stream_id in self._uncommitted_aggregate_gap_opens:
            raise RuntimeError("aggregate source gap open not durable")
        self._uncommitted_aggregate_gap_closes[stream_id] = DataGap(
            stream_id=stream_id,
            started_ms=started_ms,
            ended_ms=max(started_ms, recovered_ms),
            reason="recovered",
        )
        await self._persist_uncommitted_aggregate_gap_close(stream_id)

    async def on_event(self, lane: int, event: StreamEvent) -> None:
        self._require_lane(lane)
        await self._serialize_ingress(lane, event)

    async def _on_event_serialized(
        self, lane: int, event: StreamEvent,
    ) -> None:
        stream_id = event_stream_id(event)
        # No live event is accepted after an uncertain durable OPEN gap
        # write until the original source-gap receipt succeeds.
        await self._persist_uncommitted_aggregate_gap_open(stream_id)
        await self._persist_uncommitted_aggregate_gap_close(stream_id)
        # A prior standby switch can have failed mid-buffer after changing
        # the active lane. Its original records must be retried first,
        # otherwise the incoming newer event overtakes the old source.
        await self._drain_active_buffer(stream_id)
        self._session_ready_lanes.add(lane)
        self._observed_lanes[stream_id].add(lane)
        recovered_lane = lane not in self._lane_gap_starts[stream_id]
        current = self.active_lane(stream_id)
        if not self._lane_is_available(stream_id, current):
            await self._switch(stream_id, lane)
        if lane == self.active_lane(stream_id):
            delivered = await self._emit_candidate(stream_id, event)
            if delivered:
                self._remember_recovery_witness(
                    stream_id, lane, event,
                )
        else:
            self._buffer(lane, stream_id, event)
        if recovered_lane and lane in self._recovery_witness_lanes[stream_id]:
            # allMids children share the first-received timestamp. A
            # recovered gap emitted HERE would split an original frame:
            # BTC@2000 -> recovered@2007 -> ETH@2000. Wait for the
            # supervisor's post-frame acknowledgement instead.
            if not (
                self._defer_all_mids_aggregate_recovery
                and event.kind is StreamKind.ALL_MIDS
            ):
                await self._close_aggregate_gap_if_needed(
                    stream_id,
                    recovered_ms=self._receive_ms(event),
                )

    async def complete_all_mids_frame(
        self, lane: int, events: tuple[StreamEvent, ...],
    ) -> None:
        """Finish only fully acknowledged original allMids child frames.

        This callback must be called by the upstream supervisor *after*
        every child and its deferred gap receipts have been acknowledged.
        An incomplete frame must never close the aggregate source gap.
        """
        self._require_lane(lane)
        if not events or any(
            event.kind is not StreamKind.ALL_MIDS for event in events
        ):
            raise ValueError("allMids frame completion requires allMids events")
        if not self._defer_all_mids_aggregate_recovery:
            raise RuntimeError("allMids frame recovery deferral is disabled")
        async with self._ingress_lock:
            # Preserve first occurrence and original namespace ordering.
            streams = tuple(dict.fromkeys(event_stream_id(e) for e in events))
            for stream_id in streams:
                await self._persist_uncommitted_aggregate_gap_open(stream_id)
                await self._persist_uncommitted_aggregate_gap_close(stream_id)
                key = (lane, stream_id)
                first_received_ms = self._all_mids_pending_witnesses.get(key)
                gap_start = self._aggregate_gap_starts.get(stream_id)
                if (
                    first_received_ms is not None
                    and gap_start is not None
                    and first_received_ms >= gap_start
                    and lane in self._recovery_witness_lanes[stream_id]
                    and self._lane_is_available(stream_id, lane)
                ):
                    await self._close_aggregate_gap_if_needed(
                        stream_id, recovered_ms=first_received_ms,
                    )
                # This is a volatile scheduling witness only. A future
                # genuinely new disconnect cannot inherit older callbacks.
                self._all_mids_pending_witnesses.pop(key, None)

    async def on_gap(self, lane: int, gap: DataGap) -> None:
        self._require_lane(lane)
        await self._serialize_ingress(lane, gap)

    async def _on_gap_serialized(self, lane: int, gap: DataGap) -> None:
        stream_id = gap.stream_id
        # Includes recovered markers: do not close an unpersisted open.
        await self._persist_uncommitted_aggregate_gap_open(stream_id)
        await self._persist_uncommitted_aggregate_gap_close(stream_id)
        # An old standby backlog must be replayed before a newer recovery
        # marker or disconnect can alter this stream's coverage state.
        await self._drain_active_buffer(stream_id)
        starts = self._lane_gap_starts[stream_id]

        if gap.reason == "recovered":
            starts.pop(lane, None)
            self._session_ready_lanes.add(lane)
            self._observed_lanes[stream_id].add(lane)
            recovered_ms = gap.ended_ms if gap.ended_ms is not None else gap.started_ms
            current = self.active_lane(stream_id)
            if not self._lane_is_available(stream_id, current):
                # Deliver the recovered lane's buffered witness before
                # promising durable continuity for the aggregate stream.
                await self._switch(stream_id, lane)
            if lane in self._recovery_witness_lanes[stream_id]:
                await self._close_aggregate_gap_if_needed(
                    stream_id,
                    recovered_ms=recovered_ms,
                )
            return

        if gap.is_open:
            if gap.reason != "stale":
                self._session_ready_lanes.discard(lane)
            starts[lane] = gap.started_ms
            if lane == self.active_lane(stream_id):
                standby = self._available_lane(
                    stream_id,
                    excluding=lane,
                )
                if standby is not None:
                    await self._switch(stream_id, standby)
            await self._open_aggregate_gap_if_needed(
                stream_id,
                started_ms=gap.started_ms,
            )
            return

        if lane != self.active_lane(stream_id):
            return
        standby = self._available_lane(stream_id, excluding=lane)
        if standby is not None:
            await self._switch(stream_id, standby)
            return
        await self._gap_sink(gap)
