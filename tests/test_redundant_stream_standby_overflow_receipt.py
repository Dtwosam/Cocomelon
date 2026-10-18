"""Promoted truncated standby buffers must emit honest source-loss receipts.

Synthetic mux tests prove bounded standby backfill is not silently
qualified as genuine continuous Hyperliquid venue coverage.
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
BASE_MS = int(BASE.timestamp() * 1_000)


def _trade(n: int) -> StreamEvent:
    return StreamEvent(
        kind=StreamKind.TRADE,
        market=MarketId("", "BTC"),
        exchange_time_ms=BASE_MS + n * 100,
        receive_time=BASE + timedelta(milliseconds=n * 100),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key=f"trades:BTC:{n}",
        payload={
            "side": "B", "price": Decimal("100"), "size": Decimal("1"),
            "hash": f"0x{n}", "tid": n, "users": ("a", "b"),
        },
    )


@pytest.mark.parametrize("standby_backlog", [2, 4])
def test_promoted_overflow_is_durable_negative_coverage_receipt(
    standby_backlog: int,
) -> None:
    async def run() -> None:
        timeline: list[StreamEvent | DataGap] = []

        async def event_sink(event: StreamEvent) -> None:
            timeline.append(event)

        async def gap_sink(gap: DataGap) -> None:
            timeline.append(gap)

        mux = RedundantStreamMux(
            event_sink=event_sink, gap_sink=gap_sink, buffer_size=1,
        )
        await mux.on_event(0, _trade(1))
        await mux.on_event(1, _trade(1))
        for n in range(2, standby_backlog + 2):
            await mux.on_event(1, _trade(n))
        # The counter counts physical evictions, including the exact
        # duplicate trade 1 already accepted on the active lane. Only
        # unacknowledged evictions create negative source-coverage debt.
        dropped_count = standby_backlog
        assert mux.ingress_diagnostics()[
            "standby_overflow_dropped_rows"
        ] == dropped_count
        assert timeline == [_trade(1)]
        await mux.on_gap(
            0, DataGap(STREAM, BASE_MS + 5000, None, "disconnect"),
        )
        assert mux.active_lane(STREAM) == 1
        assert timeline == [
            _trade(1),
            _trade(standby_backlog + 1),
            DataGap(
                STREAM, BASE_MS + 200,
                BASE_MS + (standby_backlog + 1) * 100,
                "standby_backfill_overflow",
            ),
        ]
        assert mux.ingress_diagnostics()[
            "uncommitted_standby_overflow_gap_count"
        ] == 0
        assert mux.ingress_diagnostics()[
            "standby_overflow_affected_streams"
        ] == 0
        # This is an honest uncertainty receipt, not permission to
        # reconstruct dropped original trade data from later observations.
        assert mux.failover_count == 1
        assert len([r for r in timeline if isinstance(r, StreamEvent)]) == 2

    asyncio.run(run())


@pytest.mark.parametrize("cancel", [False, True], ids=["io_failure", "cancel"])
def test_uncertain_overflow_receipt_blocks_next_market_row_and_retries_exactly(
    cancel: bool,
) -> None:
    async def run() -> None:
        accepted: list[StreamEvent] = []
        attempted: list[DataGap] = []
        reject = [True]

        async def event_sink(event: StreamEvent) -> None:
            accepted.append(event)

        async def gap_sink(gap: DataGap) -> None:
            attempted.append(gap)
            if gap.reason == "standby_backfill_overflow" and reject[0]:
                if cancel:
                    raise asyncio.CancelledError()
                raise OSError("original source negative receipt unavailable")

        mux = RedundantStreamMux(
            event_sink=event_sink, gap_sink=gap_sink, buffer_size=1,
        )
        await mux.on_event(0, _trade(1))
        await mux.on_event(1, _trade(1))
        await mux.on_event(1, _trade(2))
        await mux.on_event(1, _trade(3))
        error = asyncio.CancelledError if cancel else OSError
        expected = DataGap(
            STREAM, BASE_MS + 200, BASE_MS + 300,
            "standby_backfill_overflow",
        )
        with pytest.raises(error):
            await mux.on_gap(
                0, DataGap(STREAM, BASE_MS + 5000, None, "disconnect"),
            )
        assert mux.active_lane(STREAM) == 1
        assert accepted == [_trade(1), _trade(3)]
        assert attempted == [expected]
        assert mux.ingress_diagnostics()[
            "uncommitted_standby_overflow_gap_count"
        ] == 1

        with pytest.raises(error):
            await mux.on_event(1, _trade(4))
        assert accepted == [_trade(1), _trade(3)]
        assert attempted == [expected, expected]

        reject[0] = False
        await mux.on_event(1, _trade(4))
        assert accepted == [_trade(1), _trade(3), _trade(4)]
        assert attempted == [expected, expected, expected]
        assert mux.ingress_diagnostics()[
            "uncommitted_standby_overflow_gap_count"
        ] == 0

    asyncio.run(run())


def test_untruncated_backup_switch_does_not_invent_market_source_loss() -> None:
    async def run() -> None:
        accepted: list[StreamEvent] = []
        gaps: list[DataGap] = []

        async def event_sink(event: StreamEvent) -> None:
            accepted.append(event)

        async def gap_sink(gap: DataGap) -> None:
            gaps.append(gap)

        mux = RedundantStreamMux(
            event_sink=event_sink, gap_sink=gap_sink, buffer_size=3,
        )
        await mux.on_event(0, _trade(1))
        await mux.on_event(1, _trade(1))
        await mux.on_event(1, _trade(2))
        await mux.on_event(1, _trade(3))
        await mux.on_gap(
            0, DataGap(STREAM, BASE_MS + 5000, None, "disconnect"),
        )
        assert accepted == [_trade(1), _trade(2), _trade(3)]
        assert gaps == []
        assert mux.ingress_diagnostics()["standby_overflow_dropped_rows"] == 0

    asyncio.run(run())


def test_already_admitted_exact_backup_copy_is_not_a_missing_source_row() -> None:
    async def run() -> None:
        actual: list[StreamEvent] = []
        gaps: list[DataGap] = []

        async def event_sink(event: StreamEvent) -> None:
            actual.append(event)

        async def gap_sink(gap: DataGap) -> None:
            gaps.append(gap)

        mux = RedundantStreamMux(
            event_sink=event_sink, gap_sink=gap_sink, buffer_size=1,
        )
        for n in (1, 2, 3):
            await mux.on_event(0, _trade(n))
        await mux.on_event(1, _trade(2))
        await mux.on_event(1, _trade(3))
        assert mux.ingress_diagnostics()["standby_overflow_dropped_rows"] == 1
        assert mux.ingress_diagnostics()["standby_overflow_affected_streams"] == 0
        await mux.on_gap(
            0, DataGap(STREAM, BASE_MS + 5000, None, "disconnect"),
        )
        assert actual == [_trade(1), _trade(2), _trade(3)]
        assert gaps == []
        assert mux.failover_count == 1

    asyncio.run(run())
