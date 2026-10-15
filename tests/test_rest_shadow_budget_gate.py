"""Safety screens use only process-local snapshots and never emit HTTP."""
from __future__ import annotations

from pathlib import Path

from cocomelon.config import Settings
from cocomelon.hyperliquid.client import InfoClient
from cocomelon.hyperliquid.rate_limit import RollingRateBudget
from cocomelon.research.forward_rest_depth_shadow import (
    ENABLED_ENV,
    IP_QUOTA_ENV,
    attached_shadow_allowed,
    start_attached_paper_shadow,
)
from cocomelon.research.rest_shadow_budget_gate import (
    THREE_MARKET_SHADOW_WEIGHT,
    screen_local_rest_shadow_headroom,
)


def snapshot_with_required_peak(weight: int) -> dict[str, int | bool]:
    budget = RollingRateBudget(limit=1000)
    budget.acquire(weight)
    reader = InfoClient(Settings(), budget=budget)
    snapshot = reader.rest_budget_snapshot()
    assert snapshot is not None
    return snapshot


def test_small_observed_required_peak_is_local_only_not_ip_certification() -> None:
    snapshot = snapshot_with_required_peak(40)
    screen = screen_local_rest_shadow_headroom(snapshot)
    assert screen.permitted is True
    assert screen.reason == "local_screen_only_ip_unverified"
    assert screen.projected_peak_weight == 40 + THREE_MARKET_SHADOW_WEIGHT + 300
    assert screen.local_limit == 1000
    assert snapshot["external_process_ip_weight_verified"] is False


def test_observed_required_peak_does_not_leave_room_for_three_market_shadow() -> None:
    observed = snapshot_with_required_peak(987)
    screen = screen_local_rest_shadow_headroom(observed)
    assert screen.permitted is False
    assert screen.reason == "insufficient_peak_headroom"
    assert screen.projected_peak_weight == 1647
    assert screen.local_limit == 1000


def test_missing_unsupported_or_forged_snapshots_fail_closed() -> None:
    snapshot = snapshot_with_required_peak(20)
    invalid = [
        None,
        {},
        {**snapshot, "peak_total_rolling_weight": True},
        {**snapshot, "rolling_weight_limit": 1500},
        {**snapshot, "rolling_window_seconds": 120},
        {**snapshot, "shadow_priority_reserve_weight": 0},
        {**snapshot, "total_rolling_weight": 19},
        {**snapshot, "external_process_ip_weight_verified": True},
        {**snapshot, "source_or_execution_authority": True},
    ]
    assert all(not screen_local_rest_shadow_headroom(raw).permitted for raw in invalid)
    reader = InfoClient(Settings(), budget=RollingRateBudget(limit=1000))
    assert screen_local_rest_shadow_headroom(
        reader.rest_budget_snapshot()
    ).reason == "no_mandatory_request_baseline"


def test_prior_shadow_usage_is_not_a_clean_mandatory_baseline() -> None:
    budget = RollingRateBudget(limit=1000)
    budget.acquire(20)
    assert budget.try_acquire(2, origin="shadow", reserve_remaining=300)
    reader = InfoClient(Settings(), budget=budget)
    snapshot = reader.rest_budget_snapshot()
    assert snapshot is not None
    result = screen_local_rest_shadow_headroom(snapshot)
    assert result.permitted is False
    assert result.reason == "not_a_shadow_free_baseline"


def test_attached_observer_does_not_schedule_or_write_when_peak_is_unsafe(
    tmp_path: Path,
) -> None:
    budget = RollingRateBudget(limit=1000)
    budget.acquire(987)
    calls: list[object] = []

    def transport(*args: object) -> object:
        calls.append(args)
        raise AssertionError("optional research must not use network")

    reader = InfoClient(Settings(), budget=budget, transport=transport)
    flags = {ENABLED_ENV: "1", IP_QUOTA_ENV: "1"}
    assert not attached_shadow_allowed(reader, Settings(), environ=flags)
    assert start_attached_paper_shadow(
        reader, Settings(), tmp_path,
        session_started_ms=100,
        stop_requested=lambda: False,
        environ=flags,
    ) is None
    assert calls == []
    assert list(tmp_path.iterdir()) == []


def test_missing_required_baseline_denies_even_with_both_flags() -> None:
    budget = RollingRateBudget(limit=1000)
    reader = InfoClient(Settings(), budget=budget)
    flags = {ENABLED_ENV: "1", IP_QUOTA_ENV: "1"}
    assert not attached_shadow_allowed(reader, Settings(), environ=flags)
    assert screen_local_rest_shadow_headroom(
        reader.rest_budget_snapshot()
    ).reason == "no_mandatory_request_baseline"
