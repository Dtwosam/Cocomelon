from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/prospective-hype-v2-clean.yml")
PINNED_REVISION = "d15971eb22cec7b6fb2025bbb338c9d6d677eb63"


def _source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_v2_workflow_is_isolated_and_source_pinned() -> None:
    source = _source()

    assert "Prospective HYPE V2 Clean Observer" in source
    assert 'cron: "43,48,53 * * * *"' in source
    assert "group: prospective-hype-v2-clean-observer" in source
    assert "cancel-in-progress: false" in source
    assert "timeout-minutes: 30" in source
    assert "artifacts/prospective-hype-v2-clean" in source
    assert "prospective-hype-v2-clean-state" in source
    assert f"OBSERVER_SOURCE_REVISION: {PINNED_REVISION}" in source
    assert f"ref: {PINNED_REVISION}" in source
    assert "persist-credentials: false" in source


def test_v2_workflow_prewarms_off_peak_and_fails_closed_when_stale() -> None:
    source = _source()

    assert "Pre-warm for protected hourly capture" in source
    assert "prewarm_floor_ms = 43 * minute_ms" in source
    assert "protected_attempt_ms = 3 * minute_ms" in source
    assert "freshness_limit_ms = 15 * minute_ms" in source
    assert "PREWARM_SCHEDULE_TOO_LATE_FOR_FRESH_CAPTURE" in source
    assert "PREWARM_DELAY_OUT_OF_BOUNDS" in source


def test_v2_workflow_uses_only_v2_campaign_identity() -> None:
    source = _source()

    assert "HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V2" in source
    assert "HYPE_PROSPECTIVE_VALIDATION_V2" in source
    assert "HYPE_PROSPECTIVE_VALIDATION_V1" not in source
    assert " --campaign v2 --root " in source
    assert '"kind": "prospective-hype-v2-clean-control-plane"' in source
    assert '"schedule_minutes_utc": [43, 48, 53]' in source
    assert '"protected_attempt_minute_utc": 3' in source
    assert '"capture_transport": "off_peak_redundant_prewarm_v2"' in source
    assert '"job_timeout_minutes": 30' in source
    assert "POST_CUTOVER_CONTROL_PLANE_ATTESTATION_REQUIRED" in source


def test_v2_workflow_remains_research_only_mainnet() -> None:
    source = _source()

    assert "COCOMELON_EXECUTION_MODE: paper" in source
    assert "COCOMELON_API_URL: https://api.hyperliquid.xyz" in source
    assert "COCOMELON_WS_URL: wss://api.hyperliquid.xyz/ws" in source
    assert "contents: read" in source
    assert "actions: read" in source
    assert "testnet" not in source.lower()
    assert "promotion_eligible" in source
