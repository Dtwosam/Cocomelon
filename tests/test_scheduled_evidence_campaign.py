from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/evidence-campaign-scheduled.yml")
PINNED_CODE = "571c13bfe0bab0312940617540ec973ee3eee3c5"
PINNED_WATCHER = "390d4ba39abe4fe3f476af68587f13f2371d9cba"


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_scheduled_campaign_is_fixed_revision_mainnet_paper_only() -> None:
    text = _workflow_text()

    assert "schedule:" in text
    assert "37 1,7,13,19 * * *" in text
    assert "workflow_dispatch:" in text
    assert "COCOMELON_EXECUTION_MODE: paper" in text
    assert "COCOMELON_API_URL: https://api.hyperliquid.xyz" in text
    assert "COCOMELON_WS_URL: wss://api.hyperliquid.xyz/ws" in text
    assert f"COHORT_CODE_REVISION: {PINNED_CODE}" in text
    assert f"GAP_WATCH_REVISION: {PINNED_WATCHER}" in text
    assert f"ref: {PINNED_CODE}" in text
    assert f"ref: {PINNED_WATCHER}" in text
    assert "testnet" not in text.lower()
    assert "COCOMELON_EXECUTION_MODE: live" not in text


def test_scheduled_campaign_collects_bounded_nonoverlapping_artifacts() -> None:
    text = _workflow_text()

    assert "group: genuine-mainnet-evidence-571c13" in text
    assert "cancel-in-progress: false" in text
    assert "--seconds 2700" in text
    assert "--deep-limit 5" in text
    assert "for ATTEMPT in 1 2" in text
    assert "python -m cocomelon.ops.gap_watch" in text
    assert 'GAP_WATCH_STATUS" -eq 20' in text
    assert 'record["gap_count"] == 0' in text
    assert 'record["duplicate_count"] == 0' in text
    assert 'record["anomaly_count"] == 0' in text
    assert 'replay["data_complete"] is True' in text
    assert 'dataset["data_complete"] is True' in text
    assert '"economic_claim": "none"' in text
    assert 'assert "edge" not in replay' in text
    assert 'assert "profitable" not in replay' in text
    assert "retention-days: 90" in text
