from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/phase9-mainnet-heartbeat-smoke.yml")
PINNED_COHORT = "30c0de4bf76a5eda74c9bb71f17db00f1f9ce17e"


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_heartbeat_smoke_is_one_shot_mainnet_paper_diagnostic() -> None:
    text = _workflow_text()

    assert "push:" in text
    assert "branches: [main]" in text
    assert "phase9-mainnet-heartbeat-smoke.yml" in text
    assert "workflow_dispatch:" in text
    assert "COCOMELON_EXECUTION_MODE: paper" in text
    assert "COCOMELON_API_URL: https://api.hyperliquid.xyz" in text
    assert "COCOMELON_WS_URL: wss://api.hyperliquid.xyz/ws" in text
    assert f"COHORT_CODE_REVISION: {PINNED_COHORT}" in text
    assert f"ref: {PINNED_COHORT}" in text
    assert "COCOMELON_EXECUTION_MODE: live" not in text


def test_heartbeat_smoke_crosses_old_disconnect_boundary_and_fails_closed() -> None:
    text = _workflow_text()

    assert "--seconds 90" in text
    assert 'record["gap_count"] == 0' in text
    assert 'record["reconnect_count"] == 0' in text
    assert 'record["transport_reconnect_count"] == 0' in text
    assert 'record["redundant_ws_lane_count"] == 2' in text
    assert 'record["live_orders"] is False' in text
    assert 'record["network_access"] is True' in text
    assert "retention-days: 7" in text
    assert "economic_claim" not in text
