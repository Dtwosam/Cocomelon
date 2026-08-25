from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from cocomelon.domain.stream import DataGap, StreamEvent
from cocomelon.hyperliquid.ws_supervisor import WebSocketSupervisor


class ActiveTrafficConnection:
    def __init__(self, now_ms: list[int]) -> None:
        self._now_ms = now_ms
        self.sent: list[dict[str, object]] = []
        self.closed = False

    async def send_json(self, value: dict[str, object]) -> None:
        self.sent.append(value)

    async def recv_json(self) -> dict[str, object]:
        self._now_ms[0] += 600
        return {"channel": "pong"}

    async def close(self) -> None:
        self.closed = True


def test_heartbeat_is_periodic_even_while_server_messages_keep_arriving() -> None:
    async def run() -> None:
        now_ms = [0]
        connection = ActiveTrafficConnection(now_ms)
        events: list[StreamEvent] = []

        async def factory() -> ActiveTrafficConnection:
            return connection

        async def event_sink(event: StreamEvent) -> None:
            events.append(event)

        async def gap_sink(gap: DataGap) -> None:
            raise AssertionError(f"unexpected gap: {gap}")

        supervisor = WebSocketSupervisor(
            factory,
            [{"type": "trades", "coin": "BTC"}],
            event_sink=event_sink,
            gap_sink=gap_sink,
            clock_ms=lambda: now_ms[0],
            utcnow=lambda: datetime(2026, 8, 25, tzinfo=UTC),
            heartbeat_seconds=1.0,
        )
        await supervisor.run(max_sessions=1, max_messages_per_session=3)

        assert {"method": "ping"} in connection.sent
        assert events == []

    asyncio.run(run())
