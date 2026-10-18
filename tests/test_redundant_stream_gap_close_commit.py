"""Mux aggregate recovery CLOSE retries must preserve first original receipt.

A failed/cancelled write may have reached disk. Later source events cannot
move the original recovered end forward, or pass an uncommitted close.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from cocomelon.domain.market import MarketId
from cocomelon.domain.stream import DataGap, StreamEvent, StreamKind
from cocomelon.evidence.redundant_stream import RedundantStreamMux

STREAM = "trades:BTC"
BASE = datetime(2026, 10, 18, tzinfo=UTC)
MARKET = MarketId("", "BTC")


def _trade(tid: int, offset_ms: int) -> StreamEvent:
    return StreamEvent(
        kind=StreamKind.TRADE,
        market=MARKET,
        exchange_time_ms=1_000 + tid * 100,
        receive_time=BASE + timedelta(milliseconds=offset_ms),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key=f"trades:BTC:{tid}",
        payload={
            "side": "B", "price": Decimal("100"), "size": Decimal("1"),
            "hash": f"0x{tid}", "tid": tid, "users": ("a", "b"),
        },
    )


async def _open_with_two_failed_lanes(mux: RedundantStreamMux) -> None:
    initial = _trade(1, 100)
    await mux.on_event(0, initial)
    await mux.on_event(1, initial)
    await mux.on_gap(0, DataGap(STREAM, 2_000, None, "disconnect"))
    await mux.on_gap(1, DataGap(STREAM, 2_100, None, "disconnect"))
    # Real recovery notice alone is not a price witness.
    await mux.on_gap(0, DataGap(STREAM, 2_000, 2_500, "recovered"))
    assert mux._aggregate_gap_starts[STREAM] == 2_100


@pytest.mark.parametrize("cancel", [False, True], ids=["write_failure", "cancel"])
def test_exact_first_close_is_retried_before_new_market_event(cancel: bool) -> None:
    async def run() -> None:
        accepted: list[str] = []
        gaps: list[DataGap] = []
        recovered_attempts: list[DataGap] = []
        should_fail = [True]

        async def event_sink(event: StreamEvent) -> None:
            accepted.append(event.event_key)

        async def gap_sink(gap: DataGap) -> None:
            if gap.reason == "recovered":
                recovered_attempts.append(gap)
                if should_fail[0]:
                    if cancel:
                        raise asyncio.CancelledError()
                    raise OSError("durable mux gap close unavailable")
            gaps.append(gap)

        mux = RedundantStreamMux(event_sink=event_sink, gap_sink=gap_sink)
        await _open_with_two_failed_lanes(mux)

        original_first_event = _trade(2, 500)
        expected_error = asyncio.CancelledError if cancel else OSError
        with pytest.raises(expected_error):
            await mux.on_event(0, original_first_event)

        first_close = DataGap(
            STREAM, 2_100,
            int(original_first_event.receive_time.timestamp() * 1_000),
            "recovered",
        )
        assert recovered_attempts == [first_close]
        assert STREAM in mux._aggregate_gap_starts
        assert mux._uncommitted_aggregate_gap_closes == {STREAM: first_close}
        assert mux.ingress_diagnostics()["uncommitted_aggregate_gap_close_count"] == 1
        # Only the FIRST event passed its sink before closing was attempted.
        assert accepted == [_trade(1, 100).event_key, original_first_event.event_key]

        later = _trade(3, 950)
        # A repeated downstream write failure cannot allow a new event
        # to pass or change the original recovery receipt end timestamp.
        with pytest.raises(expected_error):
            await mux.on_event(0, later)
        assert recovered_attempts == [first_close, first_close]
        assert accepted == [_trade(1, 100).event_key, original_first_event.event_key]

        should_fail[0] = False
        await mux.on_event(0, later)
        assert recovered_attempts == [first_close, first_close, first_close]
        assert gaps[-1] == first_close
        assert accepted == [
            _trade(1, 100).event_key, original_first_event.event_key,
            later.event_key,
        ]
        assert STREAM not in mux._aggregate_gap_starts
        assert mux._uncommitted_aggregate_gap_closes == {}
        assert mux.ingress_diagnostics()["uncommitted_aggregate_gap_close_count"] == 0

    asyncio.run(run())


def test_pending_aggregate_close_retries_before_new_gap_boundary() -> None:
    async def run() -> None:
        accepted: list[str] = []
        attempts: list[DataGap] = []
        fail = [True]

        async def event_sink(event: StreamEvent) -> None:
            accepted.append(event.event_key)

        async def gap_sink(gap: DataGap) -> None:
            attempts.append(gap)
            if gap.reason == "recovered" and fail[0]:
                raise OSError("recovery receipt blocked")

        mux = RedundantStreamMux(event_sink=event_sink, gap_sink=gap_sink)
        await _open_with_two_failed_lanes(mux)
        with pytest.raises(OSError, match="blocked"):
            await mux.on_event(0, _trade(2, 500))
        first_close = attempts[-1]
        assert first_close.reason == "recovered"
        assert STREAM in mux._uncommitted_aggregate_gap_closes

        # A new genuine disconnect cannot bypass the old CLOSE or be
        # allowed to redate it as a newer source recovery timestamp.
        with pytest.raises(OSError, match="blocked"):
            await mux.on_gap(0, DataGap(STREAM, 4_000, None, "disconnect"))
        assert attempts[-1] == first_close
        assert mux._lane_gap_starts[STREAM] == {1: 2_100}
        fail[0] = False
        await mux.on_gap(0, DataGap(STREAM, 4_000, None, "disconnect"))
        assert attempts[-1] == first_close
        assert STREAM not in mux._uncommitted_aggregate_gap_closes
        assert accepted == [_trade(1, 100).event_key, _trade(2, 500).event_key]

    asyncio.run(run())


def test_healthy_close_retains_existing_exact_boundary_and_no_pending_debt() -> None:
    async def run() -> None:
        gaps: list[DataGap] = []

        async def event_sink(_event: StreamEvent) -> None:
            return None

        async def gap_sink(gap: DataGap) -> None:
            gaps.append(gap)

        mux = RedundantStreamMux(event_sink=event_sink, gap_sink=gap_sink)
        await _open_with_two_failed_lanes(mux)
        event = _trade(2, 500)
        await mux.on_event(0, event)
        assert gaps == [
            DataGap(STREAM, 2_100, None, "redundant_disconnect"),
            DataGap(
                STREAM, 2_100,
                int(event.receive_time.timestamp() * 1_000),
                "recovered",
            ),
        ]
        assert mux._uncommitted_aggregate_gap_closes == {}

    asyncio.run(run())
