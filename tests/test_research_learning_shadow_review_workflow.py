from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/research-learning-shadow-review.yml")


def test_shadow_review_is_manual_and_single_candidate_serialized() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "name: Research Learning Shadow Review Admission" in source
    assert "on:\n  workflow_dispatch:" in source
    assert "source_run_id:" in source
    assert "candidate_id:" in source
    assert "advance_to_shadow_evaluation" in source
    assert "reject_candidate" in source
    assert "rationale:" in source
    assert "group: research-learning-shadow-review-${{ inputs.candidate_id }}" in source
    assert "cancel-in-progress: false" in source


def test_shadow_review_authenticates_exact_terminal_clean_state_source() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert 'run.get("head_branch") != "main"' in source
    assert 'run.get("status") != "completed"' in source
    assert 'run.get("conclusion") != "success"' in source
    assert ".github/workflows/research-learning-clean-state-sync.yml" in source
    assert ".github/workflows/research-learning-clean-state-continuity.yml" in source
    assert 'run.get("head_repository")' in source
    assert "--paginate --slurp" in source
    assert "research-learning-clean-state-[1-9][0-9]*-[1-9][0-9]*" in source
    assert "clean-state source artifact contains a symlink" in source
    assert "expected exactly one terminal candidate dossier" in source
    assert "verify_learning_clean_review_dossier" in source


def test_shadow_review_is_immutable_per_candidate_and_actor_bound() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "research-learning-shadow-review-$CANDIDATE_ID" in source
    assert "candidate already has an immutable human review decision" in source
    assert ".github/workflows/research-learning-shadow-review.yml" in source
    assert "Research Learning Shadow Review Admission" in source
    assert "REVIEWER: ${{ github.actor }}" in source
    assert '--reviewer "$REVIEWER"' in source
    assert '--reviewed-at-ms "$REVIEWED_AT_MS"' in source
    assert '--rationale "$REVIEW_RATIONALE"' in source


def test_shadow_admission_exists_only_for_explicit_advance_decision() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "cocomelon-learning-clean-review-decision" in source
    assert "Materialize shadow admission only for approved review" in source
    assert "if: ${{ inputs.decision == 'advance_to_shadow_evaluation' }}" in source
    assert "cocomelon-learning-shadow-admission" in source
    assert '--shadow-start-ms "$REVIEWED_AT_MS"' in source
    assert '"shadow_admission_id": shadow_admission_id' in source


def test_shadow_review_artifact_remains_non_live_and_durable() -> None:
    source = WORKFLOW.read_text(encoding="utf-8").lower()

    assert "retention-days: 90" in source
    assert '"paper_only": true' in source
    assert '"research_only": true' in source
    assert '"promotion_eligible": false' in source
    assert '"execution_ready": false' in source
    assert '"live_promotion_authorized": false' in source
    assert "api.hyperliquid" not in source
    assert "live promotion authorized: false" in source
    assert "execution enabled: false" in source
