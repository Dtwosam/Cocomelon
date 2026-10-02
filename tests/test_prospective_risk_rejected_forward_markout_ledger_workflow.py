from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(
    ".github/workflows/"
    "prospective-risk-rejected-fast-markout-ledger.yml"
)


def _source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_risk_rejected_ledger_workflow_is_research_only() -> None:
    source = _source()

    assert "Prospective Risk-Rejected Fast-Markout Ledger" in source
    assert "Continuous Mainnet Paper Trader" in source
    assert 'LEDGER_ISSUE: "774"' in source
    assert "actions: read" in source
    assert "contents: read" in source
    assert "issues: write" in source
    assert "actions: write" not in source
    assert "COCOMELON_EXECUTION_MODE" not in source
    assert "Execution authority:" in source
    assert "Promotion authority:" in source
    assert "Changes risk limits:" in source
    assert "Changes candidate readiness:" in source
    assert "LIVE TRADING: DISABLED." in source


def test_risk_rejected_ledger_binds_exact_compact_source() -> None:
    source = _source()

    assert (
        'run.get("path") != ".github/workflows/continuous-paper.yml"'
        in source
    )
    assert 'run.get("head_branch") != "main"' in source
    assert 'run.get("conclusion") != "success"' in source
    assert "source run attempt mismatch" in source
    assert "source repository mismatch" in source
    assert (
        'expected_name="continuous-paper-learning-source-'
        '$candidate_run_id-$candidate_attempt"'
        in source
    )
    assert "source artifact digest is missing or invalid" in source
    assert "prospective-full-stack-forward-markout-summary.json" in source


def test_risk_rejected_ledger_restores_append_only_evidence() -> None:
    source = _source()

    assert "prospective-risk-rejected-fast-markout-ledger-" in source
    assert "prospective-risk-rejected-fast-markout-ledger.json" in source
    assert (
        "update_prospective_risk_rejected_fast_markout_ledger.py"
        in source
    )
    assert "--source-artifact-digest" in source
    assert "--previous" in source
    assert "append-only invariant failure" in source
    assert "Fail closed on ledger drift" in source
    assert "Every previously published terminal row" in source


def test_risk_rejected_ledger_keeps_pending_rows_unfrozen() -> None:
    source = _source()

    assert "terminal / previous / new / pending" in source
    assert (
        "Only rows with all fixed horizons terminal become immutable"
        in source
    )
    assert "pending and missing-path rows remain unfrozen" in source
    assert (
        "cannot relax a risk veto or change any entry-candidate "
        "readiness gate"
        in source
    )


def test_risk_rejected_ledger_surfaces_reason_level_markouts() -> None:
    source = _source()

    assert "risk reason counts" in source
    assert "by risk reason" in source
    assert "stack-admit-settled={admit_n}" in source
    assert "stack-admit-mean={admit_mean}" in source
    assert "leave_one_opportunity_min_mean" in source
    assert "leave_one_market_min_mean" in source


def test_risk_rejected_ledger_non_success_wake_falls_back() -> None:
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
    assert (
        "actions/workflows/continuous-paper.yml/runs?"
        "branch=main&status=completed&per_page=50"
        in source
    )


def test_risk_rejected_waiting_and_blocked_status_use_quoted_builders() -> None:
    source = _source()
    waiting = source.split(
        "      - name: Publish waiting-for-source status",
        1,
    )[1].split(
        "      - name: Restore previous fast-markout ledger",
        1,
    )[0]
    blocked = source.split(
        "      - name: Publish blocked ledger status",
        1,
    )[1].split(
        "      - name: Fail closed on ledger drift",
        1,
    )[0]

    assert "python - <<'PY'" in waiting
    assert "python - <<'PY'" in blocked
    assert "os.environ['SOURCE_RUN_ID']" in waiting
    assert "os.environ['SOURCE_RUN_ATTEMPT']" in waiting
    assert "os.environ['RESOLUTION_MODE']" in waiting
    assert 'os.environ.get("ERROR_TEXT")' in blocked


def test_risk_rejected_source_skips_empty_successful_handoffs() -> None:
    source = _source()

    assert "artifact_for_run()" in source
    assert "latest_successful_with_compact_artifact" in source
    assert "selected source has no authenticated compact artifact" in source
    assert "artifact_candidates" in source
    assert 'EVENT_NAME" != "workflow_dispatch"' in source
