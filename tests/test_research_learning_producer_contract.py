from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/research-campaign-scheduled.yml")
COHORT = Path("src/cocomelon/research/cohort.py")


def test_scheduled_paper_producer_materializes_authenticated_learning_features() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    cohort = COHORT.read_text(encoding="utf-8")

    assert "complete_research_cohort(" in workflow
    assert 'feature_store_path=output / "learning-features"' in cohort
    assert '"learning-features",' in cohort
    assert '"feature_snapshot_count": feature_snapshot_count' in cohort
    assert '"feature_snapshot_state_digest": feature_snapshot_state_digest' in cohort
    assert "research replay feature snapshot coverage is incomplete" in cohort


def test_learning_feature_capture_remains_inside_trusted_completion_code() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    evaluation = workflow.split("- name: Evaluate fanout candidates serially", 1)[1].split(
        "- name: Render research decision throughput summary",
        1,
    )[0]

    assert "complete_research_cohort(" in evaluation
    assert "control-src" in workflow
    assert "candidate-src" not in evaluation
    assert "COCOMELON_EXECUTION_MODE: paper" in workflow
