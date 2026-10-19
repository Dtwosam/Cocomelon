"""Failed standby backfill cannot be overtaken after lane promotion.

The original upstream receive/exchange times and data gaps remain unchanged.
This proves error/cancel behavior, not full market-data-source qualification.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from cocomelon.domain.market import MarketId
from cocomelon.domain.stream import DataGap, StreamEvent, StreamKind
from cocomelon.evidence.redundant_stream import RedundantStreamMux

BASE = datetime(2026, 10, 18, tzinfo=UTC)
STREAM = "trades:BTC"
MARKET = MarketId("", "BTC")


def _trade(index: int, receive_offset_ms: int) -> StreamEvent:
    exchange_ms = index * 1_000
    return StreamEvent(
        kind=StreamKind.TRADE,
        market=MARKET,
        exchange_time_ms=exchange_ms,
        receive_time=BASE + timedelta(milliseconds=receive_offset_ms),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key=f"trades:BTC:{exchange_ms}:{index}",
        payload={
            "side": "B", "price": Decimal("100"), "size": Decimal("1"),
            "hash": f"0x{index}", "tid": index, "users": ("a", "b"),
        },
    )


@pytest.mark.parametrize("cancel", [False, True], ids=["sink_error", "sink_cancel"])
def test_failed_standby_switch_retries_oldest_buffer_before_later_event(
    cancel: bool,
) -> None:
    async def run() -> None:
        first, second, third, fourth = (
            _trade(1, 100), _trade(2, 200),
            _trade(3, 300), _trade(4, 400),
        )
        admitted: list[StreamEvent] = []
        gaps: list[DataGap] = []
        attempts: list[str] = []
        deny_second = [True]

        async def event_sink(event: StreamEvent) -> None:
            attempts.append(event.event_key)
            if event == second and deny_second[0]:
                if cancel:
                    raise asyncio.CancelledError()
                raise OSError("standby source sink unavailable")
            admitted.append(event)

        async def gap_sink(gap: DataGap) -> None:
            gaps.append(gap)

        mux = RedundantStreamMux(event_sink=event_sink, gap_sink=gap_sink)
        await mux.on_event(0, first)
        await mux.on_event(1, first)
        await mux.on_event(1, second)
        await mux.on_event(1, third)
        original_receive_times = (
            second.receive_time, third.receive_time, fourth.receive_time,
        )
        expected_error = asyncio.CancelledError if cancel else OSError
        with pytest.raises(expected_error):
            await mux.on_gap(
                0, DataGap(STREAM, 350, None, "disconnect")
            )
        assert mux.active_lane(STREAM) == 1
        assert mux.failover_count == 1
        assert tuple(mux._buffers[(1, STREAM)]) == (second, third)
        assert admitted == [first]
        assert gaps == []

        # Previously active_lane already said standby=1, so _on_event
        # skipped its still-uncommitted queue and admitted event #4.
        # Repeated sink failure must never let #4 overtake #2.
        with pytest.raises(expected_error):
            await mux.on_event(1, fourth)
        assert admitted == [first]
        assert tuple(mux._buffers[(1, STREAM)]) == (second, third)
        assert attempts.count(second.event_key) == 2
        assert fourth.event_key not in attempts

        deny_second[0] = False
        await mux.on_event(1, fourth)
        assert admitted == [first, second, third, fourth]
        assert tuple(mux._buffers[(1, STREAM)]) == ()
        assert tuple(item.receive_time for item in admitted[1:]) == (
            original_receive_times
        )
        assert mux._last_emitted[STREAM] == fourth
        assert mux.failover_count == 1
        assert gaps == []

    asyncio.run(run())


@pytest.mark.parametrize("cancel", [False, True], ids=["sink_error", "sink_cancel"])
def test_pending_original_standby_backfill_precedes_subsequent_gap_marker(
    cancel: bool,
) -> None:
    async def run() -> None:
        first, second, third = (
            _trade(1, 100), _trade(2, 200), _trade(3, 300),
        )
        events: list[StreamEvent] = []
        gaps: list[DataGap] = []
        attempts: list[str] = []
        deny_second = [True]

        async def event_sink(event: StreamEvent) -> None:
            attempts.append(event.event_key)
            if event == second and deny_second[0]:
                if cancel:
                    raise asyncio.CancelledError()
                raise OSError("original backfill rejected")
            events.append(event)

        async def gap_sink(gap: DataGap) -> None:
            gaps.append(gap)

        mux = RedundantStreamMux(event_sink=event_sink, gap_sink=gap_sink)
        await mux.on_event(0, first)
        await mux.on_event(1, first)
        await mux.on_event(1, second)
        await mux.on_event(1, third)
        with pytest.raises(asyncio.CancelledError if cancel else OSError):
            await mux.on_gap(
                0, DataGap(STREAM, 350, None, "disconnect")
            )
        later_gap = DataGap(STREAM, 400, None, "disconnect")
        # A fresh disconnect cannot mark this already-active standby as
        # unavailable before its older buffered market rows are accepted.
        with pytest.raises(asyncio.CancelledError if cancel else OSError):
            await mux.on_gap(1, later_gap)
        assert mux._lane_gap_starts[STREAM] == {0: 350}
        assert events == [first]
        assert gaps == []
        deny_second[0] = False
        await mux.on_gap(1, later_gap)
        assert events == [first, second, third]
        assert gaps == [DataGap(STREAM, 400, None, "redundant_disconnect")]
        assert not mux._buffers[(1, STREAM)]
        assert mux._aggregate_gap_starts[STREAM] == 400

    asyncio.run(run())


def test_normal_standby_switch_still_emits_buffered_original_records_once() -> None:
    async def run() -> None:
        first, second, third = (
            _trade(1, 100), _trade(2, 200), _trade(3, 300),
        )
        events: list[StreamEvent] = []
        gaps: list[DataGap] = []

        async def event_sink(event: StreamEvent) -> None:
            events.append(event)

        async def gap_sink(gap: DataGap) -> None:
            gaps.append(gap)

        mux = RedundantStreamMux(event_sink=event_sink, gap_sink=gap_sink)
        await mux.on_event(0, first)
        await mux.on_event(1, first)
        await mux.on_event(1, second)
        await mux.on_gap(0, DataGap(STREAM, 250, None, "disconnect"))
        await mux.on_event(1, third)
        assert events == [first, second, third]
        assert not gaps
        assert mux.failover_count == 1
        assert mux._last_emitted[STREAM] == third

    asyncio.run(run())


def test_unseen_retrograde_standby_print_emits_negative_source_gap() -> None:
    async def run() -> None:
        newest = _trade(3, 300)
        delayed = _trade(2, 200)
        next_print = _trade(4, 400)
        originals: list[StreamEvent] = []
        gaps: list[DataGap] = []

        async def event_sink(event: StreamEvent) -> None:
            originals.append(event)

        async def gap_sink(gap: DataGap) -> None:
            gaps.append(gap)

        mux = RedundantStreamMux(event_sink=event_sink, gap_sink=gap_sink)
        await mux.on_event(0, newest)
        await mux.on_event(1, delayed)
        await mux.on_gap(0, DataGap(STREAM, 350, None, "disconnect"))
        assert originals == [newest]
        assert gaps == [DataGap(
            STREAM, delayed.exchange_time_ms, newest.exchange_time_ms,
            "redundant_unseen_retrograde",
        )]
        assert not mux._buffers[(1, STREAM)]
        assert mux.ingress_diagnostics()["retrograde_unseen_gap_count"] == 1
        assert mux.ingress_diagnostics()["uncommitted_retrograde_gap_count"] == 0
        assert delayed.event_key not in mux._seen_keys[STREAM]
        assert delayed.event_key in mux._retrograde_rejected_keys[STREAM]
        await mux.on_event(1, delayed)
        assert len(gaps) == 1
        await mux.on_event(1, next_print)
        assert originals == [newest, next_print]
        assert len(gaps) == 1

    asyncio.run(run())


@pytest.mark.parametrize("cancel", [False, True], ids=["sink_error", "sink_cancel"])
def test_retrograde_gap_failure_retries_exact_gap_before_newer_source(
    cancel: bool,
) -> None:
    async def run() -> None:
        newest, delayed, following = (
            _trade(3, 300), _trade(2, 200), _trade(4, 400),
        )
        originals: list[StreamEvent] = []
        attempts: list[DataGap] = []
        accepted_gaps: list[DataGap] = []
        fail = [True]

        async def event_sink(event: StreamEvent) -> None:
            originals.append(event)

        async def gap_sink(gap: DataGap) -> None:
            attempts.append(gap)
            if fail[0]:
                if cancel:
                    raise asyncio.CancelledError()
                raise OSError("retrograde gap ledger unavailable")
            accepted_gaps.append(gap)

        mux = RedundantStreamMux(event_sink=event_sink, gap_sink=gap_sink)
        await mux.on_event(0, newest)
        await mux.on_event(1, delayed)
        exc = asyncio.CancelledError if cancel else OSError
        with pytest.raises(exc):
            await mux.on_gap(0, DataGap(STREAM, 350, None, "disconnect"))
        assert mux.active_lane(STREAM) == 1
        assert originals == [newest]
        assert tuple(mux._buffers[(1, STREAM)]) == (delayed,)
        assert mux.ingress_diagnostics()["uncommitted_retrograde_gap_count"] == 1
        with pytest.raises(exc):
            await mux.on_event(1, following)
        assert len(attempts) == 2 and attempts[0] == attempts[1]
        assert originals == [newest]
        fail[0] = False
        await mux.on_event(1, following)
        assert accepted_gaps == [attempts[0]]
        assert originals == [newest, following]
        assert mux.ingress_diagnostics()["uncommitted_retrograde_gap_count"] == 0
        assert mux.ingress_diagnostics()["retrograde_unseen_gap_count"] == 1

    asyncio.run(run())


def test_exact_already_admitted_older_standby_copy_needs_no_negative_gap() -> None:
    async def run() -> None:
        earlier, newer = _trade(2, 200), _trade(3, 300)
        events: list[StreamEvent] = []
        gaps: list[DataGap] = []

        async def event_sink(event: StreamEvent) -> None:
            events.append(event)

        async def gap_sink(gap: DataGap) -> None:
            gaps.append(gap)

        mux = RedundantStreamMux(event_sink=event_sink, gap_sink=gap_sink)
        await mux.on_event(0, earlier)
        await mux.on_event(0, newer)
        await mux.on_event(1, earlier)
        await mux.on_gap(0, DataGap(STREAM, 350, None, "disconnect"))
        assert events == [earlier, newer]
        assert not gaps
        assert mux.ingress_diagnostics()["retrograde_unseen_gap_count"] == 0

    asyncio.run(run())
