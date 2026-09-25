from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/research-learning-clean-state-bootstrap.yml")


def test_clean_state_bootstrap_follows_successful_clean_admission() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "Research Learning Clean State Bootstrap" in source
    assert 'workflows: ["Research Learning Clean Admission"]' in source
    assert "types: [completed]" in source
    assert "workflow_dispatch:" in source
    assert "upstream_run_id:" in source
    assert "contents: read" in source
    assert "actions: read" in source
    assert "actions: write" not in source


def test_clean_state_bootstrap_reauthenticates_exact_admission_artifact() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert 'run.get("head_branch") != "main"' in source
    assert 'run.get("status") != "completed"' in source
    assert 'run.get("conclusion") != "success"' in source
    assert (
        'run.get("path") != ".github/workflows/research-learning-clean-admission.yml"'
        in source
    )
    assert 'run.get("name") != "Research Learning Clean Admission"' in source
    assert 'repository.get("full_name") != os.environ["GITHUB_REPOSITORY"]' in source
    assert "research-learning-clean-admission-[1-9][0-9]*-[1-9][0-9]*" in source
    assert "multiple clean admission artifacts found" in source
    assert "clean admission artifact digest is missing" in source


def test_clean_state_bootstrap_creates_empty_verified_evidence_state() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "cocomelon-learning-clean-state" in source
    assert ".prediction_count == 0" in source
    assert ".settled_outcome_count == 0" in source
    assert ".unsettled_trade_prediction_count == 0" in source
    assert '.status == "waiting_for_validation_start"' in source
    assert '.status == "collecting"' in source
    assert "bootstrapped candidate count does not match admission" in source
    assert "source_admission_id" in source


def test_clean_state_bootstrap_is_operational_only() -> None:
    source = WORKFLOW.read_text(encoding="utf-8").lower()

    assert "research-learning-clean-state-" in source
    assert "retention-days: 90" in source
    assert "cocomelon-learning-candidate-predict" not in source
    assert "cocomelon-learning-clean-validation-score" not in source
    assert "api.hyperliquid" not in source
    assert "promotion authorized: false" in source
    assert "execution enabled: false" in source
