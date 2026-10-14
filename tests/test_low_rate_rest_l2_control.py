from __future__ import annotations

import json

import pytest

from cocomelon.research.full_depth_cadence_probe import FullDepthCadenceProbe
from cocomelon.research.low_rate_rest_l2_control import (
    COHORT,
    POLL_INTERVAL_MS,
    REQUEST_WEIGHT,
    SCHEMA,
    URL,
    WEIGHT_BUDGET_PER_MINUTE,
    RestFullDepthControl,
    compare_rest_vs_ws,
    duration_request_limit,
    public_l2_request,
)


def rest_book(market: str, time_ms: int, *, depth: int = 20) -> dict[str, object]:
    return {
        "coin": market,
        "time": time_ms,
        "levels": [
            [
                {"px": str(100 - i), "sz": "2", "n": 1}
                for i in range(depth)
            ],
            [
                {"px": str(101 + i), "sz": "2", "n": 1}
                for i in range(depth)
            ],
        ],
    }


def synthetic() -> tuple[dict[str, object], dict[str, object]]:
    begin = 10_000_000_000
    base_utc = 1_800_000_000_000
    rest = RestFullDepthControl(start_ns=begin)
    ws = FullDepthCadenceProbe(COHORT, start_ns=begin)
    for coin in COHORT:
        for elapsed_ms in range(0, 180_001, 1_000):
            rest.request_count += 1
            receipt = rest.observe(
                coin,
                rest_book(coin, base_utc + elapsed_ms - 300),
                monotonic_ns=begin + elapsed_ms * 1_000_000,
                receive_utc_ms=base_utc + elapsed_ms,
                request_latency_ms=110,
            )
            assert receipt is not None
        for elapsed_ms in range(0, 180_001, 6_000):
            receipt = ws.ingest(
                {"channel": "l2Book", "data": rest_book(
                    coin, base_utc + elapsed_ms - 300
                )},
                monotonic_ns=begin + elapsed_ms * 1_000_000,
                receive_utc_ms=base_utc + elapsed_ms,
            )
            assert receipt is not None
    rest_report = rest.summary(end_ns=begin + 180_001_000_000)
    ws_report = ws.summary(end_ns=begin + 180_001_000_000)
    rest_report["observation_window_completed"] = True
    ws_report["observation_window_completed"] = True
    ws_report["connections"] = 1
    return rest_report, ws_report


def test_rest_requests_are_only_anonymous_three_coin_info_posts() -> None:
    assert len(COHORT) == 3
    assert REQUEST_WEIGHT == 2
    assert POLL_INTERVAL_MS == 1_000
    assert WEIGHT_BUDGET_PER_MINUTE == 360
    assert duration_request_limit(180_000) == 543
    for coin in COHORT:
        req = public_l2_request(coin)
        assert req.full_url == URL
        assert req.get_method() == "POST"
        assert json.loads(req.data or b"{}") == {"type": "l2Book", "coin": coin}
        assert "Authorization" not in req.headers
    with pytest.raises(ValueError):
        public_l2_request("BTC")


def test_rest_probe_does_not_convert_replays_to_new_depth_evidence() -> None:
    control = RestFullDepthControl(start_ns=1_000)
    book = rest_book("BLUR", 10_000)
    first = control.observe(
        "BLUR", book, monotonic_ns=1_000,
        receive_utc_ms=10_100, request_latency_ms=80,
    )
    second = control.observe(
        "BLUR", book, monotonic_ns=6_000_001_000,
        receive_utc_ms=16_100, request_latency_ms=80,
    )
    assert first is not None and second is not None
    assert first["schema"] == SCHEMA
    assert first["full_depth_20x20_observed"] is True
    assert first["production_trading_authorized"] is False
    assert second["result"] == "duplicate"
    out = control.summary(end_ns=8_000_001_000)
    rows = out["markets"]
    assert isinstance(rows, dict)
    assert rows["BLUR"]["unique"] == 1
    assert rows["BLUR"]["duplicates"] == 1
    assert out["production_trading_authorized"] is False
    assert out["source_completeness_certified"] is False


def test_mismatched_market_and_empty_book_are_not_invented() -> None:
    control = RestFullDepthControl(start_ns=100)
    assert control.observe(
        "BLUR", rest_book("BOME", 1_000),
        monotonic_ns=100, receive_utc_ms=1_000, request_latency_ms=5
    ) is None
    assert control.invalid_response_count == 1
    invalid = rest_book("BLUR", 2_000)
    invalid["levels"] = [[], []]
    assert control.observe(
        "BLUR", invalid,
        monotonic_ns=200, receive_utc_ms=2_000, request_latency_ms=5,
    ) is not None
    row = control.summary(end_ns=1_000_000_100)["markets"]
    assert isinstance(row, dict)
    assert row["BLUR"]["both_sides_20_levels"] == 0


def test_fast_enough_rest_20x20_control_is_still_not_trading_authorized() -> None:
    rest, ws = synthetic()
    out = compare_rest_vs_ws(rest, ws)
    assert out["valid_diagnostic"] is True
    assert rest["http_requests"] == 3 * 181
    assert out["rest_rate_weight_cap_per_minute"] == 360
    blur = out["markets"]["BLUR"]
    assert blur["rest_distinct_20x20_books"] == 181
    assert blur["ws_distinct_20x20_books"] == 31
    assert blur["rest_3s_fresh_time"] > blur["ws_3s_fresh_time"]
    assert blur["rest_full_depth_observed"] is True
    for flag in (
        "production_source_switch_authorized",
        "gap_history_repaired",
        "paper_order_or_account_changed",
        "live_execution_authorized",
        "after_cost_profit_verified",
    ):
        assert out[flag] is False


def test_rest_five_level_responses_disqualify_full_depth() -> None:
    rest, ws = synthetic()
    report = rest["markets"]
    assert isinstance(report, dict)
    report["BLUR"]["both_sides_20_levels"] = 0
    out = compare_rest_vs_ws(rest, ws)
    assert out["valid_diagnostic"] is False


def test_http_error_and_rate_overflow_fail_comparison() -> None:
    rest, ws = synthetic()
    rest["http_errors"] = 1
    assert compare_rest_vs_ws(rest, ws)["valid_diagnostic"] is False
    rest["http_errors"] = 0
    rest["http_429_count"] = 1
    assert compare_rest_vs_ws(rest, ws)["valid_diagnostic"] is False
    rest["http_429_count"] = 0
    rest["http_requests"] = 600
    assert compare_rest_vs_ws(rest, ws)["valid_diagnostic"] is False


def test_missing_or_disconnected_ws_source_fails_diagnostic() -> None:
    rest, ws = synthetic()
    ws["connection_errors"] = 1
    assert compare_rest_vs_ws(rest, ws)["valid_diagnostic"] is False
    ws["connection_errors"] = 0
    ws["observation_window_completed"] = False
    assert compare_rest_vs_ws(rest, ws)["valid_diagnostic"] is False


def test_noncohort_rejection_and_no_private_account_api() -> None:
    control = RestFullDepthControl(start_ns=100)
    with pytest.raises(ValueError):
        control.observe(
            "BTC", rest_book("BTC", 1_000),
            monotonic_ns=100, receive_utc_ms=1_000, request_latency_ms=50
        )
