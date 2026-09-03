from __future__ import annotations

from pathlib import Path

RESEARCH_WORKFLOW = Path(".github/workflows/research-campaign-scheduled.yml")
V4_WORKFLOW = Path(".github/workflows/evidence-campaign-v4-scheduled.yml")


def test_research_capture_uses_current_control_with_unique_source_identity() -> None:
    source = RESEARCH_WORKFLOW.read_text(encoding="utf-8")

    assert "SOURCE_ID: research-mainnet-${{ github.run_id }}-${{ github.run_attempt }}" in source
    assert "Checkout trusted research capture control revision" in source
    assert "ref: ${{ github.sha }}" in source
    assert "cocomelon record-mainnet-evidence" in source


def test_research_capture_timeout_has_alignment_headroom() -> None:
    source = RESEARCH_WORKFLOW.read_text(encoding="utf-8")
    capture_job = source.split("\n  capture-control:\n", 1)[1].split("\n  candidate-decisions:\n", 1)[0]

    assert "timeout-minutes: 60" in capture_job
    assert "--seconds 1800" in capture_job


def test_v4_remains_pinned_and_cannot_enter_research_alignment_path() -> None:
    source = V4_WORKFLOW.read_text(encoding="utf-8")

    assert "COHORT_CODE_REVISION: 0c14c9cfa37c80babc65d050fed6d4465dcb9032" in source
    assert "ref: 0c14c9cfa37c80babc65d050fed6d4465dcb9032" in source
    assert "SOURCE_ID:" not in source
    assert 'ENTRY_WINDOW_SECONDS: 2700' in source
    assert 'CAPTURE_WINDOW_SECONDS: 18900' in source
    assert 'MAX_POSITION_AGE_SECONDS: 14400' in source


def test_alignment_does_not_change_research_economics() -> None:
    workflow = RESEARCH_WORKFLOW.read_text(encoding="utf-8")
    cohort = Path("src/cocomelon/research/cohort.py").read_text(encoding="utf-8")
    bootstrap = Path("src/cocomelon/research/bootstrap.py").read_text(encoding="utf-8")

    assert "RESEARCH_ENTRY_WINDOW_MS = 300_000" in cohort
    assert "RESEARCH_MAX_POSITION_AGE_MS = 1_200_000" in cohort
    assert "RESEARCH_CAPTURE_SECONDS = 1_800" in cohort
    assert '"risk_per_trade": str(_BOOTSTRAP_RISK_PER_TRADE)' in bootstrap
    assert "--seconds 1800" in workflow
