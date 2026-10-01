from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(
    ".github/workflows/prospective-full-stack-reflow-exact-ledger.yml"
)


def _source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_full_stack_reflow_exact_ledger_is_research_only() -> None:
    source = _source()

    assert "Prospective Full-Stack Reflow Exact PnL Ledger" in source
    assert "push:" in source
    assert '"Continuous Mainnet Paper Trader"' in source
    assert "actions: read" in source
    assert "contents: read" in source
    assert "issues: write" in source
    assert "actions: write" not in source
    assert 'LEDGER_ISSUE: "738"' in source
    assert "COCOMELON_EXECUTION_MODE" not in source
    assert "gh workflow run" not in source


def test_full_stack_reflow_exact_ledger_binds_exact_compact_source() -> None:
    source = _source()

    assert (
        'run.get("path") != ".github/workflows/continuous-paper.yml"'
        in source
    )
    assert 'run.get("head_branch") != "main"' in source
    assert 'run.get("status") != "completed"' in source
    assert 'run.get("conclusion") != "success"' in source
    assert "source run attempt mismatch" in source
    assert "source repository mismatch" in source
    assert (
        'artifact_name="continuous-paper-learning-source-$run_id-$run_attempt"'
        in source
    )
    assert "source artifact digest is missing or invalid" in source
    assert "prospective-full-stack-capacity-reflow-summary.json" in source
    assert "journal.sqlite3" not in source


def test_full_stack_reflow_exact_ledger_restores_append_only_history() -> None:
    source = _source()

    assert "prospective-full-stack-reflow-exact-ledger-" in source
    assert "prospective-full-stack-reflow-exact-ledger.json" in source
    assert "update_prospective_full_stack_reflow_exact_ledger.py" in source
    assert "--source-artifact-digest" in source
    assert "--previous" in source
    assert "append-only invariant failure" in source
    assert "Fail closed on exact reflow ledger drift" in source
    assert "Every previously published exact row" in source
    assert "pending option-horizons" in source


def test_full_stack_reflow_exact_ledger_keeps_horizons_separate() -> None:
    source = _source()

    assert "Fixed exit horizons" in source
    assert "no best-horizon selection" in source
    assert "cross-horizon aggregation" in source
    assert "for horizon_ms in ledger["horizons_ms"]" in source
    assert "summary["by_horizon"][str(horizon_ms)]" in source


def test_full_stack_reflow_exact_ledger_non_success_wake_falls_back() -> None:
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


def test_full_stack_reflow_exact_ledger_status_is_authority_negative() -> None:
    source = _source()

    assert "**Execution authority:**" in source
    assert "**Promotion authority:**" in source
    assert "**Changes readiness gates:**" in source
    assert "**LIVE TRADING: DISABLED.**" in source
    assert "fully closed exits with complete crossed funding-boundary" in source


def test_full_stack_reflow_exact_ledger_heredocs_escape_markdown() -> None:
    source = _source()

    for title in (
        "Publish waiting-for-summary status",
        "Publish blocked exact reflow ledger status",
    ):
        start = source.index(f"- name: {title}")
        heredoc = source.index(
            "cat > /tmp/full-stack-reflow-ledger-status.md <<EOF",
            start,
        )
        end = source.index("\n          EOF", heredoc)
        block = source[heredoc:end]
        assert "\\`" in block
        assert "`" not in block.replace("\\`", "")
