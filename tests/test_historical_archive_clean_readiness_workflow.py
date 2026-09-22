from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/historical-archive-clean-readiness.yml")


def test_readiness_workflow_is_manual_read_only_and_offline_marketwise() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in source
    assert "schedule:" not in source
    assert "contents: read" in source
    assert "actions: read" in source
    assert "contents: write" not in source
    assert "actions: write" not in source
    assert "COCOMELON_API_URL" not in source
    assert "InfoClient" not in source
    assert "place_order" not in source
    assert "submit_order" not in source


def test_readiness_workflow_verifies_frozen_runtime_and_pin_scoped_state() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "ARCHIVE_CLEAN_FROZEN_REVISION" in source
    assert "ARCHIVE_CLEAN_RUNTIME_ARTIFACT_ID" in source
    assert "ARCHIVE_CLEAN_PIN_ID" in source
    assert "ARCHIVE_CLEAN_CAMPAIGN_ENABLED" in source
    assert "Checkout frozen observer revision" in source
    assert 'test "$actual_revision" = "$FROZEN_REVISION"' in source
    assert "cocomelon-historical-archive-clean-runtime verify" in source
    assert "historical-archive-clean-runtime-" in source
    assert "RUNTIME_PUBLISHER_WORKFLOW_PATH" in source
    assert "historical-archive-clean-runtime-publish.yml" in source
    assert "ARCHIVE_CLEAN_RUNTIME_ARTIFACT_NAME_MISMATCH" in source
    assert "ARCHIVE_CLEAN_RUNTIME_PRODUCER_WORKFLOW_MISMATCH" in source
    assert "ARCHIVE_CLEAN_RUNTIME_PRODUCER_REVISION_MISMATCH" in source
    assert 'run.get("head_sha") != os.environ["FROZEN_REVISION"]' in source
    assert "ARCHIVE_CLEAN_RUNTIME_PRODUCER_EVENT_MISMATCH" in source
    assert "historical-archive-clean-state-" in source
    assert "actions/artifacts?name=$STATE_ARTIFACT_NAME" in source
    assert 'run.get("path") != os.environ["WORKFLOW_PATH"]' in source



def test_readiness_uses_bootstrap_only_when_observer_state_is_missing() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    observer_restore = source.index("Restore latest pin-scoped observer state")
    bootstrap_restore = source.index("Restore pre-cutover bootstrap fallback")
    readiness = source.index("Build offline activation readiness report")

    assert observer_restore < bootstrap_restore < readiness
    assert "steps.restore.outputs.restored_artifact_id == 'none'" in source
    assert "BOOTSTRAP_STATE_ARTIFACT_NAME" in source
    assert "historical-archive-clean-bootstrap-state-" in source
    assert "BOOTSTRAP_WORKFLOW_PATH" in source
    assert "ARCHIVE_CLEAN_BOOTSTRAP_PRODUCER_WORKFLOW_MISMATCH" in source
    assert "ARCHIVE_CLEAN_BOOTSTRAP_PRODUCER_REPOSITORY_MISMATCH" in source
    assert "ARCHIVE_CLEAN_BOOTSTRAP_PRODUCER_BRANCH_MISMATCH" in source
    assert "ARCHIVE_CLEAN_BOOTSTRAP_PRODUCER_REVISION_MISMATCH" in source
    assert "ARCHIVE_CLEAN_BOOTSTRAP_PRODUCER_EVENT_MISMATCH" in source
    assert "ARCHIVE_CLEAN_BOOTSTRAP_PRODUCER_NOT_SUCCESS" in source
    assert "--verify-only" in source

def test_readiness_report_is_uploaded_before_terminal_failure() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    build = source.index("Build offline activation readiness report")
    upload = source.index("Upload immutable readiness report")
    gate = source.index("Fail closed if activation is not operationally valid")

    assert build < upload < gate
    assert "cocomelon-historical-archive-clean-readiness" in source
    assert "operationally_valid" in source
    assert "historical-archive-clean-readiness-" in source
    assert "continue-on-error: true" in source


def test_readiness_summary_redacts_interim_economics() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    start = source.index("Publish redacted readiness summary")
    end = source.index("Upload immutable readiness report")
    summary = source[start:end]

    assert "interim economics: redacted" in summary
    assert "mean_net_return" not in summary
    assert "net_return_sum" not in summary
    assert "execution ready: false" in summary

def test_readiness_requires_activation_authorization_when_campaign_enabled() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    restore = source.index("Restore authenticated activation authorization when enabled")
    checkout = source.index("Checkout activation auditor revision when enabled")
    verify = source.index("Verify activation authorization when enabled")
    readiness = source.index("Build offline activation readiness report")

    assert restore < checkout < verify < readiness
    assert "env.CAMPAIGN_ENABLED == 'true'" in source
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
    assert 'run.get("event") not in {"workflow_dispatch", "workflow_run"}' in source
    assert "ARCHIVE_CLEAN_ACTIVATION_PRODUCER_NOT_SUCCESS" in source
    assert "ARCHIVE_CLEAN_ACTIVATION_PRODUCER_NOT_PRE_CUTOVER" in source
    assert "authorization_source_revision" in source
    assert "steps.activation_restore.outputs.source_revision" in source
    assert "path: activation-auditor" in source
    assert "PYTHONPATH: ${{ github.workspace }}/activation-auditor/src" in source
    assert "historical_archive_clean_activation_cli" in source
    assert "--verify-only" in source
