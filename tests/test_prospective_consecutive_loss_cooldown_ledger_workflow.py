from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(
    ".github/workflows/prospective-consecutive-loss-cooldown-ledger.yml"
)


def _source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_cooldown_ledger_workflow_is_research_only() -> None:
    source = _source()

    assert "Prospective Consecutive-Loss Cooldown Ledger" in source
    assert "push:" in source
    assert (
        '"src/cocomelon/research/'
        'prospective_consecutive_loss_cooldown_ledger.py"'
        in source
    )
    assert (
        '"scripts/update_prospective_consecutive_loss_cooldown_ledger.py"'
        in source
    )
    assert (
        '"Continuous Mainnet Paper Trader"'
        in source
    )
    assert "actions: read" in source
    assert "contents: read" in source
    assert "issues: write" in source
    assert "actions: write" not in source
    assert 'LEDGER_ISSUE: "733"' in source
    assert "COCOMELON_EXECUTION_MODE" not in source
    assert "gh workflow run" not in source


def test_cooldown_ledger_binds_exact_compact_source() -> None:
    source = _source()

    assert (
        'run.get("path") != ".github/workflows/continuous-paper.yml"'
        in source
    )
    assert 'run.get("head_branch") != "main"' in source
    assert 'run.get("status") != "completed"' in source
    assert 'run.get("conclusion") not in {"success", "failure"}' in source
    assert 'actions/runs/$candidate_run_id/jobs?per_page=100' in source
    assert 'job.get("name") == "paper"' in source
    assert '"Run continuous paper trader"' in source
    assert '"Measure durable continuous paper state"' in source
    assert '"Upload durable continuous paper state"' in source
    assert '"Upload compact continuous learning source"' in source
    assert "source run attempt mismatch" in source
    assert "source repository mismatch" in source
    assert (
        'local expected_name="continuous-paper-learning-source-'
        '$candidate_run_id-$candidate_attempt"'
        in source
    )
    assert "latest_evidence_eligible_with_compact_artifact" in source
    assert "source artifact digest is missing or invalid" in source
    assert (
        "prospective-consecutive-loss-cooldown-shadow-summary.json"
        in source
    )
    assert (
        "prospective-consecutive-loss-cooldown-shadow-state.json"
        in source
    )
    assert "journal.sqlite3" not in source


def test_cooldown_ledger_waits_for_new_format_without_credit() -> None:
    source = _source()

    assert 'echo "eligible=false"' in source
    assert "waiting for new-format compact source" in source
    assert "No clean option row is credited from this run." in source
    assert "predates export of the frozen cooldown state/summary" in source


def test_cooldown_ledger_restores_and_extends_append_only_evidence() -> None:
    source = _source()

    assert "prospective-consecutive-loss-cooldown-ledger-" in source
    assert "prospective-consecutive-loss-cooldown-ledger.json" in source
    assert (
        "update_prospective_consecutive_loss_cooldown_ledger.py"
        in source
    )
    assert "--source-artifact-digest" in source
    assert "--previous" in source
    assert "append-only invariant failure" in source
    assert "Fail closed on cooldown ledger drift" in source
    assert "Every previously published terminal row" in source
    assert "still-pending options" in source
    assert "**Execution authority:**" in source
    assert "**Promotion authority:**" in source
    assert "**Changes risk limits:**" in source
    assert "**LIVE TRADING: DISABLED.**" in source


def test_cooldown_ledger_accepts_only_authenticated_fail_closed_handoff() -> None:
    source = _source()

    assert "paper_run_is_evidence_eligible()" in source
    assert "wait_for_paper_run_completion()" in source
    assert "allowed_failed_steps" in source
    assert "Queue fallback exact successor continuous paper worker" in source
    assert "Queue exact successor from fast resume" in source
    assert 'resolution_mode="durable_upgrade_handoff_event"' in source
    assert "latest_evidence_eligible_with_compact_artifact" in source
    assert "selected source paper run is not evidence-eligible" in source
    assert (
        "branch=main&status=completed&per_page=100"
        in source
    )


def test_cooldown_ledger_unquoted_status_heredocs_escape_markdown() -> None:
    source = _source()

    for title in (
        "Publish waiting-for-state status",
        "Publish blocked ledger status",
    ):
        start = source.index(f"- name: {title}")
        heredoc = source.index(
            "cat > /tmp/cooldown-ledger-status.md <<EOF",
            start,
        )
        end = source.index("\n          EOF", heredoc)
        block = source[heredoc:end]
        assert "\\`" in block
        assert "`" not in block.replace("\\`", "")
