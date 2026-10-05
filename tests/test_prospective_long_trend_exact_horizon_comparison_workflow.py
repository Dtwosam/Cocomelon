from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(
    ".github/workflows/prospective-long-trend-exact-horizon-comparison.yml"
)
SCRIPT = Path(
    "scripts/evaluate_prospective_long_trend_exact_horizon_comparison.py"
)
MODULE = Path(
    "src/cocomelon/research/prospective_long_trend_exact_horizon_comparison.py"
)


def _source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_exact_horizon_comparison_workflow_is_research_only() -> None:
    source = _source()

    assert "Prospective Reopened LONG Trend Exact 5m vs 15m" in source
    assert 'EVIDENCE_ISSUE: "896"' in source
    assert "actions: read" in source
    assert "contents: read" in source
    assert "issues: write" in source
    assert "actions: write" not in source
    assert "COCOMELON_EXECUTION_MODE" not in source
    assert "**Execution authority:**" in source
    assert "**Promotion authority:**" in source
    assert "**Changes risk limits:**" in source
    assert "**LIVE TRADING: DISABLED.**" in source


def test_exact_horizon_comparison_has_periodic_artifact_catchup() -> None:
    source = _source()

    assert "  schedule:" in source
    assert '    - cron: "37 * * * *"' in source
    assert "latest_successful_with_state_artifact" in source
    assert '      - "Continuous Mainnet Paper Trader"' in source


def test_exact_horizon_comparison_uses_authenticated_durable_state() -> None:
    source = _source()

    assert "continuous-paper-state-" in source
    assert (
        "manual source has no authenticated durable state artifact"
        in source
    )
    assert 'run.get("head_branch") != "main"' in source
    assert 'run.get("conclusion") != "success"' in source
    assert "source run attempt mismatch" in source
    assert "source repository mismatch" in source
    assert "state artifact digest is missing or invalid" in source
    assert "state artifact digest mismatch" in source
    assert "continuous-paper-state.tar" in source


def test_exact_horizon_comparison_requires_shared_evidence_roots() -> None:
    source = _source()
    download = source.split(
        "      - name: Download authenticated durable state",
        1,
    )[1].split(
        "      - name: Evaluate paired exact LONG trend horizons",
        1,
    )[0]

    assert "prospective-full-stack-forward-markout-summary.json" in download
    assert "prospective-long-trend-execution-shadow-source.json" in download
    assert "opening-opportunities/records" in download
    assert "opening-opportunity-exit-books/records" in download
    assert "replacement-funding-boundaries/records" in download


def test_exact_horizon_comparison_publishes_paired_robustness() -> None:
    source = _source()

    assert (
        "evaluate_prospective_long_trend_exact_horizon_comparison.py"
        in source
    )
    assert "source 5m / source 15m / common source" in source
    assert "source-only 5m / source-only 15m" in source
    assert "5m incomplete reasons" in source
    assert "15m incomplete reasons" in source
    assert "exact 5m / exact 15m / paired" in source
    assert "5m-only / 15m-only exact" in source
    assert "total / mean delta (5m - 15m)" in source
    assert "size-normalized total / mean return delta" in source
    assert "leave-one-trade min / max delta" in source
    assert "leave-one-market min / max delta" in source
    assert "chronological first / second half delta" in source
    assert "size-normalized leave-one-trade min / max" in source
    assert "size-normalized leave-one-market min / max" in source
    assert "size-normalized chronological first / second half" in source
    assert "5m robustly better" in source
    assert "15m robustly better" in source
    assert "preferred horizon" in source
    assert "5m size-normalized robustly better" in source
    assert "15m size-normalized robustly better" in source
    assert "size-normalized preferred horizon" in source
    assert "Only opportunities with exact execution PnL on both" in source


def test_exact_horizon_comparison_uploads_common_freeze_summaries() -> None:
    source = _source()

    assert "prospective-long-trend-exact-horizon-comparison.json" in source
    assert "prospective-long-trend-common-freeze-5m-summary.json" in source
    assert "prospective-long-trend-common-freeze-15m-summary.json" in source
    assert (
        "prospective-long-trend-exact-horizon-comparison-"
        "${{ github.run_id }}-${{ github.run_attempt }}"
        in source
    )
    assert "retention-days: 90" in source


def test_exact_horizon_comparison_cli_uses_common_freeze() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "COMMON_FROZEN_STARTED_AT_MS" in source
    assert "ProspectiveLongTrend5mExitState" in source
    assert "ProspectiveLongTrend15mExitState" in source
    assert "prospective_long_trend_5m_exit_summary" in source
    assert "prospective_long_trend_15m_exit_summary" in source
    assert "prospective_long_trend_exact_horizon_comparison" in source
    assert "_execution_config_from_durable_long_trend_source" in source


def test_exact_horizon_comparison_freeze_is_literal_and_auditable() -> None:
    source = MODULE.read_text(encoding="utf-8")

    assert (
        "COMMON_FROZEN_STARTED_AT_MS: Final = 1_791_193_533_061"
        in source
    )
    assert "FIVE_MINUTE_HORIZON_MS: Final = 300_000" in source
    assert "FIFTEEN_MINUTE_HORIZON_MS: Final = 900_000" in source
    assert "MIN_PAIRED_OPTIONS: Final = 12" in source
    assert "MIN_MARKETS: Final = 4" in source
