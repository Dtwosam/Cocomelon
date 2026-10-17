"""Project row-budget pressure from REAL offers, never claim source validity."""
from __future__ import annotations

import asyncio
from pathlib import Path

from cocomelon.domain.replay import ReplayRecord, SourceRecordKind
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.research.original_paper_v3_capture import (
    FROZEN_FORWARD_SOURCE_DURATION_MS,
    MAX_SOURCE_ROWS,
    MIN_ROW_RATE_PROJECTION_WINDOW_MS,
    OriginalPaperMicrostructureCapture,
)
from scripts.render_continuous_paper_live_status import _v3_live_capture_lines

HEAD = "a" * 40
BASE = 1_792_160_000_000


def _row(at_ms: int, key: str) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=at_ms,
        source="hyperliquid-mainnet-ws",
        schema_version=1,
        market="TEST",
        exchange_time_ms=at_ms,
        event_key=key,
        event_kind="l2_book",
        payload_json='{"levels":[[],[]]}',
    )


def test_72h_estimate_is_unavailable_without_10min_of_original_observation() -> None:
    recorder = object.__new__(OriginalPaperMicrostructureCapture)
    recorder.first_offered_available_at_ms = BASE
    recorder._max_offered_available_at_ms = BASE + 9 * 60 * 1_000
    recorder.offered_count = 1_000_000
    out = recorder._negative_72h_row_budget_projection()
    assert MIN_ROW_RATE_PROJECTION_WINDOW_MS == 600_000
    assert FROZEN_FORWARD_SOURCE_DURATION_MS == 259_200_000
    assert out["estimated_72h_original_rows_at_observed_offer_rate"] is None
    assert out["estimated_72h_source_rows_exceed_fixed_limit"] is None
    assert out["estimated_72h_source_projection_not_qualification"] is True


def test_72h_row_projection_exposes_both_high_and_low_observed_rates() -> None:
    recorder = object.__new__(OriginalPaperMicrostructureCapture)
    recorder.first_offered_available_at_ms = BASE
    recorder._max_offered_available_at_ms = BASE + 11 * 60 * 1_000
    recorder.offered_count = 150_000
    high = recorder._negative_72h_row_budget_projection()
    assert MAX_SOURCE_ROWS == 5_000_000
    assert high["estimated_72h_original_rows_at_observed_offer_rate"] == (
        (150_000 * FROZEN_FORWARD_SOURCE_DURATION_MS + 660_000 - 1)
        // 660_000
    )
    assert high["estimated_72h_source_rows_exceed_fixed_limit"] is True

    recorder.offered_count = 100
    low = recorder._negative_72h_row_budget_projection()
    assert low["estimated_72h_source_rows_exceed_fixed_limit"] is False
    assert low["estimated_72h_source_projection_not_qualification"] is True


def test_failed_original_capture_still_denied_regardless_of_projected_capacity(
    tmp_path: Path,
) -> None:
    async def run() -> tuple[dict[str, object], dict[str, object]]:
        recorder = OriginalPaperMicrostructureCapture(
            tmp_path / "original",
            run_id="39071958397", run_attempt="1", head_sha=HEAD,
            selected_markets=("TEST",), first_observed_ms=BASE,
            replay_config=BaselineReplayConfig(),
        )
        recorder.offer(_row(BASE, "first"))
        recorder.offer(_row(BASE + 660_000, "highest"))
        recorder.offer(
            _row(BASE + 659_999, "genuine_backward"),
            paper_previous_at_ms=BASE + 660_000,
        )
        return recorder.live_diagnostic_snapshot(), await recorder.close()

    live, terminal = asyncio.run(run())
    assert live["source_integrity_certified"] is False
    assert live["capture_admissible_from_heartbeat"] is False
    assert live["received_clock_regressions"] == 1
    assert live["estimated_72h_source_rows_exceed_fixed_limit"] is False
    assert terminal["estimated_72h_source_rows_exceed_fixed_limit"] is False
    assert terminal["complete"] is False
    assert terminal["failure"] == "original_received_clock_regression"
    assert terminal["promotion_authority"] is False

    rendered = "\n".join(_v3_live_capture_lines(live))
    assert "conditional 72h ORIGINAL row projection" in rendered
    assert "not qualification" in rendered
    assert "source and after-cost profit certification: FALSE" in rendered
