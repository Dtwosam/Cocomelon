"""V2 independent cross-worker audit remains read-only and optional."""

from __future__ import annotations

from pathlib import Path


def test_selected_v2_anchor_not_promoted_or_assumed_first() -> None:
    source = Path(
        ".github/workflows/independent-fresh-trend-v2-source-audit.yml"
    ).read_text()
    assert "anchor_run_id:" in source
    assert "anchor_attempt:" in source
    assert "PINNED_ANCHOR_RUN:" in source
    assert "scripts.audit_fresh_trend_v2_selected_anchor" in source
    assert "--anchor-artifact-zip" in source
    assert "--current-artifact-zip" in source
    assert "actual original v2 genesis proven: FALSE" in source
    assert "verified full mainnet source, 72h positive expectancy: FALSE / FALSE" in source
    assert "execution / promotion authority: FALSE / FALSE" in source
    assert "COCOMELON_EXECUTION_MODE: live" not in source
    assert "HYPERLIQUID_PRIVATE_KEY" not in source

    current = source.index(
        "      - name: Independently authenticate frozen v2 source and reconcile accounts"
    )
    anchor = source.index("      - name: Select independently checkable v2 source anchor")
    lineage = source.index(
        "      - name: Verify independently matched v2 cross-worker ledger and gap history"
    )
    upload = source.index("      - name: Upload independent selected-anchor v2 continuity")
    assert current < anchor < lineage < upload
    assert "continue-on-error: true" in source


def test_previous_v1_anchor_and_gap_functions_keep_original_default() -> None:
    text = Path("scripts/audit_both_side_trend_ledger_anchor.py").read_text()
    assert "state_member: str = STATE_MEMBER" in text
    assert "ledger_member: str = LEDGER_MEMBER" in text
    assert "both-side-trend-paired-shadow-v1/review-ledger.jsonl" in text
    assert "both-side-trend-paired-shadow-v1/paired-shadow-state.json" in text
    assert 'ORIGINAL_ANCHOR_RUN_ID: Final = 38281228549' in text
