"""A failed WS gap RECOVERED receipt must retain its exact original timestamp."""
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


def test_failed_recovered_marker_retries_identical_witness_before_duplicate() -> None:
    async def run() -> None:
        clock = [2_000]
        events: list[str] = []
        gaps: list[DataGap] = []
        recovered_attempts: list[DataGap] = []
        remaining_failures = 2

        async def factory() -> object:
            raise AssertionError("no network required")

        async def event_sink(event: StreamEvent) -> None:
            events.append(event.event_key)

        async def gap_sink(gap: DataGap) -> None:
            nonlocal remaining_failures
            if gap.reason == "recovered":
                recovered_attempts.append(gap)
                if remaining_failures:
                    remaining_failures -= 1
                    raise OSError("recovered gap store unavailable")
            gaps.append(gap)

        supervisor = WebSocketSupervisor(
            factory, ({"type": "trades", "coin": "BTC"},),
            event_sink=event_sink, gap_sink=gap_sink,
            clock_ms=lambda: clock[0],
            utcnow=lambda: datetime(2026, 10, 17, tzinfo=UTC),
        )
        await supervisor._open_disconnect_gaps(1_000)
        with pytest.raises(RuntimeError, match="recovered gap store unavailable"):
            await supervisor._dispatch(_trade(1, 2_000))
        assert events == ["trades:BTC:2000:1"]
        assert [g.reason for g in gaps] == ["disconnect"]
        assert "trades:BTC" in supervisor._open_gaps
        assert supervisor.l2_delivery_diagnostics(
            now_ms=2_000
        )["uncommitted_source_gap_recovered_count"] == 1
        pending = supervisor._uncommitted_recovered_gaps["trades:BTC"]
        assert pending.started_ms == 1_000
        assert pending.ended_ms == 2_000
        assert supervisor.health.duplicate_count == 0

        # A later redelivery must first retry the EXACT initial witness;
        # if that retry fails, no duplicate or new source event can advance.
        clock[0] = 3_000
        with pytest.raises(RuntimeError, match="recovered gap store unavailable"):
            await supervisor._dispatch(_trade(1, 2_000))
        assert len(recovered_attempts) == 2
        assert recovered_attempts[0] is pending
        assert recovered_attempts[1] is pending
        assert events == ["trades:BTC:2000:1"]
        assert supervisor.health.duplicate_count == 0

        clock[0] = 4_000
        await supervisor._dispatch(_trade(1, 2_000))
        assert recovered_attempts == [pending, pending, pending]
        assert gaps == [gaps[0], pending]
        assert [g.reason for g in gaps] == ["disconnect", "recovered"]
        assert gaps[1].started_ms == 1_000
        assert gaps[1].ended_ms == 2_000  # not backdated to 4000
        assert events == ["trades:BTC:2000:1"]
        assert supervisor.health.duplicate_count == 1
        assert not supervisor._open_gaps
        assert not supervisor._uncommitted_recovered_gaps
        assert supervisor.l2_delivery_diagnostics(
            now_ms=4_000
        )["uncommitted_source_gap_recovered_count"] == 0

    asyncio.run(run())


def test_cancelled_recovery_marker_must_finish_before_new_original_event() -> None:
    async def run() -> None:
        clock = [2_000]
        started = asyncio.Event()
        should_block = True
        observed: list[str] = []
        recovered_attempts: list[DataGap] = []

        async def factory() -> object:
            raise AssertionError("no network required")

        async def event_sink(event: StreamEvent) -> None:
            observed.append("event:" + event.event_key)

        async def gap_sink(gap: DataGap) -> None:
            if gap.reason == "recovered":
                recovered_attempts.append(gap)
                if should_block:
                    started.set()
                    await asyncio.Event().wait()
            observed.append("gap:" + gap.reason)

        supervisor = WebSocketSupervisor(
            factory, ({"type": "trades", "coin": "BTC"},),
            event_sink=event_sink, gap_sink=gap_sink,
            clock_ms=lambda: clock[0],
            utcnow=lambda: datetime(2026, 10, 17, tzinfo=UTC),
        )
        await supervisor._open_disconnect_gaps(1_000)
        task = asyncio.create_task(supervisor._dispatch(_trade(1, 2_000)))
        await asyncio.wait_for(started.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert observed == ["gap:disconnect", "event:trades:BTC:2000:1"]
        pending = supervisor._uncommitted_recovered_gaps["trades:BTC"]
        assert pending.ended_ms == 2_000
        assert len(recovered_attempts) == 1

        should_block = False
        clock[0] = 3_000
        await supervisor._dispatch(_trade(2, 3_000))
        assert recovered_attempts == [pending, pending]
        assert observed == [
            "gap:disconnect", "event:trades:BTC:2000:1",
            "gap:recovered", "event:trades:BTC:3000:2",
        ]
        assert not supervisor._open_gaps
        assert not supervisor._uncommitted_recovered_gaps

    asyncio.run(run())


def test_opening_disconnect_first_commits_pending_prior_recovery() -> None:
    async def run() -> None:
        clock = [2_000]
        attempts: list[DataGap] = []
        reject_recovery = True

        async def factory() -> object:
            raise AssertionError("no network required")

        async def event_sink(event: StreamEvent) -> None:
            del event

        async def gap_sink(gap: DataGap) -> None:
            nonlocal reject_recovery
            attempts.append(gap)
            if gap.reason == "recovered" and reject_recovery:
                reject_recovery = False
                raise OSError("temporary failed recovery receipt")

        supervisor = WebSocketSupervisor(
            factory, ({"type": "trades", "coin": "BTC"},),
            event_sink=event_sink, gap_sink=gap_sink,
            clock_ms=lambda: clock[0],
            utcnow=lambda: datetime(2026, 10, 17, tzinfo=UTC),
        )
        await supervisor._open_disconnect_gaps(1_000)
        with pytest.raises(RuntimeError, match="temporary failed recovery"):
            await supervisor._dispatch(_trade(1, 2_000))
        clock[0] = 5_000
        await supervisor._open_disconnect_gaps(5_000)
        assert [(gap.reason, gap.started_ms, gap.ended_ms) for gap in attempts] == [
            ("disconnect", 1_000, None),
            ("recovered", 1_000, 2_000),
            ("recovered", 1_000, 2_000),
            ("disconnect", 5_000, None),
        ]
        assert supervisor._open_gaps["trades:BTC"].started_ms == 5_000
        assert not supervisor._uncommitted_recovered_gaps

    asyncio.run(run())
