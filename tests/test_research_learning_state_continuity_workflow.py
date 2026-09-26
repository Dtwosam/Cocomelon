from __future__ import annotations

from pathlib import Path

CONTINUITY = Path(".github/workflows/research-learning-state-continuity.yml")
EVIDENCE = Path(".github/workflows/research-learning-evidence.yml")
CATCHUP = Path(".github/workflows/research-learning-catchup.yml")
DASHBOARD = Path(".github/workflows/research-dashboard.yml")


def test_continuity_workflow_is_read_only_and_bounded() -> None:
    source = CONTINUITY.read_text(encoding="utf-8")

    assert "Research Learning State Continuity" in source
    assert 'cron: "17 3 * * *"' in source
    assert "workflow_dispatch:" in source
    assert "actions: read" in source
    assert "actions: write" not in source
    assert 'MAX_STATE_AGE_DAYS: "14"' in source
    assert "retention-days: 90" in source


def test_continuity_workflow_reauthenticates_state_before_republishing() -> None:
    source = CONTINUITY.read_text(encoding="utf-8")

    assert "LearningEvidenceLedger" in source
    assert "LearningFeatureSnapshotStore" in source
    assert 'sync.get("learning_state_digest") != ledger.state_digest' in source
    assert 'sync.get("feature_state_digest") != features.state_digest' in source
    assert "verify_learning_state_lineage" in source
    assert 'sync.get("lineage_sequence") != lineage.sequence' in source
    assert 'sync.get("lineage_entry_id") != lineage.entry_id' in source
    assert 'sync.get("learning_record_count") != len(records)' in source
    assert 'sync.get("feature_snapshot_count") != len(snapshots)' in source
    assert "eligible + quarantined != len(records)" in source
    assert 'payload.get("research_only") is not True' in source
    assert 'payload.get("promotion_eligible") is not False' in source
    assert 'payload.get("execution_ready") is not False' in source


def test_learning_state_consumers_trust_all_authenticated_state_producers() -> None:
    continuity_path = ".github/workflows/research-learning-state-continuity.yml"
    for workflow in (EVIDENCE, CATCHUP, DASHBOARD):
        source = workflow.read_text(encoding="utf-8")
        assert continuity_path in source
        assert ".github/workflows/research-learning-evidence.yml" in source
        assert ".github/workflows/continuous-paper-learning-evidence.yml" in source


def test_continuity_workflow_cannot_train_promote_or_execute() -> None:
    source = CONTINUITY.read_text(encoding="utf-8").lower()

    assert "cocomelon-learning-experiment" not in source
    assert "cocomelon-learning-tree" not in source
    assert "live_execution" not in source
    assert "api.hyperliquid" not in source
    assert "execution enabled: false" in source
