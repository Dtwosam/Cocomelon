from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(
    ".github/workflows/prospective-momentum-band-entry-ledger.yml"
)


def _source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_momentum_band_ledger_workflow_is_research_only() -> None:
    source = _source()

    assert "Prospective Momentum-Band Entry Ledger" in source
    assert "push:" in source
    assert (
        '".github/workflows/prospective-momentum-band-entry-ledger.yml"'
        in source
    )
    assert '"Continuous Mainnet Paper Trader"' in source
    assert "github.event.workflow_run.conclusion == 'success'" not in source
    assert "paper_run_is_evidence_eligible()" in source
    assert 'echo "source_eligible=false"' not in source
    assert "actions/runs/$candidate_run_id/jobs?per_page=100" in source
    assert "Fail closed on upgrade handoff source" in source
    assert "latest_evidence_eligible_with_compact_artifact" in source
    assert "steps.source.outputs.source_eligible == 'true'" in source
    assert "actions: read" in source
    assert "contents: read" in source
    assert "issues: write" in source
    assert "actions: write" not in source
    assert 'LEDGER_ISSUE: "728"' in source
    assert "gh workflow run" not in source
    assert "COCOMELON_EXECUTION_MODE" not in source


def test_momentum_band_ledger_binds_exact_compact_source() -> None:
    source = _source()

    assert (
        'run.get("path") != ".github/workflows/continuous-paper.yml"'
        in source
    )
    assert 'run.get("head_branch") != "main"' in source
    assert 'run.get("status") != "completed"' in source
    assert 'run.get("conclusion") not in {"success", "failure"}' in source
    assert "source run attempt mismatch" in source
    assert "source repository mismatch" in source
    assert "latest_evidence_eligible_with_compact_artifact" in source
    assert (
        "actions/workflows/continuous-paper.yml/runs?"
        "branch=main&status=completed"
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
    assert "prospective-momentum-band-entry-state.json" in source
    assert "learning-features" in source
    assert "feature_store_path" in source


def test_momentum_band_ledger_handles_old_source_without_credit() -> None:
    source = _source()

    assert 'echo "eligible=false"' in source
    assert "waiting for new-format compact source" in source
    assert "No prospective row is credited from this run." in source
    assert "predates export of the frozen momentum-band state" in source
    assert r"\`$SOURCE_RUN_ID\`" in source
    assert r"\`$SOURCE_RUN_ATTEMPT\`" in source
    assert r"\`$RESOLUTION_MODE\`" in source
    assert r"\`false\`" in source


def test_momentum_band_ledger_restores_append_only_evidence() -> None:
    source = _source()

    assert "prospective-momentum-band-entry-ledger-" in source
    assert "prospective-momentum-band-entry-ledger.json" in source
    assert "update_prospective_momentum_band_entry_ledger.py" in source
    assert "--source-artifact-digest" in source
    assert "--previous" in source
    assert "append-only invariant failure" in source
    assert r"\`$error\`" in source
    assert "Fail closed on momentum-band ledger drift" in source
    assert "Every previously published trade row" in source
    assert "feature integrity clean" in source
    assert "feature_status" in source
    assert "signed_return_1h" in source
    assert "signed_day_return" in source
    assert "**Execution authority:**" in source
    assert "**Promotion authority:**" in source
    assert "**LIVE TRADING: DISABLED.**" in source


def test_momentum_band_ledger_accepts_only_durable_handoff_failures() -> None:
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
