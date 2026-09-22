from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/historical-archive-clean.yml")
CONTROL_PLANE = Path(
    "src/cocomelon/research/historical_archive_clean_control_plane.py"
)


def test_archive_clean_workflow_is_disabled_by_default_and_paper_only() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "ARCHIVE_CLEAN_CAMPAIGN_ENABLED == 'true'" in source
    assert "github.ref == 'refs/heads/main'" in source
    assert "COCOMELON_EXECUTION_MODE: paper" in source
    assert "COCOMELON_API_URL: https://api.hyperliquid.xyz" in source
    assert "COCOMELON_WS_URL: wss://api.hyperliquid.xyz/ws" in source
    assert "contents: read" in source
    assert "actions: read" in source
    assert "contents: write" not in source
    assert "actions: write" not in source
    assert "COCOMELON_LIVE_ACK" not in source
    assert "private key" not in source.lower()
    assert "wallet" not in source.lower()
    assert "place_order" not in source
    assert "submit_order" not in source


def test_archive_clean_workflow_retries_inside_fifteen_minute_freshness() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    cron = "2,7,12,17,22,27,32,37,42,47,52,57 * * * *"
    assert f'cron: "{cron}"' in source
    assert f'SCHEDULE_CRON: "{cron}"' in source
    control_plane = CONTROL_PLANE.read_text(encoding="utf-8")
    assert (
        "CAPTURE_ATTEMPT_MINUTES_UTC = "
        "(2, 7, 12, 17, 22, 27, 32, 37, 42, 47, 52, 57)"
        in control_plane
    )
    assert "MAX_ENTRY_CANDLE_AGE_MS" in control_plane
    assert "workflow_dispatch:" in source
    assert "cancel-in-progress: false" in source
    assert "timeout-minutes: 12" in source


def test_archive_clean_workflow_uses_frozen_revision_runtime_and_pin() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "ARCHIVE_CLEAN_FROZEN_REVISION" in source
    assert "ARCHIVE_CLEAN_RUNTIME_ARTIFACT_ID" in source
    assert "ARCHIVE_CLEAN_PIN_ID" in source
    assert "Checkout frozen observer revision" in source
    assert "vars.ARCHIVE_CLEAN_FROZEN_REVISION" in source
    assert 'test "$actual_revision" = "$FROZEN_REVISION"' in source
    assert "Download pinned runtime artifact" in source
    assert "/actions/artifacts/$RUNTIME_ARTIFACT_ID/zip" in source
    assert "cocomelon-historical-archive-clean-runtime verify" in source
    assert '--pin-id "$PIN_ID"' in source
    assert "load_pinned_archive_clean_runtime" in source
    assert "ARCHIVE_CLEAN_RUNTIME_ARTIFACT_EXPIRED" in source
    assert "ARCHIVE_CLEAN_RUNTIME_ARTIFACT_NOT_MAIN" in source
    assert "historical-archive-clean-runtime-" in source
    assert "ARCHIVE_CLEAN_RUNTIME_ARTIFACT_NAME_MISMATCH" in source
    assert "RUNTIME_PUBLISHER_WORKFLOW_PATH" in source
    assert "historical-archive-clean-runtime-publish.yml" in source
    assert "ARCHIVE_CLEAN_RUNTIME_PRODUCER_WORKFLOW_MISMATCH" in source
    assert "ARCHIVE_CLEAN_RUNTIME_PRODUCER_REPOSITORY_MISMATCH" in source
    assert "ARCHIVE_CLEAN_RUNTIME_PRODUCER_BRANCH_MISMATCH" in source
    assert "ARCHIVE_CLEAN_RUNTIME_PRODUCER_REVISION_MISMATCH" in source
    assert 'run.get("head_sha") != os.environ["FROZEN_REVISION"]' in source
    assert "ARCHIVE_CLEAN_RUNTIME_PRODUCER_EVENT_MISMATCH" in source
    assert "ARCHIVE_CLEAN_RUNTIME_PRODUCER_NOT_SUCCESS" in source


def test_archive_clean_state_is_pin_scoped_and_producer_authenticated() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "historical-archive-clean-state-" in source
    assert "vars.ARCHIVE_CLEAN_PIN_ID" in source
    assert "actions/artifacts?name=$STATE_ARTIFACT_NAME" in source
    assert '.workflow_run.head_branch == "main"' in source
    assert "/actions/runs/$run_id" in source
    assert 'run.get("path") != os.environ["WORKFLOW_PATH"]' in source
    assert 'run.get("repository", {}).get("full_name")' in source
    assert 'run.get("event") not in {"schedule", "workflow_dispatch"}' in source
    assert 'run.get("conclusion") not in {"success", "failure"}' in source



def test_archive_clean_observer_uses_bootstrap_only_as_first_state_fallback() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    normal_restore = source.index("Restore latest cumulative clean state")
    bootstrap_restore = source.index("Restore pre-cutover bootstrap fallback")
    continuity = source.index("Verify state continuity and canonical finalization")

    assert normal_restore < bootstrap_restore < continuity
    assert "steps.restore.outputs.restored_artifact_id == 'none'" in source
    assert "BOOTSTRAP_STATE_ARTIFACT_NAME" in source
    assert "historical-archive-clean-bootstrap-state-" in source
    assert "BOOTSTRAP_WORKFLOW_PATH" in source
    assert "historical-archive-clean-bootstrap.yml" in source
    assert "ARCHIVE_CLEAN_BOOTSTRAP_PRODUCER_WORKFLOW_MISMATCH" in source
    assert "ARCHIVE_CLEAN_BOOTSTRAP_PRODUCER_REPOSITORY_MISMATCH" in source
    assert "ARCHIVE_CLEAN_BOOTSTRAP_PRODUCER_BRANCH_MISMATCH" in source
    assert "ARCHIVE_CLEAN_BOOTSTRAP_PRODUCER_REVISION_MISMATCH" in source
    assert "ARCHIVE_CLEAN_BOOTSTRAP_PRODUCER_EVENT_MISMATCH" in source
    assert "ARCHIVE_CLEAN_BOOTSTRAP_PRODUCER_NOT_SUCCESS" in source
    assert "--verify-only" in source
    assert "RESTORED_OBSERVER_ARTIFACT_ID" in source
    assert "RESTORED_BOOTSTRAP_ARTIFACT_ID" in source


def test_archive_clean_observer_requires_authenticated_activation_before_continuity() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    bootstrap = source.index("Restore pre-cutover bootstrap fallback")
    activation_restore = source.index("Restore authenticated activation authorization")
    auditor_checkout = source.index("Checkout activation auditor revision")
    activation_verify = source.index("Verify activation authorization")
    continuity = source.index("Verify state continuity and canonical finalization")
    cycle = source.index("Run pinned paper-only clean cycle")

    assert (
        bootstrap
        < activation_restore
        < auditor_checkout
        < activation_verify
        < continuity
        < cycle
    )
    assert "ACTIVATION_ARTIFACT_NAME" in source
    assert "historical-archive-clean-activation-" in source
    assert "ACTIVATION_WORKFLOW_PATH" in source
    assert "historical-archive-clean-activation.yml" in source
    assert "ARCHIVE_CLEAN_ACTIVATION_AUTHORIZATION_REQUIRED" in source
    assert "ARCHIVE_CLEAN_ACTIVATION_PRODUCER_WORKFLOW_MISMATCH" in source
    assert "ARCHIVE_CLEAN_ACTIVATION_PRODUCER_REPOSITORY_MISMATCH" in source
    assert "ARCHIVE_CLEAN_ACTIVATION_PRODUCER_BRANCH_MISMATCH" in source
    assert "ARCHIVE_CLEAN_ACTIVATION_PRODUCER_REVISION_MISMATCH" in source
    assert "ARCHIVE_CLEAN_ACTIVATION_PRODUCER_EVENT_MISMATCH" in source
    assert "ARCHIVE_CLEAN_ACTIVATION_PRODUCER_NOT_SUCCESS" in source
    assert "ARCHIVE_CLEAN_ACTIVATION_PRODUCER_NOT_PRE_CUTOVER" in source
    assert "authorization_source_revision" in source
    assert "steps.activation_restore.outputs.source_revision" in source
    assert "path: activation-auditor" in source
    assert "PYTHONPATH: ${{ github.workspace }}/activation-auditor/src" in source
    assert "historical_archive_clean_activation_cli" in source
    assert "--verify-only" in source

def test_archive_clean_workflow_fails_closed_on_post_cutover_state_reset() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "POST_CUTOVER_ARCHIVE_CLEAN_STATE_RESTORE_REQUIRED" in source
    assert "POST_CUTOVER_ARCHIVE_CLEAN_CHECKPOINT_REQUIRED" in source
    control_plane = CONTROL_PLANE.read_text(encoding="utf-8")
    assert "POST_CUTOVER_ARCHIVE_CLEAN_CONTROL_PLANE_REQUIRED" in control_plane
    assert "CONFLICTING_ARCHIVE_CLEAN_CONTROL_PLANE_ATTESTATION" in control_plane
    assert 'state_root / "checkpoint.json"' in source
    assert 'state_root / "control-plane.json"' in control_plane


def test_archive_clean_control_plane_is_frozen_into_cumulative_state() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "ensure_archive_clean_control_plane" in source
    assert "CAPTURE_SCHEDULE_CRON" in source
    assert "ARCHIVE_CLEAN_CAPTURE_SCHEDULE_MISMATCH" in source
    assert 'Path(os.environ["STATE_ROOT"])' in source
    assert 'frozen_revision=os.environ["FROZEN_REVISION"]' in source
    assert 'runtime_artifact_id=os.environ["RUNTIME_ARTIFACT_ID"]' in source
    assert "/tmp/archive-clean-control-plane.json" in source


def test_archive_clean_workflow_runs_checkpoint_cycle_and_append_only_lineage() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "cocomelon-historical-archive-clean-cycle" in source
    assert '--checkpoint "$STATE_ROOT/checkpoint.json"' in source
    assert '--cycle-evidence-root "$CYCLE_ROOT"' in source
    assert '--source-root "$SOURCE_ROOT"' in source
    assert '/ "receipts"' in source
    assert "completed_at_ms" in source
    assert "receipt_id" in source
    assert "cocomelon-historical-archive-clean-lineage" in source
    assert '--receipts-root "$STATE_ROOT/receipts"' in source
    assert "/tmp/archive-clean-lineage.json" in source


def test_archive_clean_workflow_preserves_state_and_evidence_before_failure() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    terminal = source.index("Preserve terminal failure status")
    state_upload = source.index("Upload cumulative archive clean state")
    cycle_upload = source.index("Upload immutable cycle evidence")
    source_upload = source.index("Upload immutable source captures")
    lineage_upload = source.index("Upload immutable lineage report")
    failure_upload = source.index("Upload cycle failure receipt")

    assert state_upload < terminal
    assert cycle_upload < terminal
    assert source_upload < terminal
    assert lineage_upload < terminal
    assert failure_upload < terminal
    assert "continue-on-error: true" in source
    assert "historical-archive-clean-failed-cycle-" in source


def test_archive_clean_finalization_is_terminal_and_canonical() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "Determine terminal finalization readiness" in source
    assert "finalization_not_before_ms" in source
    assert "pending_signal_count == 0" in source
    assert "active_position_count == 0" in source
    assert "cocomelon-historical-archive-clean-finalize" in source
    assert '--output-root "$STATE_ROOT/finalization"' in source
    assert "historical-archive-clean-finalization-" in source
    assert "steps.finalization.outputs.finalization_id" in source
    assert "verify_archive_clean_finalization" in source
    assert "already finalized" in source.lower()


def test_archive_clean_summary_redacts_interim_economics() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    summary_start = source.index("Publish redacted run summary")
    summary_end = source.index("Upload cumulative archive clean state")
    summary = source[summary_start:summary_end]

    assert "interim economics: redacted" in summary
    assert "mean_net_return" not in summary
    assert "net_return_sum" not in summary
    assert "gross_return_sum" not in summary
    assert "modeled_cost_sum" not in summary
    assert "execution ready: false" in summary
