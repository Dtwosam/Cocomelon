from __future__ import annotations

from pathlib import Path


def test_failure_receipt_workflow_is_research_only_and_append_only() -> None:
    source = Path(
        ".github/workflows/prospective-candidate-failure-receipts.yml"
    ).read_text(encoding="utf-8")

    assert "Prospective Trade Quality Readiness" in source
    assert "prospective-trade-quality-readiness-" in source
    assert "Restore previous first-failure receipts" in source
    assert "update_prospective_candidate_failure_receipts.py" in source
    assert "prospective-candidate-failure-receipts.json" in source
    assert 'RECEIPT_ISSUE: "702"' in source
    assert "actions: read" in source
    assert "contents: read" in source
    assert "issues: write" in source
    assert "workflow_dispatch" in source
    assert "schedule:" in source

    forbidden = (
        "continuous-paper.yml",
        "workflow_dispatch inputs confirm",
        "PaperExecutionAdapter",
        "live_orders: true",
    )
    assert all(item not in source for item in forbidden)
