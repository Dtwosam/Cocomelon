from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from cocomelon.domain.stream import DataGap, StreamEvent
from cocomelon.hyperliquid.ws_supervisor import WebSocketSupervisor


class Connection:
    def __init__(self, rows: list[object]) -> None:
        self.rows = list(rows)

    async def send_json(self, value: dict[str, object]) -> None:
        return None

    async def recv_json(self) -> dict[str, object]:
        row = self.rows.pop(0)
        if isinstance(row, BaseException):
            raise row
        assert isinstance(row, dict)
        return row

    async def close(self) -> None:
        return None


def _mids(px: str) -> dict[str, object]:
    return {"channel": "allMids", "data": {"mids": {"BTC": px}}}


def test_all_mids_disconnect_opens_and_recovers_continuity_gap() -> None:
    async def run() -> None:
        first = Connection([_mids("100"), ConnectionError("drop")])
        second = Connection([_mids("101"), ConnectionError("bounded")])
        pool = [first, second]
        events: list[StreamEvent] = []
        gaps: list[DataGap] = []
        now = [1_000]

        async def factory() -> Connection:
            return pool.pop(0)

        async def event_sink(event: StreamEvent) -> None:
            events.append(event)
            now[0] += 100

        async def gap_sink(gap: DataGap) -> None:
            gaps.append(gap)

        async def no_sleep(_: float) -> None:
            return None

        supervisor = WebSocketSupervisor(
            factory,
            [{"type": "allMids"}],
            event_sink=event_sink,
            gap_sink=gap_sink,
            clock_ms=lambda: now[0],
            utcnow=lambda: datetime(2026, 8, 25, tzinfo=UTC),
            sleep=no_sleep,
        )
        await supervisor.run(max_sessions=2, max_messages_per_session=2)

        assert len(events) == 2
        assert any(
            gap.stream_id == "allMids"
            and gap.reason == "disconnect"
            and gap.ended_ms is None
            for gap in gaps
        )
        assert any(
            gap.stream_id == "allMids"
            and gap.reason == "recovered"
            and gap.ended_ms is not None
            for gap in gaps
        )

    asyncio.run(run())
