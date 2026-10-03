from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(
    ".github/workflows/risk-budget-conjunctive-investigation-dossier.yml"
)


def _source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_conjunctive_dossier_workflow_is_research_only() -> None:
    source = _source()

    assert "Risk-Budget Conjunctive Investigation Dossier" in source
    assert 'DOSSIER_ISSUE: "809"' in source
    assert "actions: read" in source
    assert "contents: read" in source
    assert "issues: write" in source
    assert "actions: write" not in source
    assert "COCOMELON_EXECUTION_MODE" not in source
    assert "**Execution authority:**" in source
    assert "**Promotion authority:**" in source
    assert "**Changes risk limits:**" in source
    assert "**LIVE TRADING: DISABLED.**" in source


def test_conjunctive_dossier_restores_both_component_ledgers() -> None:
    source = _source()

    assert "prospective-risk-rejected-fast-markout-ledger.yml" in source
    assert "prospective-risk-rejected-stop-path-ledger.yml" in source
    assert "prospective-risk-rejected-fast-markout-ledger.json" in source
    assert "prospective-risk-rejected-stop-path-ledger.json" in source
    assert "branch=main&status=success&per_page=100" in source
    assert "startsWith($prefix)" not in source
    assert "startswith($prefix)" in source


def test_conjunctive_dossier_fails_closed_on_component_drift() -> None:
    source = _source()

    assert "Build conjunctive dossier" in source
    assert "continue-on-error: true" in source
    assert "Publish blocked dossier status" in source
    assert "Fail closed on dossier drift" in source
    assert "No risk reason is credited as investigable." in source


def test_conjunctive_dossier_surfaces_exact_source_alignment() -> None:
    source = _source()

    assert "source aligned" in source
    assert "return paper source" in source
    assert "stop paper source" in source
    assert "same authenticated paper run/attempt/artifact digest" in source
    assert "economic={economic}, stop={stop}" in source
    assert "conjunctive={conjunctive}" in source


def test_conjunctive_dossier_wakes_from_both_component_workflows() -> None:
    source = _source()

    assert '"Prospective Risk-Rejected Fast-Markout Ledger"' in source
    assert '"Prospective Risk-Rejected Stop-Path Ledger"' in source
    assert "types:" in source
    assert "- completed" in source


def test_conjunctive_dossier_surfaces_post_integrity_scope() -> None:
    source = _source()

    assert "effective integrity clean" in source
    assert "integrity scope" in source
    assert "post-integrity source aligned / start" in source
    assert "same post-integrity-miss boundary" in source
    assert "pass both independent gates from scratch" in source



def test_conjunctive_dossier_surfaces_frozen_weekly_drawdown_5m_candidate() -> None:
    source = _source()

    assert "Frozen weekly-drawdown 5m recovery candidate" in source
    assert "paired review rows / required" in source
    assert "economic / stop-survival ready" in source
    assert "ready for exact execution-shadow investigation" in source
    assert "first 20 paired" in source
    assert "Discovery rows cannot enter the validation cohort" in source
    assert "later rows cannot rescue a failed first-20 review" in source
    assert "cannot relax the weekly drawdown veto" in source
