from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(
    ".github/workflows/profit-lock-execution-ledger.yml"
)
PAPER_WORKFLOW = Path(".github/workflows/continuous-paper.yml")


def _source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_profit_lock_execution_ledger_is_research_only() -> None:
    source = _source()

    assert "Profit-Lock Execution Shadow Ledger" in source
    assert "workflow_dispatch:" in source
    assert "workflow_run:" not in source
    assert "push:" not in source
    assert "github.event.workflow_run.conclusion == 'success'" not in source
    assert "paper_run_is_evidence_eligible()" in source
    assert "actions/runs/$candidate_run_id/jobs?per_page=100" in source
    assert "Run continuous paper trader" in source
    assert "Measure durable continuous paper state" in source
    assert "Upload durable continuous paper state" in source
    assert "Upload compact continuous learning source" in source
    assert "Fail closed on upgrade handoff source" in source
    assert "latest_evidence_eligible_with_compact_artifact" in source
    assert "actions: write" in source
    assert "contents: read" in source
    assert "issues: write" in source
    assert 'LEDGER_ISSUE: "721"' in source
    assert "prospective-breakeven-profit-lock-readiness.yml" in source
    assert 'source_run_id=$GITHUB_RUN_ID' in source
    assert 'source_run_attempt=$GITHUB_RUN_ATTEMPT' in source
    assert "COCOMELON_EXECUTION_MODE" not in source


def test_profit_lock_manual_dispatch_waits_for_exact_paper_completion() -> None:
    source = _source()

    assert "wait_for_paper_run_completion()" in source
    assert "source paper run did not complete within 10 minutes" in source
    assert "INPUT_RUN_ID" in source
    assert "INPUT_RUN_ATTEMPT" in source
    assert 'resolution_mode="manual_exact"' in source
    assert "Queue exact breakeven readiness" in source
    assert "steps.ledger_upload.outcome == 'success'" in source


def test_profit_lock_execution_ledger_binds_exact_compact_source() -> None:
    source = _source()

    assert 'run.get("path") != ".github/workflows/continuous-paper.yml"' in source
    assert 'run.get("head_branch") != "main"' in source
    assert 'run.get("status") != "completed"' in source
    assert '"success", "failure"' in source
    assert "source run attempt mismatch" in source
    assert "source repository mismatch" in source
    assert "latest_evidence_eligible_with_compact_artifact" in source
    assert (
        "actions/workflows/continuous-paper.yml/runs?"
        "branch=main&status=completed&per_page=100"
        in source
    )
    assert (
        'local expected_name="continuous-paper-learning-source-'
        '$candidate_run_id-$candidate_attempt"'
        in source
    )
    assert "latest_evidence_eligible_with_compact_artifact" in source
    assert "source artifact digest is missing or invalid" in source
    assert "journal.sqlite3" in source
    assert "profit-lock-execution-shadow-state.json" in source


def test_profit_lock_execution_ledger_waits_for_new_compact_state() -> None:
    source = _source()

    assert 'echo "eligible=false"' in source
    assert "waiting for compact execution-shadow state" in source
    assert "No visible-book execution outcome is credited" in source
    assert "profit-lock-execution-shadow-state.json" in source
    assert r"\`$SOURCE_RUN_ID\`" in source
    assert r"\`$SOURCE_RUN_ATTEMPT\`" in source
    assert r"\`$RESOLUTION_MODE\`" in source


def test_profit_lock_execution_ledger_restores_append_only_evidence() -> None:
    source = _source()

    assert "profit-lock-execution-ledger-" in source
    assert "profit-lock-execution-ledger.json" in source
    assert "update_profit_lock_execution_ledger.py" in source
    assert "--source-artifact-digest" in source
    assert "--previous" in source
    assert "append-only invariant failure" in source
    assert r"\`$error\`" in source
    assert "Fail closed on profit-lock execution ledger drift" in source
    assert "Volume readiness is the pre-existing review gate." in source
    assert "Economic and leave-one-out fields are descriptive" in source
    assert "**Execution authority:**" in source
    assert "**Promotion authority:**" in source
    assert "**LIVE TRADING: DISABLED.**" in source


def test_paper_worker_dispatches_exact_profit_lock_ledger() -> None:
    source = PAPER_WORKFLOW.read_text(encoding="utf-8")

    assert "Queue exact profit-lock execution ledger" in source
    assert "gh workflow run profit-lock-execution-ledger.yml" in source
    assert '-f "source_run_id=$GITHUB_RUN_ID"' in source
    assert '-f "source_run_attempt=$GITHUB_RUN_ATTEMPT"' in source
    assert "steps.compact_learning_upload.outcome == 'success'" in source


def test_compact_paper_source_exports_execution_shadow_state() -> None:
    source = PAPER_WORKFLOW.read_text(encoding="utf-8")

    artifact = "continuous-paper-learning-source-${{ github.run_id }}"
    assert artifact in source
    assert (
        "continuous-paper-state/"
        "profit-lock-execution-shadow-state.json"
        in source
    )
