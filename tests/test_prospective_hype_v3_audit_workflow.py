from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/prospective-hype-v3-audit.yml")
PINNED_REVISION = "298723c52d6a3b09839d05451d3d7db9753815bf"
PINNED_WORKFLOW_BLOB = "e00502dacb925d03bd90328f6ea39f6d195d0fa5"


def _source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_v3_audit_is_event_driven_and_has_no_schedule_dependency() -> None:
    source = _source()

    assert '"Prospective HYPE V3 Clean Observer"' in source
    assert "workflow_run:" in source
    assert "workflow_dispatch:" in source
    assert "\n  schedule:" not in source
    assert "cron:" not in source


def test_v3_audit_ignores_pr_validation_workflow_completions() -> None:
    source = _source()

    assert "github.event.workflow_run.head_branch == 'main'" in source
    assert "github.event.workflow_run.event == 'push'" in source
    assert "github.event.workflow_run.event == 'workflow_dispatch'" in source
    assert 'run.get("event") in {"push", "workflow_dispatch"}' in source
    assert 'previous_run.get("event") in {"push", "workflow_dispatch"}' in source


def test_v3_audit_is_read_only_and_uses_frozen_source() -> None:
    source = _source()

    assert "contents: read" in source
    assert "actions: read" in source
    assert "actions: write" not in source
    assert f"ref: {PINNED_REVISION}" in source
    assert f"PINNED_SOURCE_REVISION: {PINNED_REVISION}" in source
    assert "persist-credentials: false" in source


def test_v3_audit_authenticates_exact_campaign_runtime_and_control_plane() -> None:
    source = _source()

    assert "HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V3" in source
    assert "HYPE_PROSPECTIVE_VALIDATION_V3" in source
    assert '"kind": "prospective-hype-v3-clean-control-plane"' in source
    assert '"capture_transport": "rolling_workflow_dispatch_queue_v3"' in source
    assert '"protected_capture_minute_utc": 3' in source
    assert '"queue_depth": 4' in source
    assert '"queue_horizon_ms": 14_400_000' in source
    assert '"prepare_handoff_lead_ms": 600_000' in source
    assert '"duplicate_policy": "lowest_covering_run_id"' in source
    assert '"bootstrap_event": "push"' in source
    assert '"capture_event": "workflow_dispatch"' in source
    assert '"concurrency_mode": "target_leader_election"' in source
    assert '"prepare_job_timeout_minutes": 270' in source
    assert '"observe_job_timeout_minutes": 30' in source
    assert '"actions_permission": "write"' in source
    assert '"schema_version": 3' in source


def test_v3_audit_binds_every_state_producer_to_frozen_workflow_bytes() -> None:
    source = _source()

    assert f"OBSERVER_WORKFLOW_BLOB_SHA: {PINNED_WORKFLOW_BLOB}" in source
    assert "PRODUCER_WORKFLOW_BLOB_METADATA_FAILED" in source
    assert "PREVIOUS_PRODUCER_WORKFLOW_BLOB_METADATA_FAILED" in source
    assert "PRODUCER_WORKFLOW_BLOB_DRIFT" in source
    assert "PREVIOUS_PRODUCER_WORKFLOW_BLOB_DRIFT" in source
    assert '"observer_workflow_blob_sha": os.environ["WORKFLOW_BLOB_SHA"]' in source


def test_v3_audit_verifies_four_future_dispatch_targets() -> None:
    source = _source()

    assert "Capture V3 dispatch queue" in source
    assert "next_protected_capture_ms" in source
    assert "future_capture_targets" in source
    assert "missing_future_targets" in source
    assert "normalize_dispatch_runs" in source
    assert "DISPATCH_QUEUE_GAP" in source
    assert '"dispatch_queue_status": "covered"' in source
    assert '"dispatch_queue_depth": 4' in source
    assert '"dispatch_queue_targets": queue_targets' in source
    assert '"dispatch_queue_missing_targets": missing_queue_targets' in source


def test_v3_audit_is_duplicate_follower_aware_before_state_failure() -> None:
    source = _source()

    assert "UPSTREAM_JOB_DISCOVERY_FAILED" in source
    assert "DUPLICATE_FOLLOWER_NO_STATE" in source
    assert 'conclusions.get("prepare") == "success"' in source
    assert 'conclusions.get("observe") == "skipped"' in source
    assert "Preserve duplicate follower audit receipt" in source
    assert '"audit_status": "duplicate_follower"' in source


def test_v3_audit_enforces_append_only_lineage_and_no_backfill() -> None:
    source = _source()

    assert "CAMPAIGN_MANIFEST_DRIFT" in source
    assert "RUNTIME_ATTESTATION_DRIFT" in source
    assert "CONTROL_PLANE_DRIFT" in source
    assert "PREVIOUS_OBSERVATION_REWRITTEN_OR_REMOVED" in source
    assert "PREVIOUS_OUTCOME_REWRITTEN_OR_REMOVED" in source
    assert "HISTORICAL_OBSERVATION_BACKFILL_FORBIDDEN" in source
    assert '"lineage_status": lineage_status' in source
    assert '"appended_observation_count": appended_observation_count' in source
    assert '"appended_outcome_count": appended_outcome_count' in source


def test_v3_audit_stays_performance_blind_and_non_promotional() -> None:
    source = _source()

    assert '"interim_economics_redacted": True' in source
    assert '"promotion_eligible": False' in source
    assert '"mean_net_return"' not in source
    assert '"total_net_return"' not in source
    assert "eligible_for_candidate_review" not in source


def test_v3_audit_preserves_failure_receipt_before_failing_red() -> None:
    source = _source()

    upload = source.index("Upload V3 independent audit receipt")
    preserve = source.index("Preserve V3 audit failure status")
    assert upload < preserve
    assert "prospective-hype-v3-independent-audit-failure" in source
    assert "if-no-files-found: error" in source
    assert "always()" in source
    assert "DISPATCH_QUEUE_DISCOVERY_FAILED" in source
