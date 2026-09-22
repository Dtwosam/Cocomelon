from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/prospective-hype-blind-monitor.yml")


def test_blind_monitor_is_read_only_and_never_invokes_frozen_observer() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "contents: read" in source
    assert "actions: read" in source
    assert "contents: write" not in source
    assert "actions: write" not in source
    assert "cocomelon-prospective-hype-observer" not in source
    assert "prospective-hype-clean.yml" not in source
    assert "COCOMELON_EXECUTION_MODE" not in source


def test_blind_monitor_runs_after_capture_and_lineage_schedules() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert 'cron: "25 * * * *"' in source
    assert 'cron: "20 * * * *"' not in source
    assert 'cron: "3,8,13 * * * *"' not in source
    assert "group: prospective-hype-blind-monitor" in source
    assert "cancel-in-progress: false" in source


def test_blind_monitor_matches_state_to_latest_health_run() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert 'item["name"].startswith("prospective-hype-clean-health-")' in source
    assert 'item["name"].startswith("prospective-hype-lineage-")' in source
    assert 'item["name"] == "prospective-hype-clean-state"' in source
    assert 'item["workflow_run"]["id"] == health["workflow_run"]["id"]' in source
    assert "len(matching_states) != 1" in source
    assert '"state_id": state["id"]' in source


def test_blind_monitor_never_downloads_or_names_interim_economics() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "prospective-hype-clean-report-" not in source
    assert "prospective-hype-report.json" not in source
    assert "prospective-hype-health.json" in source
    assert "lineage.json" in source
    for token in (
        "mean_net_return",
        "total_net_return",
        "positive_net_count",
        "non_positive_net_count",
        "gross_return",
        "net_return",
    ):
        assert token not in source


def test_blind_monitor_requires_redacted_output_and_uploads_receipt() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "cocomelon-prospective-hype-blind-monitor" in source
    assert "--state-artifact-id" in source
    assert "--audited-at-ms" in source
    assert "time.time_ns() // 1_000_000" in source
    assert 'payload["interim_economics_redacted"] is True' in source
    assert "actions/upload-artifact@v7" in source
    assert (
        "prospective-hype-blind-monitor-${{ github.run_id }}-"
        "${{ github.run_attempt }}"
    ) in source
    assert "retention-days: 90" in source
    assert "if-no-files-found: error" in source


def test_blind_monitor_validates_pull_requests_without_live_artifacts() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "pull_request:" in source
    assert 'branches:\n      - main' in source
    assert '"src/cocomelon/research/prospective_blind_monitor.py"' in source
    assert "github.event_name == 'pull_request'" in source
    assert "github.event_name != 'pull_request'" in source
    assert "Validate freshness and workflow contracts" in source
    assert "tests/test_prospective_blind_monitor.py" in source
    assert "tests/test_prospective_cutover_acceptance.py" in source
    assert "tests/test_prospective_hype_blind_monitor_workflow.py" in source


def test_blind_monitor_preserves_redacted_failure_receipt_before_failing() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "cocomelon-prospective-hype-blind-monitor-failure" in source
    assert "ARTIFACT_DISCOVERY_REQUEST_FAILED" in source
    assert "HEALTH_ARTIFACT_MISSING" in source
    assert "LINEAGE_ARTIFACT_MISSING" in source
    assert "STATE_ARTIFACT_MATCH_INVALID" in source
    assert "HEALTH_ARTIFACT_DOWNLOAD_FAILED" in source
    assert "LINEAGE_ARTIFACT_DOWNLOAD_FAILED" in source
    assert "MONITOR_BUILD_FAILED" in source
    assert "failure.json" in source
    assert "if: ${{ always() }}" in source
    assert "Preserve discovery failure receipt" in source
    assert "Preserve download failure receipt" in source
    assert "Preserve monitor failure status" in source
    assert "steps.discover.outputs.status != 'ok'" in source
    assert "steps.download.outputs.status != 'ok'" in source
    assert "steps.monitor.outputs.exit_code != '0'" in source
    for token in (
        "mean_net_return",
        "total_net_return",
        "positive_net_count",
        "non_positive_net_count",
        "gross_return",
        "net_return",
    ):
        assert token not in source


def test_blind_monitor_uses_one_audit_clock_across_all_failure_stages() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert source.count("time.time_ns() // 1_000_000") == 1
    assert "id: clock" in source
    assert "steps.clock.outputs.audited_at_ms" in source
    assert "--stage discovery" in source
    assert "--stage download" in source
    assert "--stage build" in source


def test_blind_monitor_only_consumes_live_artifacts_outside_pull_requests() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "if: ${{ github.event_name == 'pull_request' }}" in source
    assert "if: ${{ github.event_name != 'pull_request' }}" in source
    validate_index = source.index("jobs:\n  validate:")
    monitor_index = source.index("\n  monitor:")
    assert validate_index < monitor_index
