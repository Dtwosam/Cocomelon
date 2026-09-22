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


def test_lineage_audit_compares_latest_two_distinct_observer_runs() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "prospective-hype-clean-state" in source
    assert "actions/artifacts?name=$STATE_ARTIFACT_NAME" in source
    assert "select_lineage_state_pair" in source
    assert "ProspectiveArtifactSelectionError" in source
    assert '"src/cocomelon/research/prospective_artifact_selection.py"' in source
    assert '"tests/test_prospective_artifact_selection.py"' in source
    assert "previous, current = artifacts[-2:]" not in source
    assert "/artifacts/$PREVIOUS_ID/zip" in source
    assert "/artifacts/$CURRENT_ID/zip" in source
    assert "Verify selected state artifact producers" in source
    assert "/actions/runs/$run_id" in source
    assert 'run.get("path") != expected_path' in source
    assert 'expected_path = ".github/workflows/prospective-hype-clean.yml"' in source
    assert 'run.get("repository", {}).get("full_name")' in source


def test_lineage_audit_uses_artifact_creation_times_and_record_level_verifier() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert '"previous_audited_at_ms": selected.previous_audited_at_ms' in source
    assert '"current_audited_at_ms": selected.current_audited_at_ms' in source
    assert "cocomelon-prospective-hype-lineage" in source
    assert "--previous-artifact-id" in source
    assert "--current-artifact-id" in source
    assert "--previous-audited-at-ms" in source
    assert "--current-audited-at-ms" in source
    assert 'payload["lineage_status"] in {' in source
    assert '"append_only_valid"' in source
    assert '"waiting_for_second_frozen_format_state"' in source


def test_lineage_receipt_is_preserved_as_separate_immutable_artifact() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "actions/upload-artifact@v7" in source
    assert "prospective-hype-lineage-${{ github.run_id }}-${{ github.run_attempt }}" in source
    assert "artifacts/prospective-hype-lineage/lineage.json" in source
    assert "if-no-files-found: error" in source
    assert "retention-days: 90" in source



def test_lineage_audit_never_skips_an_invalid_latest_frozen_state() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "Verify latest frozen-format state and classify predecessor" in source
    assert "cocomelon-prospective-hype-state-readiness" in source
    assert '--root "$LINEAGE_ROOT/current"' in source
    assert '--root "$LINEAGE_ROOT/previous"' in source
    assert '[[ -f "$LINEAGE_ROOT/previous/control-plane.json" ]]' in source
    assert "for candidate" not in source
    assert "select_lineage_state_pair" in source


def test_lineage_bootstrap_receipt_is_only_for_pre_control_plane_predecessor() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "previous_artifact_predates_control_plane_freeze" in source
    assert 'HAS_FROZEN_PAIR: ${{ steps.compatibility.outputs.has_frozen_pair }}' in source
    assert 'if [[ "$HAS_FROZEN_PAIR" == "true" ]]; then' in source
    assert '"current_state_digest": current["state_digest"]' in source
    assert '"runtime_attestation_id": current["runtime_attestation_id"]' in source
    assert '"control_plane_id": current["control_plane_id"]' in source



def test_lineage_audit_runs_hourly_after_frozen_capture_attempts() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert 'cron: "20 * * * *"' in source
    assert "group: prospective-hype-lineage-audit" in source
    assert "cancel-in-progress: false" in source
    assert 'cron: "47 * * * *"' not in source
    assert "cocomelon-prospective-hype-observer" not in source


def test_lineage_audit_preserves_redacted_failure_receipt_before_failing() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "cocomelon-prospective-hype-lineage-failure" in source
    assert "LINEAGE_ARTIFACT_DISCOVERY_FAILED" in source
    assert "LINEAGE_ARTIFACT_PROVENANCE_FAILED" in source
    assert "LINEAGE_STATE_DOWNLOAD_FAILED" in source
    assert "LINEAGE_STATE_READINESS_FAILED" in source
    assert "LINEAGE_APPEND_ONLY_VERIFY_FAILED" in source
    assert "LINEAGE_RECEIPT_UPLOAD_FAILED" in source
    assert "failure.json" in source
    assert "Upload lineage failure receipt" in source
    assert "Preserve lineage failure status" in source
    assert "continue-on-error: true" in source
    assert "if-no-files-found: error" in source


def test_lineage_provenance_failure_is_terminal() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    terminal_index = source.index("Preserve lineage failure status")
    terminal_tail = source[terminal_index:]
    assert "steps.provenance.outcome == 'failure'" in terminal_tail


def test_lineage_failure_artifact_cannot_match_success_prefix() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "name: prospective-hype-lineage-${{ github.run_id }}-" in source
    assert "name: prospective-hype-failed-lineage-audit-${{ github.run_id }}-" in source
    assert "name: prospective-hype-lineage-failure-${{ github.run_id }}-" not in source


def test_lineage_audit_uses_one_clock_for_failure_evidence() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert source.count("time.time_ns() // 1_000_000") == 1
    assert "id: clock" in source
    assert "steps.clock.outputs.audited_at_ms" in source
    assert '--audited-at-ms "$AUDIT_MS"' in source


def test_lineage_failure_paths_remain_economics_redacted() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    for token in (
        '"mean_net_return":',
        '"total_net_return":',
        '"positive_net_count":',
        '"non_positive_net_count":',
        '"gross_return":',
        '"net_return":',
        '"pnl":',
    ):
        assert token not in source
