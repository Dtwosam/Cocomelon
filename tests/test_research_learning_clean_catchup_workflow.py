from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/research-learning-clean-catchup.yml")


def test_clean_catchup_has_bounded_recurring_and_event_wakeups() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "Research Learning Clean Catch-up" in source
    assert 'cron: "*/10 * * * *"' in source
    assert "Research Learning Clean State Bootstrap" in source
    assert "Research Learning Clean State Campaign Follower" in source
    assert "types: [completed]" in source
    assert "workflow_dispatch:" in source
    assert "actions: write" in source
    assert "cancel-in-progress: false" in source


def test_clean_catchup_restores_only_trusted_latest_lineages() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "research-learning-clean-state-[1-9][0-9]*-[1-9][0-9]*" in source
    assert ".github/workflows/research-learning-clean-state-bootstrap.yml" in source
    assert ".github/workflows/research-learning-clean-state-sync.yml" in source
    assert 'run.get("status") != "completed"' in source
    assert 'run.get("name") != contract["name"]' in source
    assert 'run.get("conclusion") != "success"' in source
    assert 'run.get("head_branch") != "main"' in source
    assert 'run.get("head_sha")' in source
    assert "trusted clean-state artifact digest is missing" in source


def test_clean_catchup_chooses_one_oldest_missing_campaign() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "cocomelon-learning-clean-sequence" in source
    assert 'payload.get("action") == "missing_campaign"' in source
    assert "created_ms, run_id, run_attempt = min(missing)" in source
    assert '"repair_needed": True' in source
    assert "missing campaign run attempt changed" in source
    assert "missing campaign artifact is unavailable or ambiguous" in source
    assert "missing campaign artifact digest is invalid" in source
    assert "repaired stages this pass: 1" in source


def test_clean_catchup_avoids_duplicate_active_follower_dispatch() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "research-learning-clean-state-sync.yml/runs?per_page=100" in source
    assert '.status == "queued" or .status == "in_progress"' in source
    assert "clean-state follower already active; deferring repair" in source
    assert "research-learning-clean-state-sync.yml/dispatches" in source
    assert '"upstream_run_id": os.environ["RUN_ID"]' in source


def test_clean_catchup_remains_research_only() -> None:
    source = WORKFLOW.read_text(encoding="utf-8").lower()

    assert "api.hyperliquid" not in source
    assert "live_execution" not in source
    assert "promotion authorized: false" in source
    assert "execution enabled: false" in source
    assert "research-only: true" in source
