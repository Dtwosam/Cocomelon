from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/research-learning-clean-state-sync.yml")


def test_clean_state_follower_tracks_successful_paper_campaigns() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "Research Learning Clean State Campaign Follower" in source
    assert 'workflows: ["Scheduled Research Mainnet Replay Campaign"]' in source
    assert "types: [completed]" in source
    assert "workflow_dispatch:" in source
    assert "upstream_run_id:" in source
    assert "contents: read" in source
    assert "actions: read" in source
    assert "actions: write" not in source
    assert "cancel-in-progress: false" in source


def test_clean_state_follower_reauthenticates_exact_campaign() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert 'run.get("head_branch") != "main"' in source
    assert 'run.get("status") != "completed"' in source
    assert 'run.get("conclusion") != "success"' in source
    assert 'run.get("event") != "workflow_dispatch"' in source
    assert (
        'run.get("path") != ".github/workflows/research-campaign-scheduled.yml"'
        in source
    )
    assert 'run.get("name") != "Scheduled Research Mainnet Replay Campaign"' in source
    assert 'repository.get("full_name") != os.environ["GITHUB_REPOSITORY"]' in source
    assert 'ARTIFACT_NAME="research-campaign-$RUN_ID-$RUN_ATTEMPT"' in source
    assert "expected exactly one complete research campaign artifact" in source
    assert "research campaign artifact digest is missing" in source


def test_clean_state_follower_restores_only_trusted_latest_generations() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "research-learning-clean-state-[1-9][0-9]*-[1-9][0-9]*" in source
    assert ".github/workflows/research-learning-clean-state-bootstrap.yml" in source
    assert ".github/workflows/research-learning-clean-state-sync.yml" in source
    assert '"Research Learning Clean State Bootstrap"' in source
    assert '"Research Learning Clean State Campaign Follower"' in source
    assert 'or run.get("head_branch") != "main"' in source
    assert 'or run.get("status") != "completed"' in source
    assert 'or run.get("conclusion") != "success"' in source
    assert "name in selected" in source
    assert "trusted clean-state artifact digest is missing" in source


def test_clean_state_follower_verifies_and_versions_candidate_state() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "verify_learning_clean_state" in source
    assert "cocomelon-learning-clean-sequence" in source
    assert "--paginate --slurp" in source
    assert 'if [ "$ACTION" = "gap" ]; then' in source
    assert "clean campaign gap detected" in source
    assert "skip_already_processed" in source
    assert "skip_predates_bootstrap" in source
    assert "steps.sequence.outputs.action == 'process'" in source
    assert "cocomelon-learning-clean-campaign-sync" in source
    assert "state-history/$PRIOR_STATE_ID.json" in source
    assert "conflicting clean-state history entry" in source
    assert "campaign-syncs/$CAMPAIGN_RUN_ID-$CAMPAIGN_RUN_ATTEMPT.json" in source
    assert "conflicting clean campaign sync receipt" in source
    assert "cocomelon-learning-clean-state" in source
    assert 'if [ "$STATUS" = "ready_to_score" ]; then' in source
    assert "cocomelon-learning-clean-validation-score" in source
    assert "cocomelon-learning-clean-finalize" in source
    assert "verify_learning_clean_finalization" in source
    assert 'FINAL_PATH="$FINAL_ROOT/candidate-finalization.json"' in source
    assert "finalization_materialized" in source
    assert "processed clean candidate count does not match bootstrap" in source


def test_clean_state_follower_keeps_operator_surface_blind_and_research_only() -> None:
    source = WORKFLOW.read_text(encoding="utf-8").lower()

    assert "overall_mean_net_r" not in source
    assert "qualifies_clean_validation" not in source
    assert "predicted_net_r" not in source
    assert "eligible_for_candidate_review" not in source
    assert '"verdict"' not in source
    assert "api.hyperliquid" not in source
    assert "promotion authorized: false" in source
    assert "execution enabled: false" in source
    assert '"promotion_eligible": false' in source
    assert '"execution_ready": false' in source


def test_clean_state_follower_republishes_same_lineage_name_with_long_retention() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "name: ${{ matrix.artifact_name }}" in source
    assert "path: next-state/" in source
    assert "retention-days: 90" in source
    assert "next-state/generations/" in source
    assert "source_state_artifact_digest" in source
    assert "campaign_artifact_digest" in source
