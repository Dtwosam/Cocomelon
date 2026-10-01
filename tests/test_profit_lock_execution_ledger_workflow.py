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
    assert "push:" in source
    assert '".github/workflows/profit-lock-execution-ledger.yml"' in source
    assert '"Continuous Mainnet Paper Trader"' in source
    assert "github.event.workflow_run.conclusion == 'success'" not in source
    assert "EVENT_CONCLUSION:" in source
    assert '"$EVENT_CONCLUSION" = "success"' in source
    assert "latest_successful_after_non_success_wake" in source
    assert "actions: read" in source
    assert "contents: read" in source
    assert "issues: write" in source
    assert "actions: write" not in source
    assert 'LEDGER_ISSUE: "721"' in source
    assert "gh workflow run" not in source
    assert "COCOMELON_EXECUTION_MODE" not in source


def test_profit_lock_execution_ledger_binds_exact_compact_source() -> None:
    source = _source()

    assert 'run.get("path") != ".github/workflows/continuous-paper.yml"' in source
    assert 'run.get("head_branch") != "main"' in source
    assert 'run.get("status") != "completed"' in source
    assert 'run.get("conclusion") != "success"' in source
    assert "source run attempt mismatch" in source
    assert "source repository mismatch" in source
    assert "latest_successful_push" in source
    assert (
        "actions/workflows/continuous-paper.yml/runs?"
        "branch=main&status=completed&per_page=50"
        in source
    )
    assert (
        'artifact_name="continuous-paper-learning-source-$run_id-$run_attempt"'
        in source
    )
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


def test_compact_paper_source_exports_execution_shadow_state() -> None:
    source = PAPER_WORKFLOW.read_text(encoding="utf-8")

    artifact = "continuous-paper-learning-source-${{ github.run_id }}"
    assert artifact in source
    assert (
        "continuous-paper-state/"
        "profit-lock-execution-shadow-state.json"
        in source
    )
