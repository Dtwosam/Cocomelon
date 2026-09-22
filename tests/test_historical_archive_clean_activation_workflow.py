from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/historical-archive-clean-activation.yml")


def test_activation_workflow_is_manual_read_only_offline_and_disabled_safe() -> None:
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
    assert "campaign enabled at authorization: false" in source
    assert "execution ready: false" in source


def test_activation_workflow_authenticates_runtime_and_bootstrap_producers() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "RUNTIME_PUBLISHER_WORKFLOW_PATH" in source
    assert "historical-archive-clean-runtime-publish.yml" in source
    assert "ARCHIVE_CLEAN_RUNTIME_PRODUCER_WORKFLOW_MISMATCH" in source
    assert "ARCHIVE_CLEAN_RUNTIME_PRODUCER_REPOSITORY_MISMATCH" in source
    assert "ARCHIVE_CLEAN_RUNTIME_PRODUCER_BRANCH_MISMATCH" in source
    assert "ARCHIVE_CLEAN_RUNTIME_PRODUCER_REVISION_MISMATCH" in source
    assert "ARCHIVE_CLEAN_RUNTIME_PRODUCER_EVENT_MISMATCH" in source
    assert "ARCHIVE_CLEAN_RUNTIME_PRODUCER_NOT_SUCCESS" in source
    assert "BOOTSTRAP_WORKFLOW_PATH" in source
    assert "historical-archive-clean-bootstrap.yml" in source
    assert "ARCHIVE_CLEAN_BOOTSTRAP_PRODUCER_WORKFLOW_MISMATCH" in source
    assert "ARCHIVE_CLEAN_BOOTSTRAP_PRODUCER_REPOSITORY_MISMATCH" in source
    assert "ARCHIVE_CLEAN_BOOTSTRAP_PRODUCER_BRANCH_MISMATCH" in source
    assert "ARCHIVE_CLEAN_BOOTSTRAP_PRODUCER_REVISION_MISMATCH" in source
    assert "ARCHIVE_CLEAN_BOOTSTRAP_PRODUCER_EVENT_MISMATCH" in source
    assert "ARCHIVE_CLEAN_BOOTSTRAP_PRODUCER_NOT_SUCCESS" in source


def test_activation_workflow_restores_bootstrap_before_authorization() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    bootstrap = source.index("Restore authenticated pre-cutover bootstrap state")
    authorize = source.index("Create pre-cutover activation authorization")

    assert bootstrap < authorize
    assert "--state-root \"$STATE_ROOT\"" in source
    assert "cocomelon-historical-archive-clean-activation" in source
    assert "ARCHIVE_CLEAN_ACTIVATION_CAMPAIGN_ENABLED_FORBIDDEN" in source
    assert "ARCHIVE_CLEAN_ACTIVATION_AUTHORIZATION_REQUIRED" in source
    assert "ARCHIVE_CLEAN_ACTIVATION_EXECUTION_READY_FORBIDDEN" in source

def test_activation_workflow_uploads_separate_pin_scoped_artifact() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "actions/upload-artifact@v7" in source
    assert "ACTIVATION_ARTIFACT_NAME" in source
    assert "historical-archive-clean-activation-" in source
    assert "retention-days: 90" in source
    assert "activation.json" in source
    assert "ARCHIVE_CLEAN_ACTIVATION_FILE_SET_MISMATCH" in source


def test_activation_workflow_separates_auditor_from_frozen_scorer_revision() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "AUTHORIZATION_SOURCE_REVISION: ${{ github.sha }}" in source
    assert "Checkout activation auditor revision" in source
    assert "ref: ${{ github.sha }}" in source
    assert 'test "$(git rev-parse HEAD)" = "$AUTHORIZATION_SOURCE_REVISION"' in source
    assert "require_current_source_match=False" in source
    assert '--authorization-source-revision "$AUTHORIZATION_SOURCE_REVISION"' in source
    assert "ARCHIVE_CLEAN_ACTIVATION_SOURCE_REVISION_MISMATCH" in source
    assert 'run.get("head_sha") != os.environ["FROZEN_REVISION"]' in source

def test_activation_workflow_auto_runs_only_after_successful_main_bootstrap() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_run:" in source
    assert "Historical Archive Clean Bootstrap" in source
    assert "types:" in source
    assert "- completed" in source
    assert "github.event_name == 'workflow_run'" in source
    assert "github.event.workflow_run.conclusion == 'success'" in source
    assert "github.event.workflow_run.head_branch == 'main'" in source
    assert "github.event_name == 'workflow_dispatch'" in source
    assert "schedule:" not in source

