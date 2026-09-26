from pathlib import Path

WORKFLOW = Path(".github/workflows/continuous-paper-learning-evidence.yml")


def _source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_continuous_learning_sync_follows_completed_paper_workers() -> None:
    source = _source()
    assert "Continuous Paper Learning Evidence Sync" in source
    assert 'workflows: ["Continuous Mainnet Paper Trader"]' in source
    assert "types: [completed]" in source
    assert "workflow_dispatch:" in source
    assert "continuous-paper-state-$RUN_ID-$RUN_ATTEMPT" in source
    assert "artifact_present=false" in source
    assert "Legacy pre-feature continuous paper worker" in source


def test_continuous_learning_sync_is_serialized_and_research_only() -> None:
    source = _source()
    assert "group: continuous-paper-learning-state" in source
    assert "cancel-in-progress: false" in source
    assert "cocomelon-continuous-paper-learning-sync" in source
    assert "cocomelon-learning-readiness" in source
    assert "continuous-paper-learning-state" in source
    assert "retention-days: 90" in source
    assert "research only: true" in source
    assert "promotion eligible: false" in source
    assert "execution ready: false" in source


def test_continuous_learning_sync_authenticates_main_worker_lineage() -> None:
    source = _source()
    assert 'run.get("path") != ".github/workflows/continuous-paper.yml"' in source
    assert 'run.get("head_branch") != "main"' in source
    assert 'run.get("conclusion") != "success"' in source
    assert 'repository.get("full_name") != os.environ["GITHUB_REPOSITORY"]' in source
    assert "upstream-artifact-digest" in source
    assert "feature_snapshot_state_digest" in source
