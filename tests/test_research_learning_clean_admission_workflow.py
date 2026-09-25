from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/research-learning-clean-admission.yml")


def test_clean_admission_follows_successful_autonomous_cycle() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "Research Learning Clean Admission" in source
    assert 'workflows: ["Research Autonomous Learning Cycle"]' in source
    assert "types: [completed]" in source
    assert "workflow_dispatch:" in source
    assert "upstream_run_id:" in source
    assert "contents: read" in source
    assert "actions: read" in source
    assert "actions: write" not in source


def test_clean_admission_reauthenticates_exact_cycle_run_and_artifact() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert 'run.get("head_branch") != "main"' in source
    assert 'run.get("status") != "completed"' in source
    assert 'run.get("conclusion") != "success"' in source
    assert (
        'run.get("path") != ".github/workflows/research-learning-cycle.yml"'
        in source
    )
    assert 'run.get("name") != "Research Autonomous Learning Cycle"' in source
    assert '(run.get("head_repository") or {}).get("full_name")' not in source
    assert 'repository.get("full_name") != os.environ["GITHUB_REPOSITORY"]' in source
    assert "research-learning-cycle-[1-9][0-9]*-[1-9][0-9]*" in source
    assert "multiple autonomous learning cycle artifacts found" in source
    assert "artifact.get(\"digest\")" in source


def test_clean_admission_materializes_only_qualified_frozen_candidates() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "for LABEL in baseline tree" in source
    assert "_qualifies_development" in source
    assert "cocomelon-learning-candidate-package" in source
    assert "cocomelon-learning-clean-validation-spec" in source
    assert "candidate identity changed during admission" in source
    assert "has a freeze despite failing development qualification" in source
    assert "not-ready learning cycle unexpectedly contains frozen candidates" in source
    assert ".prospective_only == true" in source
    assert ".research_only == true" in source
    assert ".promotion_eligible == false" in source
    assert ".execution_ready == false" in source


def test_clean_admission_publishes_immutable_research_artifact_only() -> None:
    source = WORKFLOW.read_text(encoding="utf-8").lower()

    assert "research-learning-clean-admission-" in source
    assert "retention-days: 90" in source
    assert "cocomelon-learning-candidate-predict" not in source
    assert "cocomelon-learning-clean-validation-score" not in source
    assert "api.hyperliquid" not in source
    assert "execution enabled: false" in source
