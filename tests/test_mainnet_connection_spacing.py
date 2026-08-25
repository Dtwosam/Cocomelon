from __future__ import annotations

import asyncio

import pytest

from cocomelon.config import Settings
from cocomelon.evidence import cli_support


class FakeConnection:
    async def send_json(self, message: dict[str, object]) -> None:
        return None

    async def recv_json(self) -> dict[str, object]:
        raise AssertionError("not used")

    async def close(self) -> None:
        return None


def test_mainnet_connection_factory_enforces_shared_start_spacing() -> None:
    build_factory = cli_support._build_spaced_mainnet_connection_factory
    now = 100.0
    starts: list[float] = []
    sleeps: list[float] = []

    def monotonic() -> float:
        return now

    async def sleep(seconds: float) -> None:
        nonlocal now
        sleeps.append(seconds)
        now += seconds

    async def connect(settings: Settings) -> FakeConnection:
        starts.append(now)
        return FakeConnection()

    factory = build_factory(
        Settings(),
        environ={"COCOMELON_WS_CONNECT_SPACING_SECONDS": "15"},
        connect=connect,
        monotonic=monotonic,
        sleep=sleep,
    )

    async def run() -> None:
        await asyncio.gather(factory(), factory(), factory())

    asyncio.run(run())

    assert starts == [100.0, 115.0, 130.0]
    assert sleeps == [15.0, 15.0]


def test_mainnet_connection_spacing_env_fails_closed_on_invalid_values() -> None:
    parse_spacing = cli_support._ws_connect_spacing_seconds

    assert parse_spacing({}) == 0.0
    assert parse_spacing({"COCOMELON_WS_CONNECT_SPACING_SECONDS": "15"}) == 15.0

    for value in ("-1", "nan", "inf", "not-a-number"):
        with pytest.raises(ValueError, match="connect spacing"):
            parse_spacing({"COCOMELON_WS_CONNECT_SPACING_SECONDS": value})
