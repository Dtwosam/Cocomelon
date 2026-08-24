from __future__ import annotations

import hashlib
import json
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable, Mapping

from cocomelon.domain.stream import DataGap, StreamEvent
from cocomelon.hyperliquid.ws_supervisor import event_stream_id

EventSink = Callable[[StreamEvent], Awaitable[None]]
GapSink = Callable[[DataGap], Awaitable[None]]


class RedundantStreamMux:
    """Merge redundant normalized public streams without hiding true data loss.

    One lane is active per stream while the other continuously buffers normalized
    events. A lane-local disconnect switches to a healthy standby and backfills
    events the active lane did not emit. A durable gap is forwarded only once all
    lanes are unavailable for the same stream.
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
        self._active: dict[str, int] = {}
        self._buffers: dict[tuple[int, str], deque[StreamEvent]] = defaultdict(deque)
        self._lane_gap_starts: dict[str, dict[int, int]] = defaultdict(dict)
        self._aggregate_gap_starts: dict[str, int] = {}
        self._seen_keys: dict[str, set[str]] = defaultdict(set)
        self._seen_queues: dict[str, deque[str]] = defaultdict(deque)
        self._last_emitted: dict[str, StreamEvent] = {}
        self._failover_count = 0

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
            return event.receive_time <= previous.receive_time
        return False

    async def _emit_candidate(self, stream_id: str, event: StreamEvent) -> None:
        if self._is_older_than_last_emitted(stream_id, event):
            return
        if self._is_duplicate(stream_id, event):
            return
        await self._event_sink(event)
        self._last_emitted[stream_id] = event
        self._remember_key(stream_id, event.event_key)

    def _buffer(self, lane: int, stream_id: str, event: StreamEvent) -> None:
        buffer = self._buffers[(lane, stream_id)]
        buffer.append(event)
        while len(buffer) > self._buffer_size:
            buffer.popleft()

    async def _switch(self, stream_id: str, lane: int) -> None:
        current = self.active_lane(stream_id)
        if current == lane:
            return
        self._active[stream_id] = lane
        self._failover_count += 1
        buffer = self._buffers[(lane, stream_id)]
        while buffer:
            await self._emit_candidate(stream_id, buffer.popleft())

    def _available_lane(self, stream_id: str, *, excluding: int) -> int | None:
        gapped = self._lane_gap_starts[stream_id]
        for lane in range(self._lane_count):
            if lane != excluding and lane not in gapped:
                return lane
        return None

    async def on_event(self, lane: int, event: StreamEvent) -> None:
        self._require_lane(lane)
        stream_id = event_stream_id(event)
        if lane == self.active_lane(stream_id):
            await self._emit_candidate(stream_id, event)
            return
        self._buffer(lane, stream_id, event)

    async def _open_aggregate_gap_if_needed(self, stream_id: str) -> None:
        starts = self._lane_gap_starts[stream_id]
        if len(starts) != self._lane_count or stream_id in self._aggregate_gap_starts:
            return
        started_ms = max(starts.values())
        self._aggregate_gap_starts[stream_id] = started_ms
        await self._gap_sink(
            DataGap(
                stream_id=stream_id,
                started_ms=started_ms,
                ended_ms=None,
                reason="redundant_disconnect",
            )
        )

    async def _close_aggregate_gap_if_needed(
        self,
        stream_id: str,
        *,
        recovered_ms: int,
    ) -> None:
        started_ms = self._aggregate_gap_starts.pop(stream_id, None)
        if started_ms is None:
            return
        await self._gap_sink(
            DataGap(
                stream_id=stream_id,
                started_ms=started_ms,
                ended_ms=max(started_ms, recovered_ms),
                reason="recovered",
            )
        )

    async def on_gap(self, lane: int, gap: DataGap) -> None:
        self._require_lane(lane)
        stream_id = gap.stream_id
        starts = self._lane_gap_starts[stream_id]

        if gap.reason == "recovered":
            starts.pop(lane, None)
            recovered_ms = gap.ended_ms if gap.ended_ms is not None else gap.started_ms
            await self._close_aggregate_gap_if_needed(
                stream_id,
                recovered_ms=recovered_ms,
            )
            current = self.active_lane(stream_id)
            if current in starts and lane not in starts:
                await self._switch(stream_id, lane)
            return

        if gap.is_open:
            starts[lane] = gap.started_ms
            if lane == self.active_lane(stream_id):
                standby = self._available_lane(stream_id, excluding=lane)
                if standby is not None:
                    await self._switch(stream_id, standby)
            await self._open_aggregate_gap_if_needed(stream_id)
            return

        if lane != self.active_lane(stream_id):
            return
        standby = self._available_lane(stream_id, excluding=lane)
        if standby is not None:
            await self._switch(stream_id, standby)
            return
        await self._gap_sink(gap)
