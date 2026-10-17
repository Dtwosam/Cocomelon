"""Concurrent redundant WS lanes must not leapfrog awaited original events."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cocomelon.domain.market import MarketId
from cocomelon.domain.stream import DataGap, StreamEvent, StreamKind
from cocomelon.evidence.redundant_stream import RedundantStreamMux

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


def test_same_stream_concurrent_callbacks_cannot_overtake_awaited_sink() -> None:
    async def run() -> None:
        delivered: list[str] = []
        waiting = asyncio.Event()
        release = asyncio.Event()
        gaps: list[DataGap] = []
        first = _trade(1, 1000, 100)
        second = _trade(2, 2000, 200)
        third = _trade(3, 3000, 300)

        async def event_sink(event: StreamEvent) -> None:
            if event.event_key == second.event_key:
                waiting.set()
                await release.wait()
            delivered.append(event.event_key)

        async def gap_sink(gap: DataGap) -> None:
            gaps.append(gap)

        mux = RedundantStreamMux(event_sink=event_sink, gap_sink=gap_sink)
        await mux.on_event(0, first)
        second_task = asyncio.create_task(mux.on_event(0, second))
        await asyncio.wait_for(waiting.wait(), timeout=5)
        # A concurrent callback enters while the second event has not
        # finished its sink. Without a lock, the third delivery overtakes.
        third_task = asyncio.create_task(mux.on_event(0, third))
        await asyncio.sleep(0)
        assert not third_task.done()
        assert delivered == [first.event_key]
        inflight = mux.ingress_diagnostics()
        assert inflight["serialization_enabled"] is True
        assert inflight["active_waiters"] == 2
        assert inflight["peak_waiters"] == 2
        assert inflight["contended_calls"] == 1
        assert inflight["source_gap_or_paper_promotion_authority"] is False
        release.set()
        await asyncio.wait_for(
            asyncio.gather(second_task, third_task), timeout=5
        )
        assert delivered == [
            first.event_key, second.event_key, third.event_key,
        ]
        assert mux._last_emitted["trades:BTC"].event_key == third.event_key
        assert mux.ingress_diagnostics()["active_waiters"] == 0
        assert mux.ingress_diagnostics()["completed_calls"] == 3
        assert mux.ingress_diagnostics()["max_lock_wait_ms"] >= 0
        assert mux.ingress_diagnostics()["max_lock_hold_ms"] >= 0
        assert not gaps

    asyncio.run(run())


def test_lane_disconnect_cannot_flush_standby_ahead_of_inflight_emit() -> None:
    async def run() -> None:
        delivered: list[str] = []
        gaps: list[DataGap] = []
        waiting = asyncio.Event()
        release = asyncio.Event()
        first = _trade(1, 1000, 100)
        second = _trade(2, 2000, 200)
        third = _trade(3, 3000, 300)

        async def event_sink(event: StreamEvent) -> None:
            if event.event_key == second.event_key:
                waiting.set()
                await release.wait()
            delivered.append(event.event_key)

        async def gap_sink(gap: DataGap) -> None:
            gaps.append(gap)

        mux = RedundantStreamMux(event_sink=event_sink, gap_sink=gap_sink)
        await mux.on_event(0, first)
        await mux.on_event(1, first)
        await mux.on_event(1, third)
        second_task = asyncio.create_task(mux.on_event(0, second))
        await asyncio.wait_for(waiting.wait(), timeout=5)

        # The primary-lane disconnect races with an unfinished original
        # event write. Do not flush standby into the same source stream yet.
        switch_task = asyncio.create_task(
            mux.on_gap(
                0, DataGap("trades:BTC", 350, None, "disconnect"),
            )
        )
        await asyncio.sleep(0)
        assert not switch_task.done()
        assert mux.failover_count == 0
        assert delivered == [first.event_key]
        assert mux.ingress_diagnostics()["contended_calls"] == 1

        release.set()
        await asyncio.wait_for(
            asyncio.gather(second_task, switch_task), timeout=5
        )
        assert delivered == [
            first.event_key, second.event_key, third.event_key,
        ]
        assert mux.failover_count == 1
        assert mux.active_lane("trades:BTC") == 1
        assert mux._last_emitted["trades:BTC"].event_key == third.event_key
        assert gaps == []

    asyncio.run(run())


def test_failed_pending_delivery_does_not_allow_concurrent_gap_switch() -> None:
    async def run() -> None:
        waiting = asyncio.Event()
        release = asyncio.Event()
        gaps: list[DataGap] = []
        first = _trade(1, 1000, 100)
        rejected = _trade(2, 2000, 200)

        async def event_sink(event: StreamEvent) -> None:
            if event.event_key == rejected.event_key:
                waiting.set()
                await release.wait()
                raise RuntimeError("original durable receipt rejected")

        async def gap_sink(gap: DataGap) -> None:
            gaps.append(gap)

        mux = RedundantStreamMux(event_sink=event_sink, gap_sink=gap_sink)
        await mux.on_event(0, first)
        await mux.on_event(1, first)
        bad_task = asyncio.create_task(mux.on_event(0, rejected))
        await asyncio.wait_for(waiting.wait(), timeout=5)
        gap_task = asyncio.create_task(
            mux.on_gap(0, DataGap("trades:BTC", 250, None, "disconnect"))
        )
        await asyncio.sleep(0)
        assert not gap_task.done()
        assert mux.failover_count == 0
        release.set()
        try:
            await asyncio.wait_for(bad_task, timeout=5)
        except RuntimeError as exc:
            assert str(exc) == "original durable receipt rejected"
        else:
            raise AssertionError("durable sink failure must propagate")
        await asyncio.wait_for(gap_task, timeout=5)
        assert mux._last_emitted["trades:BTC"].event_key == first.event_key
        assert mux.active_lane("trades:BTC") == 1
        metrics = mux.ingress_diagnostics()
        assert metrics["failed_calls"] == 1
        assert metrics["contended_calls"] == 1
        assert metrics["completed_calls"] == 3
        assert metrics["active_waiters"] == 0
        assert not gaps

    asyncio.run(run())
