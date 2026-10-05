from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(
    ".github/workflows/prospective-range-compression-entry-evidence.yml"
)


def _source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_range_compression_evidence_workflow_is_research_only() -> None:
    source = _source()

    assert "Prospective Range-Compression Entry Evidence" in source
    assert "workflow_dispatch:" in source
    assert "workflow_run:" not in source
    assert "push:" not in source
    assert "paper_run_is_evidence_eligible()" in source
    assert "steps.source.outputs.source_eligible == 'true'" in source
    assert "actions: read" in source
    assert "contents: read" in source
    assert "issues: write" in source
    assert "actions: write" not in source
    assert 'EVIDENCE_ISSUE: "924"' in source
    assert "COCOMELON_EXECUTION_MODE" not in source
    assert "**Execution authority:**" in source
    assert "**Promotion authority:**" in source
    assert "**LIVE TRADING: DISABLED.**" in source


def test_range_compression_evidence_binds_exact_compact_source() -> None:
    source = _source()

    assert (
        'run.get("path") != ".github/workflows/continuous-paper.yml"'
        in source
    )
    assert 'run.get("head_branch") != "main"' in source
    assert 'run.get("status") != "completed"' in source
    assert 'run.get("conclusion") not in {"success", "failure"}' in source
    assert "source run attempt mismatch" in source
    assert "source repository mismatch" in source
    assert "source artifact digest is missing or invalid" in source
    assert "journal.sqlite3" in source
    assert "prospective-range-compression-entry-state.json" in source
    assert "learning-features" in source
    assert "--source-head-sha" in source
    assert "Fail closed on upgrade handoff source" in source


def test_range_compression_evidence_is_append_only() -> None:
    source = _source()

    assert "prospective-range-compression-entry-evidence-" in source
    assert "prospective-range-compression-entry-evidence.json" in source
    assert (
        "update_prospective_range_compression_entry_evidence.py"
        in source
    )
    assert "--previous" in source
    assert "append-only invariant failure" in source
    assert "Fail closed on range-compression evidence drift" in source
    assert "Every previously published trade row" in source
    assert "evidence SHA-256" in source
    assert "Range 15m" in source


def test_continuous_paper_dispatches_exact_range_evidence() -> None:
    source = Path(
        ".github/workflows/continuous-paper.yml"
    ).read_text(encoding="utf-8")

    assert "Queue exact range-compression entry evidence" in source
    assert (
        "gh workflow run "
        "prospective-range-compression-entry-evidence.yml"
        in source
    )
    assert '-f "source_run_id=$GITHUB_RUN_ID"' in source
    assert '-f "source_run_attempt=$GITHUB_RUN_ATTEMPT"' in source
    assert "steps.compact_learning_upload.outcome == 'success'" in source
