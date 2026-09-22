from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(
    ".github/workflows/historical-archive-clean-runtime-publish.yml"
)


def test_runtime_publisher_is_manual_read_only_and_never_activates() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in source
    assert "schedule:" not in source
    assert "github.ref == 'refs/heads/main'" in source
    assert "contents: read" in source
    assert "actions: read" in source
    assert "contents: write" not in source
    assert "actions: write" not in source
    assert "ARCHIVE_CLEAN_CAMPAIGN_ENABLED" not in source
    assert "gh variable set" not in source
    assert "gh api --method PATCH" not in source
    assert "campaign enabled: false" in source
    assert "execution ready: false" in source
    assert "Activation variables are intentionally not changed" in source


def test_runtime_publisher_requires_precommitted_package_identity() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "candidate_package_artifact_id:" in source
    assert "expected_package_id:" in source
    assert '[[ "$PACKAGE_ARTIFACT_ID" =~ ^[0-9]+$ ]]' in source
    assert '[[ "$EXPECTED_PACKAGE_ID" =~ ^[0-9a-f]{64}$ ]]' in source
    assert "historical-archive-clean-candidate-package-" in source
    assert "ARCHIVE_CLEAN_PACKAGE_ARTIFACT_NAME_MISMATCH" in source
    assert "ARCHIVE_CLEAN_PACKAGE_ID_NOT_EXPECTED" in source
    assert "ARCHIVE_CLEAN_PACKAGE_FILE_SET_MISMATCH" in source
    assert "cocomelon-historical-archive-candidate-package verify-portable" in source


def test_runtime_publisher_authenticates_package_artifact_producer() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "/actions/artifacts/$PACKAGE_ARTIFACT_ID" in source
    assert "/actions/runs/$producer_run_id" in source
    assert "ARCHIVE_CLEAN_PACKAGE_ARTIFACT_EXPIRED" in source
    assert "ARCHIVE_CLEAN_PACKAGE_PRODUCER_REPOSITORY_MISMATCH" in source
    assert "ARCHIVE_CLEAN_PACKAGE_PRODUCER_BRANCH_MISMATCH" in source
    assert "ARCHIVE_CLEAN_PACKAGE_PRODUCER_NOT_SUCCESS" in source
    assert "ARCHIVE_CLEAN_PACKAGE_PRODUCER_EVENT_MISMATCH" in source
    assert 'run.get("head_branch") != "main"' in source


def test_runtime_publisher_publishes_and_reverifies_package_bound_runtime() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "cocomelon-historical-archive-clean-runtime publish-package" in source
    assert "cocomelon-historical-archive-clean-runtime verify" in source
    assert "ARCHIVE_CLEAN_RUNTIME_PACKAGE_BINDING_REQUIRED" in source
    assert "ARCHIVE_CLEAN_RUNTIME_PACKAGE_ID_MISMATCH" in source
    assert "ARCHIVE_CLEAN_RUNTIME_EXECUTION_READY_FORBIDDEN" in source
    assert "portable_package_bound" in source
    assert "candidate_package_id" in source


def test_runtime_publisher_uploads_pin_scoped_runtime_and_publication_receipt() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "actions/upload-artifact@v7" in source
    assert "historical-archive-clean-runtime-${{ steps.runtime.outputs.pin_id }}" in source
    assert "steps.runtime_upload.outputs.artifact-id" in source
    assert "historical-archive-clean-runtime-publication-" in source
    assert '"runtime_artifact_id": os.environ["RUNTIME_ARTIFACT_ID"]' in source
    assert '"frozen_revision": os.environ["GITHUB_SHA"]' in source
    assert '"package_id": os.environ["PACKAGE_ID"]' in source
    assert '"pin_id": os.environ["PIN_ID"]' in source
    assert '"execution_ready": False' in source
