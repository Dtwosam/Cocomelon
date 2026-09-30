from __future__ import annotations

from pathlib import Path


def test_prospective_readiness_workflow_is_fail_closed() -> None:
    source = Path(
        ".github/workflows/prospective-trade-quality-readiness.yml"
    ).read_text(encoding="utf-8")

    assert "Prospective Cadence Prediction Ledger" in source
    assert "Prospective Cadence A/B Ledger" in source
    assert "Prospective Side-Conditioned Timing Ledger" in source
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
    assert "paper entries, timing, sizing, stops, risk" in source
