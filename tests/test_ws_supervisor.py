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


class HangingConnection(FakeConnection):
    async def recv_json(self) -> dict[str, object]:
        await asyncio.Future()
        raise AssertionError("unreachable")


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


def book(time_ms: int = 1000) -> dict[str, object]:
    return {
        "channel": "l2Book",
        "data": {
            "coin": "BTC",
            "levels": [
                [{"n": 1, "px": "99", "sz": "1"}],
                [{"n": 1, "px": "101", "sz": "1"}],
            ],
            "time": time_ms,
        },
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


def test_server_silence_forces_reconnect() -> None:
    async def run() -> None:
        first = HangingConnection([])
        second = HangingConnection([])
        pool = [first, second]
        gaps: list[DataGap] = []
        sleeps: list[float] = []
        loop = asyncio.get_running_loop()

        async def factory() -> HangingConnection:
            return pool.pop(0)

        async def event_sink(_event: StreamEvent) -> None:
            raise AssertionError("silent connections must not emit events")

        async def gap_sink(gap: DataGap) -> None:
            gaps.append(gap)

        async def fake_sleep(value: float) -> None:
            sleeps.append(value)

        supervisor = WebSocketSupervisor(
            factory,
            ({"type": "trades", "coin": "BTC"},),
            event_sink=event_sink,
            gap_sink=gap_sink,
            clock_ms=lambda: int(loop.time() * 1_000),
            utcnow=lambda: datetime.now(UTC),
            sleep=fake_sleep,
            heartbeat_seconds=1.0,
            stale_after_ms=1_000,
            server_silence_timeout_ms=20,
        )
        await supervisor.run(
            max_sessions=2,
            max_messages_per_session=1,
        )

        assert first.closed is True
        assert second.closed is True
        assert supervisor.health.reconnect_count == 1
        assert sleeps == [1.0]
        assert any(
            gap.reason == "disconnect"
            and gap.stream_id == "trades:BTC"
            for gap in gaps
        )

    asyncio.run(run())


def test_systemic_l2_stale_on_active_socket_forces_reconnect() -> None:
    async def run() -> None:
        now = [1_000]

        def book_for(coin: str, time_ms: int) -> dict[str, object]:
            return {
                "channel": "l2Book",
                "data": {
                    "coin": coin,
                    "levels": [
                        [{"n": 1, "px": "99", "sz": "1"}],
                        [{"n": 1, "px": "101", "sz": "1"}],
                    ],
                    "time": time_ms,
                },
            }

        first_rows: list[tuple[int, object]] = [
            (1_000, book_for("BTC", 1_000)),
            (1_001, book_for("ETH", 1_001)),
            (7_000, trade(1, 7_000)),
        ]
        second_rows: list[tuple[int, object]] = [
            (8_000, trade(2, 8_000)),
            (8_001, book_for("BTC", 8_001)),
            (8_002, book_for("ETH", 8_002)),
        ]

        class ClockedConnection(FakeConnection):
            def __init__(self, rows: list[tuple[int, object]]) -> None:
                super().__init__([])
                self.clock_rows = rows

            async def recv_json(self) -> dict[str, object]:
                timestamp_ms, row = self.clock_rows.pop(0)
                now[0] = timestamp_ms
                if isinstance(row, BaseException):
                    raise row
                assert isinstance(row, dict)
                return row

        first = ClockedConnection(first_rows)
        second = ClockedConnection(second_rows)
        pool = [first, second]
        gaps: list[DataGap] = []
        sleeps: list[float] = []

        async def factory() -> ClockedConnection:
            return pool.pop(0)

        async def event_sink(_event: StreamEvent) -> None:
            return None

        async def gap_sink(gap: DataGap) -> None:
            gaps.append(gap)

        async def fake_sleep(value: float) -> None:
            sleeps.append(value)

        supervisor = WebSocketSupervisor(
            factory,
            (
                {"type": "l2Book", "coin": "BTC"},
                {"type": "l2Book", "coin": "ETH"},
                {"type": "trades", "coin": "BTC"},
            ),
            event_sink=event_sink,
            gap_sink=gap_sink,
            clock_ms=lambda: now[0],
            utcnow=lambda: datetime.fromtimestamp(
                now[0] / 1000,
                tz=UTC,
            ),
            sleep=fake_sleep,
            stale_after_ms=5_000,
            systemic_l2_stale_reconnect_fraction=0.5,
        )
        await supervisor.run(
            max_sessions=2,
            max_messages_per_session=3,
        )

        assert first.closed is True
        assert second.closed is True
        assert supervisor.health.reconnect_count == 1
        assert supervisor.health.systemic_l2_stale_reconnect_count == 1
        assert sleeps == [1.0]
        assert any(
            gap.reason == "stale"
            and gap.stream_id == "l2Book:BTC"
            for gap in gaps
        )
        assert any(
            gap.reason == "stale"
            and gap.stream_id == "l2Book:ETH"
            for gap in gaps
        )


def test_duplicate_l2_snapshot_does_not_mask_stale_payload_reconnect() -> None:
    async def run() -> None:
        now = [1_000]
        same_book = {
            "channel": "l2Book",
            "data": {
                "coin": "BTC",
                "levels": [
                    [{"n": 1, "px": "99", "sz": "1"}],
                    [{"n": 1, "px": "101", "sz": "1"}],
                ],
                "time": 1_000,
            },
        }
        rows: list[tuple[int, object]] = [
            (1_000, same_book),
            (6_000, same_book),
            (7_000, trade(1, 7_000)),
        ]

        class ClockedConnection(FakeConnection):
            def __init__(self) -> None:
                super().__init__([])
                self.clock_rows = rows

            async def recv_json(self) -> dict[str, object]:
                timestamp_ms, row = self.clock_rows.pop(0)
                now[0] = timestamp_ms
                assert isinstance(row, dict)
                return row

        connection = ClockedConnection()
        gaps: list[DataGap] = []

        async def factory() -> ClockedConnection:
            return connection

        async def event_sink(_event: StreamEvent) -> None:
            return None

        async def gap_sink(gap: DataGap) -> None:
            gaps.append(gap)

        supervisor = WebSocketSupervisor(
            factory,
            (
                {"type": "l2Book", "coin": "BTC"},
                {"type": "trades", "coin": "BTC"},
            ),
            event_sink=event_sink,
            gap_sink=gap_sink,
            clock_ms=lambda: now[0],
            utcnow=lambda: datetime.fromtimestamp(
                now[0] / 1000,
                tz=UTC,
            ),
            stale_after_ms=5_000,
            systemic_l2_stale_reconnect_fraction=0.5,
        )

        await supervisor.run(
            max_sessions=1,
            max_messages_per_session=3,
        )

        assert supervisor.health.duplicate_count == 1
        assert supervisor.health.systemic_l2_stale_reconnect_count == 1
        assert connection.closed is True
        assert any(
            gap.reason == "stale"
            and gap.stream_id == "l2Book:BTC"
            for gap in gaps
        )
        assert supervisor.stale_l2_streams(now_ms=7_000) == (
            "l2Book:BTC",
        )

    asyncio.run(run())


def test_systemic_l2_reconnect_grace_delays_lane_teardown() -> None:
    async def run() -> None:
        now = [1_000]

        def book_for(coin: str, time_ms: int) -> dict[str, object]:
            return {
                "channel": "l2Book",
                "data": {
                    "coin": coin,
                    "levels": [
                        [{"n": 1, "px": "99", "sz": "1"}],
                        [{"n": 1, "px": "101", "sz": "1"}],
                    ],
                    "time": time_ms,
                },
            }

        rows: list[tuple[int, object]] = [
            (1_000, book_for("BTC", 1_000)),
            (1_001, book_for("ETH", 1_001)),
            (7_000, trade(1, 7_000)),
        ]

        class ClockedConnection(FakeConnection):
            def __init__(self) -> None:
                super().__init__([])
                self.clock_rows = rows

            async def recv_json(self) -> dict[str, object]:
                timestamp_ms, row = self.clock_rows.pop(0)
                now[0] = timestamp_ms
                assert isinstance(row, dict)
                return row

        connection = ClockedConnection()
        gaps: list[DataGap] = []

        async def factory() -> ClockedConnection:
            return connection

        async def event_sink(_event: StreamEvent) -> None:
            return None

        async def gap_sink(gap: DataGap) -> None:
            gaps.append(gap)

        supervisor = WebSocketSupervisor(
            factory,
            (
                {"type": "l2Book", "coin": "BTC"},
                {"type": "l2Book", "coin": "ETH"},
                {"type": "trades", "coin": "BTC"},
            ),
            event_sink=event_sink,
            gap_sink=gap_sink,
            clock_ms=lambda: now[0],
            utcnow=lambda: datetime.fromtimestamp(
                now[0] / 1000,
                tz=UTC,
            ),
            stale_after_ms=5_000,
            systemic_l2_stale_reconnect_fraction=0.5,
            systemic_l2_stale_reconnect_grace_ms=3_000,
        )
        await supervisor.run(
            max_sessions=1,
            max_messages_per_session=3,
        )

        assert supervisor.health.reconnect_count == 0
        assert supervisor.health.systemic_l2_stale_reconnect_count == 0
        assert any(
            gap.reason == "stale"
            and gap.stream_id == "l2Book:BTC"
            for gap in gaps
        )
        assert any(
            gap.reason == "stale"
            and gap.stream_id == "l2Book:ETH"
            for gap in gaps
        )

    asyncio.run(run())


def test_systemic_l2_stale_reconnect_grace_must_be_non_negative() -> None:
    with pytest.raises(
        ValueError,
        match="systemic_l2_stale_reconnect_grace_ms",
    ):
        WebSocketSupervisor(
            lambda: None,  # type: ignore[arg-type]
            (),
            event_sink=lambda _event: None,  # type: ignore[arg-type]
            gap_sink=lambda _gap: None,  # type: ignore[arg-type]
            clock_ms=lambda: 0,
            utcnow=lambda: datetime.now(UTC),
            systemic_l2_stale_reconnect_grace_ms=-1,
        )


def test_systemic_l2_stale_reconnect_fraction_must_be_valid() -> None:
    for value in (0.0, -0.1, 1.1):
        with pytest.raises(
            ValueError,
            match="systemic_l2_stale_reconnect_fraction",
        ):
            WebSocketSupervisor(
                lambda: None,  # type: ignore[arg-type]
                (),
                event_sink=lambda _event: None,  # type: ignore[arg-type]
                gap_sink=lambda _gap: None,  # type: ignore[arg-type]
                clock_ms=lambda: 0,
                utcnow=lambda: datetime.now(UTC),
                systemic_l2_stale_reconnect_fraction=value,
            )


def test_server_silence_timeout_must_be_positive() -> None:
    with pytest.raises(
        ValueError,
        match="server_silence_timeout_ms",
    ):
        WebSocketSupervisor(
            lambda: None,  # type: ignore[arg-type]
            (),
            event_sink=lambda _event: None,  # type: ignore[arg-type]
            gap_sink=lambda _gap: None,  # type: ignore[arg-type]
            clock_ms=lambda: 0,
            utcnow=lambda: datetime.now(UTC),
            server_silence_timeout_ms=0,
        )


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


def test_hot_buffered_websocket_yields_between_messages() -> None:
    async def run() -> None:
        connection = FakeConnection(
            [trade(1, 1_000), trade(2, 1_001), trade(3, 1_002)]
        )
        order: list[str] = []

        async def factory() -> FakeConnection:
            return connection

        async def event_sink(event: StreamEvent) -> None:
            order.append(f"event:{event.event_key}")

        async def gap_sink(gap: DataGap) -> None:
            raise AssertionError(f"unexpected gap: {gap}")

        async def peer_task() -> None:
            await asyncio.sleep(0)
            order.append("peer-ran")

        peer = asyncio.create_task(peer_task())
        supervisor = WebSocketSupervisor(
            factory,
            [{"type": "trades", "coin": "BTC"}],
            event_sink=event_sink,
            gap_sink=gap_sink,
            clock_ms=lambda: 1_000,
            utcnow=lambda: datetime(2026, 8, 23, tzinfo=UTC),
        )
        await supervisor.run(
            max_sessions=1,
            max_messages_per_session=3,
        )
        await peer

        peer_index = order.index("peer-ran")
        assert 0 < peer_index < len(order) - 1

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


def test_l2_stale_overage_starts_after_hard_freshness_ceiling() -> None:
    async def run() -> None:
        connection = FakeConnection([book(1_000)])

        async def factory() -> FakeConnection:
            return connection

        async def event_sink(_event: StreamEvent) -> None:
            return None

        async def gap_sink(_gap: DataGap) -> None:
            return None

        supervisor = WebSocketSupervisor(
            factory,
            ({"type": "l2Book", "coin": "BTC"},),
            event_sink=event_sink,
            gap_sink=gap_sink,
            clock_ms=lambda: 1_000,
            utcnow=lambda: datetime.fromtimestamp(
                1,
                tz=UTC,
            ),
            stale_after_ms=5_000,
        )
        await supervisor.run(
            max_sessions=1,
            max_messages_per_session=1,
        )

        assert supervisor.l2_stale_overage_ms(
            "l2Book:BTC",
            now_ms=5_999,
        ) == 0
        assert supervisor.l2_stale_overage_ms(
            "l2Book:BTC",
            now_ms=6_000,
        ) == 0
        assert supervisor.l2_stale_overage_ms(
            "l2Book:BTC",
            now_ms=7_250,
        ) == 1_250
        assert supervisor.l2_stale_overage_ms(
            "l2Book:ETH",
            now_ms=7_250,
        ) is None

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


def test_l2_exchange_staleness_opens_and_recovers_stream_gap() -> None:
    async def run() -> None:
        now = [1_000]
        rows = [
            (1_000, book(1_000)),
            (7_000, trade(1, 7_000)),
            (7_001, book(7_001)),
        ]

        class ClockedConnection(FakeConnection):
            async def recv_json(self) -> dict[str, object]:
                timestamp_ms, row = rows.pop(0)
                now[0] = timestamp_ms
                assert isinstance(row, dict)
                return row

        connection = ClockedConnection([])
        events: list[StreamEvent] = []
        gaps: list[DataGap] = []

        async def factory() -> ClockedConnection:
            return connection

        async def event_sink(event: StreamEvent) -> None:
            events.append(event)

        async def gap_sink(gap: DataGap) -> None:
            gaps.append(gap)

        supervisor = WebSocketSupervisor(
            factory,
            (
                {"type": "l2Book", "coin": "BTC"},
                {"type": "trades", "coin": "BTC"},
            ),
            event_sink=event_sink,
            gap_sink=gap_sink,
            clock_ms=lambda: now[0],
            utcnow=lambda: datetime.fromtimestamp(
                now[0] / 1000,
                tz=UTC,
            ),
            stale_after_ms=5_000,
        )
        await supervisor.run(
            max_sessions=1,
            max_messages_per_session=3,
        )

        assert [event.kind.value for event in events] == [
            "l2_book",
            "trade",
            "l2_book",
        ]
        assert any(
            gap.stream_id == "l2Book:BTC"
            and gap.reason == "stale"
            and gap.ended_ms is None
            for gap in gaps
        )
        assert any(
            gap.stream_id == "l2Book:BTC"
            and gap.reason == "recovered"
            and gap.ended_ms is not None
            for gap in gaps
        )
        assert supervisor.stale_l2_streams(now_ms=7_001) == ()

    asyncio.run(run())


def test_l2_staleness_uses_exchange_time_not_recent_receive() -> None:
    async def run() -> None:
        now = [10_000]
        connection = FakeConnection([book(1_000)])
        gaps: list[DataGap] = []

        async def factory() -> FakeConnection:
            return connection

        async def event_sink(_event: StreamEvent) -> None:
            return None

        async def gap_sink(gap: DataGap) -> None:
            gaps.append(gap)

        supervisor = WebSocketSupervisor(
            factory,
            ({"type": "l2Book", "coin": "BTC"},),
            event_sink=event_sink,
            gap_sink=gap_sink,
            clock_ms=lambda: now[0],
            utcnow=lambda: datetime.fromtimestamp(
                now[0] / 1000,
                tz=UTC,
            ),
            stale_after_ms=5_000,
        )
        await supervisor.run(
            max_sessions=1,
            max_messages_per_session=1,
        )

        assert supervisor.l2_freshness_age_ms(
            "l2Book:BTC",
            now_ms=10_000,
        ) == 9_000
        assert supervisor.l2_freshness_age_ms(
            "l2Book:ETH",
            now_ms=10_000,
        ) is None
        assert supervisor.stale_l2_streams(now_ms=10_000) == (
            "l2Book:BTC",
        )
        assert any(
            gap.reason == "stale" and gap.stream_id == "l2Book:BTC"
            for gap in gaps
        )

    asyncio.run(run())
