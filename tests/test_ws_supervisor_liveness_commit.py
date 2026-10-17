"""WS ingress liveness must not get credit for rejected original source writes."""
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


def test_rejected_new_original_event_cannot_refresh_source_stream_liveness() -> None:
    async def run() -> None:
        clock = [2_000]
        fail_once = True
        accepted: list[str] = []
        gaps: list[DataGap] = []

        async def factory() -> object:
            raise AssertionError("no network permitted")

        async def event_sink(event: StreamEvent) -> None:
            nonlocal fail_once
            if fail_once:
                fail_once = False
                raise OSError("source record rejected")
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
        with pytest.raises(RuntimeError, match="source record rejected"):
            await supervisor._dispatch(_book(2_000))
        assert "l2Book:BTC" not in supervisor._last_stream_message
        assert "l2Book:BTC" not in supervisor._last_exchange_time
        assert not accepted
        assert not gaps

        clock[0] = 2_500
        await supervisor._dispatch(_book(2_000))
        assert len(accepted) == 1
        assert supervisor._last_stream_message["l2Book:BTC"] == 2_500
        assert supervisor._last_exchange_time["l2Book:BTC"] == 2_000
        # A duplicate is a genuine transport observation: it may refresh
        # receipt liveness, not source exchange time or fresh-book coverage.
        clock[0] = 3_100
        await supervisor._dispatch(_book(2_000))
        assert len(accepted) == 1
        assert supervisor._last_stream_message["l2Book:BTC"] == 3_100
        assert supervisor._last_exchange_time["l2Book:BTC"] == 2_000
        assert supervisor.health.duplicate_count == 1
        assert not gaps

    asyncio.run(run())


def test_failed_out_of_order_gap_receipt_cannot_refresh_source_liveness() -> None:
    async def run() -> None:
        clock = [2_000]
        failed_once = False
        gaps: list[DataGap] = []

        async def factory() -> object:
            raise AssertionError("no network permitted")

        async def event_sink(event: StreamEvent) -> None:
            del event

        async def gap_sink(gap: DataGap) -> None:
            nonlocal failed_once
            if gap.reason == "out_of_order" and not failed_once:
                failed_once = True
                raise OSError("gap evidence unavailable")
            gaps.append(gap)

        supervisor = WebSocketSupervisor(
            factory, ({"type": "l2Book", "coin": "BTC"},),
            event_sink=event_sink, gap_sink=gap_sink,
            clock_ms=lambda: clock[0],
            utcnow=lambda: datetime(2026, 10, 17, tzinfo=UTC),
            stale_after_ms=5_000,
        )
        await supervisor._dispatch(_book(2_000))
        assert supervisor._last_stream_message["l2Book:BTC"] == 2_000

        clock[0] = 3_000
        with pytest.raises(RuntimeError, match="gap evidence unavailable"):
            await supervisor._dispatch(_book(1_500))
        assert supervisor._last_stream_message["l2Book:BTC"] == 2_000
        assert supervisor._last_exchange_time["l2Book:BTC"] == 2_000
        assert not gaps

        clock[0] = 3_100
        await supervisor._dispatch(_book(1_500))
        assert [g.reason for g in gaps] == ["out_of_order"]
        assert gaps[0].started_ms == 1_500
        assert gaps[0].ended_ms == 2_000
        assert supervisor._last_stream_message["l2Book:BTC"] == 3_100
        assert supervisor._last_exchange_time["l2Book:BTC"] == 2_000

    asyncio.run(run())


def test_cancelled_event_does_not_commit_liveness() -> None:
    async def run() -> None:
        started = asyncio.Event()
        should_block = True

        async def factory() -> object:
            raise AssertionError("no network permitted")

        async def event_sink(event: StreamEvent) -> None:
            del event
            if should_block:
                started.set()
                await asyncio.Event().wait()

        async def gap_sink(gap: DataGap) -> None:
            del gap

        supervisor = WebSocketSupervisor(
            factory, ({"type": "l2Book", "coin": "BTC"},),
            event_sink=event_sink, gap_sink=gap_sink,
            clock_ms=lambda: 2_000,
            utcnow=lambda: datetime(2026, 10, 17, tzinfo=UTC),
        )
        task = asyncio.create_task(supervisor._dispatch(_book(2_000)))
        await asyncio.wait_for(started.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not supervisor._last_stream_message
        should_block = False
        await supervisor._dispatch(_book(2_000))
        assert supervisor._last_stream_message["l2Book:BTC"] == 2_000

    asyncio.run(run())
