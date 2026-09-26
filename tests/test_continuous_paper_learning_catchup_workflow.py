from pathlib import Path

WORKFLOW = Path(".github/workflows/continuous-paper-learning-catchup.yml")


def _workflow() -> str:
    assert WORKFLOW.is_file()
    return WORKFLOW.read_text(encoding="utf-8")


def test_continuous_paper_learning_catchup_is_scheduled_and_reactive() -> None:
    source = _workflow()
    assert "Continuous Paper Learning Catch-up" in source
    assert 'cron: "*/15 * * * *"' in source
    assert '"Continuous Mainnet Paper Trader"' in source
    assert '"Continuous Paper Learning Evidence Sync"' in source
    assert "workflow_dispatch:" in source
    assert "actions: write" in source


def test_continuous_paper_learning_catchup_requires_lineage_capable_artifact() -> None:
    source = _workflow()
    assert "continuous-paper-state-{run_id}-{attempt}" in source
    assert 'name.startswith("learning-features/records/")' in source
    assert 'name.startswith("opening-lineage/records/")' in source
    assert 'digest.startswith("sha256:")' in source
    assert 'run.get("conclusion") != "success"' in source


def test_continuous_paper_learning_catchup_compares_trusted_receipt() -> None:
    source = _workflow()
    assert "continuous-paper-learning-state" in source
    assert "last-source-receipt.json" in source
    assert 'receipt.get("source_kind") != "continuous_paper_worker"' in source
    assert 'receipt.get("research_only") is not True' in source
    assert 'receipt.get("promotion_eligible") is not False' in source
    assert 'receipt.get("execution_ready") is not False' in source


def test_continuous_paper_learning_catchup_dispatches_only_missing_sync() -> None:
    source = _workflow()
    assert "newest lineage-capable paper worker is already in learning state" in source
    assert "continuous-paper learning sync already active" in source
    assert "continuous-paper-learning-evidence.yml/dispatches" in source
    assert 'inputs[upstream_run_id]=$LATEST_WORKER_RUN_ID' in source
    assert "private_key" not in source.lower()
    assert "withdraw" not in source.lower()
    assert "transfer" not in source.lower()
