from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/research-learning-catchup.yml")


def _source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_learning_catchup_is_bounded_and_post_activation_only() -> None:
    source = _source()

    assert "Research Learning Catch-up" in source
    assert 'cron: "*/10 * * * *"' in source
    assert "workflow_run:" in source
    assert '"Scheduled Research Mainnet Replay Campaign"' in source
    assert '"Research Learning Evidence Sync"' in source
    assert "types: [completed]" in source
    assert "workflow_dispatch:" in source
    assert 'LEARNING_PIPELINE_ACTIVATED_AT_UTC: "2026-09-25T15:28:46Z"' in source
    assert "research-campaign-scheduled.yml" in source
    assert 'run["created_at"] >= activation' in source
    assert "newest successful post-activation research campaign" in source


def test_learning_catchup_repairs_one_stage_at_a_time() -> None:
    source = _source()

    sync_dispatch = source.index(
        "/actions/workflows/research-learning-evidence.yml/dispatches"
    )
    cycle_dispatch = source.index(
        "/actions/workflows/research-learning-cycle.yml/dispatches"
    )
    assert sync_dispatch < cycle_dispatch
    assert "exit 0" in source[sync_dispatch:cycle_dispatch]
    assert '-f upstream_run_id="$LATEST_CAMPAIGN_RUN_ID"' in source
    assert '-f upstream_run_id="$LATEST_SYNC_RUN_ID"' in source


def test_learning_catchup_uses_cumulative_state_and_skips_zero_new_records() -> None:
    source = _source()

    assert "research-learning-state" in source
    assert "last-sync.json" in source
    assert "created_records == 0" in source
    assert "research-learning-cycle-${LATEST_SYNC_RUN_ID}-${LATEST_SYNC_RUN_ATTEMPT}" in source
    assert "latest trusted learning state" in source


def test_learning_catchup_is_control_plane_only() -> None:
    source = _source().lower()

    assert "actions: write" in source
    assert "contents: read" in source
    assert "api.hyperliquid" not in source
    assert "testnet" not in source
    assert "live_execution" not in source
    assert "cocomelon-learning-experiment" not in source
    assert "cocomelon-learning-cycle " not in source


def test_learning_catchup_event_triggers_are_wakeups_not_trusted_inputs() -> None:
    source = _source()

    assert "github.event.workflow_run.id" not in source
    assert "github.event.workflow_run.head_sha" not in source
    assert "Find newest successful post-activation research campaign" in source
    assert "/actions/workflows/research-learning-evidence.yml/dispatches" in source
    assert "/actions/workflows/research-learning-cycle.yml/dispatches" in source
