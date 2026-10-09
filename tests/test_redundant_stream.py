from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from cocomelon.domain.market import MarketId
from cocomelon.domain.stream import DataGap, StreamEvent, StreamKind

MARKET = MarketId("", "BTC")
BASE = datetime(2026, 8, 25, tzinfo=UTC)


def _trade(tid: int, time_ms: int, offset_ms: int) -> StreamEvent:
    return StreamEvent(
        kind=StreamKind.TRADE,
        market=MARKET,
        exchange_time_ms=time_ms,
        receive_time=BASE + timedelta(milliseconds=offset_ms),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key=f"trades:BTC:{time_ms}:{tid}",
        payload={
            "side": "B",
            "price": Decimal("100"),
            "size": Decimal("1"),
            "hash": f"0x{tid}",
            "tid": tid,
            "users": ("a", "b"),
        },
    )


def _ctx(mark: str, offset_ms: int) -> StreamEvent:
    value = Decimal(mark)
    return StreamEvent(
        kind=StreamKind.ACTIVE_ASSET_CTX,
        market=MARKET,
        exchange_time_ms=None,
        receive_time=BASE + timedelta(milliseconds=offset_ms),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key=f"activeAssetCtx:BTC:{offset_ms}:{mark}",
        payload={
            "mark_px": value,
            "mid_px": value,
            "oracle_px": value,
            "funding": Decimal("0"),
            "open_interest": Decimal("1"),
        },
    )


def test_primary_disconnect_fails_over_and_backfills_without_gap() -> None:
    async def run() -> None:
        from cocomelon.evidence.redundant_stream import RedundantStreamMux

        events: list[StreamEvent] = []
        gaps: list[DataGap] = []

        async def event_sink(event: StreamEvent) -> None:
            events.append(event)

        async def gap_sink(gap: DataGap) -> None:
            gaps.append(gap)

        mux = RedundantStreamMux(event_sink=event_sink, gap_sink=gap_sink)
        first = _trade(1, 1_000, 10)
        second = _trade(2, 2_000, 20)

        await mux.on_event(0, first)
        await mux.on_event(1, first)
        await mux.on_event(1, second)
        await mux.on_gap(
            0,
            DataGap(
                stream_id="trades:BTC",
                started_ms=2_100,
                ended_ms=None,
                reason="disconnect",
            ),
        )

        assert [event.event_key for event in events] == [first.event_key, second.event_key]
        assert gaps == []
        assert mux.failover_count == 1
        assert mux.active_lane("trades:BTC") == 1

    asyncio.run(run())


def test_dual_disconnect_emits_one_real_gap_and_first_recovery_closes_it() -> None:
    async def run() -> None:
        from cocomelon.evidence.redundant_stream import RedundantStreamMux

        events: list[StreamEvent] = []
        gaps: list[DataGap] = []

        async def event_sink(event: StreamEvent) -> None:
            events.append(event)

        async def gap_sink(gap: DataGap) -> None:
            gaps.append(gap)

        mux = RedundantStreamMux(event_sink=event_sink, gap_sink=gap_sink)
        await mux.on_event(0, _trade(1, 1_000, 10))
        await mux.on_event(1, _trade(1, 1_000, 12))

        await mux.on_gap(
            0,
            DataGap("trades:BTC", 2_000, None, "disconnect"),
        )
        await mux.on_gap(
            1,
            DataGap("trades:BTC", 2_200, None, "disconnect"),
        )

        assert len(gaps) == 1
        assert gaps[0].ended_ms is None
        assert gaps[0].started_ms == 2_200
        assert gaps[0].reason == "redundant_disconnect"

        # A lane-local recovery marker cannot close an aggregate outage
        # without the corresponding accepted market event.
        await mux.on_event(0, _trade(2, 2_500, 50))
        await mux.on_gap(
            0,
            DataGap("trades:BTC", 2_000, 2_500, "recovered"),
        )

        assert len(gaps) == 2
        assert gaps[1].started_ms == 2_200
        assert gaps[1].ended_ms == 2_500
        assert gaps[1].reason == "recovered"
        assert mux.active_lane("trades:BTC") == 0

    asyncio.run(run())


def test_recovered_marker_without_fresh_delivered_event_keeps_gap_open() -> None:
    async def run() -> None:
        from cocomelon.evidence.redundant_stream import RedundantStreamMux

        events: list[StreamEvent] = []
        gaps: list[DataGap] = []

        async def event_sink(event: StreamEvent) -> None:
            events.append(event)

        async def gap_sink(gap: DataGap) -> None:
            gaps.append(gap)

        mux = RedundantStreamMux(event_sink=event_sink, gap_sink=gap_sink)
        await mux.on_event(0, _trade(1, 1_000, 10))
        await mux.on_event(1, _trade(1, 1_000, 12))
        await mux.on_gap(0, DataGap("trades:BTC", 2_000, None, "disconnect"))
        await mux.on_gap(1, DataGap("trades:BTC", 2_100, None, "disconnect"))
        assert len(gaps) == 1

        await mux.on_gap(0, DataGap("trades:BTC", 2_000, 2_200, "recovered"))
        assert len(gaps) == 1
        assert events[-1].event_key == "trades:BTC:1000:1"

        # Only a newly emitted witness from the recovered lane can close it.
        await mux.on_event(0, _trade(2, 2_300, 30))
        assert [gap.reason for gap in gaps] == [
            "redundant_disconnect", "recovered"
        ]

    asyncio.run(run())


def test_failed_recovered_lane_delivery_cannot_heal_aggregate_gap() -> None:
    async def run() -> None:
        from cocomelon.evidence.redundant_stream import RedundantStreamMux

        gaps: list[DataGap] = []
        events: list[StreamEvent] = []

        async def event_sink(event: StreamEvent) -> None:
            if event.event_key == "trades:BTC:3000:3":
                raise RuntimeError("journal write rejected")
            events.append(event)

        async def gap_sink(gap: DataGap) -> None:
            gaps.append(gap)

        mux = RedundantStreamMux(event_sink=event_sink, gap_sink=gap_sink)
        await mux.on_event(0, _trade(1, 1_000, 10))
        await mux.on_event(1, _trade(1, 1_000, 12))
        await mux.on_gap(0, DataGap("trades:BTC", 2_000, None, "disconnect"))
        await mux.on_gap(1, DataGap("trades:BTC", 2_100, None, "disconnect"))

        # The unavailable lane buffers an event until its recovery marker;
        # flushing it fails, so an aggregate recovery must not be persisted.
        await mux.on_event(1, _trade(3, 3_000, 30))
        with pytest.raises(RuntimeError, match="journal write rejected"):
            await mux.on_gap(
                1, DataGap("trades:BTC", 2_100, 3_000, "recovered")
            )
        assert [gap.reason for gap in gaps] == ["redundant_disconnect"]
        assert [event.event_key for event in events] == [
            "trades:BTC:1000:1"
        ]

    asyncio.run(run())


def test_pre_outage_buffer_cannot_certify_new_recovery() -> None:
    async def run() -> None:
        from cocomelon.evidence.redundant_stream import RedundantStreamMux

        events: list[StreamEvent] = []
        gaps: list[DataGap] = []
        origin_ms = int(BASE.timestamp() * 1_000)

        async def event_sink(event: StreamEvent) -> None:
            events.append(event)

        async def gap_sink(gap: DataGap) -> None:
            gaps.append(gap)

        mux = RedundantStreamMux(event_sink=event_sink, gap_sink=gap_sink)
        await mux.on_event(0, _trade(1, 1_000, 10))
        await mux.on_event(1, _trade(1, 1_000, 12))
        await mux.on_gap(
            0, DataGap("trades:BTC", origin_ms + 500, None, "disconnect")
        )
        await mux.on_gap(
            1, DataGap("trades:BTC", origin_ms + 510, None, "disconnect")
        )

        # An older buffered packet may be delivered successfully on switch,
        # but its receive time predates the actual aggregate outage.
        await mux.on_event(1, _trade(2, 2_000, 100))
        await mux.on_gap(
            1, DataGap(
                "trades:BTC", origin_ms + 510, origin_ms + 600, "recovered"
            )
        )
        assert [gap.reason for gap in gaps] == ["redundant_disconnect"]
        assert events[-1].event_key == "trades:BTC:2000:2"

        # Only a new post-outage event can produce a recovery notice.
        await mux.on_event(1, _trade(3, 3_000, 700))
        assert [gap.reason for gap in gaps] == [
            "redundant_disconnect", "recovered"
        ]

    asyncio.run(run())


def test_failover_suppresses_receive_time_only_cross_lane_duplicate() -> None:
    async def run() -> None:
        from cocomelon.evidence.redundant_stream import RedundantStreamMux

        events: list[StreamEvent] = []

        async def event_sink(event: StreamEvent) -> None:
            events.append(event)

        async def gap_sink(gap: DataGap) -> None:
            raise AssertionError(f"unexpected aggregate gap: {gap}")

        mux = RedundantStreamMux(
            event_sink=event_sink,
            gap_sink=gap_sink,
            receive_only_duplicate_window_ms=1_000,
        )
        primary = _ctx("100", 100)
        duplicate = _ctx("100", 140)
        changed = _ctx("101", 180)

        await mux.on_event(0, primary)
        await mux.on_event(1, duplicate)
        await mux.on_event(1, changed)
        await mux.on_gap(
            0,
            DataGap("activeAssetCtx:BTC", 500, None, "disconnect"),
        )

        assert [event.payload["mark_px"] for event in events] == [
            Decimal("100"),
            Decimal("101"),
        ]

    asyncio.run(run())


def test_inactive_lane_local_anomaly_is_suppressed_when_active_lane_covers() -> None:
    async def run() -> None:
        from cocomelon.evidence.redundant_stream import RedundantStreamMux

        gaps: list[DataGap] = []

        async def event_sink(event: StreamEvent) -> None:
            return None

        async def gap_sink(gap: DataGap) -> None:
            gaps.append(gap)

        mux = RedundantStreamMux(event_sink=event_sink, gap_sink=gap_sink)
        await mux.on_event(0, _trade(1, 1_000, 10))
        await mux.on_gap(
            1,
            DataGap("trades:BTC", 900, 1_000, "out_of_order"),
        )

        assert gaps == []
        assert mux.active_lane("trades:BTC") == 0

    asyncio.run(run())
