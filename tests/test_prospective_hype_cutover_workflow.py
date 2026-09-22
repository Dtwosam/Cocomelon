from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/prospective-hype-cutover-acceptance.yml")


def test_cutover_audit_is_read_only_and_never_invokes_frozen_observer() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "contents: read" in source
    assert "actions: read" in source
    assert "contents: write" not in source
    assert "actions: write" not in source
    assert "cocomelon-prospective-hype-observer" not in source
    assert "COCOMELON_EXECUTION_MODE" not in source


def test_cutover_audit_is_bounded_to_the_frozen_cutover_window() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert 'cron: "30 * 23-25 9 *"' in source
    assert "now.year == 2026" in source
    assert "now.month == 9" in source
    assert "23 <= now.day <= 25" in source
    assert 'os.environ["GITHUB_EVENT_NAME"] == "workflow_dispatch"' in source
    assert "group: prospective-hype-cutover-acceptance" in source
    assert "cancel-in-progress: false" in source


def test_cutover_audit_reuses_one_canonical_receipt() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "CUTOVER_ARTIFACT_NAME: prospective-hype-cutover-acceptance" in source
    assert 'item["name"] == os.environ["CUTOVER_ARTIFACT_NAME"]' in source
    assert '"has_receipt": "true"' in source
    assert "Verify existing canonical cutover receipt" in source
    assert "cocomelon-prospective-hype-cutover verify" in source
    assert "Upload one canonical cutover receipt" in source
    assert "name: prospective-hype-cutover-acceptance" in source
    assert "Verify selected audit artifact producer" in source
    assert 'expected_path=".github/workflows/prospective-hype-cutover-acceptance.yml"' in source
    assert 'expected_path=".github/workflows/prospective-hype-blind-monitor.yml"' in source


def test_cutover_audit_waits_for_first_anchor_and_append_only_lineage() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "plan.first_expected_anchor_ms" in source
    assert 'payload.get("expected_anchor_count_to_date", 0) >= 1' in source
    assert 'payload.get("lineage_status") == "append_only_valid"' in source
    assert 'payload.get("campaign_health_status") in {"healthy", "degraded"}' in source
    assert "waiting for first legal anchor and append-only lineage" in source


def test_cutover_audit_binds_exact_state_from_blind_monitor() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert 'state_id = payload.get("state_artifact_id", "") if ready else ""' in source
    assert "/actions/artifacts/$STATE_ID" in source
    assert 'workflow_run.get("head_branch") != "main"' in source
    assert 'run.get("path") != ".github/workflows/prospective-hype-clean.yml"' in source
    assert "/actions/runs/$state_run_id" in source
    assert "--state-artifact-id" in source
    assert "--state-audited-at-ms" in source
    assert "--audited-at-ms" in source


def test_cutover_audit_never_downloads_or_surfaces_interim_economics() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "prospective-hype-clean-report-" not in source
    assert "prospective-hype-report.json" not in source
    assert "prospective-hype-blind-monitor-" in source
    assert "monitor.json" in source
    assert 'payload["interim_economics_redacted"] is True' in source
    for token in (
        '"mean_net_return":',
        '"total_net_return":',
        '"positive_net_count":',
        '"non_positive_net_count":',
        '"gross_return":',
        '"net_return":',
    ):
        assert token not in source


def test_cutover_receipt_requires_clean_grid_and_zero_pre_cutover_records() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert 'payload["cutover_status"] == "cutover_integrity_valid"' in source
    assert 'payload["pre_cutover_observation_count"] == 0' in source
    assert 'payload["observation_grid_valid"] is True' in source
    assert 'payload["first_anchor_status"] in {"captured", "missed"}' in source
    assert "retention-days: 90" in source
    assert "if-no-files-found: error" in source


def test_cutover_audit_preserves_redacted_failure_receipt_before_failing() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "cocomelon-prospective-hype-cutover-failure" in source
    assert "CUTOVER_ARTIFACT_DISCOVERY_FAILED" in source
    assert "CUTOVER_ARTIFACT_PROVENANCE_FAILED" in source
    assert "CUTOVER_EXISTING_RECEIPT_VERIFY_FAILED" in source
    assert "CUTOVER_MONITOR_ARTIFACT_INVALID" in source
    assert "CUTOVER_MONITOR_READINESS_FAILED" in source
    assert "CUTOVER_STATE_DOWNLOAD_FAILED" in source
    assert "CUTOVER_BUILD_FAILED" in source
    assert "CUTOVER_RECEIPT_UPLOAD_FAILED" in source
    assert "id: success_upload" in source
    assert "failure.json" in source
    assert "Upload cutover failure receipt" in source
    assert "Preserve cutover failure status" in source
    assert "continue-on-error: true" in source
    assert "prospective-hype-cutover-failure-${{ github.run_id }}-" in source
    assert "if-no-files-found: error" in source


def test_cutover_audit_uses_one_clock_for_success_and_failure_receipts() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert source.count("time.time_ns() // 1_000_000") == 1
    assert "id: clock" in source
    assert "steps.clock.outputs.audited_at_ms" in source
    assert '--audited-at-ms "$AUDIT_MS"' in source
    assert '--stage "$stage"' in source


def test_cutover_waiting_for_first_anchor_is_not_classified_as_failure() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "waiting for first legal anchor and append-only lineage" in source
    assert "CUTOVER_EVIDENCE_NOT_READY" not in source
    assert "steps.ready.outputs.ready == 'true'" in source
    assert "steps.ready.outcome == 'failure'" in source


def test_cutover_failure_paths_remain_economics_redacted() -> None:
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
