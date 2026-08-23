import asyncio
from datetime import UTC, datetime

import pytest

from cocomelon.domain.stream import DataGap, StreamEvent
from cocomelon.hyperliquid.ws_supervisor import WebSocketSupervisor


class FakeConnection:
    def __init__(self, rows: list[object]) -> None:
        self.rows = list(rows)
        self.sent: list[dict[str, object]] = []
        self.closed = False

    async def send_json(self, value: dict[str, object]) -> None:
        self.sent.append(value)

    async def recv_json(self) -> dict[str, object]:
        row = self.rows.pop(0)
        if isinstance(row, BaseException):
            raise row
        assert isinstance(row, dict)
        return row

    async def close(self) -> None:
        self.closed = True


class TimeoutThenPongConnection(FakeConnection):
    def __init__(self) -> None:
        super().__init__([])
        self.calls = 0

    async def recv_json(self) -> dict[str, object]:
        self.calls += 1
        if self.calls == 1:
            await asyncio.sleep(1)
            raise AssertionError("wait_for should cancel the slow receive")
        return {"channel": "pong"}


def trade(tid: int, time_ms: int = 1000) -> dict[str, object]:
    return {
        "channel": "trades",
        "data": [
            {
                "coin": "BTC",
                "side": "B",
                "px": "100",
                "sz": "1",
                "hash": "0x1",
                "time": time_ms,
                "tid": tid,
                "users": ["a", "b"],
            }
        ],
    }


def test_reconnect_resubscribes_and_closes_gap_on_recovery() -> None:
    async def run() -> None:
        first = FakeConnection([trade(1), ConnectionError("drop")])
        second = FakeConnection([trade(2, 2000), ConnectionError("bounded end")])
        pool = [first, second]
        events: list[StreamEvent] = []
        gaps: list[DataGap] = []
        sleeps: list[float] = []
        now = [1000]

        async def factory() -> FakeConnection:
            return pool.pop(0)

        async def event_sink(event: StreamEvent) -> None:
            events.append(event)
            now[0] += 1000

        async def gap_sink(gap: DataGap) -> None:
            gaps.append(gap)

        async def fake_sleep(value: float) -> None:
            sleeps.append(value)

        supervisor = WebSocketSupervisor(
            factory,
            [{"type": "trades", "coin": "BTC"}],
            event_sink=event_sink,
            gap_sink=gap_sink,
            clock_ms=lambda: now[0],
            utcnow=lambda: datetime(2026, 8, 23, tzinfo=UTC),
            sleep=fake_sleep,
        )
        await supervisor.run(max_sessions=2, max_messages_per_session=2)

        assert len(first.sent) == 1
        assert len(second.sent) == 1
        assert [item.event_key for item in events] == [
            "trades:BTC:1000:1",
            "trades:BTC:2000:2",
        ]
        assert any(gap.ended_ms is None and gap.reason == "disconnect" for gap in gaps)
        assert any(gap.reason == "recovered" and gap.ended_ms is not None for gap in gaps)
        assert sleeps == [1.0]

    asyncio.run(run())


def test_application_heartbeat_sends_ping_and_pong_is_control_only() -> None:
    async def run() -> None:
        connection = TimeoutThenPongConnection()
        events: list[StreamEvent] = []

        async def factory() -> TimeoutThenPongConnection:
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
            clock_ms=lambda: 1000,
            utcnow=lambda: datetime(2026, 8, 23, tzinfo=UTC),
            heartbeat_seconds=0.001,
        )
        await supervisor.run(max_sessions=1, max_messages_per_session=1)

        assert {"method": "ping"} in connection.sent
        assert events == []

    asyncio.run(run())


def test_duplicate_and_out_of_order_are_not_dispatched() -> None:
    async def run() -> None:
        connection = FakeConnection([trade(1, 2000), trade(1, 2000), trade(2, 1000)])
        events: list[StreamEvent] = []
        gaps: list[DataGap] = []

        async def factory() -> FakeConnection:
            return connection

        async def event_sink(event: StreamEvent) -> None:
            events.append(event)

        async def gap_sink(gap: DataGap) -> None:
            gaps.append(gap)

        supervisor = WebSocketSupervisor(
            factory,
            [{"type": "trades", "coin": "BTC"}],
            event_sink=event_sink,
            gap_sink=gap_sink,
            clock_ms=lambda: 3000,
            utcnow=lambda: datetime(2026, 8, 23, tzinfo=UTC),
        )
        await supervisor.run(max_sessions=1, max_messages_per_session=3)

        assert len(events) == 1
        assert supervisor.health.duplicate_count == 1
        assert supervisor.health.anomaly_count == 1
        assert any(gap.reason == "out_of_order" for gap in gaps)

    asyncio.run(run())


def test_freshness_reports_stale_streams() -> None:
    async def run() -> None:
        connection = FakeConnection([trade(1)])
        events: list[StreamEvent] = []

        async def factory() -> FakeConnection:
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
            clock_ms=lambda: 1000,
            utcnow=lambda: datetime(2026, 8, 23, tzinfo=UTC),
            stale_after_ms=5000,
        )
        await supervisor.run(max_sessions=1, max_messages_per_session=1)

        assert supervisor.stale_streams(now_ms=5999) == ()
        assert supervisor.stale_streams(now_ms=6000) == ("trades:BTC",)

    asyncio.run(run())


def test_subscribed_stream_becomes_stale_before_first_event() -> None:
    async def run() -> None:
        connection = FakeConnection([{"channel": "pong"}])

        async def factory() -> FakeConnection:
            return connection

        async def event_sink(event: StreamEvent) -> None:
            raise AssertionError(f"unexpected event: {event}")

        async def gap_sink(gap: DataGap) -> None:
            raise AssertionError(f"unexpected gap: {gap}")

        supervisor = WebSocketSupervisor(
            factory,
            [{"type": "trades", "coin": "BTC"}],
            event_sink=event_sink,
            gap_sink=gap_sink,
            clock_ms=lambda: 1000,
            utcnow=lambda: datetime(2026, 8, 23, tzinfo=UTC),
            stale_after_ms=5000,
        )
        await supervisor.run(max_sessions=1, max_messages_per_session=1)

        assert supervisor.stale_streams(now_ms=5999) == ()
        assert supervisor.stale_streams(now_ms=6000) == ("trades:BTC",)

    asyncio.run(run())


def test_event_sink_failure_surfaces_without_reconnect() -> None:
    async def run() -> None:
        first = FakeConnection([trade(1)])
        second = FakeConnection([trade(2)])
        pool = [first, second]
        factory_calls = 0

        async def factory() -> FakeConnection:
            nonlocal factory_calls
            factory_calls += 1
            return pool.pop(0)

        async def event_sink(event: StreamEvent) -> None:
            raise OSError("disk full")

        async def gap_sink(gap: DataGap) -> None:
            return None

        async def fake_sleep(value: float) -> None:
            return None

        supervisor = WebSocketSupervisor(
            factory,
            [{"type": "trades", "coin": "BTC"}],
            event_sink=event_sink,
            gap_sink=gap_sink,
            clock_ms=lambda: 1000,
            utcnow=lambda: datetime(2026, 8, 23, tzinfo=UTC),
            sleep=fake_sleep,
        )

        with pytest.raises(OSError, match="disk full"):
            await supervisor.run(max_sessions=2, max_messages_per_session=1)

        assert factory_calls == 1
        assert supervisor.health.reconnect_count == 0

    asyncio.run(run())
