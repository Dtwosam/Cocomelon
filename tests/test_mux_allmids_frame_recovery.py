"""Aggregate mux recovery must not split original allMids frame children.

These test source receipts are synthetic and grant NO 72h/after-cost
certification. Original receive times, gap starts, and source bytes win.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from cocomelon.domain.market import MarketId
from cocomelon.domain.stream import DataGap, StreamEvent, StreamKind
from cocomelon.evidence.redundant_stream import RedundantStreamMux
from cocomelon.hyperliquid.ws_protocol import normalize_ws_message
from cocomelon.hyperliquid.ws_supervisor import WebSocketSupervisor

FRAME = {"channel": "allMids", "data": {"mids": {"BTC": "100", "ETH": "50"}}}
RECEIVED_MS = 2_000
STREAM = "allMids"


def _frame() -> tuple[StreamEvent, ...]:
    return tuple(normalize_ws_message(
        FRAME, receive_time=datetime.fromtimestamp(RECEIVED_MS / 1_000, UTC),
    ))


async def _prepared_mux(
    event_sink, gap_sink,
) -> RedundantStreamMux:
    mux = RedundantStreamMux(
        event_sink=event_sink,
        gap_sink=gap_sink,
        defer_all_mids_aggregate_recovery=True,
    )
    # The earlier BTC mid is intentionally different: unchanged
    # receive-only mid updates inside the 1s semantic dedup window
    # are correctly suppressed and cannot be a recovery witness.
    initial = tuple(normalize_ws_message(
        {"channel": "allMids", "data": {"mids": {"BTC": "90"}}},
        receive_time=datetime.fromtimestamp(1, UTC),
    ))
    await mux.on_event(0, initial[0])
    await mux.on_event(1, initial[0])
    await mux.on_gap(0, DataGap(STREAM, 1_100, None, "disconnect"))
    await mux.on_gap(1, DataGap(STREAM, 1_200, None, "disconnect"))
    # Recovery notice alone is not replayable new original market evidence.
    await mux.on_gap(0, DataGap(STREAM, 1_100, 1_900, "recovered"))
    assert mux._aggregate_gap_starts[STREAM] == 1_200
    return mux


def test_mux_aggregate_recovery_follows_all_original_frame_children() -> None:
    async def run() -> None:
        timeline: list[StreamEvent | DataGap] = []

        async def event_sink(event: StreamEvent) -> None:
            timeline.append(event)

        async def gap_sink(gap: DataGap) -> None:
            timeline.append(gap)

        mux = await _prepared_mux(event_sink, gap_sink)
        timeline.clear()
        frame = _frame()
        await mux.on_event(0, frame[0])
        # Old mux emitted a wall-clock recovery here, before child #2.
        assert timeline == [frame[0]]
        assert STREAM in mux._aggregate_gap_starts
        await mux.on_event(0, frame[1])
        assert timeline == list(frame)
        await mux.complete_all_mids_frame(0, frame)
        assert timeline == [
            *frame, DataGap(STREAM, 1_200, RECEIVED_MS, "recovered"),
        ]
        assert STREAM not in mux._aggregate_gap_starts
        assert len({
            int(event.receive_time.timestamp() * 1_000)
            for event in frame
        }) == 1
        assert mux._all_mids_pending_witnesses == {}

    asyncio.run(run())


@pytest.mark.parametrize("cancel", [False, True], ids=["error", "cancel"])
def test_incomplete_mux_frame_cannot_heal_aggregate_gap(cancel: bool) -> None:
    async def run() -> None:
        timeline: list[StreamEvent | DataGap] = []
        reject_eth = [True]

        async def event_sink(event: StreamEvent) -> None:
            if event.market.coin == "ETH" and reject_eth[0]:
                if cancel:
                    raise asyncio.CancelledError()
                raise OSError("ETH original source write rejected")
            timeline.append(event)

        async def gap_sink(gap: DataGap) -> None:
            timeline.append(gap)

        mux = await _prepared_mux(event_sink, gap_sink)
        timeline.clear()
        frame = _frame()
        await mux.on_event(0, frame[0])
        with pytest.raises(asyncio.CancelledError if cancel else OSError):
            await mux.on_event(0, frame[1])
        assert timeline == [frame[0]]
        assert STREAM in mux._aggregate_gap_starts
        # Production frame completion is forbidden until every child has
        # been acknowledged. The supervisor callback tests this contract.
        reject_eth[0] = False
        await mux.on_event(0, frame[0])  # Genuine replay, duplicate.
        await mux.on_event(0, frame[1])
        await mux.complete_all_mids_frame(0, frame)
        assert timeline == [
            *frame, DataGap(STREAM, 1_200, RECEIVED_MS, "recovered"),
        ]

    asyncio.run(run())


def test_supervisor_frame_ack_is_post_children_and_deferred_mux_close() -> None:
    async def run() -> None:
        timeline: list[StreamEvent | DataGap] = []
        notifications: list[tuple[StreamEvent, ...]] = []

        async def event_sink(event: StreamEvent) -> None:
            timeline.append(event)

        async def gap_sink(gap: DataGap) -> None:
            timeline.append(gap)

        mux = await _prepared_mux(event_sink, gap_sink)
        timeline.clear()
        frame = _frame()

        async def connection():
            raise AssertionError("no network required")

        async def frame_ack(events: tuple[StreamEvent, ...]) -> None:
            if not notifications:
                # First callback follows both original equal-time children
                # BEFORE the mux has published aggregate recovery.
                assert tuple(timeline) == frame
            else:
                # An identical replay can receive a second frame-complete
                # callback, but may not re-emit either original child or
                # remove/re-publish the already persisted source gap.
                assert tuple(timeline) == (
                    *frame,
                    DataGap(STREAM, 1_200, RECEIVED_MS, "recovered"),
                )
            notifications.append(events)
            await mux.complete_all_mids_frame(0, events)

        supervisor = WebSocketSupervisor(
            connection,
            [{"type": "allMids"}],
            event_sink=lambda event: mux.on_event(0, event),
            gap_sink=lambda gap: mux.on_gap(0, gap),
            clock_ms=lambda: RECEIVED_MS,
            utcnow=lambda: datetime.fromtimestamp(RECEIVED_MS / 1_000, UTC),
            all_mids_frame_sink=frame_ack,
        )
        await supervisor._dispatch(FRAME)
        assert notifications == [frame]
        assert timeline == [
            *frame, DataGap(STREAM, 1_200, RECEIVED_MS, "recovered"),
        ]
        # A genuine replay cannot claim a second recovered receipt.
        await supervisor._dispatch(FRAME)
        assert len(timeline) == 3

    asyncio.run(run())


def test_supervisor_does_not_ack_failed_partial_frame() -> None:
    async def run() -> None:
        seen: list[str] = []
        frame_complete: list[tuple[StreamEvent, ...]] = []
        fail_eth = [True]

        async def connection():
            raise AssertionError("no network required")

        async def event_sink(event: StreamEvent) -> None:
            if event.market.coin == "ETH" and fail_eth[0]:
                raise OSError("original journal ETH failed")
            seen.append(event.market.coin)

        async def frame_sink(events: tuple[StreamEvent, ...]) -> None:
            frame_complete.append(events)

        supervisor = WebSocketSupervisor(
            connection,
            [{"type": "allMids"}],
            event_sink=event_sink,
            gap_sink=lambda gap: asyncio.sleep(0),
            clock_ms=lambda: RECEIVED_MS,
            utcnow=lambda: datetime.fromtimestamp(RECEIVED_MS / 1_000, UTC),
            all_mids_frame_sink=frame_sink,
        )
        with pytest.raises(RuntimeError, match="ETH failed"):
            await supervisor._dispatch(FRAME)
        assert seen == ["BTC"]
        assert frame_complete == []
        fail_eth[0] = False
        await supervisor._dispatch(FRAME)
        assert seen == ["BTC", "ETH"]
        assert frame_complete == [_frame()]

    asyncio.run(run())


def test_paper_wires_full_frame_boundary_with_live_orders_still_disabled() -> None:
    from pathlib import Path

    worker = (
        Path(__file__).resolve().parents[1]
        / "src/cocomelon/continuous_paper.py"
    ).read_text(encoding="utf-8")
    assert "defer_all_mids_aggregate_recovery=True" in worker
    assert "await mux.complete_all_mids_frame(" in worker
    assert "after_frame_sink=finish_named_recovery" in worker
    assert "all_mids_frame_sink=lane_all_mids_frame_sink" in worker
    assert "await pump.process(_record_from_stream(event))" in worker


def test_guarded_complete_frame_blocks_newer_other_stream_between_children() -> None:
    async def run() -> None:
        timeline: list[StreamEvent | DataGap] = []
        btc_written = asyncio.Event()
        let_eth_continue = asyncio.Event()
        frame = _frame()

        async def event_sink(event: StreamEvent) -> None:
            timeline.append(event)
            if event.event_key == frame[0].event_key:
                btc_written.set()
                await let_eth_continue.wait()

        async def gap_sink(gap: DataGap) -> None:
            timeline.append(gap)

        mux = await _prepared_mux(event_sink, gap_sink)
        timeline.clear()

        async def connection():
            raise AssertionError("no network required")

        async def frame_complete(events: tuple[StreamEvent, ...]) -> None:
            await mux.complete_all_mids_frame(0, events)

        supervisor = WebSocketSupervisor(
            connection,
            [{"type": "allMids"}],
            event_sink=lambda event: mux.on_event(0, event),
            gap_sink=lambda gap: mux.on_gap(0, gap),
            clock_ms=lambda: RECEIVED_MS,
            utcnow=lambda: datetime.fromtimestamp(RECEIVED_MS / 1_000, UTC),
            all_mids_frame_sink=frame_complete,
            all_mids_frame_dispatch_guard=(
                lambda events, dispatch:
                mux.serialize_all_mids_frame_dispatch(0, events, dispatch)
            ),
        )
        frame_task = asyncio.create_task(supervisor._dispatch(FRAME))
        await asyncio.wait_for(btc_written.wait(), timeout=3)
        later = StreamEvent(
            kind=StreamKind.L2_BOOK,
            market=MarketId("", "BTC"),
            exchange_time_ms=2_400,
            receive_time=datetime.fromtimestamp(2.4, UTC),
            schema_version=1,
            source="hyperliquid-mainnet-ws",
            event_key="later-BTC-book",
            payload={"bids": (), "asks": ()},
        )
        later_task = asyncio.create_task(mux.on_event(0, later))
        await asyncio.sleep(0)
        # The whole allMids frame holds the receipt-order lock. A later
        # market event from a concurrent task cannot divide same-time kids.
        assert timeline == [frame[0]]
        assert not later_task.done()
        let_eth_continue.set()
        await asyncio.wait_for(asyncio.gather(frame_task, later_task), timeout=3)
        assert timeline == [
            *frame,
            DataGap(STREAM, 1_200, RECEIVED_MS, "recovered"),
            later,
        ]
        assert mux._frame_owner_task is None
        assert mux.ingress_diagnostics()["active_waiters"] == 0

    asyncio.run(run())


@pytest.mark.parametrize("cancel", [False, True], ids=["exception", "cancellation"])
def test_guarded_partial_frame_releases_lock_without_claiming_recovery(
    cancel: bool,
) -> None:
    async def run() -> None:
        seen: list[str] = []
        failures = [True]
        frame_completions = []

        async def event_sink(event: StreamEvent) -> None:
            if event.market.coin == "ETH" and failures[0]:
                if cancel:
                    raise asyncio.CancelledError()
                raise OSError("source write unavailable")
            seen.append(event.market.coin)

        mux = await _prepared_mux(event_sink, lambda gap: asyncio.sleep(0))
        seen.clear()

        async def connection():
            raise AssertionError("no network required")

        async def frame_complete(events: tuple[StreamEvent, ...]) -> None:
            frame_completions.append(events)
            await mux.complete_all_mids_frame(0, events)

        supervisor = WebSocketSupervisor(
            connection,
            [{"type": "allMids"}],
            event_sink=lambda event: mux.on_event(0, event),
            gap_sink=lambda gap: mux.on_gap(0, gap),
            clock_ms=lambda: RECEIVED_MS,
            utcnow=lambda: datetime.fromtimestamp(RECEIVED_MS / 1_000, UTC),
            all_mids_frame_sink=frame_complete,
            all_mids_frame_dispatch_guard=(
                lambda events, dispatch:
                mux.serialize_all_mids_frame_dispatch(0, events, dispatch)
            ),
        )
        expected = asyncio.CancelledError if cancel else RuntimeError
        with pytest.raises(expected):
            await supervisor._dispatch(FRAME)
        assert seen == ["BTC"]
        assert frame_completions == []
        assert mux._frame_owner_task is None
        assert STREAM in mux._aggregate_gap_starts
        failures[0] = False
        # Retrying the real frame should not deadlock or create a false
        # second BTC source observation after it was already acknowledged.
        await asyncio.wait_for(supervisor._dispatch(FRAME), timeout=3)
        assert seen == ["BTC", "ETH"]
        assert frame_completions == [_frame()]
        assert STREAM not in mux._aggregate_gap_starts
        assert mux._frame_owner_task is None

    asyncio.run(run())


def test_original_allmids_frame_guard_is_production_wired() -> None:
    from pathlib import Path

    worker = (
        Path(__file__).resolve().parents[1]
        / "src/cocomelon/continuous_paper.py"
    ).read_text(encoding="utf-8")
    assert "all_mids_frame_dispatch_guard=lane_frame_dispatch_guard" in worker
    assert "await mux.serialize_all_mids_frame_dispatch(" in worker
    assert "all_mids_frame_sink=lane_all_mids_frame_sink" in worker
