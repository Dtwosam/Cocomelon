from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(
    ".github/workflows/prospective-side-conditioned-timing-ledger.yml"
)


def test_timing_ledger_workflow_is_pinned_and_research_only() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "Prospective Side-Conditioned Timing Ledger" in source
    assert "Prospective Side-Conditioned Timing Audit" in source
    assert "c5861658158014b359d9e00a67be96f8ba42275e" in source
    assert 'TIMING_LEDGER_ISSUE: "692"' in source
    assert "actions: read" in source
    assert "contents: read" in source
    assert "issues: write" in source
    assert "continuous-paper-side-conditioned-timing-" in source
    assert "update_prospective_side_conditioned_timing_ledger.py" in source
    assert "gh workflow run" not in source
    assert "COCOMELON_EXECUTION_MODE" not in source


def test_timing_ledger_workflow_uses_safe_artifact_transport() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "| @tsv" in source
    assert 'then "(.[0].id)' not in source
    assert 'then "\\(.[0].id)' not in source
    assert "Prospective timing append-only ledger is blocked." in source
    assert "No timing-ledger evidence is published" in source
