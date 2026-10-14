from __future__ import annotations

from collections.abc import Mapping

import pytest

from cocomelon.research.full_depth_cadence_probe import (
    DEFAULT_MARKETS,
    FullDepthCadenceProbe,
)
from cocomelon.research.simultaneous_public_l2_control import (
    FAST_SCHEMA,
    FastL2Control,
    compare_control,
    fast_control_subscription,
)


def book(*, market: str, exchange_ms: int, depth: int) -> dict[str, object]:
    return {
        "channel": "l2Book",
        "data": {
            "coin": market,
            "time": exchange_ms,
            "levels": [
                [
                    {"px": str(100 - level), "sz": "2", "n": 1}
                    for level in range(depth)
                ],
                [
                    {"px": str(101 + level), "sz": "2", "n": 1}
                    for level in range(depth)
                ],
            ],
        },
    }


def synthetic_pair(
    *, fast_interval_ms: int = 1_000,
    fast_depth: int = 5,
    full_depth: int = 20,
) -> tuple[dict[str, object], dict[str, object]]:
    start_ns = 100_000_000_000
    start_utc_ms = 1_800_000_000_000
    full = FullDepthCadenceProbe(DEFAULT_MARKETS, start_ns=start_ns)
    fast = FastL2Control(DEFAULT_MARKETS, start_ns=start_ns)
    for market in DEFAULT_MARKETS:
        for elapsed_ms in range(0, 180_001, 6_000):
            assert full.ingest(
                book(
                    market=market,
                    exchange_ms=start_utc_ms + elapsed_ms - 300,
                    depth=full_depth,
                ),
                receive_utc_ms=start_utc_ms + elapsed_ms,
                monotonic_ns=start_ns + elapsed_ms * 1_000_000,
            ) is not None
        for elapsed_ms in range(0, 180_001, fast_interval_ms):
            assert fast.ingest(
                book(
                    market=market,
                    exchange_ms=start_utc_ms + elapsed_ms - 300,
                    depth=fast_depth,
                ),
                receive_utc_ms=start_utc_ms + elapsed_ms,
                monotonic_ns=start_ns + elapsed_ms * 1_000_000,
            ) is not None
    deep = full.summary(end_ns=start_ns + 180_001_000_000)
    control = fast.summary(end_ns=start_ns + 180_001_000_000)
    deep["connections"] = 1
    control["connections"] = 1
    deep["observation_window_completed"] = True
    control["observation_window_completed"] = True
    return deep, control


def test_fast_subscription_is_public_and_never_used_by_trading_protocol() -> None:
    assert fast_control_subscription("BLUR") == {
        "method": "subscribe",
        "subscription": {"type": "l2Book", "coin": "BLUR", "fast": True},
    }
    with pytest.raises(ValueError, match="frozen"):
        fast_control_subscription("BTC")
    with pytest.raises(ValueError, match="cohort"):
        FastL2Control(("BLUR",), start_ns=1)


def test_control_receipts_mark_all_depth_as_nontrading() -> None:
    fast = FastL2Control(DEFAULT_MARKETS, start_ns=1_000)
    receipt = fast.ingest(
        book(market="BLUR", exchange_ms=2_000, depth=5),
        receive_utc_ms=2_200,
        monotonic_ns=1_000,
    )
    assert receipt is not None
    assert receipt["schema"] == FAST_SCHEMA
    assert receipt["bid_levels"] == 5
    assert receipt["ask_levels"] == 5
    assert receipt["full_depth_20x20_eligible"] is False
    assert receipt["trading_authority"] is False
    report = fast.summary(end_ns=5_000_000_000)
    assert report["full_depth_20x20_eligible"] is False
    assert report["source_completeness_certified"] is False
    assert report["trading_authority"] is False
    assert report["after_cost_profit_verified"] is False


def test_simultaneous_control_is_faster_but_never_source_swappable() -> None:
    deep, fast = synthetic_pair()
    report = compare_control(deep, fast)
    assert report["diagnostic_comparison_valid"] is True
    blur = report["markets"]["BLUR"]
    assert blur["default_20x20_unique_books"] == 31
    assert blur["fast_control_unique_books"] == 181
    assert blur["default_20x20_depth_observed"] is True
    assert blur["fast_control_max_levels_each_side"] == [5, 5]
    assert blur["control_minus_full_age_fraction"] > 0.3
    for field in (
        "full_depth_source_swap_authorized", "five_level_execution_authorized",
        "signed_market_evidence_changed", "live_trading_authorized",
        "profitability_verified",
    ):
        assert report[field] is False
    assert all(
        values["fast_control_20x20_eligible"] is False
        for values in report["markets"].values()
    )


def test_slow_fast_control_still_valid_as_diagnostic_not_edge() -> None:
    deep, fast = synthetic_pair(fast_interval_ms=6_000)
    report = compare_control(deep, fast)
    assert report["diagnostic_comparison_valid"] is True
    assert report["markets"]["BLUR"]["control_minus_full_age_fraction"] == 0
    assert report["five_level_execution_authorized"] is False


def test_fast_control_vendor_ignores_fast_flag_must_fail_diagnostic() -> None:
    deep, fast = synthetic_pair(fast_depth=20)
    report = compare_control(deep, fast)
    assert fast["unexpected_more_than_5_levels_count"] > 0
    assert report["diagnostic_comparison_valid"] is False
    assert report["five_level_execution_authorized"] is False


def test_incomplete_full_20_by_20_depth_fails_even_if_fast_good() -> None:
    deep, fast = synthetic_pair(full_depth=5)
    report = compare_control(deep, fast)
    assert report["diagnostic_comparison_valid"] is False
    assert report["full_depth_source_swap_authorized"] is False


def test_reconnect_or_protocol_error_fails_clean_paired_comparison() -> None:
    deep, fast = synthetic_pair()
    deep["connections"] = 2
    assert compare_control(deep, fast)["diagnostic_comparison_valid"] is False
    deep["connections"] = 1
    fast["protocol_errors"] = 1
    assert compare_control(deep, fast)["diagnostic_comparison_valid"] is False
    fast["protocol_errors"] = 0
    fast["observation_window_completed"] = False
    assert compare_control(deep, fast)["diagnostic_comparison_valid"] is False


def test_duplicate_control_receipt_does_not_refresh_freshness() -> None:
    fast = FastL2Control(DEFAULT_MARKETS, start_ns=1_000)
    msg = book(market="BLUR", exchange_ms=1_000, depth=5)
    first = fast.ingest(msg, receive_utc_ms=1_200, monotonic_ns=1_000)
    replay = fast.ingest(
        msg,
        receive_utc_ms=5_000,
        monotonic_ns=4_000_001_000,
    )
    assert first is not None and replay is not None
    assert replay["result"] == "duplicate"
    summary = fast.summary(end_ns=8_000_001_000)
    rows = summary["markets"]
    assert isinstance(rows, dict)
    blur = rows["BLUR"]
    assert isinstance(blur, Mapping)
    assert blur["unique"] == 1
    assert blur["duplicates"] == 1
    assert blur["control_source_age_under_3s_fraction"] < 0.4


def test_missing_coin_cannot_be_diagnostic_complete() -> None:
    deep, fast = synthetic_pair()
    markets = fast["markets"]
    assert isinstance(markets, dict)
    markets["BLUR"]["unique"] = 0
    assert compare_control(deep, fast)["diagnostic_comparison_valid"] is False
