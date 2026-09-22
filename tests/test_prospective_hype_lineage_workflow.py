from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/prospective-hype-lineage.yml")


def test_lineage_audit_is_read_only_and_separate_from_frozen_observer() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "contents: read" in source
    assert "actions: read" in source
    assert "contents: write" not in source
    assert "actions: write" not in source
    assert "COCOMELON_EXECUTION_MODE" not in source
    assert "cocomelon-prospective-hype-observer" not in source
    assert "prospective-hype-clean.yml" not in source


def test_lineage_audit_compares_latest_two_main_state_artifacts() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "prospective-hype-clean-state" in source
    assert "actions/artifacts?name=$STATE_ARTIFACT_NAME" in source
    assert 'item["workflow_run"]["head_branch"] == "main"' in source
    assert "previous, current = artifacts[-2:]" in source
    assert "/artifacts/$PREVIOUS_ID/zip" in source
    assert "/artifacts/$CURRENT_ID/zip" in source


def test_lineage_audit_uses_artifact_creation_times_and_record_level_verifier() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert '"previous_audited_at_ms": epoch_ms(previous["created_at"])' in source
    assert '"current_audited_at_ms": epoch_ms(current["created_at"])' in source
    assert "cocomelon-prospective-hype-lineage" in source
    assert "--previous-artifact-id" in source
    assert "--current-artifact-id" in source
    assert "--previous-audited-at-ms" in source
    assert "--current-audited-at-ms" in source
    assert 'payload["lineage_status"] == "append_only_valid"' in source


def test_lineage_receipt_is_preserved_as_separate_immutable_artifact() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "actions/upload-artifact@v7" in source
    assert "prospective-hype-lineage-${{ github.run_id }}-${{ github.run_attempt }}" in source
    assert "artifacts/prospective-hype-lineage/lineage.json" in source
    assert "if-no-files-found: error" in source
    assert "retention-days: 90" in source
