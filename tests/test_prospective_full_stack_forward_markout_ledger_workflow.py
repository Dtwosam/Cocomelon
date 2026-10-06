from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(
    ".github/workflows/prospective-full-stack-fast-markout-ledger.yml"
)


def _source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_full_stack_fast_markout_workflow_is_research_only() -> None:
    source = _source()

    assert "Prospective Full Entry-Stack Fast-Markout Ledger" in source
    assert '"Continuous Mainnet Paper Trader"' in source
    assert 'LEDGER_ISSUE: "769"' in source
    assert "actions: read" in source
    assert "contents: read" in source
    assert "issues: write" in source
    assert "actions: write" not in source
    assert "COCOMELON_EXECUTION_MODE" not in source
    assert "**Execution authority:**" in source
    assert "**Promotion authority:**" in source
    assert "**Changes closed-trade readiness:**" in source
    assert "**LIVE TRADING: DISABLED.**" in source


def test_full_stack_fast_markout_binds_exact_compact_source() -> None:
    source = _source()

    assert (
        'run.get("path") != ".github/workflows/continuous-paper.yml"'
        in source
    )
    assert 'run.get("head_branch") != "main"' in source
    assert 'run.get("conclusion") not in {"success", "failure"}' in source
    assert 'actions/runs/$candidate_run_id/jobs?per_page=100' in source
    assert 'job.get("name") == "paper"' in source
    assert '"Run continuous paper trader"' in source
    assert '"Upload compact continuous learning source"' in source
    assert "source run attempt mismatch" in source
    assert "source repository mismatch" in source
    assert (
        'expected_name="continuous-paper-learning-source-'
        '$candidate_run_id-$candidate_attempt"'
        in source
    )
    assert "source artifact digest is missing or invalid" in source
    assert "prospective-full-stack-forward-markout-summary.json" in source
    assert "prospective-two-strike-stop-filter-state.json" in source
    assert "prospective-momentum-band-entry-state.json" in source
    assert 'payload.get("stack_risk_approved_evaluated")' in source
    assert 'row.get("baseline_risk_approved") is True' in source


def test_full_stack_fast_markout_restores_append_only_evidence() -> None:
    source = _source()

    assert "prospective-full-stack-fast-markout-ledger-" in source
    assert "prospective-full-stack-fast-markout-ledger.json" in source
    assert "update_prospective_full_stack_fast_markout_ledger.py" in source
    assert "--source-artifact-digest" in source
    assert "--previous" in source
    assert "append-only invariant failure" in source
    assert "Fail closed on ledger drift" in source
    assert "Every previously published terminal row" in source


def test_full_stack_fast_markout_keeps_pending_rows_unfrozen() -> None:
    source = _source()

    assert "terminal / previous / new / pending" in source
    assert "settled, definitively stale, or explicitly unsupported" in source
    assert "Pending or missing-path rows remain unfrozen." in source
    assert "Per-horizon early review bar" in source
    assert (
        "cannot change the full entry stack's closed-trade readiness gates"
        in source
    )


def test_full_stack_fast_markout_legacy_source_waits() -> None:
    source = _source()
    compact = source.split(
        "      - name: Download compact paper source",
        1,
    )[1].split(
        "      - name: Publish waiting-for-source status",
        1,
    )[0]

    assert 'print("current" if current else "legacy")' in compact
    assert 'if [ "$format_check" != "current" ]; then' in compact
    assert "predates risk-approved full-stack row lineage" in compact
    assert 'echo "eligible=false"' in compact
    assert "Fail closed on ledger drift" not in compact


def test_full_stack_fast_markout_accepts_fail_closed_handoff() -> None:
    source = _source()

    assert 'if [ "$EVENT_NAME" = "workflow_run" ]; then' in source
    assert 'resolution_mode="completed_event"' in source
    assert 'run.get("conclusion") in {"success", "failure"}' in source
    assert (
        'run.get("conclusion") not in {"success", "failure"}'
        in source
    )
    assert 'actions/runs/$candidate_run_id/jobs?per_page=100' in source
    assert 'job.get("name") == "paper"' in source
    assert '"Run continuous paper trader"' in source
    assert '"Upload compact continuous learning source"' in source
    assert (
        "latest_completed_with_authenticated_compact_artifact"
        in source
    )


def test_full_stack_fast_markout_status_uses_quoted_python_builders() -> None:
    source = _source()
    waiting = source.split(
        "      - name: Publish waiting-for-source status",
        1,
    )[1].split(
        "      - name: Restore previous fast-markout ledger",
        1,
    )[0]
    blocked = source.split(
        "      - name: Publish blocked ledger status",
        1,
    )[1].split(
        "      - name: Fail closed on ledger drift",
        1,
    )[0]
    clean = source.split(
        "      - name: Publish clean ledger status",
        1,
    )[1]

    assert "python - <<'PY'" in waiting
    assert "python - <<'PY'" in blocked
    assert "os.environ['SOURCE_RUN_ID']" in waiting
    assert "os.environ['SOURCE_RUN_ATTEMPT']" in waiting
    assert "os.environ['RESOLUTION_MODE']" in waiting
    assert "WAIT_REASON" in waiting
    assert 'os.environ.get("ERROR_TEXT")' in blocked
    assert r"\`false\`" not in clean
