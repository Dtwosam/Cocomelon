from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import cast

import pytest

from cocomelon.config import Settings
from cocomelon.domain.market import MarketId
from cocomelon.hyperliquid.client import InfoClient, InfoHttpError
from cocomelon.hyperliquid.rate_limit import RollingRateBudget
from cocomelon.research.forward_rest_depth_shadow import (
    COHORT,
    RestDepthShadow,
    RestShadowConfig,
    _DepthClock,
    run_to_files,
)


def book(market: str, when_ms: int, *, depth: int = 20) -> dict[str, object]:
    return {
        "coin": market,
        "time": when_ms,
        "levels": [
            [
                {"px": str(100 - n), "sz": "1.5", "n": 1}
                for n in range(depth)
            ],
            [
                {"px": str(101 + n), "sz": "1.5", "n": 1}
                for n in range(depth)
            ],
        ],
    }


class FakeReader:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.response: object = book("BLUR", 5_000)

    def try_shadow_l2_book(self, market: MarketId) -> tuple[bool, object | None]:
        self.calls.append(market.wire_name)
        return True, self.response


def test_rest_shadow_default_off_never_calls_or_writes_files(tmp_path: Path) -> None:
    reader = FakeReader()
    out = tmp_path / "do-not-touch"
    result = asyncio.run(run_to_files(reader, RestShadowConfig(), out))
    assert result["enabled"] is False
    assert result["network_calls"] == 0
    assert reader.calls == []
    assert not out.exists()


def test_shadow_requires_frozen_cohort_and_conservative_interval() -> None:
    assert COHORT == ("BLUR", "BOME", "CASHCAT")
    with pytest.raises(ValueError, match="frozen"):
        RestShadowConfig(enabled=True, markets=("BLUR",))
    with pytest.raises(ValueError, match="once"):
        RestShadowConfig(enabled=True, poll_interval_ms=500)
    with pytest.raises(ValueError, match="duration"):
        RestShadowConfig(enabled=True, duration_seconds=10)
    with pytest.raises(ValueError, match="disabled"):
        RestDepthShadow(FakeReader(), config=RestShadowConfig(), start_ns=0)


def test_depth_clock_integrates_only_actual_twenty_by_twenty_source_time() -> None:
    start = 10_000_000_000
    clock = _DepthClock()
    clock.update(now_ns=start + 1_000_000_000, age_ms=300, full_depth=True)
    assert clock.read(now_ns=start + 5_000_000_000, start_ns=start) == {
        "full_depth_source_fresh_3000_fraction": 0.54,
        "full_depth_source_fresh_5000_fraction": 0.8,
    }
    clock.update(now_ns=start + 5_000_000_000, age_ms=50, full_depth=False)
    a = clock.read(now_ns=start + 9_000_000_000, start_ns=start)
    assert a["full_depth_source_fresh_3000_fraction"] == 0.3
    assert a["full_depth_source_fresh_5000_fraction"] == pytest.approx(4 / 9, abs=1e-6)


def test_unique_duplicate_and_shallow_rest_cannot_inflate_20_depth() -> None:
    start = 2_000_000_000
    probe = RestDepthShadow(
        FakeReader(), config=RestShadowConfig(enabled=True), start_ns=start
    )
    first = probe.record(
        "BLUR", book("BLUR", 1_000),
        now_ns=start, utc_ms=1_100, result="ok",
    )
    duplicate = probe.record(
        "BLUR", book("BLUR", 1_000),
        now_ns=start + 4_000_000_000, utc_ms=5_100, result="ok",
    )
    shallow = probe.record(
        "BLUR", book("BLUR", 6_000, depth=5),
        now_ns=start + 5_000_000_000, utc_ms=6_100, result="ok",
    )
    assert first["status"] == "unique"
    assert duplicate["status"] == "duplicate"
    assert shallow["status"] == "unique"
    s = probe.summary(now_ns=start + 10_000_000_000)
    assert s["duplicate_books"] == 1
    assert s["shallow_books"] == 1
    assert s["actual_http_requests"] == 3
    assert s["markets"]["BLUR"]["full_depth_source_fresh_3000_fraction"] == 0.29
    assert s == probe.summary(now_ns=start + 10_000_000_000)
    for flag in (
        "source_completeness_certified", "production_source_authorized",
        "signed_gap_history_changed", "paper_account_changed",
        "execution_authority", "profitability_verified",
    ):
        assert s[flag] is False


def test_http_and_source_clock_anomalies_fail_closed() -> None:
    start = 1_000
    obj = RestDepthShadow(
        FakeReader(), config=RestShadowConfig(enabled=True), start_ns=start
    )
    assert obj.record(
        "BLUR", None, now_ns=start, utc_ms=1000, result="http_error"
    )["status"] == "http_error"
    assert obj.record(
        "BLUR", book("BOME", 2_000),
        now_ns=start + 1_000_000, utc_ms=2_000, result="ok"
    )["status"] == "invalid"
    future = obj.record(
        "BLUR", book("BLUR", 9_000),
        now_ns=start + 2_000_000, utc_ms=8_000, result="ok"
    )
    rollback = obj.record(
        "BLUR", book("BLUR", 8_000),
        now_ns=start + 3_000_000, utc_ms=10_000, result="ok"
    )
    assert future["status"] == "unique"
    assert rollback["status"] == "out_of_order"
    summary = obj.summary(now_ns=start + 1_000_000_000)
    assert summary["http_errors"] == 1
    assert summary["protocol_failures"] == 1
    assert summary["future_dated_books"] == 1
    assert summary["out_of_order_books"] == 1
    assert summary["markets"]["BLUR"]["full_depth_source_fresh_3000_fraction"] == 0


def test_shadow_slice_and_shared_quota_skips_are_not_source_receipts() -> None:
    start = 100
    reader = FakeReader()
    slice_budget = RollingRateBudget(
        limit=2, monotonic=lambda: 10.0,
    )
    obj = RestDepthShadow(
        reader, config=RestShadowConfig(enabled=True),
        start_ns=start, slice_budget=slice_budget
    )
    a = obj.record(
        "BLUR", None, now_ns=start, utc_ms=1000,
        result="shared_budget_skipped",
    )
    b = obj.record(
        "BOME", None, now_ns=start, utc_ms=1000,
        result="shadow_budget_skipped",
    )
    assert a["status"] == "shared_budget_skipped"
    assert b["status"] == "shadow_budget_skipped"
    stats = obj.summary(now_ns=start + 1_000_000_000)
    assert stats["shared_budget_skips"] == 1
    assert stats["shadow_slice_budget_skips"] == 1
    assert stats["actual_http_requests"] == 0
    assert stats["markets"]["BLUR"]["unique"] == 0


def test_nonblocking_limiter_is_atomic_across_paper_and_shadow_threads() -> None:
    fixed = [100.0]
    budget = RollingRateBudget(limit=30, monotonic=lambda: fixed[0])
    with ThreadPoolExecutor(max_workers=12) as pool:
        grants = list(pool.map(budget.try_acquire, [2] * 100))
    assert sum(grants) == 15
    assert budget.used_weight == 30
    assert budget.try_acquire(2) is False
    fixed[0] = 160.001
    assert budget.try_acquire(2) is True
    assert budget.used_weight == 2


def test_required_reader_preserves_blocking_budget_semantics() -> None:
    now = [0.0]
    sleeps: list[float] = []
    def pause(amount: float) -> None:
        sleeps.append(amount)
        now[0] += amount
    budget = RollingRateBudget(
        limit=2, monotonic=lambda: now[0], sleep=pause
    )
    assert budget.try_acquire(2) is True
    budget.acquire(2)
    assert sleeps == [60.0]
    assert budget.used_weight == 2


def test_shadow_info_read_denied_without_network_when_shared_quota_full() -> None:
    calls: list[dict[str, object]] = []
    def transport(url: str, payload: dict[str, object], timeout: float) -> object:
        del url, timeout
        calls.append(payload)
        return book("BLUR", 1_000)
    budget = RollingRateBudget(limit=2)
    client = InfoClient(Settings(), budget=budget, transport=transport)
    assert budget.try_acquire(2) is True
    allowed, value = client.try_shadow_l2_book(MarketId(dex="", coin="BLUR"))
    assert not allowed and value is None
    assert calls == []


def test_shadow_http_one_shot_no_retry_and_weight_charged_on_error() -> None:
    attempts = 0
    def transport(url: str, payload: dict[str, object], timeout: float) -> object:
        nonlocal attempts
        del url, payload
        attempts += 1
        assert timeout == 4.0
        raise InfoHttpError(429, "test")
    budget = RollingRateBudget(limit=2)
    client = InfoClient(Settings(), budget=budget, transport=transport)
    with pytest.raises(InfoHttpError):
        client.try_shadow_l2_book(MarketId(dex="", coin="BLUR"))
    assert attempts == 1
    assert budget.used_weight == 2
    allowed, value = client.try_shadow_l2_book(MarketId(dex="", coin="BLUR"))
    assert not allowed and value is None
    assert attempts == 1


def test_poll_one_never_bypasses_budget_or_emits_trade_event() -> None:
    reader = FakeReader()
    start_ns = time.monotonic_ns()
    budget = RollingRateBudget(limit=2)
    assert budget.try_acquire(2)
    observer = RestDepthShadow(
        reader, config=RestShadowConfig(enabled=True),
        start_ns=start_ns, slice_budget=budget,
    )
    output = asyncio.run(observer.poll_one("BLUR", now_ns=start_ns))
    assert output["status"] == "shadow_budget_skipped"
    assert output["source_authority"] is False
    assert output["account_or_order_changed"] is False
    assert reader.calls == []


def test_priority_reserve_prevents_shadow_from_exhausting_mandatory_quota() -> None:
    calls: list[str] = []
    budget = RollingRateBudget(limit=1000)
    assert budget.try_acquire(698)
    def transport(url: str, payload: dict[str, object], timeout: float) -> object:
        del url, timeout
        calls.append(cast(str, payload["type"]))
        return book("BLUR", 1_000)
    client = InfoClient(Settings(), budget=budget, transport=transport)
    allowed, response = client.try_shadow_l2_book(MarketId(dex="", coin="BLUR"))
    assert allowed is True
    assert response is not None
    assert budget.used_weight == 700
    second, result = client.try_shadow_l2_book(MarketId(dex="", coin="BLUR"))
    assert second is False and result is None
    assert budget.used_weight == 700
    assert calls == ["l2Book"]
    # Critical ordinary InfoClient reads are *not* denied the reserved 300.
    client.meta_and_asset_ctxs()
    assert budget.used_weight == 720


def test_unknown_shared_budget_implementation_denies_shadow_without_io() -> None:
    class IncompleteBudget:
        def acquire(self, weight: int) -> None:
            del weight
    calls = 0
    def transport(url: str, payload: dict[str, object], timeout: float) -> object:
        nonlocal calls
        del url, payload, timeout
        calls += 1
        return {}
    client = InfoClient(
        Settings(), budget=IncompleteBudget(), transport=transport,
    )
    allowed, value = client.try_shadow_l2_book(MarketId(dex="", coin="BLUR"))
    assert allowed is False and value is None
    assert calls == 0


def test_shadow_reservations_exclude_invalid_negative_priority_reserve() -> None:
    budget = RollingRateBudget(limit=1000)
    for bad in (-1, True):
        with pytest.raises(ValueError, match="reserve_remaining"):
            budget.try_acquire(2, reserve_remaining=bad)
    assert budget.used_weight == 0
