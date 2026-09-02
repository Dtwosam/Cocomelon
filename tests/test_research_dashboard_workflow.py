from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/research-dashboard.yml")


def _workflow() -> str:
    assert WORKFLOW.is_file(), "research dashboard workflow must exist"
    return WORKFLOW.read_text(encoding="utf-8")


def test_research_dashboard_refreshes_from_research_campaign_and_on_main_push() -> None:
    workflow = _workflow()

    assert "Cocomelon Research Dashboard Refresh" in workflow
    assert "workflow_run:" in workflow
    assert '"Scheduled Research Mainnet Replay Campaign"' in workflow
    assert "types: [completed]" in workflow
    assert "schedule:" in workflow
    assert "workflow_dispatch:" in workflow
    assert "push:" in workflow
    assert "branches: [main]" in workflow


def test_research_dashboard_is_research_only_and_can_update_issues() -> None:
    workflow = _workflow()

    assert "contents: read" in workflow
    assert "actions: read" in workflow
    assert "issues: write" in workflow
    assert "research-authoritative-registry" in workflow
    assert "research-campaign-scheduled.yml" in workflow
    assert "research-v4-registry-sync.yml" in workflow
    assert "v4-mainnet-corpus" not in workflow
    assert "phase9-v4" not in workflow.lower()


def test_research_dashboard_validates_registry_producer_before_rendering() -> None:
    workflow = _workflow()

    assert "head_branch == \"main\"" in workflow
    assert "status == \"completed\"" in workflow
    assert "workflow_run.head_sha" in workflow
    assert "research.sqlite3" in workflow
    assert "cocomelon-research-status" in workflow
    assert "--format markdown" in workflow


def test_research_dashboard_maintains_one_named_issue() -> None:
    workflow = _workflow()

    assert 'DASHBOARD_TITLE: "Cocomelon Research Dashboard"' in workflow
    assert "state=all" in workflow
    assert "pull_request" in workflow
    assert "matching research dashboard issues" in workflow
    assert "gh api --method POST" in workflow
    assert "gh api --method PATCH" in workflow
    assert "TOUCHED / NON-PROMOTIONAL" in workflow


def test_research_dashboard_issue_lookup_fails_closed_before_creation() -> None:
    workflow = _workflow()

    assert 'ISSUE_NUMBERS_TEXT="$(' in workflow
    assert 'if [ -n "$ISSUE_NUMBERS_TEXT" ]; then' in workflow
    assert "mapfile -t ISSUE_NUMBERS < <(" not in workflow
