from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/historical-archive-clean-bootstrap.yml")


def test_bootstrap_workflow_is_manual_read_only_offline_and_disabled_safe() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in source
    assert "schedule:" not in source
    assert "github.ref == 'refs/heads/main'" in source
    assert "contents: read" in source
    assert "actions: read" in source
    assert "contents: write" not in source
    assert "actions: write" not in source
    assert 'test "${CAMPAIGN_ENABLED:-false}" != "true"' in source
    assert "COCOMELON_API_URL" not in source
    assert "COCOMELON_WS_URL" not in source
    assert "InfoClient" not in source
    assert "place_order" not in source
    assert "submit_order" not in source
    assert "market access performed: false" in source
    assert "campaign enabled: false" in source
    assert "execution ready: false" in source


def test_bootstrap_workflow_authenticates_package_bound_runtime_producer() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "ARCHIVE_CLEAN_FROZEN_REVISION" in source
    assert "ARCHIVE_CLEAN_RUNTIME_ARTIFACT_ID" in source
    assert "ARCHIVE_CLEAN_PIN_ID" in source
    assert "historical-archive-clean-runtime-" in source
    assert "RUNTIME_PUBLISHER_WORKFLOW_PATH" in source
    assert "historical-archive-clean-runtime-publish.yml" in source
    assert "ARCHIVE_CLEAN_RUNTIME_ARTIFACT_NAME_MISMATCH" in source
    assert "ARCHIVE_CLEAN_RUNTIME_PRODUCER_WORKFLOW_MISMATCH" in source
    assert "ARCHIVE_CLEAN_RUNTIME_PRODUCER_REPOSITORY_MISMATCH" in source
    assert "ARCHIVE_CLEAN_RUNTIME_PRODUCER_BRANCH_MISMATCH" in source
    assert "ARCHIVE_CLEAN_RUNTIME_PRODUCER_REVISION_MISMATCH" in source
    assert "ARCHIVE_CLEAN_RUNTIME_PRODUCER_EVENT_MISMATCH" in source
    assert "ARCHIVE_CLEAN_RUNTIME_PRODUCER_NOT_SUCCESS" in source
    assert 'run.get("head_sha") != os.environ["FROZEN_REVISION"]' in source
    assert "portable_package_bound" in source
    assert "ARCHIVE_CLEAN_BOOTSTRAP_PACKAGE_BINDING_REQUIRED" in source


def test_bootstrap_workflow_restores_only_authenticated_prior_bootstrap() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "historical-archive-clean-bootstrap-state-" in source
    assert "BOOTSTRAP_WORKFLOW_PATH" in source
    assert "historical-archive-clean-bootstrap.yml" in source
    assert "ARCHIVE_CLEAN_BOOTSTRAP_ARTIFACT_NAME_MISMATCH" in source
    assert "ARCHIVE_CLEAN_BOOTSTRAP_PRODUCER_WORKFLOW_MISMATCH" in source
    assert "ARCHIVE_CLEAN_BOOTSTRAP_PRODUCER_REPOSITORY_MISMATCH" in source
    assert "ARCHIVE_CLEAN_BOOTSTRAP_PRODUCER_BRANCH_MISMATCH" in source
    assert "ARCHIVE_CLEAN_BOOTSTRAP_PRODUCER_REVISION_MISMATCH" in source
    assert "ARCHIVE_CLEAN_BOOTSTRAP_PRODUCER_EVENT_MISMATCH" in source
    assert "ARCHIVE_CLEAN_BOOTSTRAP_PRODUCER_NOT_SUCCESS" in source


def test_bootstrap_workflow_creates_only_canonical_empty_state() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "cocomelon-historical-archive-clean-bootstrap" in source
    assert "--frozen-revision" in source
    assert "--runtime-artifact-id" in source
    assert "ARCHIVE_CLEAN_BOOTSTRAP_CAMPAIGN_ENABLED_FORBIDDEN" in source
    assert "ARCHIVE_CLEAN_BOOTSTRAP_EXECUTION_READY_FORBIDDEN" in source
    assert "ARCHIVE_CLEAN_BOOTSTRAP_STATE_NAME_MISMATCH" in source
    assert "ARCHIVE_CLEAN_BOOTSTRAP_FILE_SET_MISMATCH" in source
    assert '"bootstrap.json"' in source
    assert '"checkpoint.json"' in source
    assert '"control-plane.json"' in source


def test_bootstrap_workflow_uploads_separate_pin_scoped_state() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "actions/upload-artifact@v7" in source
    assert "BOOTSTRAP_STATE_ARTIFACT_NAME" in source
    assert "historical-archive-clean-bootstrap-state-" in source
    assert "retention-days: 90" in source
    assert "historical-archive-clean-state-${{ vars.ARCHIVE_CLEAN_PIN_ID }}" not in source
