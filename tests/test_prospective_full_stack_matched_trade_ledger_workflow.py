from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(
    ".github/workflows/prospective-full-stack-matched-trade-ledger.yml"
)


def _source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_full_stack_matched_ledger_is_research_only() -> None:
    source = _source()

    assert "Prospective Full-Stack Matched-Trade Ledger" in source
    assert '"Continuous Mainnet Paper Trader"' in source
    assert "actions: read" in source
    assert "contents: read" in source
    assert "issues: write" in source
    assert "actions: write" not in source
    assert 'LEDGER_ISSUE: "740"' in source
    assert "COCOMELON_EXECUTION_MODE" not in source
    assert "gh workflow run" not in source


def test_full_stack_matched_ledger_binds_summary_and_journal() -> None:
    source = _source()

    assert (
        "continuous-paper-learning-source-"
        "$candidate_run_id-$candidate_attempt"
        in source
    )
    assert "paper_run_is_evidence_eligible()" in source
    assert "latest_evidence_eligible_with_compact_artifact" in source
    assert "Fail closed on upgrade handoff source" in source
    assert "source artifact digest is missing or invalid" in source
    assert "prospective-full-stack-entry-exit-summary.json" in source
    assert "journal.sqlite3" in source
    assert "source run attempt mismatch" in source
    assert "source repository mismatch" in source


def test_full_stack_matched_ledger_restores_history_and_fails_closed() -> None:
    source = _source()

    assert "prospective-full-stack-matched-trade-ledger-" in source
    assert "prospective-full-stack-matched-trade-ledger.json" in source
    assert "update_prospective_full_stack_matched_trade_ledger.py" in source
    assert "--source-artifact-digest" in source
    assert "--previous" in source
    assert "append-only invariant failure" in source
    assert "Fail closed on matched-trade ledger drift" in source


def test_full_stack_matched_ledger_blocks_review_on_pending_trades() -> None:
    source = _source()

    assert "terminal rows / previous / new / pending" in source
    assert "Any pending closed trade keeps integrity incomplete" in source
    assert "candidate profitable / improvement positive" in source
    assert "candidate LOO trade/market robust" in source
    assert "delta LOO trade/market robust" in source
    assert "ready for evidence review" in source


def test_full_stack_matched_ledger_keeps_replacements_separate() -> None:
    source = _source()

    assert "Replacement-trade economics remain separate in Issue #738" in source
    assert "matched-trade contribution only" in source
    assert "portfolio counterfactual" not in source.lower()


def test_full_stack_matched_ledger_accepts_only_durable_handoff_failures() -> None:
    source = _source()

    assert "paper_run_is_evidence_eligible()" in source
    assert "Run continuous paper trader" in source
    assert "Measure durable continuous paper state" in source
    assert "Upload durable continuous paper state" in source
    assert "Upload compact continuous learning source" in source
    assert "Fail closed on upgrade handoff source" in source
    assert "latest_evidence_eligible_with_compact_artifact" in source
    assert (
        "actions/workflows/continuous-paper.yml/runs?"
        "branch=main&status=completed&per_page=100"
        in source
    )


def test_full_stack_matched_status_is_authority_negative() -> None:
    source = _source()

    assert "**Execution authority:**" in source
    assert "**Promotion authority:**" in source
    assert "**Changes readiness gates:**" in source
    assert "**LIVE TRADING: DISABLED.**" in source
