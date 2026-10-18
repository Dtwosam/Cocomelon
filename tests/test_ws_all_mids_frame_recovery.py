"""A recovery receipt must not split children of one original allMids frame."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from cocomelon.domain.stream import DataGap, StreamEvent
from cocomelon.hyperliquid.ws_client import WsConnection
from cocomelon.hyperliquid.ws_protocol import normalize_ws_message
from cocomelon.hyperliquid.ws_supervisor import WebSocketSupervisor

FRAME = {"channel": "allMids", "data": {"mids": {"BTC": "100", "ETH": "50"}}}
RECEIVED_MS = 2_000


def test_recovery_follows_all_children_without_changing_original_clocks() -> None:
    async def run() -> None:
        now = [1_000]
        timeline: list[StreamEvent | DataGap] = []
        observed: list[int] = []

        async def connection() -> WsConnection:
            raise AssertionError("no network expected")

        async def event_sink(event: StreamEvent) -> None:
            timeline.append(event)
            observed.append(int(event.receive_time.timestamp() * 1_000))
            now[0] += 7

        async def gap_sink(gap: DataGap) -> None:
            timeline.append(gap)
            observed.append(now[0])

        supervisor = WebSocketSupervisor(
            connection, [{"type": "allMids"}],
            event_sink=event_sink, gap_sink=gap_sink,
            clock_ms=lambda: now[0],
            utcnow=lambda: datetime.fromtimestamp(RECEIVED_MS / 1_000, UTC),
        )
        await supervisor._open_disconnect_gaps(now[0])
        timeline.clear()
        observed.clear()
        now[0] = RECEIVED_MS
        await supervisor._dispatch(FRAME)

        assert [type(item) for item in timeline] == [StreamEvent, StreamEvent, DataGap]
        children = [item for item in timeline if isinstance(item, StreamEvent)]
        assert children == normalize_ws_message(
            FRAME, receive_time=datetime.fromtimestamp(RECEIVED_MS / 1_000, UTC),
        )
        assert [int(item.receive_time.timestamp() * 1_000) for item in children] == [
            RECEIVED_MS, RECEIVED_MS,
        ]
        recovery = timeline[-1]
        assert isinstance(recovery, DataGap)
        assert recovery == DataGap("allMids", 1_000, RECEIVED_MS, "recovered")
        assert observed == [RECEIVED_MS, RECEIVED_MS, RECEIVED_MS + 14]

        # An exact redelivery may neither repeat the accepted children nor
        # manufacture another recovered receipt.
        await supervisor._dispatch(FRAME)
        assert len(timeline) == 3

    asyncio.run(run())


@pytest.mark.parametrize("cancel", [False, True], ids=["sink_failure", "sink_cancel"])
def test_incomplete_frame_keeps_gap_open_until_remaining_child_is_accepted(
    cancel: bool,
) -> None:
    async def run() -> None:
        accepted: list[StreamEvent] = []
        gaps: list[DataGap] = []
        fail_eth = [True]

        async def connection() -> WsConnection:
            raise AssertionError("no network expected")

        async def event_sink(event: StreamEvent) -> None:
            if event.market.canonical == "ETH" and fail_eth[0]:
                if cancel:
                    raise asyncio.CancelledError()
                raise RuntimeError("ETH sink unavailable")
            accepted.append(event)

        async def gap_sink(gap: DataGap) -> None:
            gaps.append(gap)

        supervisor = WebSocketSupervisor(
            connection, [{"type": "allMids"}],
            event_sink=event_sink, gap_sink=gap_sink,
            clock_ms=lambda: RECEIVED_MS,
            utcnow=lambda: datetime.fromtimestamp(RECEIVED_MS / 1_000, UTC),
        )
        await supervisor._open_disconnect_gaps(1_000)
        expected_error = asyncio.CancelledError if cancel else RuntimeError
        with pytest.raises(expected_error):
            await supervisor._dispatch(FRAME)
        assert [event.market.canonical for event in accepted] == ["BTC"]
        assert gaps == [DataGap("allMids", 1_000, None, "disconnect")]
        assert "allMids" in supervisor._open_gaps

        fail_eth[0] = False
        await supervisor._dispatch(FRAME)
        assert [event.market.canonical for event in accepted] == ["BTC", "ETH"]
        assert gaps == [
            DataGap("allMids", 1_000, None, "disconnect"),
            DataGap("allMids", 1_000, RECEIVED_MS, "recovered"),
        ]
        assert "allMids" not in supervisor._open_gaps

    asyncio.run(run())


def test_normal_frame_preserves_every_normalized_child() -> None:
    async def run() -> None:
        events: list[StreamEvent] = []
        gaps: list[DataGap] = []

        async def connection() -> WsConnection:
            raise AssertionError("no network expected")

        async def event_sink(event: StreamEvent) -> None:
            events.append(event)

        async def gap_sink(gap: DataGap) -> None:
            gaps.append(gap)

        received = datetime.fromtimestamp(RECEIVED_MS / 1_000, UTC)
        supervisor = WebSocketSupervisor(
            connection, [{"type": "allMids"}],
            event_sink=event_sink, gap_sink=gap_sink,
            clock_ms=lambda: RECEIVED_MS, utcnow=lambda: received,
        )
        await supervisor._dispatch(FRAME)
        assert events == normalize_ws_message(FRAME, receive_time=received)
        assert gaps == []

    asyncio.run(run())


@pytest.mark.parametrize("cancel", [False, True], ids=["gap_failure", "gap_cancel"])
def test_failed_recovery_receipt_retries_after_full_frame_without_reemitting_children(
    cancel: bool,
) -> None:
    async def run() -> None:
        events: list[StreamEvent] = []
        attempts: list[DataGap] = []
        fail_recovery = [True]

        async def connection() -> WsConnection:
            raise AssertionError("no network expected")

        async def event_sink(event: StreamEvent) -> None:
            events.append(event)

        async def gap_sink(gap: DataGap) -> None:
            if gap.reason == "recovered":
                attempts.append(gap)
                if fail_recovery[0]:
                    if cancel:
                        raise asyncio.CancelledError()
                    raise RuntimeError("recovery sink unavailable")

        received = datetime.fromtimestamp(RECEIVED_MS / 1_000, UTC)
        supervisor = WebSocketSupervisor(
            connection, [{"type": "allMids"}],
            event_sink=event_sink, gap_sink=gap_sink,
            clock_ms=lambda: RECEIVED_MS, utcnow=lambda: received,
        )
        await supervisor._open_disconnect_gaps(1_000)
        expected_error = asyncio.CancelledError if cancel else RuntimeError
        with pytest.raises(expected_error):
            await supervisor._dispatch(FRAME)
        assert events == normalize_ws_message(FRAME, receive_time=received)
        original_recovery = DataGap("allMids", 1_000, RECEIVED_MS, "recovered")
        assert attempts == [original_recovery]
        assert "allMids" in supervisor._open_gaps

        fail_recovery[0] = False
        await supervisor._dispatch(FRAME)
        assert events == normalize_ws_message(FRAME, receive_time=received)
        assert attempts == [original_recovery, original_recovery]
        assert "allMids" not in supervisor._open_gaps

    asyncio.run(run())


@pytest.mark.parametrize("cancel", [False, True], ids=["mixed_failure", "mixed_cancel"])
def test_mixed_namespace_retry_closes_both_original_frame_streams(cancel: bool) -> None:
    async def run() -> None:
        frame = {
            "channel": "allMids",
            "data": {"mids": {"BTC": "100", "xyz:ABC": "50"}},
        }
        now = [RECEIVED_MS]
        fail_xyz = [True]
        events: list[StreamEvent] = []
        gaps: list[DataGap] = []
        timeline: list[StreamEvent | DataGap] = []

        async def connection() -> WsConnection:
            raise AssertionError("no network expected")

        async def event_sink(event: StreamEvent) -> None:
            if event.market.dex == "xyz" and fail_xyz[0]:
                if cancel:
                    raise asyncio.CancelledError()
                raise RuntimeError("xyz sink unavailable")
            events.append(event)
            timeline.append(event)

        async def gap_sink(gap: DataGap) -> None:
            gaps.append(gap)
            timeline.append(gap)

        received = datetime.fromtimestamp(RECEIVED_MS / 1_000, UTC)
        supervisor = WebSocketSupervisor(
            connection, [{"type": "allMids"}, {"type": "allMids", "dex": "xyz"}],
            event_sink=event_sink, gap_sink=gap_sink,
            clock_ms=lambda: now[0], utcnow=lambda: received,
        )
        await supervisor._open_disconnect_gaps(1_000)
        timeline.clear()
        expected_error = asyncio.CancelledError if cancel else RuntimeError
        with pytest.raises(expected_error):
            await supervisor._dispatch(frame)
        assert [event.market.canonical for event in events] == ["BTC"]
        assert not [gap for gap in gaps if gap.reason == "recovered"]
        assert set(supervisor._open_gaps) == {"allMids", "allMids:xyz"}

        fail_xyz[0] = False
        now[0] = RECEIVED_MS
        await supervisor._dispatch(frame)
        assert events == normalize_ws_message(frame, receive_time=received)
        assert [type(item) for item in timeline] == [
            StreamEvent, StreamEvent, DataGap, DataGap,
        ]
        assert [gap for gap in gaps if gap.reason == "recovered"] == [
            DataGap("allMids", 1_000, RECEIVED_MS, "recovered"),
            DataGap("allMids:xyz", 1_000, RECEIVED_MS, "recovered"),
        ]
        assert supervisor._open_gaps == {}

    asyncio.run(run())


def test_duplicate_predating_new_disconnect_cannot_recover_the_new_gap() -> None:
    async def run() -> None:
        events: list[StreamEvent] = []
        gaps: list[DataGap] = []
        now = [RECEIVED_MS]

        async def connection() -> WsConnection:
            raise AssertionError("no network expected")

        async def event_sink(event: StreamEvent) -> None:
            events.append(event)

        async def gap_sink(gap: DataGap) -> None:
            gaps.append(gap)

        received = datetime.fromtimestamp(RECEIVED_MS / 1_000, UTC)
        supervisor = WebSocketSupervisor(
            connection, [{"type": "allMids"}],
            event_sink=event_sink, gap_sink=gap_sink,
            clock_ms=lambda: now[0], utcnow=lambda: received,
        )
        await supervisor._dispatch(FRAME)
        now[0] = 3_000
        await supervisor._open_disconnect_gaps(now[0])
        now[0] = 4_000
        await supervisor._dispatch(FRAME)
        assert events == normalize_ws_message(FRAME, receive_time=received)
        assert gaps == [DataGap("allMids", 3_000, None, "disconnect")]
        assert supervisor._open_gaps == {
            "allMids": DataGap("allMids", 3_000, None, "disconnect"),
        }

    asyncio.run(run())
