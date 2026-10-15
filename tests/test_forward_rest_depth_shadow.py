from __future__ import annotations

import asyncio
import hashlib
import json
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



def test_attached_shadow_requires_both_flags_same_reader_and_paper_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cocomelon.config import ExecutionMode
    from cocomelon.research import forward_rest_depth_shadow as observer

    reader = InfoClient(Settings())
    flags = {
        observer.ENABLED_ENV: "1",
        observer.IP_QUOTA_ENV: "1",
    }
    assert not observer.attached_shadow_allowed(reader, Settings(), environ={})
    assert not observer.attached_shadow_allowed(
        reader, Settings(), environ={observer.ENABLED_ENV: "1"}
    )
    assert not observer.attached_shadow_allowed(
        reader, Settings(execution_mode=ExecutionMode.LIVE), environ=flags
    )
    assert observer.attached_shadow_allowed(reader, Settings(), environ=flags)

    calls: list[tuple[object, object, Path]] = []

    async def no_network_run(
        selected_reader: object,
        config: RestShadowConfig,
        root: Path,
        *,
        stop_requested: object = None,
    ) -> dict[str, object]:
        calls.append((selected_reader, config, root))
        assert callable(stop_requested)
        return {"observation_window_completed": False}

    monkeypatch.setattr(observer, "run_to_files", no_network_run)

    async def run() -> None:
        for env in ({}, {observer.ENABLED_ENV: "1"}):
            assert observer.start_attached_paper_shadow(
                reader, Settings(), tmp_path,
                session_started_ms=111, stop_requested=lambda: False,
                environ=env,
            ) is None
        assert observer.start_attached_paper_shadow(
            reader, Settings(), tmp_path,
            session_started_ms=111, stop_requested=lambda: True,
            environ=flags,
        ) is None
        task = observer.start_attached_paper_shadow(
            reader, Settings(), tmp_path,
            session_started_ms=111, stop_requested=lambda: False,
            environ=flags,
        )
        assert task is not None
        await task

    asyncio.run(run())
    assert len(calls) == 1
    assert calls[0][0] is reader
    assert isinstance(calls[0][1], RestShadowConfig)
    assert cast(RestShadowConfig, calls[0][1]).enabled is True
    assert calls[0][2] == tmp_path / "rest-depth-research-only-111"


def test_attached_shadow_stop_does_not_emit_any_http_or_qualify(
    tmp_path: Path,
) -> None:
    reader = FakeReader()

    async def run() -> dict[str, object]:
        return await run_to_files(
            reader,
            RestShadowConfig(enabled=True),
            tmp_path / "stopped",
            stop_requested=lambda: True,
        )

    report = asyncio.run(run())
    assert reader.calls == []
    assert report["observation_window_completed"] is False
    assert report["actual_http_requests"] == 0
    assert report["interrupted"] is False
    raw = (tmp_path / "stopped" / "shadow-attempts.jsonl").read_bytes()
    assert raw == b""
    assert report["receipt_sha256"] == hashlib.sha256(raw).hexdigest()


def test_attached_shadow_cancel_writes_incomplete_receipt_not_trading_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cocomelon.research import forward_rest_depth_shadow as observer

    ready = asyncio.Event()

    async def mock_collect(
        shadow: RestDepthShadow,
        *,
        receipts: object,
        stop_requested: object = None,
    ) -> dict[str, object]:
        del shadow, stop_requested
        assert hasattr(receipts, "write")
        receipts.write('{"kind":"uncompleted_research"}\n')
        ready.set()
        await asyncio.Future()
        return {"observation_window_completed": True}

    monkeypatch.setattr(observer, "collect_shadow", mock_collect)

    async def run() -> None:
        task = asyncio.create_task(observer.run_to_files(
            FakeReader(),
            RestShadowConfig(enabled=True),
            tmp_path / "interrupted",
        ))
        await ready.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    folder = tmp_path / "interrupted"
    receipts = (folder / "shadow-attempts.jsonl").read_bytes()
    report = json.loads((folder / "summary.json").read_text())
    assert report["interrupted"] is True
    assert report["observation_window_completed"] is False
    assert report["receipt_sha256"] == hashlib.sha256(receipts).hexdigest()
    assert report["execution_authority"] is False
    assert report["paper_account_changed"] is False


def test_first_http_429_opens_source_only_circuit_without_more_network() -> None:
    class RateLimitedReader:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def try_shadow_l2_book(self, market: MarketId) -> tuple[bool, object | None]:
            self.calls.append(market.wire_name)
            raise InfoHttpError(429, "test rate limit")

    async def run() -> tuple[list[dict[str, object]], int]:
        reader = RateLimitedReader()
        now_ns = time.monotonic_ns()
        shadow = RestDepthShadow(
            reader,
            config=RestShadowConfig(enabled=True),
            start_ns=now_ns,
        )
        first = await shadow.poll_one("BLUR", now_ns=now_ns)
        second = await shadow.poll_one("BOME", now_ns=time.monotonic_ns())
        third = await shadow.poll_one("CASHCAT", now_ns=time.monotonic_ns())
        summary = shadow.summary(now_ns=time.monotonic_ns())
        assert first["status"] == "http_error"
        assert first["http_429"] is True
        assert second["status"] == third["status"] == "rate_limit_circuit_open"
        assert second["source_authority"] is False
        assert summary["http_429_count"] == 1
        assert summary["rate_limit_circuit_open"] is True
        assert summary["rate_limit_circuit_skips"] == 2
        assert summary["actual_http_requests"] == 1
        assert summary["execution_authority"] is False
        return [first, second, third], len(reader.calls)

    receipts, calls = asyncio.run(run())
    assert calls == 1
    assert len(receipts) == 3


def test_non_429_transport_error_does_not_claim_hard_rate_limit() -> None:
    class FailingReader:
        def try_shadow_l2_book(self, market: MarketId) -> tuple[bool, object | None]:
            del market
            raise InfoHttpError(502, "temporary")

    async def run() -> dict[str, object]:
        ns = time.monotonic_ns()
        shadow = RestDepthShadow(
            FailingReader(), config=RestShadowConfig(enabled=True),
            start_ns=ns,
        )
        first = await shadow.poll_one("BLUR", now_ns=ns)
        assert first["status"] == "http_error"
        assert "http_429" not in first
        return shadow.summary(now_ns=time.monotonic_ns())

    summary = asyncio.run(run())
    assert summary["http_errors"] == 1
    assert summary["http_429_count"] == 0
    assert summary["rate_limit_circuit_open"] is False


def test_shared_budget_reports_attributed_required_and_shadow_weight() -> None:
    clock = [100.0]
    budget = RollingRateBudget(limit=1000, monotonic=lambda: clock[0])
    def transport(url: str, payload: dict[str, object], timeout: float) -> object:
        del url, timeout
        return book("BLUR", 1000) if payload["type"] == "l2Book" else {}
    reader = InfoClient(Settings(), budget=budget, transport=transport)
    assert reader.meta_and_asset_ctxs() == {}
    allowed, value = reader.try_shadow_l2_book(MarketId(dex="", coin="BLUR"))
    assert allowed is True
    assert value is not None
    assert budget.try_acquire(4) is True
    snapshot = reader.rest_budget_snapshot()
    assert snapshot is not None
    assert snapshot["total_rolling_weight"] == 26
    assert snapshot["required_rolling_weight"] == 20
    assert snapshot["shadow_rolling_weight"] == 2
    assert snapshot["other_rolling_weight"] == 4
    assert snapshot["peak_total_rolling_weight"] == 26
    assert snapshot["peak_required_rolling_weight"] == 20
    assert snapshot["peak_shadow_rolling_weight"] == 2
    assert snapshot["shadow_admitted_lifetime"] == 1
    assert snapshot["shadow_denied_lifetime"] == 0
    assert snapshot["shadow_priority_reserve_weight"] == 300
    assert snapshot["external_process_ip_weight_verified"] is False
    assert snapshot["source_or_execution_authority"] is False
    clock[0] = 161
    expired = reader.rest_budget_snapshot()
    assert expired is not None
    assert expired["total_rolling_weight"] == 0
    assert expired["required_rolling_weight"] == 0
    assert expired["shadow_rolling_weight"] == 0
    assert expired["peak_total_rolling_weight"] == 26


def test_shared_budget_records_shadow_priority_denials_without_network() -> None:
    observed: list[str] = []
    def transport(url: str, payload: dict[str, object], timeout: float) -> object:
        del url, timeout
        observed.append(str(payload["type"]))
        return {}
    budget = RollingRateBudget(limit=1000)
    client = InfoClient(Settings(), budget=budget, transport=transport)
    assert budget.try_acquire(700)
    denied, value = client.try_shadow_l2_book(MarketId(dex="", coin="BLUR"))
    assert denied is False and value is None
    assert observed == []
    snapshot = client.rest_budget_snapshot()
    assert snapshot is not None
    assert snapshot["total_rolling_weight"] == 700
    assert snapshot["other_rolling_weight"] == 700
    assert snapshot["shadow_rolling_weight"] == 0
    assert snapshot["shadow_denied_lifetime"] == 1


def test_shadow_summary_exposes_only_local_reader_budget_not_external_ip(
) -> None:
    budget = RollingRateBudget(limit=1000)
    reader = InfoClient(Settings(), budget=budget, transport=lambda *args: {})
    shadow = RestDepthShadow(
        reader,
        config=RestShadowConfig(enabled=True),
        start_ns=time.monotonic_ns(),
    )
    report = shadow.summary(now_ns=time.monotonic_ns())
    local = report["same_reader_rest_budget_snapshot"]
    assert isinstance(local, dict)
    assert local["rolling_weight_limit"] == 1000
    assert local["external_process_ip_weight_verified"] is False
    assert local["source_or_execution_authority"] is False
    assert report["execution_authority"] is False
    assert report["other_process_ip_weight_verified"] is False


def test_invalid_local_budget_origin_rejected_before_any_reservation() -> None:
    budget = RollingRateBudget(limit=50)
    with pytest.raises(ValueError, match="origin"):
        budget.try_acquire(2, origin="required")
    assert budget.snapshot()["total_rolling_weight"] == 0
