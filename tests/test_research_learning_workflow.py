from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/research-learning-evidence.yml")


def _source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_research_learning_workflow_follows_completed_research_campaigns() -> None:
    source = _source()

    assert "Research Learning Evidence Sync" in source
    assert 'workflows: ["Scheduled Research Mainnet Replay Campaign"]' in source
    assert "types: [completed]" in source
    assert "workflow_dispatch:" in source
    assert "upstream_run_id:" in source
    assert "\n  schedule:" not in source
    assert "github.event.workflow_run.conclusion == 'success'" in source
    assert "github.event.workflow_run.head_branch == 'main'" in source
    assert "github.event_name == 'workflow_dispatch'" in source
    assert 'inputs.upstream_run_id' in source


def test_research_learning_workflow_restores_and_publishes_cumulative_state() -> None:
    source = _source()

    assert "research-learning-state" in source
    assert "cocomelon-research-learning-sync" in source
    assert "cocomelon-learning-readiness" in source
    assert "learning-state/ledger" in source
    assert "learning-state/features" in source
    assert "research-campaign-${RUN_ID}-${RUN_ATTEMPT}" in source
    assert 'run.get("id") != int(os.environ["RUN_ID"])' in source
    assert 'run.get("head_sha")' in source


def test_research_learning_workflow_remains_observational_and_paper_only() -> None:
    source = _source().lower()

    assert "cocomelon_execution_mode: paper" in source
    assert "api.hyperliquid" not in source
    assert "testnet" not in source
    assert "live_execution" not in source
    assert "cocomelon-learning-experiment" not in source
    assert "cocomelon-learning-tree" not in source
    assert "promotion_eligible" not in source
