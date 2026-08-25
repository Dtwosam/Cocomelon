from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/phase9-mainnet-heartbeat-smoke.yml")
PINNED_COHORT = "6de9d86aa7c36fce4f459e0bcc4e004de9215f25"


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
    assert "COCOMELON_WS_CONNECT_SPACING_SECONDS: 15" in text
    assert f"COHORT_CODE_REVISION: {PINNED_COHORT}" in text
    assert f"ref: {PINNED_COHORT}" in text
    assert "COCOMELON_EXECUTION_MODE: live" not in text


def test_heartbeat_smoke_requires_gap_free_merged_feed_and_keeps_reconnect_diagnostics() -> None:
    text = _workflow_text()

    assert "duration_seconds=90" in text
    assert 'record["gap_count"] == 0' in text
    assert 'record["duplicate_count"] == 0' in text
    assert 'record["anomaly_count"] == 0' in text
    assert 'assert record["reconnect_count"] == 0' not in text
    assert 'assert record["transport_reconnect_count"] == 0' not in text
    assert '"reconnect_count": record["reconnect_count"]' in text
    assert '"transport_reconnect_count": record["transport_reconnect_count"]' in text
    assert 'record["redundant_ws_lane_count"] == 2' in text
    assert 'record["live_orders"] is False' in text
    assert 'record["network_access"] is True' in text
    assert "retention-days: 7" in text
    assert "economic_claim" not in text


def test_heartbeat_smoke_records_lane_readiness_trace_without_changing_acceptance() -> None:
    text = _workflow_text()

    assert "lane-trace.jsonl" in text
    assert "RedundantStreamMux" in text
    assert '"first_event"' in text
    assert '"gap"' in text
    assert "record_mainnet_evidence_payload" in text
    assert "runner=_run_mainnet_evidence" in text


def test_heartbeat_smoke_traces_websocket_startup_stages() -> None:
    text = _workflow_text()

    assert "TracedConnection" in text
    assert '"connection_start"' in text
    assert '"connection_ready"' in text
    assert '"connection_error"' in text
    assert '"send_start"' in text
    assert '"send_done"' in text
    assert '"recv_start"' in text
    assert '"recv_done"' in text
    assert '"recv_error"' in text
    assert "ws_client.connect_mainnet_ws = traced_connect_mainnet_ws" in text
