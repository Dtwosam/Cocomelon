from pathlib import Path

WORKFLOW = Path(
    ".github/workflows/"
    "prospective-breakeven-profit-lock-readiness.yml"
)


def test_breakeven_readiness_binds_immutable_sources() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "Profit-Lock Execution Shadow Ledger" in source
    assert 'READINESS_ISSUE: "724"' in source
    assert "profit-lock-execution-ledger-" in source
    assert "validate_profit_lock_execution_ledger" in source
    assert "paper_run_id" in source
    assert "paper_run_attempt" in source
    assert "artifact_name" in source
    assert "artifact_digest" in source
    assert "Compact paper artifact digest mismatch." in source
    assert "prospective-breakeven-profit-lock-state.json" in source
    assert "evaluate_prospective_breakeven_profit_lock.py" in source


def test_breakeven_readiness_selects_newest_ledger_with_exact_artifact() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "ledger_artifact_for_run()" in source
    assert "profit-lock-execution-ledger-$candidate_run_id-$candidate_attempt" in source
    assert "status=completed&per_page=100" in source
    assert 'run.get("head_branch") == "main"' in source
    assert 'run.get("conclusion") == "success"' in source
    assert "created_at" in source
    assert "reverse=True" in source
    assert "latest_successful_with_ledger_artifact" in source


def test_breakeven_readiness_accepts_only_attested_handoff_paper_failures() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "actions/runs/$PAPER_RUN_ID/jobs?per_page=100" in source
    assert 'run.get("path") != ".github/workflows/continuous-paper.yml"' in source
    assert 'run.get("conclusion") not in {"success", "failure"}' in source
    assert "Run continuous paper trader" in source
    assert "Measure durable continuous paper state" in source
    assert "Upload durable continuous paper state" in source
    assert "Upload compact continuous learning source" in source
    assert "Fail closed on upgrade handoff source" in source
    assert "paper source failure is not a durable upgrade handoff" in source


def test_breakeven_readiness_never_backfills_pre_freeze_evidence() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "waiting for first post-freeze clean source" in source
    assert "receive zero clean credit" in source
    assert "No freeze timestamp is reconstructed or guessed." in source
    assert "BLOCKED — clean evidence invariant failure" in source
    assert "Fail closed on clean-evidence invariant failure" in source


def test_breakeven_readiness_has_no_execution_or_promotion_authority() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "**Execution authority:**" in source
    assert "**Promotion authority:**" in source
    assert "**LIVE TRADING: DISABLED.**" in source
    assert "ready for review" in source
    assert "cannot move stops or grant execution/promotion authority" in source


def test_breakeven_status_markdown_avoids_shell_backtick_substitution() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "cat > /tmp/breakeven-status.md <<EOF" not in source
    assert source.count(
        'Path("/tmp/breakeven-status.md").write_text('
    ) == 3
    assert '- candidate state present: `false`' in source
    assert '**Execution authority:** `false`' in source
    assert '**Promotion authority:** `false`' in source
