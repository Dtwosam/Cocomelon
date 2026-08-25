from __future__ import annotations

import asyncio

import pytest

from cocomelon.hyperliquid.ws_client import ConnectionSpacingGate, _connect_spacing_seconds


def test_connection_spacing_gate_separates_successive_connect_slots() -> None:
    async def run() -> None:
        now = [0.0]
        sleeps: list[float] = []
        gate = ConnectionSpacingGate()

        async def fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)
            now[0] += seconds

        await gate.wait(15.0, sleep=fake_sleep, monotonic=lambda: now[0])
        await gate.wait(15.0, sleep=fake_sleep, monotonic=lambda: now[0])

        assert sleeps == [15.0]

    asyncio.run(run())


def test_connection_spacing_env_is_explicit_and_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("COCOMELON_WS_CONNECT_SPACING_SECONDS", raising=False)
    assert _connect_spacing_seconds() == 0.0

    monkeypatch.setenv("COCOMELON_WS_CONNECT_SPACING_SECONDS", "15")
    assert _connect_spacing_seconds() == 15.0

    monkeypatch.setenv("COCOMELON_WS_CONNECT_SPACING_SECONDS", "-1")
    with pytest.raises(ValueError, match="non-negative"):
        _connect_spacing_seconds()

    monkeypatch.setenv("COCOMELON_WS_CONNECT_SPACING_SECONDS", "not-a-number")
    with pytest.raises(ValueError, match="number"):
        _connect_spacing_seconds()
