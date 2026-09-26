from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/research-learning-shadow-state-bootstrap.yml")


def test_shadow_state_bootstrap_follows_only_successful_human_review() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "name: Research Learning Shadow State Bootstrap" in source
    assert 'workflows: ["Research Learning Shadow Review Admission"]' in source
    assert "types: [completed]" in source
    assert "workflow_dispatch:" in source
    assert "upstream_run_id:" in source
    assert "contents: read" in source
    assert "actions: read" in source
    assert "actions: write" not in source
    assert "group: research-learning-shadow-state-lineage-mutator" in source
    assert "cancel-in-progress: false" in source


def test_shadow_state_bootstrap_authenticates_exact_manual_review_artifact() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert 'run.get("head_branch") != "main"' in source
    assert 'run.get("status") != "completed"' in source
    assert 'run.get("conclusion") != "success"' in source
    assert 'run.get("event") != "workflow_dispatch"' in source
    assert ".github/workflows/research-learning-shadow-review.yml" in source
    assert "Research Learning Shadow Review Admission" in source
    assert 'run.get("head_repository")' in source
    assert "--paginate --slurp" in source
    assert "research-learning-shadow-review-[0-9a-f]{64}" in source
    assert "expected exactly one shadow review artifact" in source
    assert "shadow review artifact contains a symlink" in source


def test_shadow_state_bootstrap_reverifies_decision_admission_and_provenance() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "review provenance identity mismatch" in source
    assert "review provenance is non-canonical" in source
    assert "verify_learning_clean_review_decision" in source
    assert "verify_learning_shadow_admission" in source
    assert "review decision does not match provenance" in source
    assert "approved review is missing shadow admission" in source
    assert "rejected review unexpectedly carries shadow admission" in source
    assert "review decision carries invalid authority" in source
    assert "shadow admission carries invalid authority" in source


def test_shadow_state_bootstrap_refuses_duplicate_durable_lineage() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "research-learning-shadow-state-$CANDIDATE_ID" in source
    assert ".github/workflows/research-learning-shadow-state-bootstrap.yml" in source
    assert ".github/workflows/research-learning-shadow-state-sync.yml" in source
    assert ".github/workflows/research-learning-shadow-state-continuity.yml" in source
    assert "approved candidate already has a durable shadow-state lineage" in source


def test_shadow_state_bootstrap_initializes_empty_non_economic_state() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "cocomelon-learning-shadow-state" in source
    assert ".closed_paper_trade_count == 0" in source
    assert ".campaign_count == 0" in source
    assert ".paper_only == true" in source
    assert ".research_only == true" in source
    assert ".promotion_eligible == false" in source
    assert ".execution_ready == false" in source
    assert ".live_promotion_authorized == false" in source
    assert "if: ${{ steps.review.outputs.authorized == 'true' }}" in source


def test_shadow_state_bootstrap_is_paper_only_and_durable() -> None:
    source = WORKFLOW.read_text(encoding="utf-8").lower()

    assert "retention-days: 90" in source
    assert "api.hyperliquid" not in source
    assert "live promotion authorized: false" in source
    assert "execution enabled: false" in source
    assert "profit_factor" not in source
    assert "net_r" not in source
