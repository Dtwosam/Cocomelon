from __future__ import annotations

import asyncio
import math
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import datetime

from cocomelon.domain.stream import DataGap, FreshnessState, StreamEvent, StreamHealth, StreamKind
from cocomelon.hyperliquid.ws_client import WsConnection
from cocomelon.hyperliquid.ws_protocol import (
    WsProtocolError,
    normalize_ws_message,
    subscribe_message,
    subscription_id,
)

ConnectionFactory = Callable[[], Awaitable[WsConnection]]
EventSink = Callable[[StreamEvent], Awaitable[None]]
GapSink = Callable[[DataGap], Awaitable[None]]
Sleep = Callable[[float], Awaitable[None]]
ClockMs = Callable[[], int]
UtcNow = Callable[[], datetime]
Subscription = Mapping[str, object]


class _SinkFailure(RuntimeError):
    def __init__(self, cause: Exception) -> None:
        super().__init__(str(cause))
        self.cause = cause


def event_stream_id(event: StreamEvent) -> str:
    if event.kind is StreamKind.ALL_MIDS:
        return f"allMids:{event.market.dex}" if event.market.dex else "allMids"
    if event.kind is StreamKind.ACTIVE_ASSET_CTX:
        return f"activeAssetCtx:{event.market.wire_name}"
    if event.kind is StreamKind.L2_BOOK:
        return f"l2Book:{event.market.wire_name}"
    if event.kind is StreamKind.TRADE:
        return f"trades:{event.market.wire_name}"
    interval = event.payload.get("interval")
    if not isinstance(interval, str) or not interval:
        raise WsProtocolError("normalized candle event is missing interval")
    return f"candle:{event.market.wire_name}:{interval}"


class WebSocketSupervisor:
    def __init__(
        self,
        connection_factory: ConnectionFactory,
        subscriptions: Sequence[Subscription],
        *,
        event_sink: EventSink,
        gap_sink: GapSink,
        clock_ms: ClockMs,
        utcnow: UtcNow,
        sleep: Sleep = asyncio.sleep,
        heartbeat_seconds: float = 45.0,
        stale_after_ms: int = 15_000,
        server_silence_timeout_ms: int | None = None,
        systemic_l2_stale_reconnect_fraction: float | None = None,
        systemic_l2_stale_reconnect_grace_ms: int = 0,
        dedup_size: int = 2048,
    ) -> None:
        if heartbeat_seconds <= 0:
            raise ValueError("heartbeat_seconds must be positive")
        if stale_after_ms <= 0:
            raise ValueError("stale_after_ms must be positive")
        if (
            server_silence_timeout_ms is not None
            and server_silence_timeout_ms <= 0
        ):
            raise ValueError(
                "server_silence_timeout_ms must be positive or None"
            )
        if (
            systemic_l2_stale_reconnect_fraction is not None
            and not 0 < systemic_l2_stale_reconnect_fraction <= 1
        ):
            raise ValueError(
                "systemic_l2_stale_reconnect_fraction must be in (0, 1]"
            )
        if systemic_l2_stale_reconnect_grace_ms < 0:
            raise ValueError(
                "systemic_l2_stale_reconnect_grace_ms must be non-negative"
            )
        if dedup_size <= 0:
            raise ValueError("dedup_size must be positive")
        self._connection_factory = connection_factory
        self._subscriptions = tuple(dict(item) for item in subscriptions)
        self._event_sink = event_sink
        self._gap_sink = gap_sink
        self._clock_ms = clock_ms
        self._utcnow = utcnow
        self._sleep = sleep
        self._heartbeat_seconds = heartbeat_seconds
        self._stale_after_ms = stale_after_ms
        self._server_silence_timeout_ms = server_silence_timeout_ms
        self._systemic_l2_stale_reconnect_fraction = (
            systemic_l2_stale_reconnect_fraction
        )
        self._systemic_l2_stale_reconnect_grace_ms = (
            systemic_l2_stale_reconnect_grace_ms
        )
        self._dedup_size = dedup_size
        self._recent_keys: dict[str, deque[str]] = defaultdict(deque)
        self._recent_key_sets: dict[str, set[str]] = defaultdict(set)
        self._last_exchange_time: dict[str, int] = {}
        self._last_stream_message: dict[str, int] = {}
        self._open_gaps: dict[str, DataGap] = {}
        self._connected = False
        self._last_server_message_ms: int | None = None
        self._reconnect_count = 0
        self._systemic_l2_stale_reconnect_count = 0
        self._duplicate_count = 0
        self._anomaly_count = 0

    @property
    def health(self) -> StreamHealth:
        return StreamHealth(
            connected=self._connected,
            last_server_message_ms=self._last_server_message_ms,
            reconnect_count=self._reconnect_count,
            systemic_l2_stale_reconnect_count=(
                self._systemic_l2_stale_reconnect_count
            ),
            duplicate_count=self._duplicate_count,
            anomaly_count=self._anomaly_count,
        )

    def _l2_stream_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                subscription_id(subscription)
                for subscription in self._subscriptions
                if subscription.get("type") == "l2Book"
            )
        )

    def _l2_freshness_anchor_ms(self, stream_id: str) -> int | None:
        exchange_time = self._last_exchange_time.get(stream_id)
        if exchange_time is not None:
            return exchange_time
        return self._last_stream_message.get(stream_id)

    def _l2_stream_is_stale(
        self,
        stream_id: str,
        *,
        now_ms: int,
    ) -> bool:
        anchor = self._l2_freshness_anchor_ms(stream_id)
        return (
            anchor is not None
            and now_ms - anchor >= self._stale_after_ms
        )

    def _next_l2_stale_deadline_ms(self) -> int | None:
        deadlines = tuple(
            anchor + self._stale_after_ms
            for stream_id in self._l2_stream_ids()
            if stream_id not in self._open_gaps
            if (
                anchor := self._l2_freshness_anchor_ms(stream_id)
            )
            is not None
        )
        return None if not deadlines else min(deadlines)

    def _systemic_l2_stale_while_server_active(
        self,
        *,
        now_ms: int,
    ) -> bool:
        fraction = self._systemic_l2_stale_reconnect_fraction
        if fraction is None:
            return False
        stream_ids = self._l2_stream_ids()
        if not stream_ids:
            return False
        last_server_message_ms = self._last_server_message_ms
        if (
            last_server_message_ms is None
            or now_ms - last_server_message_ms >= self._stale_after_ms
        ):
            return False
        reconnect_after_ms = (
            self._stale_after_ms
            + self._systemic_l2_stale_reconnect_grace_ms
        )
        silent_count = sum(
            (
                (last_received_ms := self._last_stream_message.get(stream_id))
                is not None
                and now_ms - last_received_ms >= reconnect_after_ms
            )
            for stream_id in stream_ids
        )
        stale_payload_count = sum(
            (
                (exchange_time_ms := self._last_exchange_time.get(stream_id))
                is not None
                and now_ms - exchange_time_ms >= reconnect_after_ms
            )
            for stream_id in stream_ids
        )
        minimum_stale = (
            1
            if len(stream_ids) == 1
            else max(2, math.ceil(len(stream_ids) * fraction))
        )
        return (
            silent_count >= minimum_stale
            or stale_payload_count >= minimum_stale
        )

    def _raise_if_systemic_l2_stale(
        self,
        *,
        now_ms: int,
    ) -> None:
        if not self._systemic_l2_stale_while_server_active(
            now_ms=now_ms
        ):
            return
        self._systemic_l2_stale_reconnect_count += 1
        raise ConnectionError(
            "systemic l2 subscription staleness on active websocket"
        )

    async def _open_l2_stale_gaps_if_needed(
        self,
        now_ms: int,
    ) -> None:
        for stream_id in self._l2_stream_ids():
            if stream_id in self._open_gaps:
                continue
            anchor = self._l2_freshness_anchor_ms(stream_id)
            if (
                anchor is None
                or now_ms - anchor < self._stale_after_ms
            ):
                continue
            started_ms = anchor + self._stale_after_ms
            gap = DataGap(
                stream_id=stream_id,
                started_ms=started_ms,
                ended_ms=None,
                reason="stale",
            )
            self._open_gaps[stream_id] = gap
            await self._emit_gap(gap)

    async def _subscribe_all(self, connection: WsConnection) -> None:
        ordered = sorted(self._subscriptions, key=subscription_id)
        for subscription in ordered:
            stream_id = subscription_id(subscription)
            await connection.send_json(subscribe_message(subscription))
            self._last_stream_message[stream_id] = self._clock_ms()

    async def _emit_event(self, event: StreamEvent) -> None:
        try:
            await self._event_sink(event)
        except Exception as exc:
            raise _SinkFailure(exc) from exc

    async def _emit_gap(self, gap: DataGap) -> None:
        try:
            await self._gap_sink(gap)
        except Exception as exc:
            raise _SinkFailure(exc) from exc

    def _remember(self, stream_id: str, event_key: str) -> bool:
        keys = self._recent_key_sets[stream_id]
        if event_key in keys:
            return False
        queue = self._recent_keys[stream_id]
        queue.append(event_key)
        keys.add(event_key)
        while len(queue) > self._dedup_size:
            oldest = queue.popleft()
            keys.discard(oldest)
        return True

    async def _open_disconnect_gaps(self, now_ms: int) -> None:
        for subscription in self._subscriptions:
            stream_id = subscription_id(subscription)
            if stream_id in self._open_gaps:
                continue
            gap = DataGap(
                stream_id=stream_id,
                started_ms=now_ms,
                ended_ms=None,
                reason="disconnect",
            )
            self._open_gaps[stream_id] = gap
            await self._gap_sink(gap)

    async def _close_gap_if_needed(self, stream_id: str, now_ms: int) -> None:
        gap = self._open_gaps.pop(stream_id, None)
        if gap is None:
            return
        await self._emit_gap(
            DataGap(
                stream_id=stream_id,
                started_ms=gap.started_ms,
                ended_ms=max(gap.started_ms, now_ms),
                reason="recovered",
            )
        )

    async def _dispatch(self, raw: object) -> None:
        now_ms = self._clock_ms()
        events = normalize_ws_message(raw, receive_time=self._utcnow())
        for event in events:
            stream_id = event_stream_id(event)
            # Receive-time stream liveness is distinct from book-state
            # freshness. Even an exact duplicate proves the subscription
            # delivered a message now, so refresh the liveness clock before
            # replay deduplication. Exchange-time freshness remains strict
            # below and still drives stale-book gaps/eligibility.
            self._last_stream_message[stream_id] = now_ms
            if not self._remember(stream_id, event.event_key):
                self._duplicate_count += 1
                continue

            exchange_time = event.exchange_time_ms
            previous_exchange_time = self._last_exchange_time.get(stream_id)
            if (
                exchange_time is not None
                and previous_exchange_time is not None
                and exchange_time < previous_exchange_time
            ):
                self._anomaly_count += 1
                await self._emit_gap(
                    DataGap(
                        stream_id=stream_id,
                        started_ms=exchange_time,
                        ended_ms=previous_exchange_time,
                        reason="out_of_order",
                    )
                )
                continue

            if exchange_time is not None:
                self._last_exchange_time[stream_id] = exchange_time
            if (
                event.kind is StreamKind.L2_BOOK
                and self._l2_stream_is_stale(
                    stream_id,
                    now_ms=now_ms,
                )
            ):
                await self._open_l2_stale_gaps_if_needed(now_ms)
            else:
                await self._close_gap_if_needed(
                    stream_id,
                    now_ms,
                )
            await self._emit_event(event)

    def _reset_l2_freshness_for_session(
        self,
        *,
        session_started_ms: int,
    ) -> None:
        for stream_id in self._l2_stream_ids():
            self._last_exchange_time.pop(stream_id, None)
            self._last_stream_message[stream_id] = session_started_ms

    async def _session(
        self,
        connection: WsConnection,
        *,
        max_messages: int | None,
    ) -> None:
        await self._subscribe_all(connection)
        received = 0
        heartbeat_ms = max(1, int(self._heartbeat_seconds * 1000))
        session_started_ms = self._clock_ms()
        self._reset_l2_freshness_for_session(
            session_started_ms=session_started_ms
        )
        last_session_message_ms: int | None = None
        next_heartbeat_ms = session_started_ms + heartbeat_ms
        while max_messages is None or received < max_messages:
            now_ms = self._clock_ms()
            next_stale_ms = self._next_l2_stale_deadline_ms()
            wake_ms = next_heartbeat_ms
            if next_stale_ms is not None:
                wake_ms = min(wake_ms, next_stale_ms)
            silence_deadline_ms: int | None = None
            if self._server_silence_timeout_ms is not None:
                silence_anchor_ms = (
                    session_started_ms
                    if last_session_message_ms is None
                    else last_session_message_ms
                )
                silence_deadline_ms = (
                    silence_anchor_ms
                    + self._server_silence_timeout_ms
                )
                wake_ms = min(wake_ms, silence_deadline_ms)
            remaining_seconds = max(
                0.0,
                (wake_ms - now_ms) / 1000,
            )
            if remaining_seconds == 0.0:
                if (
                    silence_deadline_ms is not None
                    and now_ms >= silence_deadline_ms
                ):
                    raise ConnectionError(
                        "websocket server message silence timeout"
                    )
                await self._open_l2_stale_gaps_if_needed(now_ms)
                self._raise_if_systemic_l2_stale(now_ms=now_ms)
                if now_ms >= next_heartbeat_ms:
                    await connection.send_json({"method": "ping"})
                    next_heartbeat_ms = (
                        self._clock_ms() + heartbeat_ms
                    )
                continue
            try:
                raw = await asyncio.wait_for(
                    connection.recv_json(),
                    timeout=remaining_seconds,
                )
            except TimeoutError:
                now_ms = self._clock_ms()
                if (
                    silence_deadline_ms is not None
                    and now_ms >= silence_deadline_ms
                ):
                    raise ConnectionError(
                        "websocket server message silence timeout"
                    ) from None
                await self._open_l2_stale_gaps_if_needed(now_ms)
                self._raise_if_systemic_l2_stale(now_ms=now_ms)
                heartbeat_due = wake_ms == next_heartbeat_ms
                if heartbeat_due or now_ms >= next_heartbeat_ms:
                    await connection.send_json({"method": "ping"})
                    next_heartbeat_ms = (
                        self._clock_ms() + heartbeat_ms
                    )
                continue
            received_at_ms = self._clock_ms()
            self._last_server_message_ms = received_at_ms
            last_session_message_ms = received_at_ms
            await self._dispatch(raw)
            received += 1

            # recv_json() and downstream sinks can both complete immediately
            # when the socket and replay pipeline are hot. Yield explicitly
            # so one websocket lane cannot monopolize the event loop and
            # starve the redundant lane, freshness watchdogs, or control
            # tasks while consuming an already-buffered message burst.
            await asyncio.sleep(0)

            now_ms = self._clock_ms()
            await self._open_l2_stale_gaps_if_needed(now_ms)
            self._raise_if_systemic_l2_stale(now_ms=now_ms)
            if now_ms >= next_heartbeat_ms:
                await connection.send_json({"method": "ping"})
                next_heartbeat_ms = (
                    self._clock_ms() + heartbeat_ms
                )

    async def run(
        self,
        *,
        max_sessions: int | None = None,
        max_messages_per_session: int | None = None,
    ) -> None:
        if max_sessions is not None and max_sessions <= 0:
            raise ValueError("max_sessions must be positive")
        if max_messages_per_session is not None and max_messages_per_session <= 0:
            raise ValueError("max_messages_per_session must be positive")

        session_count = 0
        backoff = 1.0
        while max_sessions is None or session_count < max_sessions:
            connection: WsConnection | None = None
            try:
                connection = await self._connection_factory()
                session_count += 1
                self._connected = True
                await self._session(connection, max_messages=max_messages_per_session)
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except _SinkFailure as exc:
                raise exc.cause from exc
            except WsProtocolError:
                raise
            except Exception:
                self._connected = False
                await self._open_disconnect_gaps(self._clock_ms())
                if max_sessions is not None and session_count >= max_sessions:
                    return
                self._reconnect_count += 1
                await self._sleep(backoff)
                backoff = min(backoff * 2.0, 30.0)
            finally:
                if connection is not None:
                    await connection.close()
                self._connected = False

    def l2_stale_overage_ms(
        self,
        stream_id: str,
        *,
        now_ms: int,
    ) -> int | None:
        if stream_id not in self._l2_stream_ids():
            return None
        anchor = self._l2_freshness_anchor_ms(stream_id)
        if anchor is None:
            return None
        return max(
            0,
            now_ms - anchor - self._stale_after_ms,
        )

    def stale_l2_streams(
        self,
        *,
        now_ms: int,
    ) -> tuple[str, ...]:
        return tuple(
            stream_id
            for stream_id in self._l2_stream_ids()
            if self._l2_stream_is_stale(
                stream_id,
                now_ms=now_ms,
            )
        )

    def stale_streams(self, *, now_ms: int) -> tuple[str, ...]:
        stale = []
        for stream_id, last_message_ms in self._last_stream_message.items():
            state = FreshnessState(
                stream_id=stream_id,
                last_message_ms=last_message_ms,
                stale_after_ms=self._stale_after_ms,
            )
            if state.is_stale(now_ms=now_ms):
                stale.append(stream_id)
        return tuple(sorted(stale))
