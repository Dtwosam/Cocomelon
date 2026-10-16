"""Verify genuine PAPER gap receipt clocks never rewrite source gap bounds."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from cocomelon.continuous_paper import _RecordPump, _record_from_gap
from cocomelon.domain.replay import ReplayRecord, SourceRecordKind
from cocomelon.domain.stream import DataGap
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.research.original_paper_v3_capture import (
    RECORD_FILE,
    OriginalPaperMicrostructureCapture,
)

BASE = 1_792_162_800_000


class _Pipeline:
    def __init__(self) -> None:
        self.records: list[ReplayRecord] = []

    def on_record(self, record: ReplayRecord, _ms: int) -> tuple[object, ...]:
        self.records.append(record)
        return ()

    def finalize(self, _ms: int) -> tuple[object, ...]:
        return ()


class _Journal:
    def iter_trades(self) -> tuple[object, ...]:
        return ()

    def record_observation(self, _value: object) -> None:
        raise AssertionError("no observations expected")


def _book(at: int) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=at,
        source="hyperliquid-mainnet-ws",
        schema_version=1,
        market="TEST",
        exchange_time_ms=at - 2,
        event_key="actual-L2-received",
        event_kind="l2_book",
        payload_json=json.dumps({"bids": [], "asks": []}),
    )


def test_gap_availability_is_serialized_real_observation_not_history(
    monkeypatch, tmp_path: Path,
) -> None:
    import cocomelon.continuous_paper as paper
    import cocomelon.research.original_paper_v3_capture as capture_module

    now = [BASE + 3_000]
    monkeypatch.setattr(paper, "utc_now_ms", lambda: now[0])
    monkeypatch.setattr(capture_module, "utc_now_ms", lambda: now[0])

    original_gap = DataGap(
        stream_id="l2Book:TEST", started_ms=BASE,
        ended_ms=BASE + 2, reason="recovered",
    )
    # The old offline helper remains available for historical gap replay.
    assert _record_from_gap(original_gap).available_at_ms == BASE + 2

    async def scenario():
        capture = OriginalPaperMicrostructureCapture(
            tmp_path / "original", run_id="998877", run_attempt="1",
            head_sha="f" * 40, selected_markets=("TEST",),
            first_observed_ms=BASE, replay_config=BaselineReplayConfig(),
        )
        pipeline = _Pipeline()
        pump = _RecordPump(
            pipeline,  # type: ignore[arg-type]
            _Journal(),  # type: ignore[arg-type]
            last_available_at_ms=BASE,
            original_v3_capture=capture,
        )
        await pump.process(_book(BASE + 2_990))

        # Hold the record pump lock before the gap can enter.
        # Receipt time must be assigned AFTER releasing the lock.
        await pump._lock.acquire()
        task = asyncio.create_task(pump.process(original_gap))
        await asyncio.sleep(0)
        now[0] = BASE + 3_010
        pump._lock.release()
        await task
        return await capture.close(), pipeline.records

    terminal, pipeline_records = asyncio.run(scenario())
    assert terminal["complete"] is True
    assert terminal["original_received_clock_regressions"] == 0
    assert terminal["offered_count"] == terminal["written_count"] == 2
    assert terminal["gap_closed_offered_count"] == 1
    assert terminal["gap_max_boundary_age_ms"] == 3_008
    assert terminal["gap_boundary_age_over_1s_count"] == 1
    rows = [
        json.loads(line)
        for line in (tmp_path / "original" / RECORD_FILE).read_text().splitlines()
    ]
    assert rows[0]["available_at_ms"] == BASE + 2_990
    assert rows[1]["available_at_ms"] == BASE + 3_010
    assert pipeline_records[-1].available_at_ms == BASE + 3_010
    assert json.loads(rows[-1]["payload_json"]) == {
        "stream_id": "l2Book:TEST",
        "started_ms": BASE,
        "ended_ms": BASE + 2,
        "reason": "recovered",
    }
    assert rows[-1]["record_kind"] == "data_gap"
    # Local recorder completeness is not an eligible 72h source.
    assert terminal["external_market_completeness_authenticated"] is False
    assert terminal["promotion_authority"] is False


def test_gap_observation_input_must_be_real_valid_milliseconds() -> None:
    gap = DataGap(stream_id="l2Book:TEST", started_ms=BASE,
                  ended_ms=None, reason="stale")
    for bad in (True, -1, "not-a-time"):
        try:
            _record_from_gap(gap, observed_at_ms=bad)  # type: ignore[arg-type]
        except ValueError:
            pass
        else:
            raise AssertionError("invalid gap timestamp accepted")
