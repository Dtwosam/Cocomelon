from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/research-learning-cycle.yml")


def _source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_learning_cycle_workflow_follows_successful_learning_sync() -> None:
    source = _source()

    assert "Research Autonomous Learning Cycle" in source
    assert 'workflows: ["Research Learning Evidence Sync"]' in source
    assert "types: [completed]" in source
    assert "workflow_dispatch:" in source
    assert "upstream_run_id:" in source
    assert "github.event.workflow_run.conclusion == 'success'" in source
    assert "github.event.workflow_run.head_branch == 'main'" in source
    assert "github.event_name == 'workflow_dispatch'" in source
    assert 'inputs.upstream_run_id' in source
    assert "\n  schedule:" not in source


def test_learning_cycle_workflow_binds_exact_state_artifact_and_protocol() -> None:
    source = _source()

    assert "research-learning-state" in source
    assert "cocomelon-learning-cycle" in source
    assert "last-sync.json" in source
    assert "readiness.json" in source
    assert "git rev-parse HEAD" in source
    assert "expected-learning-state-digest" in source
    assert "expected-feature-state-digest" in source
    assert 'run.get("id") != int(os.environ["RUN_ID"])' in source
    assert 'run.get("head_sha")' in source


def test_learning_cycle_workflow_remains_research_only() -> None:
    source = _source().lower()

    assert 'cocomelon_execution_mode: paper' in source
    assert 'python -m pip install -e ".[research]"' in source
    assert "api.hyperliquid" not in source
    assert "testnet" not in source
    assert "live_execution" not in source
    assert "promotion_eligible" in source
    assert "cocomelon-learning-experiment " not in source
