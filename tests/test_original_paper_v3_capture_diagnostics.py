"""Real PAPER v3 recorder failures are preserved without creating fake source."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cocomelon.research.original_paper_v3_capture import (
    RECORD_FILE,
    STARTUP_FAILURE_FILE,
    TERMINAL_FILE,
    persist_original_capture_startup_failure,
)
from scripts.diagnose_original_paper_v3_capture import (
    diagnose_original_paper_v3_capture,
)

RUN = "38842093623"
ATTEMPT = "1"
HEAD = "a" * 40


def _diagnose(tmp_path: Path) -> dict[str, object]:
    return diagnose_original_paper_v3_capture(
        capture_root=tmp_path / "capture",
        diagnostic_root=tmp_path,
        run_id=RUN,
        run_attempt=ATTEMPT,
        head_sha=HEAD,
    )


def _assert_research_denied(payload: dict[str, object]) -> None:
    assert payload["capture_admissible_from_diagnostic"] is False
    assert payload["source_integrity_certified"] is False
    assert payload["independent_venue_feed_complete"] is False
    assert payload["positive_after_cost_account_pnl_verified"] is False
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False


def test_missing_genuine_capture_is_not_misreported_as_a_success(
    tmp_path: Path,
) -> None:
    before = set(tmp_path.iterdir())
    result = _diagnose(tmp_path)
    assert result["diagnostic_reason"] == "capture_root_never_created"
    assert result["terminal_receipt_observed"] is False
    assert result["original_written_count"] is None
    assert set(tmp_path.iterdir()) == before
    _assert_research_denied(result)


def test_startup_exception_class_is_preserved_without_error_content(
    tmp_path: Path,
) -> None:
    persist_original_capture_startup_failure(
        tmp_path,
        run_id=RUN,
        run_attempt=ATTEMPT,
        head_sha=HEAD,
        error=OSError("private-path-do-not-share"),
    )
    marker = tmp_path / STARTUP_FAILURE_FILE
    raw = marker.read_text()
    assert "private-path-do-not-share" not in raw
    result = _diagnose(tmp_path)
    assert result["diagnostic_reason"] == "recorder_initialization_failed"
    assert result["startup_exception_class"] == "OSError"
    assert result["startup_failure_marker_matches_worker"] is True
    assert result["original_capture_root_exists"] is False
    assert marker.read_text() == raw
    _assert_research_denied(result)


def test_startup_forgery_from_other_worker_fails_identity_parity(
    tmp_path: Path,
) -> None:
    persist_original_capture_startup_failure(
        tmp_path,
        run_id="38842093624",
        run_attempt=ATTEMPT,
        head_sha=HEAD,
        error=ValueError("not admissible"),
    )
    report = _diagnose(tmp_path)
    assert report["diagnostic_reason"] == "startup_failure_identity_mismatch"
    assert report["startup_failure_marker_matches_worker"] is False
    assert report["startup_exception_class"] is None
    _assert_research_denied(report)


@pytest.mark.parametrize("failure", [
    "original_capture_queue_overflow",
    "original_received_clock_regression",
    "write_failed:OSError",
    "offer_after_close",
    None,
])
def test_original_incomplete_terminal_and_record_counts_remain_visible(
    tmp_path: Path, failure: str | None,
) -> None:
    capture = tmp_path / "capture"
    capture.mkdir()
    original = capture / RECORD_FILE
    original.write_bytes(b'{"original":true}\n')
    (capture / TERMINAL_FILE).write_text(json.dumps({
        "run_id": RUN,
        "run_attempt": ATTEMPT,
        "head_sha": HEAD,
        "complete": False,
        "failure": failure,
        "offered_count": 17,
        "written_count": 13,
        "dropped_count": 4,
        "original_received_clock_regressions": 1,
    }))
    bytes_before = original.read_bytes()
    report = _diagnose(tmp_path)
    assert report["diagnostic_reason"] == (
        f"capture_terminal_incomplete:{failure or 'unknown'}"
    )
    assert report["original_offered_count"] == 17
    assert report["original_written_count"] == 13
    assert report["original_dropped_count"] == 4
    assert report["original_receive_clock_regressions"] == 1
    assert report["original_journal_byte_count"] == len(bytes_before)
    assert original.read_bytes() == bytes_before
    _assert_research_denied(report)


def test_negative_terminal_keeps_clock_cause_and_unacknowledged_offers(
    tmp_path: Path,
) -> None:
    capture = tmp_path / "capture"
    capture.mkdir()
    (capture / RECORD_FILE).write_bytes(b'{"original":true}\\n')
    (capture / TERMINAL_FILE).write_text(json.dumps({
        "run_id": RUN, "run_attempt": ATTEMPT, "head_sha": HEAD,
        "complete": False,
        "failure": "original_received_clock_regression",
        "offered_count": 9,
        "written_count": 6,
        "dropped_count": 2,
        "offered_not_written_or_dropped_count": 1,
        "original_received_clock_regressions": 2,
        "regressions_vs_prior_offered": 2,
        "regressions_vs_paper_clock": 1,
        "max_original_clock_backward_ms": 120,
        "first_regression_cause": "both_prior_input_and_paper_clock",
        "first_regression_event_kind": "l2_book",
    }))
    report = _diagnose(tmp_path)
    assert report["original_offered_not_written_or_dropped_count"] == 1
    assert report["original_regressions_vs_prior_offered"] == 2
    assert report["original_regressions_vs_paper_clock"] == 1
    assert report["original_max_clock_backward_ms"] == 120
    assert report["original_first_regression_cause"] == (
        "both_prior_input_and_paper_clock"
    )
    assert report["original_first_regression_event_kind"] == "l2_book"
    _assert_research_denied(report)


def test_foreign_terminal_never_exposes_original_clock_cause(
    tmp_path: Path,
) -> None:
    capture = tmp_path / "capture"
    capture.mkdir()
    (capture / TERMINAL_FILE).write_text(json.dumps({
        "run_id": "9999999999", "run_attempt": ATTEMPT, "head_sha": HEAD,
        "first_regression_cause": "paper_previous_clock",
        "regressions_vs_paper_clock": 123,
        "max_original_clock_backward_ms": 123,
        "offered_not_written_or_dropped_count": 123,
    }))
    report = _diagnose(tmp_path)
    assert report["diagnostic_reason"] == "terminal_identity_mismatch"
    assert report["original_first_regression_cause"] is None
    assert report["original_regressions_vs_paper_clock"] is None
    assert report["original_max_clock_backward_ms"] is None
    assert report["original_offered_not_written_or_dropped_count"] is None
    _assert_research_denied(report)


def test_matching_terminal_without_original_journal_stays_blocked(
    tmp_path: Path,
) -> None:
    capture = tmp_path / "capture"
    capture.mkdir()
    (capture / TERMINAL_FILE).write_text(json.dumps({
        "run_id": RUN, "run_attempt": ATTEMPT, "head_sha": HEAD,
        "complete": True, "failure": None,
        "offered_count": 1, "written_count": 1, "dropped_count": 0,
    }))
    result = _diagnose(tmp_path)
    assert result["diagnostic_reason"] == (
        "complete_receipt_missing_original_journal"
    )
    _assert_research_denied(result)


def test_terminal_from_other_worker_is_never_attributed_to_this_run(
    tmp_path: Path,
) -> None:
    capture = tmp_path / "capture"
    capture.mkdir()
    (capture / TERMINAL_FILE).write_text(json.dumps({
        "run_id": "100", "run_attempt": ATTEMPT, "head_sha": HEAD,
        "complete": True,
    }))
    report = _diagnose(tmp_path)
    assert report["diagnostic_reason"] == "terminal_identity_mismatch"
    assert report["original_offered_count"] is None
    _assert_research_denied(report)


def test_complete_local_receipt_never_certifies_source_from_diagnostics(
    tmp_path: Path,
) -> None:
    capture = tmp_path / "capture"
    capture.mkdir()
    (capture / RECORD_FILE).write_bytes(b'{"original":true}\n')
    (capture / TERMINAL_FILE).write_text(json.dumps({
        "run_id": RUN, "run_attempt": ATTEMPT, "head_sha": HEAD,
        "complete": True,
        "offered_count": 1, "written_count": 1,
        "failure": None, "dropped_count": 0,
    }))
    report = _diagnose(tmp_path)
    assert report["diagnostic_reason"] == (
        "local_capture_terminal_complete_needs_external_audit"
    )
    _assert_research_denied(report)


def test_actual_paper_workflow_uploads_negative_v3_diagnostic_after_handoff() -> None:
    workflow = Path(".github/workflows/continuous-paper.yml").read_text()
    seal = workflow.index("- name: Seal frozen v3 original microstructure source")
    source_upload = workflow.index(
        "- name: Upload frozen v3 original microstructure source"
    )
    diagnose = workflow.index("- name: Diagnose frozen v3 original capture after handoff")
    upload = workflow.index("- name: Upload frozen v3 original capture diagnostic")
    assert seal < source_upload < diagnose < upload
    assert "diagnose_original_paper_v3_capture.py" in workflow
    assert "continuous-paper-v3-source-diagnostic-" in workflow
    assert "steps.diagnose_v3_original_capture.outcome == 'success'" in workflow
    assert 'V3_CAPTURE_ORIGINAL_SOURCE: "1"' in workflow
    assert "original_paper_v3_capture.py" in workflow
    assert "live_orders_enabled: true" not in workflow

def test_original_v3_seal_and_negative_diagnostic_precede_expensive_handoff_research() -> None:
    workflow = Path(".github/workflows/continuous-paper.yml").read_text()
    fast = workflow.index("- name: Queue exact successor from fast resume")
    fallback = workflow.index(
        "- name: Queue fallback exact successor continuous paper worker"
    )
    seal = workflow.index("- name: Seal frozen v3 original microstructure source")
    upload = workflow.index("- name: Upload frozen v3 original microstructure source")
    diagnose = workflow.index("- name: Diagnose frozen v3 original capture after handoff")
    diagnostic_upload = workflow.index(
        "- name: Upload frozen v3 original capture diagnostic"
    )
    deferred = workflow.index(
        "- name: Audit all closed paper trades and recorded entry-to-exit charts"
    )
    large_rebuild = workflow.index(
        "- name: Rebuild deferred full-stack markouts after handoff"
    )
    assert fast < fallback < seal < upload < diagnose < diagnostic_upload
    assert diagnostic_upload < deferred < large_rebuild
    assert "steps.seal_v3_original_source.outcome == 'success'" in (
        workflow[seal:upload + 300]
    )
    assert "steps.diagnose_v3_original_capture.outcome == 'success'" in (
        workflow[diagnose:diagnostic_upload + 300]
    )
    assert "always()" in workflow[seal:upload]
    assert "continuous-paper-v3-microstructure-" in workflow[upload:diagnose]
    assert "continuous-paper-v3-source-diagnostic-" in (
        workflow[diagnostic_upload:deferred]
    )
    assert "live_orders_enabled: true" not in (
        workflow[fallback:diagnostic_upload]
    )
