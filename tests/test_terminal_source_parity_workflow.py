from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(
    ".github/workflows/immutable-terminal-source-parity-audit.yml"
).read_text(encoding="utf-8")

CLI = Path(
    "scripts/audit_immutable_terminal_source_parity.py"
).read_text(encoding="utf-8")


def test_historical_parity_auditor_authenticates_original_and_exact_paper_source() -> None:
    assert 'ACCEPTED_LEDGER_RUN: "37859637682"' in WORKFLOW
    assert "prospective-risk-rejected-fast-markout-ledger-37859637682-1" in WORKFLOW
    assert "continuous-paper-full-stack-forward-markout-{source_id}-{attempt}" in WORKFLOW
    assert '"head_branch") != "main"' in WORKFLOW
    assert '"run_attempt") != att' in WORKFLOW
    assert '"head_repository"' in WORKFLOW
    assert '"digest"' in WORKFLOW
    assert "x.get(\"expired\") is False" in WORKFLOW
    assert "source workflow identity is not independently verified" in WORKFLOW
    assert "non-default source run is not complete" in WORKFLOW


def test_historical_parity_auditor_watches_each_future_paper_worker() -> None:
    assert '      - "Continuous Mainnet Paper Trader"' in WORKFLOW
    assert "types:" in WORKFLOW
    assert "      - completed" in WORKFLOW
    assert "EVENT_RUN:" in WORKFLOW
    assert "EVENT_ATTEMPT:" in WORKFLOW
    assert "if [ \"$EVENT_NAME\" = \"workflow_run\" ]" in WORKFLOW
    assert "No authenticated full-stack source for this exact paper run" in WORKFLOW


def test_historical_parity_auditor_never_grants_execution_or_rewrites_history() -> None:
    assert "  actions: read" in WORKFLOW
    assert "  contents: read" in WORKFLOW
    assert "  issues: write" not in WORKFLOW
    assert "pull-requests: write" not in WORKFLOW
    assert "actions/upload-artifact@v5" in WORKFLOW
    assert "terminal-source-parity-redacted.json" in WORKFLOW
    assert "/tmp/parity-previous/prospective-risk-rejected-fast-markout-ledger.json" in CLI or (
        "/tmp/parity-previous/prospective-risk-rejected-fast-markout-ledger.json"
        in WORKFLOW
    )
    assert "--previous-ledger" in CLI
    assert "--rebuilt-summary" in CLI
    assert "output cannot overwrite an input source" in CLI
    assert "gh api" not in CLI
    assert "execution_authority: true" not in WORKFLOW
    assert "promotion_authority: true" not in WORKFLOW
