from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(
    ".github/workflows/prospective-weekly-drawdown-5m-exit.yml"
)
SCRIPT = Path(
    "scripts/evaluate_prospective_weekly_drawdown_5m_exit.py"
)


def _source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_weekly_drawdown_5m_workflow_is_research_only() -> None:
    source = _source()

    assert "Prospective Weekly Drawdown 5m Exit Evidence" in source
    assert 'EVIDENCE_ISSUE: "842"' in source
    assert "actions: read" in source
    assert "contents: read" in source
    assert "issues: write" in source
    assert "actions: write" not in source
    assert "COCOMELON_EXECUTION_MODE" not in source
    assert "**Execution authority:**" in source
    assert "**Promotion authority:**" in source
    assert "**Changes risk limits:**" in source
    assert "**LIVE TRADING: DISABLED.**" in source


def test_weekly_drawdown_5m_workflow_uses_authenticated_paper_source() -> None:
    source = _source()

    assert '      - "Continuous Mainnet Paper Trader"' in source
    assert "continuous-paper-learning-source-" in source
    assert "latest_evidence_eligible_with_compact_artifact" in source
    assert "selected source has no authenticated compact artifact" in source
    assert 'run.get("head_branch") != "main"' in source
    assert 'conclusion not in {"success", "failure"}' in source
    assert "source run attempt mismatch" in source
    assert "source repository mismatch" in source
    assert "source artifact digest is missing or invalid" in source
    assert "source artifact digest mismatch" in source


def test_weekly_drawdown_5m_workflow_waits_for_current_candidate_source() -> None:
    source = _source()
    compact = source.split(
        "      - name: Download authenticated candidate source",
        1,
    )[1].split(
        "      - name: Publish waiting status",
        1,
    )[0]

    assert "prospective-weekly-drawdown-5m-exit-source.json" in compact
    assert "prospective-weekly-drawdown-5m-exit-source-v1" in compact
    assert "prospective-weekly-drawdown-stack-admit-5m-exit-v1" in compact
    assert 'payload.get("execution_authority") is False' in compact
    assert 'payload.get("promotion_authority") is False' in compact
    assert 'payload.get("changes_risk_limits") is False' in compact
    assert (
        'payload.get("discovery_cohort_reused_for_validation") is False'
        in compact
    )
    assert 'payload.get("cross_horizon_selection_frozen") is True' in compact
    assert "candidate source is disabled" in compact


def test_weekly_drawdown_5m_workflow_publishes_exact_economics_and_gate() -> None:
    source = _source()

    assert "evaluate_prospective_weekly_drawdown_5m_exit.py" in source
    assert "observed stop survivors / crossings / incomplete" in source
    assert "exact realized-PnL options" in source
    assert "total exact realized PnL" in source
    assert "profit factor" in source
    assert "leave-one-trade min PnL / positive" in source
    assert "leave-one-market min PnL / positive" in source
    assert "chronological halves positive" in source
    assert "investigation gate passed" in source
    assert (
        "This gate only permits deeper research investigation."
        in source
    )
    assert "does not authorize promotion" in source


def test_weekly_drawdown_5m_workflow_uploads_deterministic_summary() -> None:
    source = _source()

    assert "prospective-weekly-drawdown-5m-exit-summary.json" in source
    assert (
        "prospective-weekly-drawdown-5m-exit-${{ github.run_id }}-"
        "${{ github.run_attempt }}"
        in source
    )
    assert "retention-days: 90" in source
    upload = source.split(
        "      - uses: actions/upload-artifact@v7",
        1,
    )[1]
    assert "steps.compact.outputs.eligible == 'true'" in upload


def test_weekly_drawdown_5m_evaluator_cli_is_fail_closed() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "ProspectiveWeeklyDrawdown5mExitError" in source
    assert "prospective_weekly_drawdown_5m_exit_summary" in source
    assert "--json-out" in source
    assert "candidate_investigation_ready" in source
    assert "minimum_sample_met" in source
