"""Bound per-market scheduling in real allMids websocket frame fanout.

These tests are synthetic unit coverage only. Neither a monotonic source
certificate nor evidence of after-cost trading profitability is asserted.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cocomelon.continuous_paper import (
    ALL_MIDS_COOPERATIVE_YIELD_INTERVAL,
    _record_from_stream,
    _StreamYieldBudget,
)
from cocomelon.domain.stream import DataGap, StreamEvent, StreamKind
from cocomelon.evidence.redundant_stream import RedundantStreamMux
from cocomelon.hyperliquid.ws_protocol import normalize_ws_message


def _normalized_all_mids(count: int) -> list[StreamEvent]:
    frame = {
        "channel": "allMids",
        "data": {
            "mids": {
                f"ASSET{index:03d}": str(100 + index)
                for index in range(count)
            }
        },
    }
    return normalize_ws_message(
        frame, receive_time=datetime(2026, 10, 18, tzinfo=UTC),
    )


def test_yields_are_bounded_and_independently_accounted_per_lane() -> None:
    assert ALL_MIDS_COOPERATIVE_YIELD_INTERVAL == 8
    budget = _StreamYieldBudget(lane_count=2)
    for lane in range(2):
        for _ in range(7):
            assert budget.should_yield(lane, StreamKind.ALL_MIDS) is False
    assert budget.should_yield(0, StreamKind.ALL_MIDS) is True
    # Lane 1 has independent unfinished 7-event budget.
    assert budget.should_yield(1, StreamKind.ALL_MIDS) is True
    assert budget.should_yield(1, StreamKind.L2_BOOK) is True
    assert budget.should_yield(0, StreamKind.TRADE) is True
    assert budget.should_yield(0, StreamKind.ALL_MIDS) is False
    assert budget.should_yield(0, StreamKind.L2_BOOK) is True
    assert budget.should_yield(0, StreamKind.ALL_MIDS) is False


def test_full_frame_is_not_suppressed_or_retimed_by_cooperative_budget() -> None:
    frame = _normalized_all_mids(73)
    assert len(frame) == 73
    assert all(event.kind is StreamKind.ALL_MIDS for event in frame)
    # A single original WS frame has ONE receive timestamp, even when a
    # downstream sink must accept 73 distinct original market events.
    receive_times = {event.receive_time for event in frame}
    assert len(receive_times) == 1

    async def run(*, optimized: bool) -> tuple[list[object], int, list[DataGap]]:
        rows: list[object] = []
        gaps: list[DataGap] = []

        async def event_sink(event: StreamEvent) -> None:
            rows.append(_record_from_stream(event))

        async def gap_sink(gap: DataGap) -> None:
            gaps.append(gap)

        mux = RedundantStreamMux(event_sink=event_sink, gap_sink=gap_sink)
        budget = _StreamYieldBudget()
        yields = 0
        for event in frame:
            await mux.on_event(0, event)
            if (not optimized) or budget.should_yield(0, event.kind):
                yields += 1
                await asyncio.sleep(0)
        # Preserve a genuine subsequent same-lane GAP, not a synthetic
        # closure or an excuse to certify any failed market-data source.
        original_gap = DataGap(
            stream_id="l2Book:BTC",
            started_ms=1_000, ended_ms=1_500, reason="out_of_order",
        )
        await mux.on_gap(0, original_gap)
        return rows, yields, gaps

    prior, old_yields, old_gaps = asyncio.run(run(optimized=False))
    after, new_yields, new_gaps = asyncio.run(run(optimized=True))
    assert after == prior
    assert len(after) == 73
    assert old_yields == 73
    assert new_yields == 73 // ALL_MIDS_COOPERATIVE_YIELD_INTERVAL
    assert new_gaps == old_gaps
    assert new_gaps == [DataGap(
        stream_id="l2Book:BTC", started_ms=1_000,
        ended_ms=1_500, reason="out_of_order",
    )]
    assert len({row.available_at_ms for row in after}) == 1


def test_non_allmids_market_evidence_still_yields_immediately() -> None:
    budget = _StreamYieldBudget()
    for kind in (
        StreamKind.L2_BOOK,
        StreamKind.TRADE,
        StreamKind.ACTIVE_ASSET_CTX,
        StreamKind.CANDLE,
    ):
        assert budget.should_yield(0, kind)
    for _ in range(6):
        assert not budget.should_yield(0, StreamKind.ALL_MIDS)
    assert budget.should_yield(0, StreamKind.L2_BOOK)
    assert not budget.should_yield(0, StreamKind.ALL_MIDS)


@pytest.mark.parametrize("lane", [-1, True, 2, "0"])
def test_invalid_lane_is_denied_without_unsafe_fallback(lane: object) -> None:
    with pytest.raises(ValueError, match="lane"):
        _StreamYieldBudget(lane_count=2).should_yield(
            lane, StreamKind.ALL_MIDS,  # type: ignore[arg-type]
        )


def test_runtime_only_throttles_pure_allmids_scheduling() -> None:
    worker = (
        Path(__file__).resolve().parents[1]
        / "src/cocomelon/continuous_paper.py"
    ).read_text(encoding="utf-8")
    assert "if stream_yield_budget.should_yield(lane, event.kind):" in worker
    assert "await mux.on_event(lane, event)" in worker
    assert "await mux.on_gap(lane, gap)" in worker
    assert "await _cooperative_stream_yield()" in worker
    # Normalized exchange/source timestamps and canonical gap payloads
    # remain original first-seen inputs, never sorted or rewritten.
    assert "original_v3_capture.offer(" in worker
    assert "_record_from_stream(event)" in worker
