from __future__ import annotations

import pytest

from cocomelon.research.full_depth_cadence_probe import (
    DEFAULT_MARKETS,
    FullDepthCadenceProbe,
)


def book(
    *, coin: str = "BLUR", exchange_ms: int = 1_000,
    levels: int = 20,
) -> dict[str, object]:
    side = [
        {"px": str(100 + i), "sz": "1.5", "n": 1}
        for i in range(levels)
    ]
    return {
        "channel": "l2Book",
        "data": {"coin": coin, "time": exchange_ms, "levels": [side, side]},
    }


def test_probe_measures_elapsed_freshness_without_counting_missing_time() -> None:
    start = 5_000_000_000
    probe = FullDepthCadenceProbe(("BLUR", "BOME"), start_ns=start)
    r1 = probe.ingest(
        book(exchange_ms=500),
        receive_utc_ms=1_000,
        monotonic_ns=start + 1_000_000_000,
    )
    r2 = probe.ingest(
        book(exchange_ms=8_900),
        receive_utc_ms=9_000,
        monotonic_ns=start + 9_000_000_000,
    )
    assert r1 is not None and r2 is not None
    assert r1["result"] == "unique"
    assert r1["raw_message_sha256"] is not None
    assert r2["interval_ms"] == 8_000
    first = probe.summary(end_ns=start + 12_000_000_000)
    second = probe.summary(end_ns=start + 12_000_000_000)
    assert first == second  # summary is read-only; no double-counting
    a = first["markets"]
    assert isinstance(a, dict)
    blur = a["BLUR"]
    assert isinstance(blur, dict)
    assert blur["unique"] == 2
    assert blur["interval_samples"] == 1
    assert blur["interval_ge_3000"] == 1
    assert blur["interval_ge_5000"] == 1
    assert blur["interval_ge_8000"] == 1
    assert blur["both_sides_20_levels"] == 2
    # 3s freshness: 2.5s before gap, then 2.9s after second source event.
    assert blur["fresh_3s_time_fraction"] == 0.45
    # 5s freshness: 4.5s before gap, then 3s through sample end.
    assert blur["fresh_5s_time_fraction"] == 0.625
    bome = a["BOME"]
    assert isinstance(bome, dict)
    assert bome["fresh_3s_time_fraction"] == 0.0
    assert first["source_completeness_certified"] is False
    assert first["trading_authority"] is False


def test_duplicate_replay_does_not_refresh_freshness_or_interarrival() -> None:
    start = 2_000_000_000
    probe = FullDepthCadenceProbe(("BLUR",), start_ns=start)
    msg = book()
    first = probe.ingest(
        msg, receive_utc_ms=1_000, monotonic_ns=start
    )
    replay = probe.ingest(
        msg, receive_utc_ms=5_000, monotonic_ns=start + 4_000_000_000
    )
    assert first is not None and replay is not None
    assert replay["result"] == "duplicate"
    data = probe.summary(end_ns=start + 8_000_000_000)["markets"]
    assert isinstance(data, dict)
    blur = data["BLUR"]
    assert isinstance(blur, dict)
    assert blur["unique"] == 1
    assert blur["duplicates"] == 1
    assert blur["interval_samples"] == 0
    assert blur["fresh_3s_time_fraction"] == 0.375


def test_out_of_order_and_future_dated_sources_fail_closed() -> None:
    start = 10_000_000_000
    probe = FullDepthCadenceProbe(("BLUR",), start_ns=start)
    first = probe.ingest(
        book(exchange_ms=20_000),
        receive_utc_ms=19_000,
        monotonic_ns=start,
    )
    rollback = probe.ingest(
        book(exchange_ms=15_000),
        receive_utc_ms=24_000,
        monotonic_ns=start + 5_000_000_000,
    )
    assert first is not None and rollback is not None
    assert rollback["result"] == "out_of_order"
    summary = probe.summary(end_ns=start + 10_000_000_000)["markets"]
    assert isinstance(summary, dict)
    values = summary["BLUR"]
    assert isinstance(values, dict)
    assert values["unique"] == 1
    assert values["out_of_order"] == 1
    assert values["source_future_dated"] == 1
    assert values["fresh_3s_time_fraction"] == 0.0


def test_aged_on_arrival_never_becomes_eligible() -> None:
    start = 1_000_000_000
    probe = FullDepthCadenceProbe(("BLUR",), start_ns=start)
    assert probe.ingest(
        book(exchange_ms=1_000),
        receive_utc_ms=7_000,
        monotonic_ns=start,
    ) is not None
    values = probe.summary(end_ns=start + 5_000_000_000)["markets"]
    assert isinstance(values, dict)
    blur = values["BLUR"]
    assert isinstance(blur, dict)
    assert blur["source_age_ge_5000"] == 1
    assert blur["fresh_3s_time_fraction"] == 0.0
    assert blur["fresh_5s_time_fraction"] == 0.0


def test_ignore_non_l2_and_untracked_markets_without_widening_cohort() -> None:
    probe = FullDepthCadenceProbe(("BLUR",), start_ns=100)
    assert probe.ingest(
        {"channel": "subscriptionResponse", "data": {}},
        receive_utc_ms=0, monotonic_ns=100,
    ) is None
    assert probe.ingest(
        book(coin="BTC"), receive_utc_ms=1_000, monotonic_ns=101
    ) is None
    assert probe.ingest(
        {"channel": "l2Book", "data": {"coin": "BLUR", "time": "invalid"}},
        receive_utc_ms=1_000, monotonic_ns=102,
    ) is None
    result = probe.summary(end_ns=200)
    assert result["unique_books"] == 0
    assert result["untracked_messages"] == 1
    assert result["protocol_errors"] == 1


def test_probe_requires_frozen_public_cohort_and_monotonic_clock() -> None:
    assert len(DEFAULT_MARKETS) == 20
    assert len(set(DEFAULT_MARKETS)) == 20
    for markets in ((), ("BLUR", "BLUR"), ("",), tuple(str(i) for i in range(21))):
        with pytest.raises(ValueError):
            FullDepthCadenceProbe(markets, start_ns=100)
    probe = FullDepthCadenceProbe(("BLUR",), start_ns=100)
    with pytest.raises(ValueError):
        probe.ingest(book(), receive_utc_ms=1_000, monotonic_ns=99)
    with pytest.raises(ValueError):
        probe.summary(end_ns=99)


def test_default_probe_uses_public_full_depth_only() -> None:
    import inspect

    from cocomelon.research import full_depth_cadence_probe as module

    source = inspect.getsource(module.collect)
    assert "MAINNET_WS_URL" in source
    assert '"type": "l2Book"' in source
    assert '"fast": True' not in source
    assert "place_order" not in source
    assert "submit_order" not in source
    assert "execution" not in source
