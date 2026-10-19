"""Original WS source clocks are not acknowledged until the event sink succeeds."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from cocomelon.domain.stream import DataGap, StreamEvent
from cocomelon.hyperliquid.ws_supervisor import WebSocketSupervisor


def _book(at: int) -> dict[str, object]:
    return {
        "channel": "l2Book",
        "data": {
            "coin": "BTC",
            "levels": [
                [{"n": 1, "px": "99", "sz": "1"}],
                [{"n": 1, "px": "101", "sz": "1"}],
            ],
            "time": at,
        },
    }


def test_failed_book_sink_cannot_poison_exchange_highwater_or_l2_freshness() -> None:
    async def run() -> None:
        clock = [1_000]
        accepted: list[str] = []
        gaps: list[DataGap] = []
        reject_time = 3_000

        async def factory() -> object:
            raise AssertionError("no venue network required")

        async def event_sink(event: StreamEvent) -> None:
            if event.exchange_time_ms == reject_time:
                raise OSError("original book sink rejected")
            accepted.append(event.event_key)

        async def gap_sink(gap: DataGap) -> None:
            gaps.append(gap)

        supervisor = WebSocketSupervisor(
            factory, ({"type": "l2Book", "coin": "BTC"},),
            event_sink=event_sink, gap_sink=gap_sink,
            clock_ms=lambda: clock[0],
            utcnow=lambda: datetime(2026, 10, 17, tzinfo=UTC),
            stale_after_ms=5_000,
        )
        await supervisor._dispatch(_book(1_000))
        before = supervisor.l2_delivery_diagnostics(now_ms=1_000)
        assert supervisor._last_exchange_time["l2Book:BTC"] == 1_000
        assert before["l2_source_age_samples"] == 1
        assert before["l2_unique_interval_samples"] == 0
        assert len(accepted) == 1

        clock[0] = 3_100
        with pytest.raises(RuntimeError, match="original book sink rejected"):
            await supervisor._dispatch(_book(3_000))
        failed = supervisor.l2_delivery_diagnostics(now_ms=3_100)
        assert supervisor._last_exchange_time["l2Book:BTC"] == 1_000
        assert supervisor._l2_last_unique_receive_ms["l2Book:BTC"] == 1_000
        assert supervisor._l2_source_fresh_last["l2Book:BTC"] == (1_000, 0)
        assert failed["l2_source_age_samples"] == 1
        assert failed["l2_unique_interval_samples"] == 0
        assert failed["l2_fresh_accepted_count"] == 1
        assert len(accepted) == 1
        assert not gaps

        # This genuine source event would have been called out-of-order if
        # the FAILED 3000ms write had prematurely advanced highwater.
        clock[0] = 3_200
        await supervisor._dispatch(_book(2_000))
        assert len(accepted) == 2
        assert supervisor._last_exchange_time["l2Book:BTC"] == 2_000
        good = supervisor.l2_delivery_diagnostics(now_ms=3_200)
        assert good["l2_source_age_samples"] == 2
        assert good["l2_unique_interval_samples"] == 1
        assert good["l2_out_of_order_count"] == 0
        assert good["l2_fresh_accepted_count"] == 2
        assert not gaps

    asyncio.run(run())


def test_stale_l2_gap_uses_exact_failed_payload_timestamp_without_ack() -> None:
    async def run() -> None:
        clock = [9_500]
        accepted: list[str] = []
        gaps: list[DataGap] = []
        reject_once = True

        async def factory() -> object:
            raise AssertionError("no venue network required")

        async def event_sink(event: StreamEvent) -> None:
            nonlocal reject_once
            if reject_once:
                reject_once = False
                raise OSError("stale source write rejected")
            accepted.append(event.event_key)

        async def gap_sink(gap: DataGap) -> None:
            gaps.append(gap)

        supervisor = WebSocketSupervisor(
            factory, ({"type": "l2Book", "coin": "BTC"},),
            event_sink=event_sink, gap_sink=gap_sink,
            clock_ms=lambda: clock[0],
            utcnow=lambda: datetime(2026, 10, 17, tzinfo=UTC),
            stale_after_ms=5_000,
        )
        with pytest.raises(RuntimeError, match="stale source write rejected"):
            await supervisor._dispatch(_book(2_000))
        assert [(g.reason, g.started_ms) for g in gaps] == [("stale", 7_000)]
        assert "l2Book:BTC" not in supervisor._last_exchange_time
        assert supervisor.l2_delivery_diagnostics(
            now_ms=9_500
        )["l2_source_age_samples"] == 0
        assert not accepted
        assert "l2Book:BTC" in supervisor._open_gaps

        # Accepted redelivery remains stale: it cannot heal its own gap.
        await supervisor._dispatch(_book(2_000))
        assert len(accepted) == 1
        assert supervisor._last_exchange_time["l2Book:BTC"] == 2_000
        assert [(g.reason, g.started_ms) for g in gaps] == [("stale", 7_000)]

        clock[0] = 9_700
        await supervisor._dispatch(_book(9_700))
        assert len(accepted) == 2
        assert [(g.reason, g.started_ms) for g in gaps] == [
            ("stale", 7_000), ("recovered", 7_000),
        ]
        assert not supervisor._open_gaps
        assert supervisor.l2_delivery_diagnostics(
            now_ms=9_700
        )["l2_fresh_accepted_count"] == 1

    asyncio.run(run())


def test_cancelled_l2_sink_does_not_ack_source_clock_or_interval() -> None:
    async def run() -> None:
        clock = [2_000]
        started = asyncio.Event()
        should_block = True
        accepted: list[str] = []

        async def factory() -> object:
            raise AssertionError("no venue network required")

        async def event_sink(event: StreamEvent) -> None:
            if should_block:
                started.set()
                await asyncio.Event().wait()
            accepted.append(event.event_key)

        async def gap_sink(gap: DataGap) -> None:
            del gap

        supervisor = WebSocketSupervisor(
            factory, ({"type": "l2Book", "coin": "BTC"},),
            event_sink=event_sink, gap_sink=gap_sink,
            clock_ms=lambda: clock[0],
            utcnow=lambda: datetime(2026, 10, 17, tzinfo=UTC),
            stale_after_ms=5_000,
        )
        task = asyncio.create_task(supervisor._dispatch(_book(2_000)))
        await asyncio.wait_for(started.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert "l2Book:BTC" not in supervisor._last_exchange_time
        assert "l2Book:BTC" not in supervisor._l2_source_fresh_last
        assert "l2Book:BTC" not in supervisor._l2_last_unique_receive_ms
        assert supervisor.l2_delivery_diagnostics(
            now_ms=2_000
        )["l2_source_age_samples"] == 0
        assert not accepted

        should_block = False
        await supervisor._dispatch(_book(2_000))
        assert len(accepted) == 1
        assert supervisor._last_exchange_time["l2Book:BTC"] == 2_000
        assert supervisor.l2_delivery_diagnostics(
            now_ms=2_000
        )["l2_source_age_samples"] == 1

    asyncio.run(run())


@pytest.mark.parametrize(
    ("raw", "subscriptions", "expected_events"),
    [
        (
            {
                "channel": "trades",
                "data": [{
                    "coin": "BTC", "side": "B", "px": "100", "sz": "1",
                    "hash": "0x1", "time": 1_000, "tid": 1,
                    "users": ["a", "b"],
                }],
            },
            ({"type": "trades", "coin": "BTC"},),
            1,
        ),
        (
            {
                "channel": "allMids",
                "data": {"mids": {"BTC": "100", "ETH": "50"}},
            },
            ({"type": "allMids"},),
            2,
        ),
    ],
)
def test_session_normalization_delay_never_retimes_first_received_packet(
    raw: dict[str, object],
    subscriptions: tuple[dict[str, str], ...],
    expected_events: int,
) -> None:
    async def scenario() -> None:
        # The real packet has already been delivered by recv_json at 2s.
        # A slow normalize hook represents expensive future processing. A
        # second utcnow call inside normalization would falsely date the
        # raw original WS packet at 7s instead of the receipt at 2s.
        clock = [2_000]
        original = [2_000]
        events: list[StreamEvent] = []
        gaps: list[DataGap] = []

        class Connection:
            async def send_json(self, payload: object) -> None:
                del payload

            async def recv_json(self) -> dict[str, object]:
                return raw

        async def factory() -> object:
            raise AssertionError("no actual venue or network access")

        async def event_sink(event: StreamEvent) -> None:
            events.append(event)

        async def gap_sink(gap: DataGap) -> None:
            gaps.append(gap)

        def activity(phase: str, active: bool) -> None:
            if phase == "normalize_message" and active:
                clock[0] += 5_000
                original[0] += 5_000

        supervisor = WebSocketSupervisor(
            factory, subscriptions,
            event_sink=event_sink, gap_sink=gap_sink,
            clock_ms=lambda: clock[0],
            utcnow=lambda: datetime.fromtimestamp(original[0] / 1_000, UTC),
            activity_hook=activity,
            heartbeat_seconds=45,
        )
        await supervisor._session(Connection(), max_messages=1)
        assert len(events) == expected_events
        assert all(
            int(event.receive_time.timestamp() * 1_000) == 2_000
            for event in events
        )
        assert supervisor.health().last_server_message_ms == 2_000
        assert clock[0] == original[0] == 7_000
        assert not gaps
        assert all(
            supervisor._last_stream_message[
                "allMids" if expected_events == 2 else "trades:BTC"
            ] == 2_000
            for event in events
        )

    asyncio.run(scenario())


def test_direct_dispatch_retains_explicit_normalized_receive_clock() -> None:
    async def scenario() -> None:
        observed: list[StreamEvent] = []

        async def factory() -> object:
            raise AssertionError("no actual venue network")

        async def sink(event: StreamEvent) -> None:
            observed.append(event)

        supervisor = WebSocketSupervisor(
            factory, ({"type": "l2Book", "coin": "BTC"},),
            event_sink=sink,
            gap_sink=lambda gap: asyncio.sleep(0),
            clock_ms=lambda: 4_000,
            utcnow=lambda: datetime.fromtimestamp(4, UTC),
        )
        await supervisor._dispatch(
            _book(2_000),
            received_at_ms=3_000,
            received_at_utc=datetime.fromtimestamp(3, UTC),
        )
        assert len(observed) == 1
        assert int(observed[0].receive_time.timestamp() * 1_000) == 3_000
        assert supervisor._last_stream_message["l2Book:BTC"] == 3_000
        # The exchange timestamp is immutable and never projected forward.
        assert observed[0].exchange_time_ms == 2_000

    asyncio.run(scenario())
