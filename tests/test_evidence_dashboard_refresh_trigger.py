from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/evidence-dashboard.yml")


def test_dashboard_refreshes_after_its_main_branch_inputs_change() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "push:" in workflow
    assert "branches: [main]" in workflow
    assert "paths:" in workflow
    assert '".github/workflows/evidence-dashboard.yml"' in workflow
    assert '"scripts/build_evidence_dashboard.py"' in workflow
    assert '"scripts/apply_phase9_v3_final_verdict.py"' in workflow
    assert '"scripts/apply_v3_intake_diagnostics.py"' in workflow
