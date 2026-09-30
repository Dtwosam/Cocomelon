from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(
    ".github/workflows/prospective-cadence-comparison-ledger.yml"
)


def test_paired_ledger_workflow_is_research_only() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "Prospective Cadence A/B Ledger" in source
    assert "Prospective Cadence Model Comparison" in source
    assert "actions: read" in source
    assert "contents: read" in source
    assert "issues: write" in source
    assert 'COMPARISON_LEDGER_ISSUE: "690"' in source
    assert "cadence-model-comparison-" in source
    assert "update_cadence_prospective_comparison_ledger.py" in source
    assert "continuous-paper.yml" not in source
    assert "gh workflow run" not in source
    assert "COCOMELON_EXECUTION_MODE" not in source


def test_paired_ledger_uses_safe_artifact_identity_transport() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "| @tsv" in source
    assert 'then "(.[0].id)' not in source
    assert 'then "\\(.[0].id)' not in source
    assert "previous paired row" not in source
    assert "append-only invariant failure" in source
