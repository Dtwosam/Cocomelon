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

    assert "push:" in source
    assert 'branches:' in source
    assert '.github/workflows/prospective-hype-clean.yml' in source
    assert 'cron: "3,8,13 * * * *"' in source
    assert "workflow_dispatch:" in source
    assert "cancel-in-progress: false" in source
    assert "github.ref == 'refs/heads/main'" in source
    assert "timeout-minutes: 10" in source
    assert "OBSERVER_SOURCE_REVISION: 0131fccdb09a2b9ba959dd5785ea213a6297f719" in source
    assert "ref: 0131fccdb09a2b9ba959dd5785ea213a6297f719" in source
    assert "ref: ${{ github.sha }}" not in source
    assert "Verify frozen observer source revision" in source
    assert 'test "$actual_revision" = "$OBSERVER_SOURCE_REVISION"' in source


def test_prospective_hype_workflow_restores_and_republishes_cumulative_state() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "prospective-hype-clean-state" in source
    assert "actions/artifacts?name=$STATE_ARTIFACT_NAME" in source
    assert '.workflow_run.head_branch == "main"' in source
    assert "actions/upload-artifact@v7" in source
    assert "retention-days: 90" in source
    assert "state_digest" in source
    assert "Verify cumulative state continuity" in source
    assert "verify_prospective_state_continuity" in source
    assert "Verify prospective runtime attestation" in source
    assert "ensure_prospective_runtime_attestation" in source
    assert "git rev-parse HEAD" in source
    assert 'python - "$OBSERVER_SOURCE_REVISION"' in source
    assert "/tmp/prospective-hype-runtime.json" in source
    assert "POST_CUTOVER_PROSPECTIVE_STATE_RESTORE_REQUIRED" not in source
    assert "/tmp/prospective-hype-continuity.json" in source
    assert "prospective_clean" in source
    assert "promotion_eligible" in source
    assert "cocomelon-prospective-hype-observer" in source
    assert "cocomelon-prospective-hype-report" in source
    assert "/tmp/prospective-hype-report.json" in source
    assert 'report["state_digest"] == payload["state_digest"]' in source
    assert 'report["campaign_id"] == payload["campaign_id"]' in source
    assert 'report["plan_id"] == payload["validation_plan_id"]' in source
    assert 'report["expected_anchor_count"] == 1080' in source


def test_prospective_hype_workflow_keeps_per_run_receipt_separate() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert (
        "prospective-hype-clean-run-${{ github.run_id }}-${{ github.run_attempt }}"
        in source
    )
    assert "/tmp/prospective-hype-lineage.json" in source
    assert '"prior_state_digest"' in source
    assert '"current_state_digest"' in source
    assert '"restored_artifact_id"' in source
    assert '"receipt_id"' in source
    assert '"cycle": cycle' in source
    assert '"validation_report": report' in source
    assert '"runtime_attestation": runtime' in source
    assert '"observer_source_revision"' in source
    assert '"attestation_id"' in source
    assert (
        "prospective-hype-clean-report-${{ github.run_id }}-${{ github.run_attempt }}"
        in source
    )
    assert "observation_count_to_date" in source
    assert "expected_anchor_count_to_date" in source
    assert "missed_anchor_count_to_date" in source
    assert "capture_coverage_to_date" in source
    assert "overdue_unsettled_count" in source
    assert "GITHUB_STEP_SUMMARY" in source



def test_prospective_hype_workflow_monitors_recoverability_after_preserving_state() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "/tmp/prospective-hype-health.json" in source
    assert 'health["validation_report_id"] == report["report_id"]' in source
    assert 'health["required_final_observation_count"] == 972' in source
    assert 'health["missed_anchor_budget"] == 108' in source
    assert '"campaign_health": health' in source
    assert "remaining_missed_anchor_budget" in source
    assert "maximum_final_capture_coverage" in source
    assert "maximum_possible_settled_trades" in source
    assert "irrecoverable_reasons" in source
    assert "prospective-hype-clean-health-" in source
    assert "PROSPECTIVE_CAMPAIGN_IRRECOVERABLE" in source
    assert source.index("Upload cumulative clean evidence state") < source.index(
        "Fail closed if frozen campaign is irrecoverable"
    )
    assert source.index("Upload immutable validation report") < source.index(
        "Fail closed if frozen campaign is irrecoverable"
    )
    assert source.index("Upload immutable campaign health") < source.index(
        "Fail closed if frozen campaign is irrecoverable"
    )


def test_prospective_hype_summary_loads_frozen_runtime_before_rendering() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert source.count('Path("/tmp/prospective-hype-runtime.json")') >= 3
    summary_start = source.index("- name: Publish run summary")
    summary = source[summary_start:]
    runtime_load = summary.index(
        'Path("/tmp/prospective-hype-runtime.json").read_text'
    )
    runtime_use = summary.index("runtime['attestation_id']")
    assert runtime_load < runtime_use



def test_prospective_hype_workflow_predeclares_one_canonical_finalization() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "Build or verify canonical campaign finalization" in source
    assert 'root / "finalization.json"' in source
    assert '"kind": "prospective-hype-clean-finalization"' in source
    assert '"finalization_not_before_ms"' in source
    assert '"finalized_at_ms"' in source
    assert '"state_digest": cycle["state_digest"]' in source
    assert '"economic_payload": economic_payload' in source
    assert '"runtime_attestation_id": runtime["attestation_id"]' in source
    assert '"observer_source_revision": runtime["observer_source_revision"]' in source
    assert '"promotion_eligible": False' in source
    assert "waiting_for_exact_settlements" in source
    assert "economic_payload_changed_after_finalization" in source
    assert "state_digest_changed_after_finalization" in source
    assert "invalid_finalization_receipt" in source
    assert "PROSPECTIVE_FINALIZATION_CONFLICT" in source


def test_finalization_is_preserved_before_any_terminal_failure() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    finalization_step = source.index("Build or verify canonical campaign finalization")
    state_upload = source.index("Upload cumulative clean evidence state")
    status_upload = source.index("Upload immutable finalization status")
    canonical_upload = source.index("Upload canonical finalization receipt")
    conflict_gate = source.index("Fail closed on finalization conflict")
    health_gate = source.index("Fail closed if frozen campaign is irrecoverable")

    assert finalization_step < state_upload
    assert state_upload < status_upload < conflict_gate
    assert canonical_upload < conflict_gate
    assert status_upload < health_gate
    assert "steps.finalization.outputs.finalized == 'true'" in source
    assert "prospective-hype-clean-finalization-" in source
    assert "steps.finalization.outputs.finalization_id" in source


def test_finalization_status_is_bound_into_lineage_and_summary() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "/tmp/prospective-hype-finalization-status.json" in source
    assert '"finalization": finalization' in source
    assert "finalization['status']" in source
    assert "finalization['finalization_id']" in source
    assert 'finalization["status"] in {' in source
    assert '"pending"' in source
    assert '"waiting_for_exact_settlements"' in source
    assert '"finalized"' in source
    assert '"conflict"' in source



def test_prospective_hype_workflow_freezes_capture_control_plane_before_cutover() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "Verify prospective control-plane attestation" in source
    assert 'root / "control-plane.json"' in source
    assert '"kind": "prospective-hype-clean-control-plane"' in source
    assert '"schedule_cron": "3,8,13 * * * *"' in source
    assert '"attempt_minutes_utc": [3, 8, 13]' in source
    assert '"max_entry_candle_age_ms": MAX_ENTRY_CANDLE_AGE_MS' in source
    assert '"state_artifact_name": os.environ["STATE_ARTIFACT_NAME"]' in source
    assert '"evidence_root": os.environ["EVIDENCE_ROOT"]' in source
    assert '"concurrency_group": "prospective-hype-clean-observer"' in source
    assert '"cancel_in_progress": False' in source
    assert '"job_timeout_minutes": 10' in source
    assert '"execution_mode": os.environ["COCOMELON_EXECUTION_MODE"]' in source
    assert '"api_url": os.environ["COCOMELON_API_URL"]' in source
    assert '"ws_url": os.environ["COCOMELON_WS_URL"]' in source
    assert '"contents_permission": "read"' in source
    assert '"actions_permission": "read"' in source
    assert '"artifact_retention_days": 90' in source
    assert "POST_CUTOVER_CONTROL_PLANE_ATTESTATION_REQUIRED" in source
    assert "CONFLICTING_PROSPECTIVE_CONTROL_PLANE_ATTESTATION" in source
    assert "NON_CANONICAL_PROSPECTIVE_CONTROL_PLANE_ATTESTATION" in source


def test_control_plane_is_bound_into_lineage_summary_and_finalization() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "/tmp/prospective-hype-control-plane.json" in source
    assert '"control_plane_attestation": control_plane' in source
    assert '"control_plane_attestation_id": control_plane["control_plane_id"]' in source
    assert "control_plane['control_plane_id']" in source
    assert "control_plane['schedule_cron']" in source
    assert 'control_plane["schedule_cron"] == "3,8,13 * * * *"' in source
    assert 'control_plane["attempt_minutes_utc"] == [3, 8, 13]' in source
    assert 'control_plane["max_entry_candle_age_ms"] == 900000' in source


def test_yaml_capture_settings_match_frozen_control_plane_contract() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert 'cron: "3,8,13 * * * *"' in source
    assert "timeout-minutes: 10" in source
    assert "group: prospective-hype-clean-observer" in source
    assert "cancel-in-progress: false" in source
    assert "STATE_ARTIFACT_NAME: prospective-hype-clean-state" in source
    assert "EVIDENCE_ROOT: artifacts/prospective-hype-clean" in source
    assert "COCOMELON_EXECUTION_MODE: paper" in source
    assert "COCOMELON_API_URL: https://api.hyperliquid.xyz" in source
    assert "COCOMELON_WS_URL: wss://api.hyperliquid.xyz/ws" in source
