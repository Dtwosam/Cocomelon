from __future__ import annotations

import asyncio

from cocomelon.evidence.recording import _run_supervisor_lane


class FakeSupervisor:
    def __init__(self) -> None:
        self.run_calls = 0

    async def run(self) -> None:
        self.run_calls += 1


def test_redundant_lane_one_is_phase_offset_for_long_mainnet_capture() -> None:
    async def run() -> None:
        sleeps: list[float] = []
        supervisor = FakeSupervisor()

        async def fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)

        await _run_supervisor_lane(
            supervisor,  # type: ignore[arg-type]
            lane=1,
            duration_seconds=90,
            sleep=fake_sleep,
        )

        assert sleeps == [30.0]
        assert supervisor.run_calls == 1

    asyncio.run(run())


def test_primary_and_short_diagnostics_start_without_stagger() -> None:
    async def run() -> None:
        sleeps: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)

        primary = FakeSupervisor()
        await _run_supervisor_lane(
            primary,  # type: ignore[arg-type]
            lane=0,
            duration_seconds=90,
            sleep=fake_sleep,
        )
        short_standby = FakeSupervisor()
        await _run_supervisor_lane(
            short_standby,  # type: ignore[arg-type]
            lane=1,
            duration_seconds=59,
            sleep=fake_sleep,
        )

        assert sleeps == []
        assert primary.run_calls == 1
        assert short_standby.run_calls == 1

    asyncio.run(run())
