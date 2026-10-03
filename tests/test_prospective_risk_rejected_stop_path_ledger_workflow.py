from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(
    ".github/workflows/prospective-risk-rejected-stop-path-ledger.yml"
)


def _source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_stop_path_workflow_is_research_only() -> None:
    source = _source()

    assert "Prospective Risk-Rejected Stop-Path Ledger" in source
    assert 'LEDGER_ISSUE: "805"' in source
    assert "actions: read" in source
    assert "contents: read" in source
    assert "issues: write" in source
    assert "actions: write" not in source
    assert "COCOMELON_EXECUTION_MODE" not in source
    assert "**Execution authority:**" in source
    assert "**Promotion authority:**" in source
    assert "**LIVE TRADING: DISABLED.**" in source


def test_stop_path_workflow_binds_stop_aware_compact_source() -> None:
    source = _source()

    assert (
        'run.get("path") != ".github/workflows/continuous-paper.yml"'
        in source
    )
    assert "prospective-full-stack-forward-markout-summary.json" in source
    assert 'candidate.get("stop_path_overlay")' in source
    assert 'stop_overlay.get("enabled") is True' in source
    assert '"observed_mark_stop_crossing_only"' in source
    assert 'row.get("long_trend_carveout_stop_path")' in source
    assert "predates observed stop-path lineage" in source
    assert "--source-artifact-digest" in source


def test_stop_path_workflow_restores_append_only_overlay() -> None:
    source = _source()

    assert (
        "actions/workflows/prospective-risk-rejected-stop-path-ledger.yml/"
        "runs?status=success&per_page=100"
        in source
    )
    assert "prospective-risk-rejected-stop-path-ledger-" in source
    assert "prospective-risk-rejected-stop-path-ledger.json" in source
    assert "update_prospective_risk_rejected_stop_path_ledger.py" in source
    assert "--previous" in source
    assert "append-only invariant failure" in source
    assert "Fail closed on ledger drift" in source


def test_stop_path_workflow_surfaces_crossings_by_filter_layer() -> None:
    source = _source()

    assert "### Fixed stop-path horizons" in source
    assert "Evaluable" in source
    assert "Crossed" in source
    assert "Survived" in source
    assert "Cross frac" in source
    assert "Median TTS" in source
    assert "by stack block layer" in source
    assert "by combined-filter reason" in source
    assert 'item["by_block_layer"]' in source
    assert 'item["by_combined_reason"]' in source


def test_stop_path_workflow_surfaces_risk_budget_survival_gate() -> None:
    source = _source()

    assert "### Risk-budget stop-survival gate" in source
    assert "ready reasons" in source
    assert "minimum evaluable / markets / LONG / SHORT per horizon" in source
    assert "### Stop-survival readiness by risk reason" in source
    assert "leave_one_opportunity_min_survival_margin" in source
    assert "leave_one_market_min_survival_margin" in source
    assert "coverage_complete" in source
    assert "Issue #774 must also pass" in source
    assert "Neither gate can relax risk by itself." in source


def test_stop_path_workflow_keeps_claim_scope_narrow() -> None:
    source = _source()

    assert "reports only observed causal mark crossings" in source
    assert "does not prove the unseen intrablock path stayed clear" in source
    assert "does not simulate stop fill price" in source
    assert "Pending or missing-path opportunities remain unfrozen." in source


def test_stop_path_workflow_waits_for_legacy_source() -> None:
    source = _source()
    compact = source.split(
        "      - name: Download compact paper source",
        1,
    )[1].split(
        "      - name: Publish waiting-for-source status",
        1,
    )[0]

    assert 'print("current" if current else "legacy")' in compact
    assert 'if [ "$format_check" != "current" ]; then' in compact
    assert 'echo "eligible=false"' in compact
    assert "predates observed stop-path lineage" in compact


def test_stop_path_non_success_wake_falls_back() -> None:
    source = _source()

    assert (
        'if [ "$EVENT_NAME" = "workflow_run" ] && '
        '[ "$EVENT_CONCLUSION" = "success" ]; then'
        in source
    )
    assert 'resolution_mode="successful_event"' in source
    assert (
        'resolution_mode="latest_successful_after_non_success_wake"'
        in source
    )
    assert "latest_successful_with_compact_artifact" in source


def test_stop_path_workflow_surfaces_post_integrity_cohort() -> None:
    source = _source()

    assert "post-integrity boundary known" in source
    assert "post-integrity last miss / start" in source
    assert "post-integrity terminal opportunities" in source
    assert "post-integrity ready reasons" in source
    assert "starts strictly after the last known rank/momentum lineage miss" in source
