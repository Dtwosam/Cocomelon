from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/research-campaign-scheduled.yml")


def test_research_capture_aligns_before_acquisition_and_rechecks_v4() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    capture_start = source.index("  capture-control:\n")
    candidate_start = source.index("  candidate-decisions:\n")
    capture = source[capture_start:candidate_start]

    assert "timeout-minutes: 65" in capture
    assert "actions: read" in capture
    assert "Align research capture to deterministic decision epoch" in capture
    assert "research_capture_wait_ms" in capture
    assert "time.time_ns() // 1_000_000" in capture
    assert 'sleep "$WAIT_SECONDS"' in capture
    assert "Recheck V4 acquisition after deterministic alignment" in capture
    assert "evidence-campaign-v4-scheduled.yml/runs?per_page=100" in capture
    assert "protected V4 acquisition became active during research alignment" in capture

    align_index = capture.index("Align research capture to deterministic decision epoch")
    recheck_index = capture.index("Recheck V4 acquisition after deterministic alignment")
    acquire_index = capture.index("Acquire one public mainnet research cohort")
    assert align_index < recheck_index < acquire_index


def test_alignment_does_not_change_research_or_v4_economics() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    cohort = Path("src/cocomelon/research/cohort.py").read_text(encoding="utf-8")
    bootstrap = Path("src/cocomelon/research/bootstrap.py").read_text(encoding="utf-8")

    assert "RESEARCH_ENTRY_WINDOW_MS = 300_000" in cohort
    assert "RESEARCH_MAX_POSITION_AGE_MS = 1_200_000" in cohort
    assert "RESEARCH_CAPTURE_SECONDS = 1_800" in cohort
    assert '"risk_per_trade": str(_BOOTSTRAP_RISK_PER_TRADE)' in bootstrap
    assert "--seconds 1800" in workflow

    v4 = Path(".github/workflows/evidence-campaign-v4-scheduled.yml").read_text(
        encoding="utf-8"
    )
    assert 'ENTRY_WINDOW_SECONDS: 2700' in v4
    assert 'CAPTURE_WINDOW_SECONDS: 18900' in v4
    assert 'MAX_POSITION_AGE_SECONDS: 14400' in v4
