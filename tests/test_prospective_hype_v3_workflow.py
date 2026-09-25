from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/prospective-hype-v3-clean.yml")
PINNED_REVISION = "298723c52d6a3b09839d05451d3d7db9753815bf"


def _source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_v3_transport_is_scheduler_independent_and_source_pinned() -> None:
    source = _source()

    assert "Prospective HYPE V3 Clean Observer" in source
    assert "workflow_dispatch:" in source
    assert "target_capture_ms:" in source
    assert "queue_parent_run_id:" in source
    assert "\n  schedule:" not in source
    assert "cron:" not in source
    assert f"OBSERVER_SOURCE_REVISION: {PINNED_REVISION}" in source
    assert f"ref: {PINNED_REVISION}" in source
    assert "persist-credentials: false" in source


def test_v3_bootstrap_precreates_bounded_rolling_capture_queue() -> None:
    source = _source()

    assert "Prospective HYPE V3 bootstrap" in source
    assert "Prospective HYPE V3 capture {0}" in source
    assert 'QUEUE_DEPTH: "4"' in source
    assert 'HANDOFF_LEAD_MS: "600000"' in source
    assert "next_protected_capture_ms" in source
    assert "missing_future_targets" in source
    assert "normalize_dispatch_runs" in source
    assert "V3_QUEUE_REFILL_UNVERIFIED" in source
    assert "for attempt in {1..10}" in source


def test_v3_duplicate_dispatches_are_leader_elected_before_state_touch() -> None:
    source = _source()

    leader = source.index("Resolve deterministic transport leader")
    handoff = source.index("Hold leader until transport handoff")
    refill = source.index("Refill rolling dispatch queue")
    observe = source.index("Restore latest clean evidence state")

    assert leader < handoff < refill < observe
    assert "elect_dispatch_leader" in source
    assert '"proceed=true\\n"' in source
    assert '"proceed=false"' not in source
    assert "needs.prepare.outputs.proceed == 'true'" in source


def test_v3_dispatch_retries_only_transient_github_failures() -> None:
    source = _source()

    assert "attempt=1" in source
    assert "attempt -ge 5" in source
    assert "HTTP (500|502|503|504)" in source
    assert 'gh workflow run "$WORKFLOW_FILE"' in source
    assert '--ref main' in source


def test_v3_capture_fails_closed_outside_frozen_freshness_window() -> None:
    source = _source()

    assert "Enforce protected capture freshness" in source
    assert "ProspectiveCaptureWindow.READY" in source
    assert "V3_CAPTURE_WINDOW_" in source
    assert '"protected_capture_minute_utc": 3' in source
    assert '"max_entry_candle_age_ms": MAX_ENTRY_CANDLE_AGE_MS' in source


def test_v3_control_plane_attests_dispatch_transport_exactly() -> None:
    source = _source()

    assert '"kind": "prospective-hype-v3-clean-control-plane"' in source
    assert '"capture_transport": "rolling_workflow_dispatch_queue_v3"' in source
    assert '"queue_depth": 4' in source
    assert '"queue_horizon_ms": 14_400_000' in source
    assert '"prepare_handoff_lead_ms": 600_000' in source
    assert '"duplicate_policy": "lowest_covering_run_id"' in source
    assert '"bootstrap_event": "push"' in source
    assert '"capture_event": "workflow_dispatch"' in source
    assert '"concurrency_mode": "target_leader_election"' in source
    assert '"prepare_job_timeout_minutes": 270' in source
    assert '"observe_job_timeout_minutes": 30' in source
    assert '"actions_permission": "write"' in source
    assert '"schema_version": 3' in source


def test_v3_state_and_economics_are_isolated_from_v1_and_v2() -> None:
    source = _source()

    assert "prospective-hype-v3-clean-state" in source
    assert "artifacts/prospective-hype-v3-clean" in source
    assert "HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V3" in source
    assert "HYPE_PROSPECTIVE_VALIDATION_V3" in source
    assert "--campaign v3" in source
    assert 'payload["campaign_version"] == "v3"' in source
    assert 'report["campaign_version"] == "v3"' in source
    assert "prospective-hype-v2-clean-state" not in source
    assert "--campaign v2" not in source


def test_v3_remains_paper_only_and_non_promotional() -> None:
    source = _source()

    assert "COCOMELON_EXECUTION_MODE: paper" in source
    assert "COCOMELON_API_URL: https://api.hyperliquid.xyz" in source
    assert "COCOMELON_WS_URL: wss://api.hyperliquid.xyz/ws" in source
    assert "contents: read" in source
    assert "actions: write" in source
    assert '"promotion_eligible": False' in source
    assert "testnet" not in source.lower()
