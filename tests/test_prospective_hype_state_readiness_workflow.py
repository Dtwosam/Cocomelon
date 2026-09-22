from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/prospective-hype-state-readiness.yml")


def test_state_readiness_is_read_only_and_never_invokes_observer() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "contents: read" in source
    assert "actions: read" in source
    assert "contents: write" not in source
    assert "actions: write" not in source
    assert "cocomelon-prospective-hype-observer" not in source
    assert "COCOMELON_EXECUTION_MODE" not in source


def test_state_readiness_authenticates_selected_state_artifact_producer() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "actions/artifacts/$artifact_id" in source
    assert "actions/runs/$run_id" in source
    assert 'artifact.get("name") != "prospective-hype-clean-state"' in source
    assert 'workflow_run.get("head_branch") != "main"' in source
    assert 'run.get("head_branch") != "main"' in source
    assert 'run.get("path") != ".github/workflows/prospective-hype-clean.yml"' in source
    assert 'run.get("repository", {}).get("full_name")' in source
    assert "STATE_ARTIFACT_PRODUCER_PROVENANCE_INVALID" in source


def test_state_readiness_verifies_provenance_before_downloading_state() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    metadata_index = source.index("/actions/artifacts/$artifact_id")
    run_index = source.index("/actions/runs/$run_id")
    zip_index = source.index("/actions/artifacts/$artifact_id/zip")

    assert metadata_index < run_index < zip_index


def test_state_readiness_preserves_immutable_receipt_contract() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "cocomelon-prospective-hype-state-readiness" in source
    assert 'payload["readiness_status"] in {' in source
    assert '"ready_pre_cutover_state"' in source
    assert '"post_cutover_state_valid"' in source
    assert "prospective-hype-state-readiness-${{ github.run_id }}-" in source
    assert "if-no-files-found: error" in source
    assert "retention-days: 90" in source
