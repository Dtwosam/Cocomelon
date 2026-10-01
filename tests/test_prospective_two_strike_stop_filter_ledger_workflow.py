from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(
    ".github/workflows/prospective-two-strike-stop-filter-ledger.yml"
)


def _source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_two_strike_ledger_workflow_is_research_only() -> None:
    source = _source()

    assert "Prospective Two-Strike Stop Filter Ledger" in source
    assert "push:" in source
    assert '".github/workflows/prospective-two-strike-stop-filter-ledger.yml"' in source
    assert '"Continuous Mainnet Paper Trader"' in source
    assert "github.event.workflow_run.conclusion == 'success'" not in source
    assert "EVENT_CONCLUSION:" in source
    assert 'echo "source_eligible=false"' not in source
    assert '"$EVENT_CONCLUSION" = "success"' in source
    assert "latest_successful_after_non_success_wake" in source
    assert "steps.source.outputs.source_eligible == 'true'" in source
    assert "actions: read" in source
    assert "contents: read" in source
    assert "issues: write" in source
    assert "actions: write" not in source
    assert 'LEDGER_ISSUE: "715"' in source
    assert "gh workflow run" not in source
    assert "COCOMELON_EXECUTION_MODE" not in source


def test_two_strike_ledger_binds_exact_compact_source() -> None:
    source = _source()

    assert 'run.get("path") != ".github/workflows/continuous-paper.yml"' in source
    assert 'run.get("head_branch") != "main"' in source
    assert 'run.get("status") != "completed"' in source
    assert 'run.get("conclusion") != "success"' in source
    assert "source run attempt mismatch" in source
    assert "source repository mismatch" in source
    assert "latest_successful_push" in source
    assert "actions/workflows/continuous-paper.yml/runs?branch=main&status=completed" in source
    assert (
        'artifact_name="continuous-paper-learning-source-$run_id-$run_attempt"'
        in source
    )
    assert "source artifact digest is missing or invalid" in source
    assert "journal.sqlite3" in source
    assert "prospective-two-strike-stop-filter-state.json" in source


def test_two_strike_ledger_handles_old_source_without_credit() -> None:
    source = _source()

    assert 'echo "eligible=false"' in source
    assert "waiting for new-format compact source" in source
    assert "No prospective row is credited from this run." in source
    assert "predates export of the frozen two-strike state" in source
    assert r"\`$SOURCE_RUN_ID\`" in source
    assert r"\`$SOURCE_RUN_ATTEMPT\`" in source
    assert r"\`$RESOLUTION_MODE\`" in source
    assert r"\`false\`" in source


def test_two_strike_ledger_restores_and_extends_append_only_evidence() -> None:
    source = _source()

    assert "prospective-two-strike-stop-filter-ledger-" in source
    assert "prospective-two-strike-stop-filter-ledger.json" in source
    assert "update_prospective_two_strike_stop_filter_ledger.py" in source
    assert "--source-artifact-digest" in source
    assert "--previous" in source
    assert "append-only invariant failure" in source
    assert r"\`$error\`" in source
    assert "Fail closed on two-strike ledger drift" in source
    assert "Every previously published trade row" in source
    assert "**Execution authority:**" in source
    assert "**Promotion authority:**" in source
    assert "**LIVE TRADING: DISABLED.**" in source


def test_two_strike_ledger_non_success_wake_falls_back_to_success() -> None:
    source = _source()

    assert (
        'if [ "$EVENT_NAME" = "workflow_run" ] && '
        '[ "$EVENT_CONCLUSION" = "success" ]; then'
        in source
    )
    assert 'resolution_mode="successful_event"' in source
    assert 'resolution_mode="latest_successful_after_non_success_wake"' in source
    assert (
        'actions/workflows/continuous-paper.yml/runs?'
        'branch=main&status=completed&per_page=50'
        in source
    )
