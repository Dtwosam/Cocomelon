from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/evidence-campaign-v4-scheduled.yml")
PINNED_CODE = "0ad7c5c3626d0a4a1f2ec87c8806983d529a9be7"
ENTRY_WINDOW_SECONDS = 2700
CAPTURE_WINDOW_SECONDS = 18900
MAX_POSITION_AGE_SECONDS = 14400


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_v4_campaign_is_exact_pinned_mainnet_paper_schedule() -> None:
    text = _text()
    assert "name: Scheduled Genuine Mainnet Evidence Campaign V4" in text
    assert "schedule:" in text
    assert '37 1,7,13,19 * * *' in text
    assert "workflow_dispatch:" in text
    assert "COCOMELON_EXECUTION_MODE: paper" in text
    assert "COCOMELON_API_URL: https://api.hyperliquid.xyz" in text
    assert "COCOMELON_WS_URL: wss://api.hyperliquid.xyz/ws" in text
    assert "COCOMELON_WS_CONNECT_SPACING_SECONDS: 15" in text
    assert f"COHORT_CODE_REVISION: {PINNED_CODE}" in text
    assert f"ref: {PINNED_CODE}" in text
    assert "testnet" not in text.lower()
    assert "COCOMELON_EXECUTION_MODE: live" not in text


def test_v4_campaign_rejects_manual_dispatch_before_capture() -> None:
    text = _text()
    guard = 'if [ "$GITHUB_EVENT_NAME" != "schedule" ]; then'
    assert guard in text
    assert "V4 evidence cohorts are schedule-only" in text
    assert text.index(guard) < text.index("cocomelon record-mainnet-evidence")


def test_v4_campaign_uses_one_fixed_5h15_capture() -> None:
    text = _text()
    assert "group: genuine-mainnet-evidence-v4-0ad7c5c3" in text
    assert "cancel-in-progress: false" in text
    assert "timeout-minutes: 350" in text
    assert f"--seconds {CAPTURE_WINDOW_SECONDS}" in text
    assert "--deep-limit 5" in text
    assert "for ATTEMPT in 1 2" not in text
    assert "attempt_ledger.py" not in text
    assert "retry" not in text.lower()
    assert "python -m cocomelon.ops.gap_watch" in text
    assert "record-transport.json" in text
    assert "normalize_redundant_record_payload" in text


def test_v4_campaign_freezes_exact_thesis_expiry_replay() -> None:
    text = _text()
    assert "freeze_baseline_replay_payload" in text
    assert "lifecycle_aware=True" in text
    assert "thesis_expiry=True" in text
    assert f'assert replay["entry_window_ms"] == {ENTRY_WINDOW_SECONDS * 1000}' in text
    assert f'assert freeze["max_position_age_ms"] == {MAX_POSITION_AGE_SECONDS * 1000}' in text
    assert 'assert replay["replay_engine_version"] == "phase8-v3-thesis-expiry"' in text
    assert 'assert replay["config_version"] == "phase9-baseline-replay-v3-thesis-expiry"' in text
    assert '"phase7-v2-4h-thesis-expiry"' in text


def test_v4_campaign_requires_clean_complete_flat_replay() -> None:
    text = _text()
    assert 'replay["data_complete"] is True' in text
    assert 'dataset["data_complete"] is True' in text
    assert 'replay["opened_positions"] == replay["closed_positions"]' in text
    assert '"economic_eligible"' in text
    assert '"economic_ineligibility_reasons"' in text
    assert '"economic_claim": "none"' in text
    assert 'reasons.append("open_exposure")' in text
    assert "retention-days: 90" in text


def test_v4_campaign_is_performance_blind() -> None:
    text = _text()
    assert 'assert "edge" not in replay' in text
    assert 'assert "profitable" not in replay' in text
    summary = text[
        text.index("          summary = {") :
        text.index('          (root / "cohort-summary.json").write_text')
    ]
    forbidden = (
        '"final_equity"',
        '"pnl"',
        '"profit_factor"',
        '"mean_net_r"',
        '"win_rate"',
        '"bootstrap"',
    )
    lowered = summary.lower()
    assert all(field not in lowered for field in forbidden)


def test_v4_campaign_records_distinct_protocol_metadata() -> None:
    text = _text()
    assert '"campaign_version": "v4-thesis-expiry-mainnet"' in text
    assert f'"entry_window_seconds": {ENTRY_WINDOW_SECONDS}' in text
    assert f'"capture_window_seconds": {CAPTURE_WINDOW_SECONDS}' in text
    assert f'"max_position_age_seconds": {MAX_POSITION_AGE_SECONDS}' in text
    assert '"replay_engine_version": replay["replay_engine_version"]' in text
    assert '"config_version": replay["config_version"]' in text
    assert '"execution_config_version": "phase7-v2-4h-thesis-expiry"' in text
    artifact_name = (
        "scheduled-genuine-mainnet-evidence-v4-${{ github.run_id }}-"
        "attempt-${{ github.run_attempt }}"
    )
    assert artifact_name in text


def test_v4_campaign_does_not_run_on_repository_push() -> None:
    assert "push:" not in _text()
