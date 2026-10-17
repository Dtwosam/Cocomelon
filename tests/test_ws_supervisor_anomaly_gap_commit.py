"""Pending upstream out-of-order gap evidence must survive failed sink writes."""
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


def test_rejected_anomaly_gap_retries_exact_original_before_fresh_source() -> None:
    async def run() -> None:
        clock = [2_000]
        accepted: list[str] = []
        gaps: list[DataGap] = []
        attempts: list[DataGap] = []
        failures_remaining = 2

        async def factory() -> object:
            raise AssertionError("no venue network")

        async def event_sink(event: StreamEvent) -> None:
            accepted.append(event.event_key)

        async def gap_sink(gap: DataGap) -> None:
            nonlocal failures_remaining
            if gap.reason == "out_of_order":
                attempts.append(gap)
                if failures_remaining > 0:
                    failures_remaining -= 1
                    raise OSError("original anomaly journal unavailable")
            gaps.append(gap)

        supervisor = WebSocketSupervisor(
            factory, ({"type": "l2Book", "coin": "BTC"},),
            event_sink=event_sink, gap_sink=gap_sink,
            clock_ms=lambda: clock[0],
            utcnow=lambda: datetime(2026, 10, 17, tzinfo=UTC),
            stale_after_ms=15_000,
        )
        await supervisor._dispatch(_book(2_000))
        assert len(accepted) == 1
        clock[0] = 3_000
        with pytest.raises(RuntimeError, match="original anomaly journal unavailable"):
            await supervisor._dispatch(_book(1_500))
        pending = supervisor._uncommitted_anomaly_gaps["l2Book:BTC"]
        assert pending.reason == "out_of_order"
        assert (pending.started_ms, pending.ended_ms) == (1_500, 2_000)
        assert accepted == [accepted[0]]
        assert gaps == []
        assert supervisor._last_exchange_time["l2Book:BTC"] == 2_000
        assert supervisor._last_stream_message["l2Book:BTC"] == 2_000
        assert supervisor.l2_delivery_diagnostics(
            now_ms=3_000
        )["uncommitted_source_gap_anomaly_count"] == 1

        clock[0] = 4_000
        with pytest.raises(RuntimeError, match="original anomaly journal unavailable"):
            await supervisor._dispatch(_book(2_500))
        assert attempts == [pending, pending]
        assert len(accepted) == 1
        assert supervisor._last_exchange_time["l2Book:BTC"] == 2_000

        # A newly received valid market row can advance only after the
        # original unchanged negative anomaly evidence is accepted.
        clock[0] = 5_000
        await supervisor._dispatch(_book(2_500))
        assert attempts == [pending, pending, pending]
        assert gaps == [pending]
        assert len(accepted) == 2
        assert supervisor._last_exchange_time["l2Book:BTC"] == 2_500
        assert supervisor._last_stream_message["l2Book:BTC"] == 5_000
        assert not supervisor._uncommitted_anomaly_gaps
        assert supervisor.l2_delivery_diagnostics(
            now_ms=5_000
        )["uncommitted_source_gap_anomaly_count"] == 0

    asyncio.run(run())


def test_cancelled_anomaly_gap_persists_through_disconnect_opening() -> None:
    async def run() -> None:
        clock = [2_000]
        started = asyncio.Event()
        block = True
        gaps: list[DataGap] = []
        attempts: list[DataGap] = []

        async def factory() -> object:
            raise AssertionError("no venue network")

        async def event_sink(event: StreamEvent) -> None:
            del event

        async def gap_sink(gap: DataGap) -> None:
            if gap.reason == "out_of_order":
                attempts.append(gap)
                if block:
                    started.set()
                    await asyncio.Event().wait()
            gaps.append(gap)

        supervisor = WebSocketSupervisor(
            factory, ({"type": "l2Book", "coin": "BTC"},),
            event_sink=event_sink, gap_sink=gap_sink,
            clock_ms=lambda: clock[0],
            utcnow=lambda: datetime(2026, 10, 17, tzinfo=UTC),
            stale_after_ms=15_000,
        )
        await supervisor._dispatch(_book(2_000))
        clock[0] = 3_000
        task = asyncio.create_task(supervisor._dispatch(_book(1_500)))
        await asyncio.wait_for(started.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        pending = supervisor._uncommitted_anomaly_gaps["l2Book:BTC"]
        assert gaps == []
        assert attempts == [pending]
        assert supervisor._last_exchange_time["l2Book:BTC"] == 2_000

        block = False
        clock[0] = 4_000
        await supervisor._open_disconnect_gaps(4_000)
        assert attempts == [pending, pending]
        assert [g.reason for g in gaps] == ["out_of_order", "disconnect"]
        assert gaps[0] is pending
        assert gaps[1].started_ms == 4_000
        assert gaps[1].ended_ms is None
        assert not supervisor._uncommitted_anomaly_gaps

    asyncio.run(run())


def test_stale_gap_open_cannot_bypass_uncommitted_anomaly_witness() -> None:
    async def run() -> None:
        clock = [2_000]
        pending_attempts: list[DataGap] = []
        seen: list[DataGap] = []
        reject = True

        async def factory() -> object:
            raise AssertionError("no venue network")

        async def event_sink(event: StreamEvent) -> None:
            del event

        async def gap_sink(gap: DataGap) -> None:
            nonlocal reject
            if gap.reason == "out_of_order":
                pending_attempts.append(gap)
                if reject:
                    raise OSError("anomaly receipt unavailable")
            seen.append(gap)

        supervisor = WebSocketSupervisor(
            factory, ({"type": "l2Book", "coin": "BTC"},),
            event_sink=event_sink, gap_sink=gap_sink,
            clock_ms=lambda: clock[0],
            utcnow=lambda: datetime(2026, 10, 17, tzinfo=UTC),
            stale_after_ms=5_000,
        )
        await supervisor._dispatch(_book(2_000))
        clock[0] = 3_000
        with pytest.raises(RuntimeError, match="anomaly receipt unavailable"):
            await supervisor._dispatch(_book(1_500))
        clock[0] = 9_000
        with pytest.raises(RuntimeError, match="anomaly receipt unavailable"):
            await supervisor._open_l2_stale_gaps_if_needed(9_000)
        assert not seen
        assert not supervisor._open_gaps

        reject = False
        await supervisor._open_l2_stale_gaps_if_needed(9_000)
        assert [g.reason for g in seen] == ["out_of_order", "stale"]
        assert seen[0] is pending_attempts[0]
        assert seen[1].started_ms == 7_000
        assert seen[1].ended_ms is None

    asyncio.run(run())


def test_same_original_out_of_order_redelivery_consumes_exact_pending_receipt() -> None:
    async def run() -> None:
        clock = [2_000]
        accepted: list[str] = []
        anomaly_attempts: list[DataGap] = []
        persisted_gaps: list[DataGap] = []
        fail_once = True

        async def factory() -> object:
            raise AssertionError("no venue network")

        async def event_sink(event: StreamEvent) -> None:
            accepted.append(event.event_key)

        async def gap_sink(gap: DataGap) -> None:
            nonlocal fail_once
            if gap.reason == "out_of_order":
                anomaly_attempts.append(gap)
                if fail_once:
                    fail_once = False
                    raise OSError("one failed anomaly receipt")
            persisted_gaps.append(gap)

        supervisor = WebSocketSupervisor(
            factory, ({"type": "l2Book", "coin": "BTC"},),
            event_sink=event_sink, gap_sink=gap_sink,
            clock_ms=lambda: clock[0],
            utcnow=lambda: datetime(2026, 10, 17, tzinfo=UTC),
            stale_after_ms=15_000,
        )
        await supervisor._dispatch(_book(2_000))
        clock[0] = 3_000
        with pytest.raises(RuntimeError, match="one failed anomaly receipt"):
            await supervisor._dispatch(_book(1_500))
        frozen = anomaly_attempts[0]
        assert "l2Book:BTC" in supervisor._uncommitted_anomaly_event_keys

        # Replay EXACTLY the failed anomalous venue row. The first retry
        # commits its frozen receipt; it must not create a second anomaly.
        clock[0] = 3_200
        await supervisor._dispatch(_book(1_500))
        assert anomaly_attempts == [frozen, frozen]
        assert persisted_gaps == [frozen]
        assert len(accepted) == 1
        assert supervisor._last_exchange_time["l2Book:BTC"] == 2_000
        assert supervisor._last_stream_message["l2Book:BTC"] == 3_200
        assert not supervisor._uncommitted_anomaly_gaps
        assert not supervisor._uncommitted_anomaly_event_keys

    asyncio.run(run())
