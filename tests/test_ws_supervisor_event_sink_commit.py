"""A failed or cancelled WS event write may not become a dedup receipt.

Source recovery remains tied to a successfully delivered original event;
an uncertain write is retried at least once if a genuine redelivery arrives.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from cocomelon.domain.stream import DataGap, StreamEvent
from cocomelon.hyperliquid.ws_supervisor import WebSocketSupervisor


def _trade() -> dict[str, object]:
    return {
        "channel": "trades",
        "data": [{
            "coin": "BTC", "side": "B", "px": "100", "sz": "1",
            "hash": "0x1", "time": 2_000, "tid": 1, "users": ["a", "b"],
        }],
    }


def _book() -> dict[str, object]:
    return {
        "channel": "l2Book",
        "data": {
            "coin": "BTC",
            "levels": [
                [{"n": 1, "px": "99", "sz": "1"}],
                [{"n": 1, "px": "101", "sz": "1"}],
            ],
            "time": 2_000,
        },
    }


def test_rejected_trade_sink_does_not_commit_key_or_heal_gap() -> None:
    async def run() -> None:
        events: list[str] = []
        gaps: list[DataGap] = []
        fail_once = True

        async def factory() -> object:
            raise AssertionError("no network permitted")

        async def event_sink(event: StreamEvent) -> None:
            nonlocal fail_once
            if fail_once:
                fail_once = False
                raise OSError("durable event write rejected")
            events.append(event.event_key)

        async def gap_sink(gap: DataGap) -> None:
            gaps.append(gap)

        supervisor = WebSocketSupervisor(
            factory, ({"type": "trades", "coin": "BTC"},),
            event_sink=event_sink, gap_sink=gap_sink,
            clock_ms=lambda: 2_000,
            utcnow=lambda: datetime(2026, 10, 17, tzinfo=UTC),
        )
        await supervisor._open_disconnect_gaps(1_000)
        assert [g.reason for g in gaps] == ["disconnect"]

        with pytest.raises(RuntimeError, match="durable event write rejected"):
            await supervisor._dispatch(_trade())
        assert events == []
        assert not supervisor._recent_key_sets["trades:BTC"]
        assert [g.reason for g in gaps] == ["disconnect"]
        assert supervisor.health.duplicate_count == 0

        # A genuinely redelivered identical venue row is not erased by a
        # previous failed delivery. The successful event precedes recovery.
        await supervisor._dispatch(_trade())
        assert events == ["trades:BTC:2000:1"]
        assert [g.reason for g in gaps] == ["disconnect", "recovered"]
        assert gaps[1].started_ms == 1_000
        assert supervisor._recent_key_sets["trades:BTC"] == set(events)
        await supervisor._dispatch(_trade())
        assert events == ["trades:BTC:2000:1"]
        assert supervisor.health.duplicate_count == 1
        assert [g.reason for g in gaps] == ["disconnect", "recovered"]

    asyncio.run(run())


def test_cancelled_l2_event_sink_does_not_commit_key_or_fake_recovery() -> None:
    async def run() -> None:
        attempted: list[str] = []
        accepted: list[str] = []
        gaps: list[DataGap] = []
        first_started = asyncio.Event()
        block_first = True

        async def factory() -> object:
            raise AssertionError("no network permitted")

        async def event_sink(event: StreamEvent) -> None:
            attempted.append(event.event_key)
            if block_first:
                first_started.set()
                await asyncio.Event().wait()
            accepted.append(event.event_key)

        async def gap_sink(gap: DataGap) -> None:
            gaps.append(gap)

        supervisor = WebSocketSupervisor(
            factory, ({"type": "l2Book", "coin": "BTC"},),
            event_sink=event_sink, gap_sink=gap_sink,
            clock_ms=lambda: 2_000,
            utcnow=lambda: datetime(2026, 10, 17, tzinfo=UTC),
            stale_after_ms=5_000,
        )
        await supervisor._open_disconnect_gaps(1_000)
        task = asyncio.create_task(supervisor._dispatch(_book()))
        await asyncio.wait_for(first_started.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert attempted and not accepted
        assert not supervisor._recent_key_sets["l2Book:BTC"]
        assert [g.reason for g in gaps] == ["disconnect"]
        assert supervisor.l2_delivery_diagnostics(
            now_ms=2_000
        )["l2_fresh_accepted_count"] == 0

        block_first = False
        await supervisor._dispatch(_book())
        assert attempted == accepted * 2
        assert len(accepted) == 1
        assert [g.reason for g in gaps] == ["disconnect", "recovered"]
        assert supervisor._recent_key_sets["l2Book:BTC"] == set(accepted)
        assert supervisor.l2_delivery_diagnostics(
            now_ms=2_000
        )["l2_fresh_accepted_count"] == 1
        await supervisor._dispatch(_book())
        assert accepted == attempted[:1]
        assert supervisor.health.duplicate_count == 1
        assert [g.reason for g in gaps] == ["disconnect", "recovered"]

    asyncio.run(run())
