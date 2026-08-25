from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from cocomelon.domain.stream import DataGap, StreamEvent
from cocomelon.evidence.redundant_stream import RedundantStreamMux
from cocomelon.hyperliquid.ws_supervisor import WebSocketSupervisor

RECEIVED = datetime(2026, 8, 25, tzinfo=UTC)
SUBSCRIPTIONS = (
    {"type": "trades", "coin": "BTC"},
    {"type": "l2Book", "coin": "BTC"},
)


def _trade(tid: int, time_ms: int) -> dict[str, object]:
    return {
        "channel": "trades",
        "data": [
            {
                "coin": "BTC",
                "side": "B",
                "px": "100",
                "sz": "1",
                "hash": f"0x{tid}",
                "time": time_ms,
                "tid": tid,
                "users": ["a", "b"],
            }
        ],
    }


def _book(time_ms: int) -> dict[str, object]:
    return {
        "channel": "l2Book",
        "data": {
            "coin": "BTC",
            "levels": [
                [{"n": 1, "px": "99", "sz": "1"}],
                [{"n": 1, "px": "101", "sz": "1"}],
            ],
            "time": time_ms,
        },
    }


class ScriptedConnection:
    def __init__(self, rows: list[object], delays: list[float]) -> None:
        self._rows = list(rows)
        self._delays = list(delays)
        self.closed = False

    async def send_json(self, message: dict[str, object]) -> None:
        return None

    async def recv_json(self) -> dict[str, object]:
        delay = self._delays.pop(0)
        if delay:
            await asyncio.sleep(delay)
        row = self._rows.pop(0)
        if isinstance(row, BaseException):
            raise row
        assert isinstance(row, dict)
        return row

    async def close(self) -> None:
        self.closed = True


def test_supervisor_lane_activity_proves_cross_stream_standby_readiness() -> None:
    async def run() -> None:
        events: list[StreamEvent] = []
        gaps: list[DataGap] = []
        tick = 1_000

        def clock_ms() -> int:
            nonlocal tick
            tick += 1
            return tick

        async def event_sink(event: StreamEvent) -> None:
            events.append(event)

        async def gap_sink(gap: DataGap) -> None:
            gaps.append(gap)

        mux = RedundantStreamMux(event_sink=event_sink, gap_sink=gap_sink)
        primary = ScriptedConnection(
            [_trade(1, 1_000), ConnectionError("primary dropped")],
            [0.0, 0.04],
        )
        standby = ScriptedConnection(
            [_book(1_050), _trade(2, 2_000)],
            [0.01, 0.07],
        )

        async def primary_factory() -> ScriptedConnection:
            return primary

        async def standby_factory() -> ScriptedConnection:
            return standby

        async def primary_event_sink(event: StreamEvent) -> None:
            await mux.on_event(0, event)

        async def primary_gap_sink(gap: DataGap) -> None:
            await mux.on_gap(0, gap)

        async def standby_event_sink(event: StreamEvent) -> None:
            await mux.on_event(1, event)

        async def standby_gap_sink(gap: DataGap) -> None:
            await mux.on_gap(1, gap)

        primary_supervisor = WebSocketSupervisor(
            primary_factory,
            SUBSCRIPTIONS,
            event_sink=primary_event_sink,
            gap_sink=primary_gap_sink,
            clock_ms=clock_ms,
            utcnow=lambda: RECEIVED,
        )
        standby_supervisor = WebSocketSupervisor(
            standby_factory,
            SUBSCRIPTIONS,
            event_sink=standby_event_sink,
            gap_sink=standby_gap_sink,
            clock_ms=clock_ms,
            utcnow=lambda: RECEIVED,
        )

        await asyncio.gather(
            primary_supervisor.run(max_sessions=1, max_messages_per_session=2),
            standby_supervisor.run(max_sessions=1, max_messages_per_session=2),
        )

        assert gaps == []
        assert len(events) == 3
        assert events[0].event_key == "trades:BTC:1000:1"
        assert events[1].event_key.startswith("l2Book:BTC:1050:")
        assert events[2].event_key == "trades:BTC:2000:2"
        assert mux.active_lane("trades:BTC") == 1
        assert primary.closed is True
        assert standby.closed is True

    asyncio.run(run())
