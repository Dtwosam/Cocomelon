from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/research-dashboard.yml")


def _workflow() -> str:
    assert WORKFLOW.is_file(), "research dashboard workflow must exist"
    return WORKFLOW.read_text(encoding="utf-8")


def test_research_dashboard_refreshes_from_trusted_producers_and_on_main_push() -> None:
    workflow = _workflow()

    assert "Cocomelon Research Dashboard Refresh" in workflow
    assert "workflow_run:" in workflow
    assert '"Scheduled Research Mainnet Replay Campaign"' in workflow
    assert '"Research V4 Acquisition Authority Sync"' in workflow
    assert '"Research Learning Evidence Sync"' in workflow
    assert '"Research Autonomous Learning Cycle"' in workflow
    assert '"Research Learning Clean State Bootstrap"' in workflow
    assert '"Research Learning Clean State Campaign Follower"' in workflow
    assert '"Research Learning Clean State Continuity"' in workflow
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


def test_research_dashboard_publishes_safe_bootstrap_state_without_registry() -> None:
    workflow = _workflow()

    assert 'printf \'false\\n\' > dashboard/registry-available.txt' in workflow
    assert 'printf \'true\\n\' > dashboard/registry-available.txt' in workflow
    assert 'if [ "$(cat dashboard/registry-available.txt)" = "true" ]; then' in workflow
    assert "No trusted research registry has been published yet." in workflow
    assert "Research economics are unavailable until" in workflow
    assert 'exit 65' not in workflow


def test_research_dashboard_includes_non_economic_learning_operations() -> None:
    workflow = _workflow()

    assert "research-learning-state" in workflow
    assert "research-learning-cycle-" in workflow
    assert "cocomelon-learning-ops-status" in workflow
    assert 'CYCLE_ROOT="$(dirname "$CYCLE_PATH")"' in workflow
    assert 'cp -a "$CYCLE_ROOT"/. dashboard/cycle/' in workflow
    assert "dashboard/learning-status.md" in workflow
    assert "Continuous Learning Operations" in workflow
    assert "learning-state/last-sync.json" not in workflow
    assert "api.hyperliquid" not in workflow
    assert "live_execution" not in workflow


def test_research_dashboard_restores_only_trusted_clean_state_lineages() -> None:
    workflow = _workflow()

    assert "--paginate --slurp" in workflow
    assert "research-learning-clean-state-[1-9][0-9]*-[1-9][0-9]*" in workflow
    assert ".github/workflows/research-learning-clean-state-bootstrap.yml" in workflow
    assert ".github/workflows/research-learning-clean-state-sync.yml" in workflow
    assert ".github/workflows/research-learning-clean-state-continuity.yml" in workflow
    assert '"Research Learning Clean State Bootstrap"' in workflow
    assert '"Research Learning Clean State Campaign Follower"' in workflow
    assert '"Research Learning Clean State Continuity"' in workflow
    assert 'run.get("status") == "completed"' in workflow
    assert 'run.get("conclusion") == "success"' in workflow
    assert 'run.get("head_branch") == "main"' in workflow
    assert "trusted clean-state artifact digest is missing" in workflow


def test_research_dashboard_renders_blind_learned_clean_review_queue() -> None:
    workflow = _workflow()

    assert "cocomelon-learning-clean-review-queue" in workflow
    assert "dashboard/clean-review.md" in workflow
    assert "cat dashboard/clean-review.md" in workflow
    assert "Learned Clean Candidate Review Queue" in workflow
    assert "HUMAN REVIEW REQUIRED" in workflow
    assert "No authenticated learned clean-validation lineage" in workflow
    clean_section = workflow.split(
        "- name: Render learned clean candidate review queue",
        1,
    )[1].split(
        "- name: Render continuous learning operations status",
        1,
    )[0].lower()
    assert "overall_mean_net_r" not in clean_section
    assert "predicted_net_r" not in clean_section
    assert "qualifies_clean_validation" not in clean_section
    assert "api.hyperliquid" not in clean_section
    assert "live_execution" not in clean_section
