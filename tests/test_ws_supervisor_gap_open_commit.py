"""WS supervisor may never heal a source gap whose OPEN write was not durable."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from cocomelon.domain.stream import DataGap, StreamEvent
from cocomelon.hyperliquid.ws_supervisor import WebSocketSupervisor


def _trade(tid: int, at: int) -> dict[str, object]:
    return {
        "channel": "trades",
        "data": [{
            "coin": "BTC", "side": "B", "px": "100", "sz": "1",
            "hash": "0x1", "time": at, "tid": tid, "users": ["a", "b"],
        }],
    }


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


def test_failed_disconnect_open_blocks_source_events_until_exact_retry() -> None:
    async def run() -> None:
        events: list[str] = []
        gaps: list[DataGap] = []
        attempted: list[DataGap] = []
        fail_next = [2]
        now_ms = [3_000]

        async def event_sink(event: StreamEvent) -> None:
            events.append(event.event_key)

        async def gap_sink(gap: DataGap) -> None:
            if gap.reason == "disconnect":
                attempted.append(gap)
                if fail_next[0] > 0:
                    fail_next[0] -= 1
                    raise OSError("durable source gap unavailable")
            gaps.append(gap)

        async def factory() -> object:
            raise AssertionError("no network permitted")

        supervisor = WebSocketSupervisor(
            factory, ({"type": "trades", "coin": "BTC"},),
            event_sink=event_sink, gap_sink=gap_sink,
            clock_ms=lambda: now_ms[0],
            utcnow=lambda: datetime(2026, 10, 17, tzinfo=UTC),
        )
        with pytest.raises(RuntimeError, match="durable source gap unavailable"):
            await supervisor._open_disconnect_gaps(2_000)
        assert len(gaps) == 0
        assert "trades:BTC" in supervisor._uncommitted_open_gaps
        assert supervisor._open_gaps["trades:BTC"].started_ms == 2_000
        assert supervisor.l2_delivery_diagnostics(
            now_ms=3_000
        )["uncommitted_source_gap_open_count"] == 1

        with pytest.raises(RuntimeError, match="durable source gap unavailable"):
            await supervisor._dispatch(_trade(1, 3_000))
        assert events == []
        assert not supervisor._recent_key_sets["trades:BTC"]
        assert len(attempted) == 2
        assert attempted[0] == attempted[1]
        assert "trades:BTC" in supervisor._uncommitted_open_gaps

        # Only the original OPEN succeeding makes a later original event
        # and eventual recovery record eligible; no backdated price exists.
        await supervisor._dispatch(_trade(1, 3_000))
        assert attempted == [attempted[0]] * 3
        assert events == ["trades:BTC:3000:1"]
        assert [g.reason for g in gaps] == ["disconnect", "recovered"]
        assert gaps[0].started_ms == 2_000
        assert gaps[1].started_ms == 2_000
        assert not supervisor._open_gaps
        assert not supervisor._uncommitted_open_gaps
        assert supervisor.l2_delivery_diagnostics(
            now_ms=3_000
        )["uncommitted_source_gap_open_count"] == 0

    asyncio.run(run())


def test_failed_stale_l2_open_is_retried_at_same_threshold() -> None:
    async def run() -> None:
        events: list[str] = []
        gaps: list[DataGap] = []
        attempts: list[DataGap] = []
        fail_once = True
        now_ms = [3_200]

        async def event_sink(event: StreamEvent) -> None:
            events.append(event.event_key)

        async def gap_sink(gap: DataGap) -> None:
            nonlocal fail_once
            if gap.reason == "stale":
                attempts.append(gap)
                if fail_once:
                    fail_once = False
                    raise OSError("L2 stale OPEN rejected")
            gaps.append(gap)

        async def factory() -> object:
            raise AssertionError("no network permitted")

        supervisor = WebSocketSupervisor(
            factory, ({"type": "l2Book", "coin": "BTC"},),
            event_sink=event_sink, gap_sink=gap_sink,
            clock_ms=lambda: now_ms[0],
            utcnow=lambda: datetime(2026, 10, 17, tzinfo=UTC),
            stale_after_ms=1_000,
        )
        supervisor._last_stream_message["l2Book:BTC"] = 1_000
        with pytest.raises(RuntimeError, match="L2 stale OPEN rejected"):
            await supervisor._open_l2_stale_gaps_if_needed(2_500)
        assert supervisor._open_gaps["l2Book:BTC"].started_ms == 2_000
        assert supervisor.l2_delivery_diagnostics(
            now_ms=2_500
        )["uncommitted_source_gap_open_count"] == 1

        await supervisor._open_l2_stale_gaps_if_needed(2_800)
        assert len(attempts) == 2
        assert attempts[0] == attempts[1]
        assert gaps == [attempts[0]]
        assert supervisor.l2_delivery_diagnostics(
            now_ms=2_800
        )["uncommitted_source_gap_open_count"] == 0

        await supervisor._dispatch(_book(3_000))
        assert len(events) == 1
        assert [g.reason for g in gaps] == ["stale", "recovered"]
        assert gaps[1].started_ms == 2_000
        assert not supervisor._open_gaps

    asyncio.run(run())


def test_cancelled_supervisor_gap_open_still_requires_durable_retry() -> None:
    async def run() -> None:
        started = asyncio.Event()
        attempted: list[DataGap] = []
        gaps: list[DataGap] = []
        events: list[str] = []
        should_block = True

        async def event_sink(event: StreamEvent) -> None:
            events.append(event.event_key)

        async def gap_sink(gap: DataGap) -> None:
            if gap.reason == "disconnect":
                attempted.append(gap)
                if should_block:
                    started.set()
                    await asyncio.Event().wait()
            gaps.append(gap)

        async def factory() -> object:
            raise AssertionError("no network permitted")

        supervisor = WebSocketSupervisor(
            factory, ({"type": "trades", "coin": "BTC"},),
            event_sink=event_sink, gap_sink=gap_sink,
            clock_ms=lambda: 3_500,
            utcnow=lambda: datetime(2026, 10, 17, tzinfo=UTC),
        )
        task = asyncio.create_task(supervisor._open_disconnect_gaps(2_100))
        await asyncio.wait_for(started.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not gaps
        assert "trades:BTC" in supervisor._uncommitted_open_gaps

        should_block = False
        await supervisor._dispatch(_trade(1, 3_000))
        assert len(attempted) == 2
        assert attempted[0] == attempted[1]
        assert [g.reason for g in gaps] == ["disconnect", "recovered"]
        assert events == ["trades:BTC:3000:1"]
        assert not supervisor._uncommitted_open_gaps

    asyncio.run(run())
