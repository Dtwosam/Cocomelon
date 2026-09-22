from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/prospective-hype-clean.yml")


def test_prospective_hype_workflow_is_paper_only_and_read_only() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "COCOMELON_EXECUTION_MODE: paper" in source
    assert "https://api.hyperliquid.xyz" in source
    assert "testnet" not in source.lower()
    assert "COCOMELON_LIVE_ACK" not in source
    assert "contents: read" in source
    assert "actions: read" in source
    assert "contents: write" not in source
    assert "actions: write" not in source
    assert "wallet" not in source.lower()
    assert "private key" not in source.lower()
    assert "place_order" not in source
    assert "submit_order" not in source


def test_prospective_hype_workflow_runs_redundant_early_hour_attempts() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert 'cron: "3,8,13 * * * *"' in source
    assert "workflow_dispatch:" in source
    assert "cancel-in-progress: false" in source
    assert "github.ref == 'refs/heads/main'" in source
    assert "timeout-minutes: 10" in source


def test_prospective_hype_workflow_restores_and_republishes_cumulative_state() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "prospective-hype-clean-state" in source
    assert "actions/artifacts?name=$STATE_ARTIFACT_NAME" in source
    assert '.workflow_run.head_branch == "main"' in source
    assert "actions/upload-artifact@v7" in source
    assert "retention-days: 90" in source
    assert "state_digest" in source
    assert "prospective_clean" in source
    assert "promotion_eligible" in source
    assert "cocomelon-prospective-hype-observer" in source


def test_prospective_hype_workflow_keeps_per_run_receipt_separate() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "prospective-hype-clean-run-${{ github.run_id }}" in source
    assert "/tmp/prospective-hype-cycle.json" in source
    assert "GITHUB_STEP_SUMMARY" in source
