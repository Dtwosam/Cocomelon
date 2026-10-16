"""Optional research latency cannot repeatedly starve genuine PAPER source."""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest

from cocomelon.continuous_paper import _RecordPump
from cocomelon.domain.replay import ReplayRecord, SourceRecordKind
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.research.original_paper_v3_capture import (
    OriginalPaperMicrostructureCapture,
)

BASE = 1_792_162_800_000


class _FakePipeline:
    def __init__(self) -> None:
        self.records: list[int] = []

    def on_record(self, record: ReplayRecord, now_ms: int) -> tuple[object, ...]:
        assert record.available_at_ms == now_ms
        self.records.append(now_ms)
        return ()

    def finalize(self, _now_ms: int) -> tuple[object, ...]:
        return ()


class _FakeJournal:
    def iter_trades(self) -> tuple[object, ...]:
        return ()

    def record_observation(self, _row: object) -> None:
        raise AssertionError("no observations expected")


class _SlowResearch:
    def __init__(self) -> None:
        self.offers = 0

    def observe(self, _record: ReplayRecord, _at: int) -> None:
        self.offers += 1
        time.sleep(0.008)


def _book(at: int, key: str) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=at,
        source="hyperliquid-mainnet-ws",
        schema_version=1,
        market="TEST",
        exchange_time_ms=at - 10,
        event_key=key,
        event_kind="l2_book",
        payload_json=json.dumps({"bids": [], "asks": []}),
    )


def test_slow_optional_cadence_fails_research_closed_without_dropping_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    import cocomelon.continuous_paper as paper

    monkeypatch.setattr(paper, "MAX_OPTIONAL_CADENCE_OBSERVE_MS", 1)

    async def scenario():
        recorder = OriginalPaperMicrostructureCapture(
            tmp_path / "capture",
            run_id="123456789", run_attempt="1", head_sha="a" * 40,
            selected_markets=("TEST",),
            first_observed_ms=BASE, replay_config=BaselineReplayConfig(),
        )
        pipeline = _FakePipeline()
        shadow = _SlowResearch()
        pump = _RecordPump(
            pipeline,  # type: ignore[arg-type]
            _FakeJournal(),  # type: ignore[arg-type]
            last_available_at_ms=BASE,
            cadence_shadow=shadow,  # type: ignore[arg-type]
            original_v3_capture=recorder,
        )
        await pump.process(_book(BASE + 1, "first"))
        assert pump.cadence_shadow is None
        assert pump.cadence_shadow_error == (
            "research_cadence_observer_exceeded_latency_budget"
        )
        assert pump.cadence_shadow_payload()["enabled"] is False
        assert pump.cadence_shadow_payload()["execution_authority"] is False
        assert pump.cadence_opportunity_learning_payload()["enabled"] is False
        await pump.process(_book(BASE + 2, "second"))
        return pump, shadow, pipeline, await recorder.close()

    pump, shadow, pipeline, terminal = asyncio.run(scenario())
    assert shadow.offers == 1
    assert pipeline.records == [BASE + 1, BASE + 2]
    assert pump.processed_records == 2
    assert pump.record_pump_max_process_ms >= 1
    assert terminal["complete"] is True
    assert terminal["offered_count"] == terminal["written_count"] == 2
    assert terminal["original_received_clock_regressions"] == 0
    assert terminal["dropped_count"] == 0
    assert terminal["external_market_completeness_authenticated"] is False
    assert terminal["promotion_authority"] is False


def test_normal_fast_optional_cadence_remains_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cocomelon.continuous_paper as paper
    monkeypatch.setattr(paper, "MAX_OPTIONAL_CADENCE_OBSERVE_MS", 1_000)

    class FastResearch:
        offers = 0

        def observe(self, _record: ReplayRecord, _at: int) -> None:
            self.offers += 1

    async def scenario():
        pipeline = _FakePipeline()
        shadow = FastResearch()
        pump = _RecordPump(
            pipeline,  # type: ignore[arg-type]
            _FakeJournal(),  # type: ignore[arg-type]
            last_available_at_ms=BASE,
            cadence_shadow=shadow,  # type: ignore[arg-type]
        )
        await pump.process(_book(BASE + 1, "first"))
        await pump.process(_book(BASE + 2, "second"))
        return pump, shadow, pipeline

    pump, shadow, pipeline = asyncio.run(scenario())
    assert shadow.offers == 2
    assert pipeline.records == [BASE + 1, BASE + 2]
    assert pump.cadence_shadow is shadow
    assert pump.cadence_shadow_error is None
