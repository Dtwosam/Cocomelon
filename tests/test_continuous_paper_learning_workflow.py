from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/continuous-paper-learning-evidence.yml")


def _source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_continuous_learning_follower_tracks_successful_paper_workers() -> None:
    source = _source()

    assert "Continuous Paper Learning Evidence Sync" in source
    assert 'workflows: ["Continuous Mainnet Paper Trader"]' in source
    assert "types: [completed]" in source
    assert "workflow_dispatch:" in source
    assert "upstream_run_id:" in source
    assert "github.event.workflow_run.conclusion == 'success'" in source
    assert "github.event.workflow_run.head_branch == 'main'" in source
    assert "\n  schedule:" not in source


def test_continuous_learning_follower_authenticates_exact_worker_artifact() -> None:
    source = _source()

    assert ".github/workflows/continuous-paper.yml" in source
    assert 'run.get("name") != "Continuous Mainnet Paper Trader"' in source
    assert 'run.get("head_repository")' in source
    assert "continuous-paper-state-${RUN_ID}-${RUN_ATTEMPT}" in source
    assert "expected exactly one continuous paper state artifact" in source
    assert "continuous paper artifact digest is missing" in source
    assert "learning-source.json" in source
    assert "session-summary.json" in source
    assert "journal.sqlite3" in source
    assert "learning-features" in source


def test_continuous_learning_follower_skips_legacy_worker_without_features() -> None:
    source = _source()

    assert "learning_enabled=$LEARNING_ENABLED" in source
    assert "worker predates authenticated continuous learning capture; no-op" in source
    assert "steps.upstream.outputs.learning_enabled == 'true'" in source
    assert "state mutated: false" in source


def test_continuous_learning_follower_updates_shared_research_state_only() -> None:
    source = _source()

    assert "group: research-learning-evidence-sync" in source
    assert "cocomelon-continuous-paper-learning-sync" in source
    assert "cocomelon-learning-readiness" in source
    assert "research-learning-state" in source
    assert ".github/workflows/research-learning-evidence.yml" in source
    assert ".github/workflows/continuous-paper-learning-evidence.yml" in source
    assert ".github/workflows/research-learning-state-continuity.yml" in source
    assert "retention-days: 90" in source


def test_continuous_learning_follower_cannot_trade_train_or_promote() -> None:
    source = _source().lower()

    assert "cocomelon_execution_mode: paper" in source
    assert "api.hyperliquid" not in source
    assert "testnet" not in source
    assert "live_execution" not in source
    assert "cocomelon-learning-cycle" not in source
    assert "cocomelon-learning-experiment" not in source
    assert "execution enabled: false" in source
    assert "research-only: true" in source
