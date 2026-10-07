from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(
    ".github/workflows/prospective-long-trend-5m-exact.yml"
)
SCRIPT = Path(
    "scripts/evaluate_prospective_long_trend_5m_exit.py"
)
MODULE = Path(
    "src/cocomelon/research/prospective_long_trend_5m_exit_source.py"
)


def _source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_long_trend_5m_workflow_is_research_only() -> None:
    source = _source()

    assert "Prospective Reopened LONG Trend 5m Exact Evidence" in source
    assert 'EVIDENCE_ISSUE: "844"' in source
    assert "actions: read" in source
    assert "contents: read" in source
    assert "issues: write" in source
    assert "actions: write" not in source
    assert "COCOMELON_EXECUTION_MODE" not in source
    assert "**Execution authority:**" in source
    assert "**Promotion authority:**" in source
    assert "**Changes risk limits:**" in source
    assert "**LIVE TRADING: DISABLED.**" in source


def test_long_trend_5m_workflow_has_periodic_artifact_catchup() -> None:
    source = _source()

    assert "  schedule:" in source
    assert '    - cron: "17 * * * *"' in source
    assert "latest_evidence_eligible_with_state_artifact" in source


def test_long_trend_5m_workflow_uses_authenticated_durable_state() -> None:
    source = _source()

    assert '      - "Continuous Mainnet Paper Trader"' in source
    assert "continuous-paper-state-" in source
    assert "latest_evidence_eligible_with_state_artifact" in source
    assert (
        "no authenticated durable paper state is available"
        in source
    )
    assert 'run.get("head_branch") != "main"' in source
    assert 'conclusion not in {"success", "failure"}' in source
    assert "source run attempt mismatch" in source
    assert "source repository mismatch" in source
    assert "state artifact digest is missing or invalid" in source
    assert "state artifact digest mismatch" in source
    assert "continuous-paper-state.tar" in source


def test_long_trend_5m_workflow_requires_exact_state_evidence_roots() -> None:
    source = _source()
    download = source.split(
        "      - name: Download authenticated durable state",
        1,
    )[1].split(
        "      - name: Evaluate exact LONG trend 5m candidate",
        1,
    )[0]

    assert "prospective-full-stack-forward-markout-summary.json" in download
    assert "prospective-long-trend-execution-shadow-source.json" in download
    assert "opening-opportunities/records" in download
    assert "opening-opportunity-exit-books/records" in download
    assert "replacement-funding-boundaries/records" in download


def test_long_trend_5m_workflow_publishes_exact_economics_and_gate() -> None:
    source = _source()

    assert "evaluate_prospective_long_trend_5m_exit.py" in source
    assert "observed stop survivors / crossings / incomplete" in source
    assert "exact realized-PnL options" in source
    assert "total gross realized PnL" in source
    assert "total entry / exit fee drag" in source
    assert "gross return / fee drag / net return on entry notional" in source
    assert "total exact realized PnL" in source
    assert "profit factor" in source
    assert "leave-one-trade min PnL / positive" in source
    assert "leave-one-market min PnL / positive" in source
    assert "chronological halves positive" in source
    assert "investigation gate passed" in source
    assert "does not relax the weekly drawdown" in source


def test_long_trend_5m_workflow_uploads_source_and_summary() -> None:
    source = _source()

    assert "prospective-long-trend-5m-exit-source.json" in source
    assert "prospective-long-trend-5m-exit-summary.json" in source
    assert (
        "prospective-long-trend-5m-exact-${{ github.run_id }}-"
        "${{ github.run_attempt }}"
        in source
    )
    assert "retention-days: 90" in source


def test_long_trend_5m_cli_reads_durable_state_and_frozen_source() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "prospective-full-stack-forward-markout-summary.json" in source
    assert "prospective-long-trend-execution-shadow-source.json" in source
    assert "opening-opportunities" in source
    assert "opening-opportunity-exit-books" in source
    assert "replacement-funding-boundaries" in source
    assert "_execution_config_from_durable_long_trend_source" in source
    assert "execution_config_sha256" in source
    assert "FROZEN_STARTED_AT_MS" in source
    assert "candidate_investigation_ready" in source


def test_long_trend_5m_freeze_timestamp_is_literal_and_auditable() -> None:
    source = MODULE.read_text(encoding="utf-8")

    assert "FROZEN_STARTED_AT_MS: Final = 1_791_103_620_000" in source
    assert (
        '"entry_scope": '
        '"weekly_drawdown_only_reopened_pure_long_trend"'
        in source
    )
