from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(
    ".github/workflows/prospective-long-trend-gated-execution-shadow.yml"
)


def _source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_long_trend_execution_shadow_workflow_is_research_only() -> None:
    source = _source()

    assert "Prospective LONG+Trend Gated Execution Shadow" in source
    assert 'STATUS_ISSUE: "826"' in source
    assert "actions: read" in source
    assert "contents: read" in source
    assert "issues: write" in source
    assert "actions: write" not in source
    assert "COCOMELON_EXECUTION_MODE" not in source
    assert "**Execution authority:**" in source
    assert "**Promotion authority:**" in source
    assert "**Changes risk limits:**" in source
    assert "**Changes candidate readiness:**" in source
    assert "**LIVE TRADING: DISABLED.**" in source


def test_long_trend_execution_shadow_checks_durable_gate_first() -> None:
    source = _source()
    gate_at = source.index(
        "- name: Resolve durable LONG+trend gate ledger"
    )
    lineage_at = source.index(
        "- name: Read durable gate and exact source lineage"
    )
    dormant_at = source.index(
        "- name: Publish dormant gate status"
    )
    paper_source_at = source.index(
        "- name: Resolve exact paper source artifact"
    )

    assert gate_at < lineage_at < dormant_at < paper_source_at
    assert (
        "all_horizons_ready_for_execution_shadow_investigation"
        in source
    )
    assert (
        "steps.lineage.outputs.gate_ready != 'true'"
        in source
    )
    assert (
        "steps.lineage.outputs.gate_ready == 'true'"
        in source
    )
    assert (
        "does not download or replay the paper source until Issue #802"
        in source
    )


def test_long_trend_execution_shadow_binds_exact_paper_source() -> None:
    source = _source()

    assert 'run.get("path") != ".github/workflows/continuous-paper.yml"' in source
    assert 'run.get("head_branch") != "main"' in source
    assert "paper source attempt mismatch" in source
    assert "paper source repository mismatch" in source
    assert 'item.get("name") == os.environ["SOURCE_NAME"]' in source
    assert 'item.get("digest") == os.environ["SOURCE_DIGEST"]' in source
    assert (
        "prospective-long-trend-execution-shadow-source.json"
        in source
    )
    assert (
        "paper source predates compact LONG+trend execution-shadow export"
        in source
    )
    assert (
        "fails closed instead of substituting another run"
        in source
    )


def test_long_trend_execution_shadow_uses_normal_risk_planner_ioc_cli() -> None:
    source = _source()

    assert (
        "scripts/evaluate_prospective_long_trend_execution_shadow.py"
        in source
    )
    assert (
        "prospective-long-trend-execution-shadow.json"
        in source
    )
    assert (
        "captured risk state, planner rules, IOC rules, fees, slippage"
        in source
    )
    assert "**Realized PnL modeled:** `false`" in source
    assert "**Replacement exits modeled:** `false`" in source
    assert "fixed forward mark-to-market" in source.lower()


def test_long_trend_execution_shadow_uploads_only_evaluated_results() -> None:
    source = _source()

    assert (
        "- name: Upload gated execution-shadow result"
        in source
    )
    assert (
        "if: ${{ steps.evaluate.outcome == 'success' }}"
        in source
    )
    assert (
        "prospective-long-trend-gated-execution-shadow-"
        in source
    )
