from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

from cocomelon.domain.market import MarketId
from cocomelon.domain.stream import DataGap, StreamEvent, StreamKind

MARKET = MarketId("", "BTC")


def _trade() -> StreamEvent:
    return StreamEvent(
        kind=StreamKind.TRADE,
        market=MARKET,
        exchange_time_ms=1_000,
        receive_time=datetime(2026, 8, 25, tzinfo=UTC),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key="trades:BTC:1000:1",
        payload={
            "side": "B",
            "price": Decimal("100"),
            "size": Decimal("1"),
            "hash": "0x1",
            "tid": 1,
            "users": ("a", "b"),
        },
    )


def test_unobserved_standby_does_not_hide_primary_startup_disconnect() -> None:
    async def run() -> None:
        from cocomelon.evidence.redundant_stream import RedundantStreamMux

        gaps: list[DataGap] = []

        async def event_sink(event: StreamEvent) -> None:
            return None

        async def gap_sink(gap: DataGap) -> None:
            gaps.append(gap)

        mux = RedundantStreamMux(event_sink=event_sink, gap_sink=gap_sink)
        await mux.on_event(0, _trade())
        await mux.on_gap(0, DataGap("trades:BTC", 1_100, None, "disconnect"))

        assert len(gaps) == 1
        assert gaps[0].stream_id == "trades:BTC"
        assert gaps[0].started_ms == 1_100
        assert gaps[0].ended_ms is None
        assert gaps[0].reason == "redundant_disconnect"

    asyncio.run(run())


def test_subscription_ready_standby_covers_primary_disconnect_before_first_event() -> None:
    async def run() -> None:
        from cocomelon.evidence.redundant_stream import RedundantStreamMux

        gaps: list[DataGap] = []
        events: list[StreamEvent] = []

        async def event_sink(event: StreamEvent) -> None:
            events.append(event)

        async def gap_sink(gap: DataGap) -> None:
            gaps.append(gap)

        mux = RedundantStreamMux(event_sink=event_sink, gap_sink=gap_sink)
        await mux.on_lane_ready(0, ("trades:BTC",))
        await mux.on_lane_ready(1, ("trades:BTC",))
        await mux.on_event(0, _trade())
        await mux.on_gap(0, DataGap("trades:BTC", 1_100, None, "disconnect"))

        assert gaps == []
        assert mux.active_lane("trades:BTC") == 1

    asyncio.run(run())


def test_lane_ready_does_not_close_a_previously_open_disconnect_gap() -> None:
    async def run() -> None:
        from cocomelon.evidence.redundant_stream import RedundantStreamMux

        gaps: list[DataGap] = []

        async def event_sink(event: StreamEvent) -> None:
            return None

        async def gap_sink(gap: DataGap) -> None:
            gaps.append(gap)

        mux = RedundantStreamMux(event_sink=event_sink, gap_sink=gap_sink)
        await mux.on_lane_ready(0, ("trades:BTC",))
        await mux.on_lane_ready(1, ("trades:BTC",))
        await mux.on_gap(0, DataGap("trades:BTC", 1_100, None, "disconnect"))
        await mux.on_gap(1, DataGap("trades:BTC", 1_200, None, "disconnect"))
        assert len(gaps) == 1
        assert gaps[0].reason == "redundant_disconnect"

        await mux.on_lane_ready(0, ("trades:BTC",))

        assert len(gaps) == 1
        assert gaps[0].ended_ms is None

    asyncio.run(run())
