from pathlib import Path

WORKFLOW = Path(".github/workflows/continuous-paper-learning-evidence.yml")


def test_continuous_paper_learning_workflow_authenticates_exact_worker_artifact() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert 'workflows: ["Continuous Mainnet Paper Trader"]' in source
    assert "group: continuous-paper-learning-evidence-sync" in source
    assert 'run.get("path") != ".github/workflows/continuous-paper.yml"' in source
    assert 'run.get("name") != "Continuous Mainnet Paper Trader"' in source
    assert 'continuous-paper-state-${RUN_ID}-${RUN_ATTEMPT}' in source
    assert 'digest.startswith("sha256:")' in source
    assert "learning-features/records" in source
    assert "opening-lineage/records" in source


def test_continuous_paper_learning_workflow_is_research_only_and_durable() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "cocomelon-continuous-paper-learning-sync" in source
    assert "cocomelon-learning-readiness" in source
    assert "continuous-paper-learning-state" in source
    assert "last-source-receipt.json" in source
    assert '"upstream_artifact_digest": os.environ["UPSTREAM_ARTIFACT_DIGEST"]' in source
    assert "retention-days: 90" in source
    assert "promotion eligible: false" in source
    assert "execution enabled: false" in source
    assert "private_key" not in source.lower()
    assert "withdraw" not in source.lower()
    assert "transfer" not in source.lower()
