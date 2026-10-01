from __future__ import annotations

from pathlib import Path


def test_prospective_readiness_workflow_is_fail_closed() -> None:
    source = Path(
        ".github/workflows/prospective-trade-quality-readiness.yml"
    ).read_text(encoding="utf-8")

    assert "Prospective Cadence Prediction Ledger" in source
    assert "Prospective Cadence A/B Ledger" in source
    assert "Prospective Side-Conditioned Timing Ledger" in source
    assert "github.event.workflow_run.conclusion == 'success'" not in source
    assert 'READINESS_ISSUE: "695"' in source
    assert (
        "evaluate_prospective_trade_quality_readiness.py"
        in source
    )
    assert 'map(select(.status == "completed"))' in source
    assert 'if [[ "$conclusion" != "success" ]]' in source
    assert "Expected exactly one current $key ledger artifact." in source
    assert "**Status:** BLOCKED" in source
    assert "Fail closed on readiness integrity" in source
    assert "prospective-trade-quality-readiness.json" in source
    assert "paper " in source
    assert "entries, timing, sizing, stops, risk, promotion state" in source
    assert "no authority to change" in source


def test_prospective_readiness_blocks_no_evidence_without_stale_reuse() -> None:
    source = Path(
        ".github/workflows/prospective-trade-quality-readiness.yml"
    ).read_text(encoding="utf-8")

    assert "cadence-model-comparison-ledger-no-evidence-" in source
    assert "comparison_no_evidence" in source
    assert (
        "steps.ledgers.outputs.comparison_no_evidence != 'true'"
        in source
    )
    assert "BLOCKED — no new comparison evidence" in source
    assert "are not reused as if they were current" in source
    assert "cat > /tmp/readiness-status.md <<EOF" not in source
    assert 'Path("/tmp/readiness-status.md").write_text' in source
