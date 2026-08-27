from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/evidence-campaign-scheduled.yml")
PINNED_CODE = "f21ad7be581bc662127e75f832cd8fcbf4f5f93b"
ENTRY_WINDOW_SECONDS = 2700
CAPTURE_WINDOW_SECONDS = 5400


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_scheduled_campaign_v3_is_fixed_revision_mainnet_paper_only() -> None:
    text = _workflow_text()

    assert "name: Scheduled Genuine Mainnet Evidence Campaign V3" in text
    assert "schedule:" in text
    assert "37 1,4,7,10,13,16,19,22 * * *" in text
    assert "workflow_dispatch:" in text
    assert "COCOMELON_EXECUTION_MODE: paper" in text
    assert "COCOMELON_API_URL: https://api.hyperliquid.xyz" in text
    assert "COCOMELON_WS_URL: wss://api.hyperliquid.xyz/ws" in text
    assert "COCOMELON_WS_CONNECT_SPACING_SECONDS: 15" in text
    assert f"COHORT_CODE_REVISION: {PINNED_CODE}" in text
    assert f"ref: {PINNED_CODE}" in text
    assert "testnet" not in text.lower()
    assert "COCOMELON_EXECUTION_MODE: live" not in text


def test_scheduled_campaign_v3_records_one_fixed_lifecycle_window() -> None:
    text = _workflow_text()

    assert "group: genuine-mainnet-evidence-v3-f21ad7be" in text
    assert "cancel-in-progress: false" in text
    assert f"--seconds {CAPTURE_WINDOW_SECONDS}" in text
    assert "--deep-limit 5" in text
    assert "for ATTEMPT in 1 2" not in text
    assert "attempt_ledger.py" not in text
    assert "selection_audit" not in text
    assert "python -m cocomelon.ops.gap_watch" in text
    assert "record-transport.json" in text
    assert "normalize_redundant_record_payload" in text
    assert 'record["gap_count"] == 0' in text
    assert 'record["duplicate_count"] == 0' in text
    assert 'record["anomaly_count"] == 0' in text
    assert 'record["redundant_ws_lane_count"] == 2' in text
    assert 'record["transport_health_semantics"]' in text


def test_scheduled_campaign_v3_freezes_lifecycle_aware_replay() -> None:
    text = _workflow_text()

    assert "freeze_baseline_replay_payload" in text
    assert "lifecycle_aware=True" in text
    assert f'assert replay["entry_window_ms"] == {ENTRY_WINDOW_SECONDS * 1000}' in text
    assert (
        'assert replay["replay_engine_version"] == "phase8-v2-lifecycle-aware"'
        in text
    )
    assert (
        'assert replay["config_version"] == "phase9-baseline-replay-v2-lifecycle-aware"'
        in text
    )


def test_scheduled_campaign_v3_requires_clean_complete_flat_replay() -> None:
    text = _workflow_text()

    assert 'replay["data_complete"] is True' in text
    assert 'dataset["data_complete"] is True' in text
    assert 'replay["opened_positions"] == replay["closed_positions"]' in text
    assert '"economic_eligible"' in text
    assert '"economic_ineligibility_reasons"' in text
    assert '"economic_claim": "none"' in text
    assert 'assert "edge" not in replay' in text
    assert 'assert "profitable" not in replay' in text
    assert "retention-days: 90" in text


def test_scheduled_campaign_v3_is_performance_blind() -> None:
    text = _workflow_text()
    acquisition = text[
        text.index("Record lifecycle-aware genuine public mainnet evidence") :
        text.index("Validate and replay recorded evidence offline")
    ]

    assert "final_equity" not in acquisition
    assert "profitable" not in acquisition
    assert "pnl" not in acquisition.lower()
    assert "retry" not in acquisition.lower()
    assert 'reasons.append("open_exposure")' in acquisition


def test_scheduled_campaign_v3_records_protocol_metadata() -> None:
    text = _workflow_text()

    assert '"campaign_version": "v3-lifecycle-aware-mainnet"' in text
    assert f'"entry_window_seconds": {ENTRY_WINDOW_SECONDS}' in text
    assert f'"capture_window_seconds": {CAPTURE_WINDOW_SECONDS}' in text
    assert '"replay_engine_version": replay["replay_engine_version"]' in text
    assert '"config_version": replay["config_version"]' in text
    assert '"new_exposure_cutoff_ms": replay["new_exposure_cutoff_ms"]' in text
    assert "scheduled-genuine-mainnet-evidence-v3-${{ github.run_id }}" in text


def test_scheduled_campaign_does_not_run_on_repository_push() -> None:
    text = _workflow_text()
    assert "push:" not in text
