"""Prospective v3 source recorder health is visible without trade authority."""
from __future__ import annotations

import asyncio
from pathlib import Path

from cocomelon.domain.replay import ReplayRecord, SourceRecordKind
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.research.original_paper_v3_capture import (
    OriginalPaperMicrostructureCapture,
)
from scripts.render_continuous_paper_live_status import _v3_live_capture_lines

HEAD = "a" * 40


def _row(timestamp: int, key: str) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=timestamp,
        source="original-test-book",
        schema_version=1,
        market="TEST",
        exchange_time_ms=timestamp,
        event_key=key,
        event_kind="l2_book",
        payload_json='{"bids":[],"asks":[]}',
    )


def test_live_capture_snapshot_reads_only_memory_and_cannot_certify_trial(
    tmp_path: Path,
) -> None:
    async def execute() -> None:
        recorder = OriginalPaperMicrostructureCapture(
            tmp_path / "new-recording",
            run_id="38865259042",
            run_attempt="1",
            head_sha=HEAD,
            selected_markets=("TEST",),
            first_observed_ms=1792130000000,
            replay_config=BaselineReplayConfig(),
        )
        original = recorder.live_diagnostic_snapshot()
        assert original["enabled"] is True
        assert original["offered_count"] == 0
        assert original["written_count"] == 0
        assert original["original_selected_markets"] == 1
        assert original["capture_admissible_from_heartbeat"] is False
        assert original["promotion_authority"] is False
        recorder.offer(_row(1792130000010, "original-A"))
        recorder.offer(_row(1792130000001, "original-regressing-B"))
        report = recorder.live_diagnostic_snapshot()
        assert report["offered_count"] == 2
        assert report["dropped_count"] >= 1
        assert report["received_clock_regressions"] == 1
        assert report["failure"] == "original_received_clock_regression"
        assert report["source_integrity_certified"] is False
        assert report["after_cost_profitability_verified"] is False
        terminal = await recorder.close()
        assert terminal["complete"] is False
        assert recorder.live_diagnostic_snapshot()["closed"] is True
        assert recorder.live_diagnostic_snapshot()["execution_authority"] is False

    asyncio.run(execute())


def test_negative_live_status_renderer_never_credits_future_account() -> None:
    lines = _v3_live_capture_lines({
        "enabled": True,
        "failure": "original_capture_queue_overflow",
        "offered_count": 300,
        "written_count": 220,
        "dropped_count": 80,
        "pending_queue_depth": 32,
        "received_clock_regressions": 2,
        "last_written_available_at_ms": 1792130000000,
        "source_integrity_certified": False,
        "promotion_authority": False,
    })
    rendered = "\n".join(lines)
    assert "capture enabled: true" in rendered
    assert "original_capture_queue_overflow" in rendered
    assert "300 / 220 / 80" in rendered
    assert "32 / 2" in rendered
    assert "source and after-cost profit certification: FALSE" in rendered


def test_negative_status_shows_original_archive_budget_without_certification() -> None:
    lines = _v3_live_capture_lines({
        "enabled": True,
        "written_count": 24,
        "written_source_journal_bytes": 2048,
        "source_journal_byte_limit": 4096,
        "remaining_persisted_byte_budget": 2048,
        "source_journal_row_limit": 200,
        "remaining_persisted_row_budget": 176,
    })
    rendered = "\n".join(lines)
    assert "2048 / 4096 / 2048" in rendered
    assert "24 / 200 / 176" in rendered
    assert "source and after-cost profit certification: FALSE" in rendered


def test_raw_clock_regression_status_never_claims_valid_original_feed() -> None:
    report = "\n".join(_v3_live_capture_lines({
        "enabled": True,
        "failure": "original_received_clock_regression",
        "received_clock_regressions": 3,
        "regressions_vs_prior_offered": 3,
        "regressions_vs_paper_clock": 2,
        "first_regression_cause": "both_prior_input_and_paper_clock",
        "first_regression_event_kind": "l2_book",
        "max_original_clock_backward_ms": 41,
    }))
    assert "3 / 2" in report
    assert "both_prior_input_and_paper_clock / l2_book / 41" in report
    assert "source and after-cost profit certification: FALSE" in report


def test_missing_capture_is_unverified_in_older_worker_heartbeats() -> None:
    rendered = "\n".join(_v3_live_capture_lines(None))
    assert "not reported" in rendered
    assert "NOT VERIFIED" in rendered


def test_authenticated_operational_status_contains_only_nonqualifying_capture() -> None:
    source = Path("src/cocomelon/continuous_paper.py").read_text()
    operational_at = source.index("def _operational_live_status_payload(")
    operational_end = source.index("def _emit_operational_live_status(", operational_at)
    operational = source[operational_at:operational_end]
    assert '"v3_original_paper_source_capture": (' in operational
    assert "pump.original_v3_capture.live_diagnostic_snapshot()" in operational
    assert '"capture_admissible_from_heartbeat": False' in operational
    assert '"execution_authority": False' in operational
    assert '"promotion_authority": False' in operational
    assert 'if os.environ.get("V3_CAPTURE_ORIGINAL_SOURCE") == "1"' in operational
