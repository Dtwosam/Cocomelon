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
