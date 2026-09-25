from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(
    ".github/workflows/research-learning-clean-state-continuity.yml"
)


def test_clean_state_continuity_is_bounded_and_read_only() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "Research Learning Clean State Continuity" in source
    assert 'cron: "23 4 * * *"' in source
    assert "workflow_dispatch:" in source
    assert 'MAX_STATE_AGE_DAYS: "14"' in source
    assert "contents: read" in source
    assert "actions: read" in source
    assert "actions: write" not in source
    assert "cancel-in-progress: false" in source
    assert "retention-days: 90" in source


def test_clean_state_continuity_discovers_all_trusted_generations() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "--paginate --slurp" in source
    assert "research-learning-clean-state-[1-9][0-9]*-[1-9][0-9]*" in source
    assert ".github/workflows/research-learning-clean-state-bootstrap.yml" in source
    assert ".github/workflows/research-learning-clean-state-sync.yml" in source
    assert ".github/workflows/research-learning-clean-state-continuity.yml" in source
    assert '"Research Learning Clean State Bootstrap"' in source
    assert '"Research Learning Clean State Campaign Follower"' in source
    assert '"Research Learning Clean State Continuity"' in source
    assert "name in selected" in source
    assert "trusted clean-state artifact digest is missing" in source


def test_clean_state_continuity_reverifies_complete_lineage_before_copy() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "verify_learning_candidate_package" in source
    assert "verify_learning_clean_validation_spec" in source
    assert "LearningCleanEvidenceStore" in source
    assert "verify_learning_clean_state" in source
    assert "load_learning_clean_state" in source
    assert "LearningCleanCampaignSyncResult" in source
    assert "verify_learning_clean_validation_score" in source
    assert "verify_learning_clean_finalization" in source
    assert '"bootstrap_id"' in source
    assert '"generation_id"' in source
    assert "clean campaign sync identity mismatch" in source
    assert "clean state-history filename mismatch" in source
    assert "symlink forbidden in clean state" in source


def test_clean_state_continuity_preserves_lineage_name_without_mutation() -> None:
    source = WORKFLOW.read_text(encoding="utf-8").lower()

    assert "name: ${{ matrix.artifact_name }}" in source
    assert "path: clean-state/" in source
    assert "state mutated: false" in source
    assert "promotion authorized: false" in source
    assert "execution enabled: false" in source
    assert "cocomelon-learning-clean-campaign-sync" not in source
    assert "cocomelon-learning-candidate-predict" not in source
    assert "api.hyperliquid" not in source
