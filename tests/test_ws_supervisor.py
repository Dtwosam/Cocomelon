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


def test_failed_event_sink_cannot_record_false_websocket_recovery() -> None:
    async def run() -> None:
        first = FakeConnection([trade(1), ConnectionError("drop")])
        second = FakeConnection([trade(2, 2_000)])
        pool = [first, second]
        timeline: list[str] = []
        now = [1_000]

        async def factory() -> FakeConnection:
            return pool.pop(0)

        async def event_sink(event: StreamEvent) -> None:
            if event.event_key == "trades:BTC:2000:2":
                timeline.append("event_rejected")
                raise RuntimeError("journal write rejected")
            timeline.append("event_accepted")
            now[0] += 1_000

        async def gap_sink(gap: DataGap) -> None:
            timeline.append(gap.reason)

        async def no_sleep(_: float) -> None:
            return None

        supervisor = WebSocketSupervisor(
            factory,
            ({"type": "trades", "coin": "BTC"},),
            event_sink=event_sink,
            gap_sink=gap_sink,
            clock_ms=lambda: now[0],
            utcnow=lambda: datetime(2026, 8, 23, tzinfo=UTC),
            sleep=no_sleep,
        )
        with pytest.raises(RuntimeError, match="journal write rejected"):
            await supervisor.run(max_sessions=2, max_messages_per_session=2)

        assert timeline == [
            "event_accepted", "disconnect", "event_rejected"
        ]

    asyncio.run(run())


def test_websocket_recovery_is_persisted_after_normalized_event() -> None:
    async def run() -> None:
        first = FakeConnection([trade(1), ConnectionError("drop")])
        second = FakeConnection([trade(2, 2_000)])
        pool = [first, second]
        timeline: list[str] = []
        now = [1_000]

        async def factory() -> FakeConnection:
            return pool.pop(0)

        async def event_sink(event: StreamEvent) -> None:
            timeline.append(event.event_key)
            now[0] += 1_000

        async def gap_sink(gap: DataGap) -> None:
            timeline.append(gap.reason)

        async def no_sleep(_: float) -> None:
            return None

        supervisor = WebSocketSupervisor(
            factory,
            ({"type": "trades", "coin": "BTC"},),
            event_sink=event_sink,
            gap_sink=gap_sink,
            clock_ms=lambda: now[0],
            utcnow=lambda: datetime(2026, 8, 23, tzinfo=UTC),
            sleep=no_sleep,
        )
        await supervisor.run(max_sessions=2, max_messages_per_session=2)
        assert timeline[:4] == [
            "trades:BTC:1000:1",
            "disconnect",
            "trades:BTC:2000:2",
            "recovered",
        ]

    asyncio.run(run())


def test_websocket_supervisor_reports_normalization_activity() -> None:
    async def run() -> None:
        connection = FakeConnection([trade(1)])
        activity: list[tuple[str, bool]] = []

        async def factory() -> FakeConnection:
            return connection

        async def event_sink(_event: StreamEvent) -> None:
            return None

        async def gap_sink(_gap: DataGap) -> None:
            return None

        supervisor = WebSocketSupervisor(
            factory,
            ({"type": "trades", "coin": "BTC"},),
            event_sink=event_sink,
            gap_sink=gap_sink,
            clock_ms=lambda: 1_000,
            utcnow=lambda: datetime(2026, 8, 23, tzinfo=UTC),
            activity_hook=lambda phase, active: activity.append(
                (phase, active)
            ),
        )
        await supervisor.run(
            max_sessions=1,
            max_messages_per_session=1,
        )

        assert activity == [
            ("normalize_message", True),
            ("normalize_message", False),
        ]

    asyncio.run(run())


def test_reconnect_accepts_same_l2_snapshot_as_new_session_bootstrap() -> None:
    async def run() -> None:
        same_book = book(1_000)
        first = FakeConnection(
            [same_book, ConnectionError("drop")]
        )
        second = FakeConnection(
            [same_book, ConnectionError("bounded end")]
        )
        pool = [first, second]
        events: list[StreamEvent] = []
        gaps: list[DataGap] = []
        sleeps: list[float] = []
        now = [1_000]

        async def factory() -> FakeConnection:
            return pool.pop(0)

        async def event_sink(event: StreamEvent) -> None:
            events.append(event)

        async def gap_sink(gap: DataGap) -> None:
            gaps.append(gap)

        async def fake_sleep(value: float) -> None:
            sleeps.append(value)
            now[0] += 1_000

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
            sleep=fake_sleep,
            stale_after_ms=5_000,
        )

        await supervisor.run(
            max_sessions=2,
            max_messages_per_session=2,
        )

        assert len(events) == 2
        assert events[0].event_key == events[1].event_key
        assert supervisor.health.duplicate_count == 0
        assert supervisor.health.reconnect_count == 1
        assert sleeps == [1.0]
        assert any(
            gap.stream_id == "l2Book:BTC"
            and gap.reason == "recovered"
            and gap.ended_ms is not None
            for gap in gaps
        )

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


def test_overdue_l2_deadline_drains_buffered_fresh_book() -> None:
    async def run() -> None:
        clock_calls = 0

        def clock_ms() -> int:
            nonlocal clock_calls
            clock_calls += 1
            return 1_000 if clock_calls <= 6 else 7_000

        connection = FakeConnection(
            [book(1_000), book(7_000)]
        )
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
            ({"type": "l2Book", "coin": "BTC"},),
            event_sink=event_sink,
            gap_sink=gap_sink,
            clock_ms=clock_ms,
            utcnow=lambda: datetime.fromtimestamp(
                (1_000 if clock_calls <= 6 else 7_000) / 1000,
                tz=UTC,
            ),
            stale_after_ms=5_000,
            systemic_l2_stale_reconnect_fraction=1.0,
        )

        await supervisor.run(
            max_sessions=1,
            max_messages_per_session=2,
        )

        assert len(events) == 2
        assert supervisor.health.reconnect_count == 0
        assert supervisor.health.systemic_l2_stale_reconnect_count == 0
        assert supervisor.stale_deadline_buffered_message_count == 1
        assert not any(
            gap.reason == "stale"
            and gap.stream_id == "l2Book:BTC"
            for gap in gaps
        )

    asyncio.run(run())


def test_systemic_l2_stale_targets_resubscribe_without_claiming_freshness() -> None:
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
            async def recv_json(self) -> dict[str, object]:
                timestamp_ms, row = rows.pop(0)
                now[0] = timestamp_ms
                assert isinstance(row, dict)
                return row

        connection = ClockedConnection([])
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
            max_systemic_l2_targeted_resubscribes=1,
        )
        await supervisor.run(
            max_sessions=1,
            max_messages_per_session=3,
        )

        methods = [item.get("method") for item in connection.sent]
        assert methods.count("unsubscribe") == 2
        assert methods.count("subscribe") == 5
        assert (
            supervisor.health.systemic_l2_targeted_resubscribe_count
            == 1
        )
        assert supervisor.health.systemic_l2_stale_reconnect_count == 0
        assert supervisor.stale_l2_streams(now_ms=7_000) == (
            "l2Book:BTC",
            "l2Book:ETH",
        )
        assert supervisor.l2_freshness_age_ms(
            "l2Book:BTC",
            now_ms=7_000,
        ) == 6_000
        assert supervisor.l2_freshness_age_ms(
            "l2Book:ETH",
            now_ms=7_000,
        ) == 5_999
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


def test_broad_systemic_l2_staleness_targets_resubscribe_before_reconnect() -> None:
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
            (1_002, book_for("SOL", 1_002)),
            (1_003, book_for("DOGE", 1_003)),
            (7_000, trade(1, 7_000)),
            (7_001, book_for("BTC", 7_001)),
            (7_002, book_for("ETH", 7_002)),
            (7_003, book_for("SOL", 7_003)),
            (7_004, book_for("DOGE", 7_004)),
            (7_005, trade(2, 7_005)),
        ]

        class ClockedConnection(FakeConnection):
            async def recv_json(self) -> dict[str, object]:
                timestamp_ms, row = rows.pop(0)
                now[0] = timestamp_ms
                assert isinstance(row, dict)
                return row

        connection = ClockedConnection([])
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
                {"type": "l2Book", "coin": "SOL"},
                {"type": "l2Book", "coin": "DOGE"},
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
            max_systemic_l2_targeted_resubscribes=1,
        )
        await supervisor.run(
            max_sessions=1,
            max_messages_per_session=10,
        )

        methods = [item.get("method") for item in connection.sent]
        assert methods.count("unsubscribe") == 4
        assert methods.count("subscribe") == 9
        assert supervisor.health.reconnect_count == 0
        assert (
            supervisor.health.systemic_l2_targeted_resubscribe_count
            == 1
        )
        assert supervisor.health.systemic_l2_stale_reconnect_count == 0
        assert supervisor.stale_l2_streams(now_ms=7_005) == ()
        recovered = {
            gap.stream_id
            for gap in gaps
            if gap.reason == "recovered"
        }
        assert {
            "l2Book:BTC",
            "l2Book:ETH",
            "l2Book:SOL",
            "l2Book:DOGE",
        } <= recovered

    asyncio.run(run())


def test_targeted_l2_resubscribe_accepts_fresh_recovery_without_reconnect() -> None:
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
            (7_001, book_for("BTC", 7_001)),
            (7_002, book_for("ETH", 7_002)),
        ]

        class ClockedConnection(FakeConnection):
            async def recv_json(self) -> dict[str, object]:
                timestamp_ms, row = rows.pop(0)
                now[0] = timestamp_ms
                assert isinstance(row, dict)
                return row

        connection = ClockedConnection([])
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
            max_systemic_l2_targeted_resubscribes=1,
        )
        await supervisor.run(
            max_sessions=1,
            max_messages_per_session=5,
        )

        assert supervisor.health.reconnect_count == 0
        assert (
            supervisor.health.systemic_l2_targeted_resubscribe_count
            == 1
        )
        assert supervisor.health.systemic_l2_stale_reconnect_count == 0
        assert supervisor.stale_l2_streams(now_ms=7_002) == ()
        recovered = {
            gap.stream_id
            for gap in gaps
            if gap.reason == "recovered"
        }
        assert {"l2Book:BTC", "l2Book:ETH"} <= recovered

    asyncio.run(run())


def test_future_dated_l2_book_remains_stale() -> None:
    async def run() -> None:
        now = [6_000]
        connection = FakeConnection([book(7_000)])

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
            now_ms=6_000,
        ) == -1_000
        assert supervisor.stale_l2_streams(now_ms=6_000) == (
            "l2Book:BTC",
        )

    asyncio.run(run())


def test_future_dated_targeted_l2_recovery_times_out_to_reconnect() -> None:
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
            (7_001, book_for("BTC", 13_000)),
            (7_002, book_for("ETH", 13_000)),
            (12_001, trade(2, 12_001)),
        ]
        second_rows: list[tuple[int, object]] = [
            (13_001, book_for("BTC", 13_001)),
            (13_002, book_for("ETH", 13_002)),
            (13_003, trade(3, 13_003)),
        ]

        class ClockedConnection(FakeConnection):
            def __init__(
                self,
                rows: list[tuple[int, object]],
            ) -> None:
                super().__init__([])
                self.clock_rows = rows

            async def recv_json(self) -> dict[str, object]:
                timestamp_ms, row = self.clock_rows.pop(0)
                now[0] = timestamp_ms
                assert isinstance(row, dict)
                return row

        first = ClockedConnection(first_rows)
        second = ClockedConnection(second_rows)
        pool = [first, second]
        sleeps: list[float] = []

        async def factory() -> ClockedConnection:
            return pool.pop(0)

        async def event_sink(_event: StreamEvent) -> None:
            return None

        async def gap_sink(_gap: DataGap) -> None:
            return None

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
            max_systemic_l2_targeted_resubscribes=1,
        )
        await supervisor.run(
            max_sessions=2,
            max_messages_per_session=6,
        )

        assert first.closed is True
        assert second.closed is True
        assert supervisor.health.reconnect_count == 1
        assert (
            supervisor.health.systemic_l2_targeted_resubscribe_count
            == 1
        )
        assert supervisor.health.systemic_l2_stale_reconnect_count == 1
        assert sleeps == [1.0]

    asyncio.run(run())


def test_targeted_l2_resubscribe_falls_back_after_no_fresh_evidence() -> None:
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
            (12_001, trade(2, 12_001)),
        ]
        second_rows: list[tuple[int, object]] = [
            (13_000, book_for("BTC", 13_000)),
            (13_001, book_for("ETH", 13_001)),
            (13_002, trade(3, 13_002)),
        ]

        class ClockedConnection(FakeConnection):
            def __init__(
                self,
                rows: list[tuple[int, object]],
            ) -> None:
                super().__init__([])
                self.clock_rows = rows

            async def recv_json(self) -> dict[str, object]:
                timestamp_ms, row = self.clock_rows.pop(0)
                now[0] = timestamp_ms
                assert isinstance(row, dict)
                return row

        first = ClockedConnection(first_rows)
        second = ClockedConnection(second_rows)
        pool = [first, second]
        sleeps: list[float] = []

        async def factory() -> ClockedConnection:
            return pool.pop(0)

        async def event_sink(_event: StreamEvent) -> None:
            return None

        async def gap_sink(_gap: DataGap) -> None:
            return None

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
            max_systemic_l2_targeted_resubscribes=1,
        )
        await supervisor.run(
            max_sessions=2,
            max_messages_per_session=4,
        )

        assert first.closed is True
        assert second.closed is True
        assert supervisor.health.reconnect_count == 1
        assert (
            supervisor.health.systemic_l2_targeted_resubscribe_count
            == 1
        )
        assert supervisor.health.systemic_l2_stale_reconnect_count == 1
        assert sleeps == [1.0]

    asyncio.run(run())


def test_targeted_l2_resubscribe_limit_must_be_non_negative() -> None:
    with pytest.raises(
        ValueError,
        match="max_systemic_l2_targeted_resubscribes",
    ):
        WebSocketSupervisor(
            lambda: None,  # type: ignore[arg-type]
            (),
            event_sink=lambda _event: None,  # type: ignore[arg-type]
            gap_sink=lambda _gap: None,  # type: ignore[arg-type]
            clock_ms=lambda: 0,
            utcnow=lambda: datetime.now(UTC),
            max_systemic_l2_targeted_resubscribes=-1,
        )


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



def test_l2_delivery_diagnostics_distinguish_book_gap_causes() -> None:
    async def run() -> None:
        now = [1_000]
        accepted: list[StreamEvent] = []
        gaps: list[DataGap] = []

        async def factory() -> FakeConnection:
            return FakeConnection([])

        async def event_sink(event: StreamEvent) -> None:
            accepted.append(event)

        async def gap_sink(gap: DataGap) -> None:
            gaps.append(gap)

        supervisor = WebSocketSupervisor(
            factory,
            ({"type": "l2Book", "coin": "BTC"},),
            event_sink=event_sink,
            gap_sink=gap_sink,
            clock_ms=lambda: now[0],
            utcnow=lambda: datetime.fromtimestamp(now[0] / 1000, tz=UTC),
            stale_after_ms=5_000,
        )
        assert supervisor.l2_delivery_diagnostics(now_ms=1_000) == {
            "l2_normalized_count": 0,
            "l2_duplicate_count": 0,
            "l2_out_of_order_count": 0,
            "l2_stale_on_receive_count": 0,
            "uncommitted_source_gap_open_count": 0,
            "uncommitted_source_gap_recovered_count": 0,
            "uncommitted_source_gap_anomaly_count": 0,
            "l2_fresh_accepted_count": 0,
            "l2_max_event_sink_await_ms": 0,
            "l2_last_normalized_age_ms": None,
            "l2_last_fresh_accepted_age_ms": None,
            "l2_unique_interval_samples": 0,
            "l2_unique_interval_ge_stale_count": 0,
            "l2_unique_interval_ge_5000_count": 0,
            "l2_unique_interval_max_ms": 0,
            "l2_unique_interval_censored_count": 0,
            "l2_unique_interval_censored_ge_stale_count": 0,
            "l2_unique_interval_censored_max_elapsed_ms": 0,
            "l2_unique_stream_count": 1,
            "l2_unique_stream_unseen_count": 1,
            "l2_unique_stream_aged_ge_stale_count": 0,
            "l2_unique_stream_aged_ge_5000_count": 0,
            "l2_unique_stream_oldest_age_ms": None,
            "l2_source_age_samples": 0,
            "l2_source_age_ge_stale_count": 0,
            "l2_source_age_ge_5000_count": 0,
            "l2_source_age_max_ms": 0,
            "l2_source_future_dated_count": 0,
            "l2_source_fresh_observation_elapsed_ms": 0,
            "l2_source_fresh_3000_basis_points": 0,
            "l2_source_fresh_5000_basis_points": 0,
            "l2_source_fresh_clock_regressions": 0,
            "l2_arrival_stale_threshold_ms": 5_000,
            "l2_targeted_recovery_timeout_ms": 5_000,
            "l2_recovery_trigger_floor_ms": None,
        }
        await supervisor._dispatch(book(1_000))
        await supervisor._dispatch(book(1_000))  # same replay key
        now[0] = 1_050
        await supervisor._dispatch(book(1_050))
        now[0] = 7_000
        await supervisor._dispatch(book(1_001))  # out-of-order
        await supervisor._dispatch(book(2_000))  # too old on arrival
        now[0] = 7_010
        await supervisor._dispatch(book(7_010))  # genuinely fresh recovery

        diag = supervisor.l2_delivery_diagnostics(now_ms=7_015)
        assert diag["l2_normalized_count"] == 6
        assert diag["l2_duplicate_count"] == 1
        assert diag["l2_out_of_order_count"] == 1
        assert diag["l2_stale_on_receive_count"] == 1
        assert diag["l2_fresh_accepted_count"] == 3
        assert isinstance(diag["l2_max_event_sink_await_ms"], int)
        assert diag["l2_last_normalized_age_ms"] == 5
        assert diag["l2_last_fresh_accepted_age_ms"] == 5
        assert diag["l2_unique_interval_samples"] == 3
        assert diag["l2_unique_interval_max_ms"] == 5_950
        assert diag["l2_unique_interval_ge_stale_count"] == 1
        assert diag["l2_unique_interval_ge_5000_count"] == 1
        assert diag["l2_unique_interval_censored_count"] == 0
        assert diag["l2_unique_stream_count"] == 1
        assert diag["l2_unique_stream_unseen_count"] == 0
        assert diag["l2_unique_stream_aged_ge_stale_count"] == 0
        assert diag["l2_unique_stream_oldest_age_ms"] == 5
        assert diag["l2_source_age_samples"] == 4
        assert diag["l2_source_age_max_ms"] == 5_000
        assert diag["l2_source_age_ge_stale_count"] == 1
        assert diag["l2_source_age_ge_5000_count"] == 1
        assert diag["l2_source_future_dated_count"] == 0
        assert len(accepted) == 4
        assert any(gap.reason == "out_of_order" for gap in gaps)
        assert any(gap.reason == "recovered" for gap in gaps)
        assert set(diag) == {
            "l2_normalized_count", "l2_duplicate_count",
            "l2_out_of_order_count", "l2_stale_on_receive_count",
            "uncommitted_source_gap_open_count",
            "uncommitted_source_gap_recovered_count",
            "uncommitted_source_gap_anomaly_count",
            "l2_fresh_accepted_count", "l2_max_event_sink_await_ms",
            "l2_last_normalized_age_ms", "l2_last_fresh_accepted_age_ms",
            "l2_unique_interval_samples", "l2_unique_interval_ge_stale_count",
            "l2_unique_interval_ge_5000_count", "l2_unique_interval_max_ms",
            "l2_unique_interval_censored_count",
            "l2_unique_interval_censored_ge_stale_count",
            "l2_unique_interval_censored_max_elapsed_ms",
            "l2_unique_stream_count", "l2_unique_stream_unseen_count",
            "l2_unique_stream_aged_ge_stale_count",
            "l2_unique_stream_aged_ge_5000_count",
            "l2_unique_stream_oldest_age_ms",
            "l2_source_age_samples", "l2_source_age_ge_stale_count",
            "l2_source_age_ge_5000_count", "l2_source_age_max_ms",
            "l2_source_future_dated_count", "l2_arrival_stale_threshold_ms",
            "l2_source_fresh_observation_elapsed_ms",
            "l2_source_fresh_3000_basis_points",
            "l2_source_fresh_5000_basis_points",
            "l2_source_fresh_clock_regressions",
            "l2_targeted_recovery_timeout_ms",
            "l2_recovery_trigger_floor_ms",
        }
        assert "BTC" not in str(diag)

    asyncio.run(run())



def test_l2_interval_diagnostic_excludes_replays_and_resubscribe_downtime() -> None:
    async def run() -> None:
        now = [1_000]

        async def factory() -> FakeConnection:
            return FakeConnection([])

        async def event_sink(event: StreamEvent) -> None:
            del event

        async def gap_sink(gap: DataGap) -> None:
            del gap

        supervisor = WebSocketSupervisor(
            factory,
            ({"type": "l2Book", "coin": "BTC"},),
            event_sink=event_sink,
            gap_sink=gap_sink,
            clock_ms=lambda: now[0],
            utcnow=lambda: datetime.fromtimestamp(now[0] / 1000, tz=UTC),
            stale_after_ms=3_000,
        )
        await supervisor._dispatch(book(1_000))
        now[0] = 3_500
        await supervisor._dispatch(book(1_000))  # replay, not a distinct book
        now[0] = 5_050
        await supervisor._dispatch(book(5_050))
        diag = supervisor.l2_delivery_diagnostics(now_ms=5_050)
        assert diag["l2_unique_interval_samples"] == 1
        assert diag["l2_unique_interval_max_ms"] == 4_050
        assert diag["l2_unique_interval_ge_stale_count"] == 1
        assert diag["l2_unique_interval_ge_5000_count"] == 0
        # An old event is received now, even though its exchange timestamp
        # is too old for current-book eligibility.
        now[0] = 10_060
        await supervisor._dispatch(book(7_000))
        diag = supervisor.l2_delivery_diagnostics(now_ms=10_060)
        assert diag["l2_unique_interval_ge_5000_count"] == 1
        assert diag["l2_source_age_ge_stale_count"] == 1
        assert diag["l2_source_age_max_ms"] == 3_060

        supervisor._clear_l2_dedup_state("l2Book:BTC")
        censored = supervisor.l2_delivery_diagnostics(now_ms=10_060)
        assert censored["l2_unique_interval_censored_count"] == 1
        assert censored["l2_unique_interval_censored_ge_stale_count"] == 0
        assert censored["l2_unique_stream_unseen_count"] == 1
        now[0] = 30_000
        await supervisor._dispatch(book(30_000))
        diag = supervisor.l2_delivery_diagnostics(now_ms=30_000)
        assert diag["l2_unique_interval_samples"] == 2
        assert diag["l2_unique_interval_max_ms"] == 5_010
        assert diag["l2_source_age_samples"] == 4
        assert len(supervisor._l2_last_unique_receive_ms) == 1
        # Reconnect resets the active stream-clock, not cumulative counters.
        now[0] = 40_000
        supervisor._reset_l2_freshness_for_session(session_started_ms=40_000)
        assert supervisor._l2_last_unique_receive_ms == {}
        after = supervisor.l2_delivery_diagnostics(now_ms=40_000)
        assert after["l2_unique_interval_censored_count"] == 2
        assert after["l2_unique_interval_censored_ge_stale_count"] == 1
        assert after["l2_unique_interval_censored_max_elapsed_ms"] == 10_000
        assert after["l2_unique_stream_unseen_count"] == 1

    asyncio.run(run())



def test_l2_reset_censors_silent_stream_without_faking_freshness() -> None:
    async def run() -> None:
        now = [1_000]

        async def factory() -> FakeConnection:
            return FakeConnection([])

        async def event_sink(event: StreamEvent) -> None:
            del event

        async def gap_sink(gap: DataGap) -> None:
            del gap

        supervisor = WebSocketSupervisor(
            factory,
            ({"type": "l2Book", "coin": "BTC"},),
            event_sink=event_sink,
            gap_sink=gap_sink,
            clock_ms=lambda: now[0],
            utcnow=lambda: datetime.fromtimestamp(now[0] / 1000, tz=UTC),
            stale_after_ms=3_000,
        )
        await supervisor._dispatch(book(1_000))
        now[0] = 5_500
        diag = supervisor.l2_delivery_diagnostics(now_ms=now[0])
        assert diag["l2_unique_stream_unseen_count"] == 0
        assert diag["l2_unique_stream_aged_ge_stale_count"] == 1
        assert diag["l2_unique_stream_oldest_age_ms"] == 4_500
        assert diag["l2_unique_interval_samples"] == 0
        supervisor._clear_l2_dedup_state("l2Book:BTC")
        after = supervisor.l2_delivery_diagnostics(now_ms=now[0])
        assert after["l2_unique_stream_unseen_count"] == 1
        assert after["l2_unique_interval_censored_count"] == 1
        assert after["l2_unique_interval_censored_ge_stale_count"] == 1
        assert after["l2_unique_interval_censored_max_elapsed_ms"] == 4_500
        assert after["l2_unique_interval_samples"] == 0
        # No false event acceptance, no overwritten exchange timestamp,
        # and no suppressed gap or fabricated book freshness.
        assert supervisor._last_exchange_time["l2Book:BTC"] == 1_000
        assert supervisor._l2_stream_is_stale("l2Book:BTC", now_ms=5_500)
        await supervisor._dispatch(book(5_500))
        observed = supervisor.l2_delivery_diagnostics(now_ms=5_500)
        assert observed["l2_unique_stream_unseen_count"] == 0
        assert observed["l2_unique_interval_samples"] == 0
        assert observed["l2_unique_interval_censored_count"] == 1

    asyncio.run(run())



def test_targeted_l2_recovery_timeout_can_wait_for_fresh_book_without_false_gap() -> None:
    async def run() -> None:
        now = [1_000]
        received: list[StreamEvent] = []
        gaps: list[DataGap] = []
        connection = FakeConnection([])

        async def factory() -> FakeConnection:
            return connection

        async def sink(event: StreamEvent) -> None:
            received.append(event)

        async def gap_sink(gap: DataGap) -> None:
            gaps.append(gap)

        supervisor = WebSocketSupervisor(
            factory,
            ({"type": "l2Book", "coin": "BTC"},),
            event_sink=sink,
            gap_sink=gap_sink,
            clock_ms=lambda: now[0],
            utcnow=lambda: datetime.fromtimestamp(now[0] / 1000, tz=UTC),
            stale_after_ms=3_000,
            targeted_l2_recovery_timeout_ms=6_000,
            systemic_l2_stale_reconnect_fraction=0.5,
            max_systemic_l2_targeted_resubscribes=1,
        )
        await supervisor._dispatch(book(1_000))
        await supervisor._emit_gap(
            DataGap(
                stream_id="l2Book:BTC",
                started_ms=4_000,
                ended_ms=None,
                reason="stale",
            )
        )
        supervisor._open_gaps["l2Book:BTC"] = DataGap(
            stream_id="l2Book:BTC",
            started_ms=4_000,
            ended_ms=None,
            reason="stale",
        )
        supervisor._pending_l2_targeted_recovery_streams.add("l2Book:BTC")
        supervisor._l2_targeted_recovery_started_ms = 4_000
        now[0] = 8_500
        assert supervisor._l2_stream_is_stale("l2Book:BTC", now_ms=8_500)
        await supervisor._recover_systemic_l2_stale(
            connection, now_ms=8_500
        )
        assert "l2Book:BTC" in supervisor._pending_l2_targeted_recovery_streams
        assert supervisor.health.systemic_l2_stale_reconnect_count == 0
        assert [gap.reason for gap in gaps] == ["stale"]
        # Only genuinely new fresh book evidence may heal the original gap.
        now[0] = 9_000
        await supervisor._dispatch(book(9_000))
        assert supervisor._pending_l2_targeted_recovery_streams == set()
        assert supervisor.stale_l2_streams(now_ms=9_000) == ()
        assert [gap.reason for gap in gaps] == ["stale", "recovered"]
        assert len(received) == 2
        assert supervisor.health.systemic_l2_stale_reconnect_count == 0
        assert supervisor.l2_delivery_diagnostics(
            now_ms=9_000
        )["l2_targeted_recovery_timeout_ms"] == 6_000

    asyncio.run(run())


def test_targeted_l2_recovery_still_reconnects_at_bounded_timeout() -> None:
    async def run() -> None:
        now = [1_000]
        connection = FakeConnection([])

        async def factory() -> FakeConnection:
            return connection

        async def sink(event: StreamEvent) -> None:
            del event

        async def gap_sink(gap: DataGap) -> None:
            del gap

        supervisor = WebSocketSupervisor(
            factory,
            ({"type": "l2Book", "coin": "BTC"},),
            event_sink=sink,
            gap_sink=gap_sink,
            clock_ms=lambda: now[0],
            utcnow=lambda: datetime.fromtimestamp(now[0] / 1000, tz=UTC),
            stale_after_ms=3_000,
            targeted_l2_recovery_timeout_ms=6_000,
            systemic_l2_stale_reconnect_fraction=0.5,
            max_systemic_l2_targeted_resubscribes=1,
        )
        await supervisor._dispatch(book(1_000))
        supervisor._pending_l2_targeted_recovery_streams.add("l2Book:BTC")
        supervisor._l2_targeted_recovery_started_ms = 4_000
        with pytest.raises(
            ConnectionError, match="targeted l2 recovery timed out"
        ):
            await supervisor._recover_systemic_l2_stale(
                connection, now_ms=10_000
            )
        assert supervisor.health.systemic_l2_stale_reconnect_count == 1
        assert supervisor._pending_l2_targeted_recovery_streams == set()
        assert supervisor._l2_stream_is_stale(
            "l2Book:BTC", now_ms=10_000
        )

    asyncio.run(run())


def test_targeted_l2_recovery_timeout_must_be_positive() -> None:
    for timeout in (0, -1):
        with pytest.raises(
            ValueError, match="targeted_l2_recovery_timeout_ms"
        ):
            WebSocketSupervisor(
                lambda: None,  # type: ignore[arg-type]
                (),
                event_sink=lambda _: None,  # type: ignore[arg-type]
                gap_sink=lambda _: None,  # type: ignore[arg-type]
                clock_ms=lambda: 0,
                utcnow=lambda: datetime.now(UTC),
                targeted_l2_recovery_timeout_ms=timeout,
            )



def test_l2_recovery_trigger_waits_beyond_stale_gap_without_accepting_books() -> None:
    async def run() -> None:
        now = [1_000]
        gaps: list[DataGap] = []
        connection = FakeConnection([])

        async def factory() -> FakeConnection:
            return connection

        async def event_sink(event: StreamEvent) -> None:
            del event

        async def gap_sink(gap: DataGap) -> None:
            gaps.append(gap)

        supervisor = WebSocketSupervisor(
            factory,
            ({"type": "l2Book", "coin": "BTC"},),
            event_sink=event_sink,
            gap_sink=gap_sink,
            clock_ms=lambda: now[0],
            utcnow=lambda: datetime.fromtimestamp(now[0] / 1000, tz=UTC),
            stale_after_ms=3_000,
            systemic_l2_stale_reconnect_fraction=0.5,
            max_systemic_l2_targeted_resubscribes=1,
            targeted_l2_recovery_timeout_ms=6_000,
            systemic_l2_recovery_trigger_floor_ms=11_000,
        )
        await supervisor._dispatch(book(1_000))
        now[0] = 4_500
        supervisor._last_server_message_ms = now[0]
        await supervisor._open_l2_stale_gaps_if_needed(now[0])
        assert supervisor.stale_l2_streams(now_ms=now[0]) == ("l2Book:BTC",)
        assert any(gap.reason == "stale" for gap in gaps)
        assert supervisor._open_gaps
        await supervisor._recover_systemic_l2_stale(
            connection, now_ms=now[0]
        )
        assert not connection.sent
        assert supervisor.health.systemic_l2_targeted_resubscribe_count == 0
        assert supervisor.l2_delivery_diagnostics(
            now_ms=now[0]
        )["l2_recovery_trigger_floor_ms"] == 11_000

        # Still reject stale books after a whole missed 5s period, but
        # give another ordinary deep-book cadence a chance to arrive.
        now[0] = 9_000
        supervisor._last_server_message_ms = now[0]
        await supervisor._open_l2_stale_gaps_if_needed(now[0])
        await supervisor._recover_systemic_l2_stale(
            connection, now_ms=now[0]
        )
        assert supervisor._open_gaps
        assert not connection.sent

        # A later authentic book heals the signed gap without resubscribe.
        now[0] = 10_000
        await supervisor._dispatch(book(10_000))
        assert supervisor.stale_l2_streams(now_ms=now[0]) == ()
        assert supervisor._open_gaps == {}
        assert any(gap.reason == "recovered" for gap in gaps)
        assert not connection.sent

    asyncio.run(run())


def test_l2_silent_source_still_tries_targeted_and_reconnects_bounded() -> None:
    async def run() -> None:
        now = [1_000]
        connection = FakeConnection([])

        async def factory() -> FakeConnection:
            return connection

        async def event_sink(event: StreamEvent) -> None:
            del event

        async def gap_sink(gap: DataGap) -> None:
            del gap

        supervisor = WebSocketSupervisor(
            factory,
            ({"type": "l2Book", "coin": "BTC"},),
            event_sink=event_sink,
            gap_sink=gap_sink,
            clock_ms=lambda: now[0],
            utcnow=lambda: datetime.fromtimestamp(now[0] / 1000, tz=UTC),
            stale_after_ms=3_000,
            systemic_l2_stale_reconnect_fraction=0.5,
            max_systemic_l2_targeted_resubscribes=1,
            targeted_l2_recovery_timeout_ms=6_000,
            systemic_l2_recovery_trigger_floor_ms=11_000,
        )
        await supervisor._dispatch(book(1_000))
        now[0] = 6_500
        supervisor._last_server_message_ms = now[0]
        await supervisor._open_l2_stale_gaps_if_needed(now[0])
        await supervisor._recover_systemic_l2_stale(
            connection, now_ms=now[0]
        )
        assert supervisor._open_gaps
        assert not connection.sent

        # With two full source periods missing, targeted recovery resumes.
        now[0] = 12_500
        supervisor._last_server_message_ms = now[0]
        await supervisor._recover_systemic_l2_stale(
            connection, now_ms=now[0]
        )
        assert [message["method"] for message in connection.sent] == [
            "unsubscribe", "subscribe",
        ]
        assert supervisor._open_gaps
        assert supervisor._l2_stream_is_stale("l2Book:BTC", now_ms=now[0])
        now[0] = 18_500
        supervisor._last_server_message_ms = now[0]
        with pytest.raises(
            ConnectionError, match="targeted l2 recovery timed out"
        ):
            await supervisor._recover_systemic_l2_stale(
                connection, now_ms=now[0]
            )
        assert supervisor.health.systemic_l2_stale_reconnect_count == 1
        assert supervisor._open_gaps

    asyncio.run(run())


def test_l2_recovery_trigger_floor_must_be_positive() -> None:
    for minimum in (0, -1):
        with pytest.raises(
            ValueError, match="systemic_l2_recovery_trigger_floor_ms"
        ):
            WebSocketSupervisor(
                lambda: None,  # type: ignore[arg-type]
                (),
                event_sink=lambda _: None,  # type: ignore[arg-type]
                gap_sink=lambda _: None,  # type: ignore[arg-type]
                clock_ms=lambda: 0,
                utcnow=lambda: datetime.now(UTC),
                systemic_l2_recovery_trigger_floor_ms=minimum,
            )


def test_l2_observed_source_freshness_integrates_elapsed_time_fail_closed() -> None:
    """Observe source time only; do not infer trade/depth eligibility from it."""

    async def run() -> None:
        now = [1_000]
        events: list[StreamEvent] = []

        async def factory() -> FakeConnection:
            return FakeConnection([])

        async def event_sink(event: StreamEvent) -> None:
            events.append(event)

        async def gap_sink(gap: DataGap) -> None:
            del gap

        supervisor = WebSocketSupervisor(
            factory,
            ({"type": "l2Book", "coin": "BTC"}, {"type": "l2Book", "coin": "ETH"}),
            event_sink=event_sink,
            gap_sink=gap_sink,
            clock_ms=lambda: now[0],
            utcnow=lambda: datetime.fromtimestamp(now[0] / 1_000, tz=UTC),
            stale_after_ms=3_000,
        )
        empty = supervisor.l2_delivery_diagnostics(now_ms=1_000)
        assert empty["l2_source_fresh_3000_basis_points"] == 0

        await supervisor._dispatch(book(1_000))
        now[0] = 3_000
        initial = supervisor.l2_delivery_diagnostics(now_ms=3_000)
        assert initial["l2_source_fresh_observation_elapsed_ms"] == 2_000
        assert initial["l2_source_fresh_3000_basis_points"] == 5_000
        assert initial["l2_source_fresh_5000_basis_points"] == 5_000

        # Duplicates never refresh source freshness, even if seen after 3s.
        now[0] = 4_000
        await supervisor._dispatch(book(1_000))
        now[0] = 6_000
        aged = supervisor.l2_delivery_diagnostics(now_ms=6_000)
        assert aged["l2_source_fresh_observation_elapsed_ms"] == 5_000
        assert aged["l2_source_fresh_3000_basis_points"] == 3_000
        assert aged["l2_source_fresh_5000_basis_points"] == 5_000
        assert supervisor.l2_delivery_diagnostics(now_ms=6_000) == aged

        # A targeted resubscribe censors the old source clock. 2nd market is
        # still unseen; neither market contributes fictitious fresh time.
        supervisor._clear_l2_dedup_state("l2Book:BTC")
        now[0] = 8_000
        censored = supervisor.l2_delivery_diagnostics(now_ms=8_000)
        assert censored["l2_source_fresh_3000_basis_points"] == 2_142
        assert censored["l2_source_fresh_5000_basis_points"] == 3_571
        await supervisor._dispatch(book(8_000))
        now[0] = 10_000
        resumed = supervisor.l2_delivery_diagnostics(now_ms=10_000)
        assert resumed["l2_source_fresh_3000_basis_points"] == 2_777
        assert resumed["l2_source_fresh_5000_basis_points"] == 3_888

        # An old unique book received late contributes no new fresh time.
        now[0] = 16_000
        await supervisor._dispatch(book(11_000))
        now[0] = 18_000
        late = supervisor.l2_delivery_diagnostics(now_ms=18_000)
        assert late["l2_source_fresh_3000_basis_points"] == 1_764
        assert late["l2_source_fresh_5000_basis_points"] == 2_941
        assert len(events) == 3

    asyncio.run(run())


def test_l2_observed_source_freshness_disallows_future_dated_clock_replay() -> None:
    async def run() -> None:
        now = [2_000]

        async def factory() -> FakeConnection:
            return FakeConnection([])

        async def event_sink(event: StreamEvent) -> None:
            del event

        async def gap_sink(gap: DataGap) -> None:
            del gap

        supervisor = WebSocketSupervisor(
            factory,
            ({"type": "l2Book", "coin": "BTC"},),
            event_sink=event_sink,
            gap_sink=gap_sink,
            clock_ms=lambda: now[0],
            utcnow=lambda: datetime.fromtimestamp(now[0] / 1_000, tz=UTC),
            stale_after_ms=3_000,
        )
        await supervisor._dispatch(book(2_000))
        now[0] = 5_000
        await supervisor._dispatch(book(6_000))  # future exchange timestamp
        now[0] = 7_000
        diag = supervisor.l2_delivery_diagnostics(now_ms=7_000)
        assert diag["l2_source_fresh_3000_basis_points"] == 6_000
        assert diag["l2_source_fresh_5000_basis_points"] == 6_000

    asyncio.run(run())
