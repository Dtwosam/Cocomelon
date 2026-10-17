"""A failed original aggregate gap OPEN must not disappear or allow recovery."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from cocomelon.domain.market import MarketId
from cocomelon.domain.stream import DataGap, StreamEvent, StreamKind
from cocomelon.evidence.redundant_stream import RedundantStreamMux

STREAM = "trades:BTC"
BASE = datetime(2026, 10, 17, tzinfo=UTC)
MARKET = MarketId("", "BTC")


def _trade(tid: int, exchange_ms: int, received_ms: int) -> StreamEvent:
    return StreamEvent(
        kind=StreamKind.TRADE,
        market=MARKET,
        exchange_time_ms=exchange_ms,
        receive_time=BASE + timedelta(milliseconds=received_ms),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key=f"trades:BTC:{exchange_ms}:{tid}",
        payload={
            "side": "B", "price": Decimal("100"), "size": Decimal("1"),
            "hash": f"0x{tid}", "tid": tid, "users": ("a", "b"),
        },
    )


def test_failed_open_must_be_retried_before_any_recovery_event() -> None:
    async def run() -> None:
        events: list[str] = []
        gaps: list[DataGap] = []
        offered_opens: list[DataGap] = []
        reject_once = True

        async def event_sink(event: StreamEvent) -> None:
            events.append(event.event_key)

        async def gap_sink(gap: DataGap) -> None:
            nonlocal reject_once
            if gap.reason == "redundant_disconnect":
                offered_opens.append(gap)
                if reject_once:
                    reject_once = False
                    raise OSError("original gap receipt disk write rejected")
            gaps.append(gap)

        mux = RedundantStreamMux(event_sink=event_sink, gap_sink=gap_sink)
        first = _trade(1, 1_000, 10)
        recovery = _trade(2, 3_000, 500)
        await mux.on_event(0, first)
        await mux.on_event(1, first)
        await mux.on_gap(0, DataGap(STREAM, 2_000, None, "disconnect"))
        with pytest.raises(OSError, match="disk write rejected"):
            await mux.on_gap(1, DataGap(STREAM, 2_100, None, "disconnect"))

        assert len(gaps) == 0
        assert mux._aggregate_gap_starts[STREAM] == 2_100
        assert STREAM in mux._uncommitted_aggregate_gap_opens
        assert mux.ingress_diagnostics()["uncommitted_aggregate_gap_open_count"] == 1
        assert events == [first.event_key]
        assert mux.ingress_diagnostics()["failed_calls"] == 1

        # First attempted follow-up is a genuine new market event. The
        # original OPEN gap must persist *before* any market observation
        # can be emitted, and its original timestamp is not changed.
        await mux.on_event(0, recovery)
        assert len(offered_opens) == 2
        assert offered_opens[0] == offered_opens[1]
        assert [g.reason for g in gaps] == ["redundant_disconnect"]
        assert gaps[0].started_ms == 2_100
        assert events == [first.event_key]
        assert STREAM not in mux._uncommitted_aggregate_gap_opens
        assert mux.ingress_diagnostics()["uncommitted_aggregate_gap_open_count"] == 0

        # Recovery only follows a real delivered original event, not an
        # optimistic marker or an unpersisted aggregate start.
        await mux.on_gap(0, DataGap(STREAM, 2_000, 2_500, "recovered"))
        assert events == [first.event_key, recovery.event_key]
        assert [g.reason for g in gaps] == ["redundant_disconnect", "recovered"]
        assert gaps[1].started_ms == 2_100
        assert mux._aggregate_gap_starts.get(STREAM) is None
        assert mux.ingress_diagnostics()["failed_calls"] == 1

    asyncio.run(run())


def test_repeated_gap_write_failures_block_new_events_and_close_markers() -> None:
    async def run() -> None:
        events: list[str] = []
        gaps: list[DataGap] = []
        attempts = 0
        should_fail = True

        async def event_sink(event: StreamEvent) -> None:
            events.append(event.event_key)

        async def gap_sink(gap: DataGap) -> None:
            nonlocal attempts
            if gap.reason == "redundant_disconnect":
                attempts += 1
                if should_fail:
                    raise OSError("original evidence unavailable")
            gaps.append(gap)

        mux = RedundantStreamMux(event_sink=event_sink, gap_sink=gap_sink)
        first = _trade(1, 1_000, 10)
        await mux.on_event(0, first)
        await mux.on_event(1, first)
        await mux.on_gap(0, DataGap(STREAM, 2_000, None, "disconnect"))
        with pytest.raises(OSError, match="original evidence unavailable"):
            await mux.on_gap(1, DataGap(STREAM, 2_100, None, "disconnect"))
        with pytest.raises(OSError, match="original evidence unavailable"):
            await mux.on_event(0, _trade(2, 3_000, 500))
        with pytest.raises(OSError, match="original evidence unavailable"):
            await mux.on_gap(0, DataGap(STREAM, 2_000, 2_500, "recovered"))

        assert attempts == 3
        assert events == [first.event_key]
        assert not gaps
        assert mux._aggregate_gap_starts[STREAM] == 2_100
        assert STREAM in mux._uncommitted_aggregate_gap_opens
        assert mux.ingress_diagnostics()["failed_calls"] == 3
        assert mux.ingress_diagnostics()["completed_calls"] == 3
        assert mux.ingress_diagnostics()["uncommitted_aggregate_gap_open_count"] == 1

        # Even if the recorder is repaired later, the original gap is
        # retried with its historical source start before accepting recovery.
        should_fail = False
        await mux.on_event(0, _trade(3, 3_500, 600))
        assert len(gaps) == 1
        assert gaps[0].started_ms == 2_100
        assert gaps[0].reason == "redundant_disconnect"

    asyncio.run(run())


def test_cancelled_open_write_remains_pending_until_exact_gap_is_durable() -> None:
    async def run() -> None:
        started = asyncio.Event()
        gaps: list[DataGap] = []
        events: list[str] = []
        initial_attempt: DataGap | None = None
        block = True

        async def event_sink(event: StreamEvent) -> None:
            events.append(event.event_key)

        async def gap_sink(gap: DataGap) -> None:
            nonlocal initial_attempt
            if gap.reason == "redundant_disconnect" and block:
                initial_attempt = gap
                started.set()
                await asyncio.Event().wait()
            gaps.append(gap)

        mux = RedundantStreamMux(event_sink=event_sink, gap_sink=gap_sink)
        first = _trade(1, 1_000, 10)
        await mux.on_event(0, first)
        await mux.on_event(1, first)
        await mux.on_gap(0, DataGap(STREAM, 2_000, None, "disconnect"))
        pending = asyncio.create_task(
            mux.on_gap(1, DataGap(STREAM, 2_100, None, "disconnect"))
        )
        await asyncio.wait_for(started.wait(), timeout=5)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert STREAM in mux._uncommitted_aggregate_gap_opens
        assert gaps == []
        block = False

        # A cancelled async callback cannot erase a genuine source gap.
        await mux.on_event(0, _trade(2, 3_000, 500))
        assert gaps == [initial_attempt]
        assert mux.ingress_diagnostics()["uncommitted_aggregate_gap_open_count"] == 0
        assert gaps[0].ended_ms is None
        assert STREAM not in mux._uncommitted_aggregate_gap_opens
        assert events == [first.event_key]

    asyncio.run(run())
