from __future__ import annotations

from decimal import Decimal

import pytest

from cocomelon.domain.features import (
    FeatureSnapshot,
    TrendRegime,
    VolatilityRegime,
)
from cocomelon.domain.market import MarketId
from cocomelon.features.cross_market import (
    CrossMarketFeatureError,
    basket_breadth_bucket,
    basket_direction_bucket,
    build_cross_market_contexts,
    relative_strength_bucket,
)

BTC = MarketId("", "BTC")
ETH = MarketId("", "ETH")
SOL = MarketId("", "SOL")
HYPE = MarketId("", "HYPE")


def _snapshot(
    market: MarketId,
    *,
    as_of_ms: int = 10_000,
    received_at_ms: int = 9_000,
    return_5m: str | None = None,
    return_15m: str | None = None,
    return_1h: str | None = None,
    return_4h: str | None = None,
    source: str = "hyperliquid-mainnet-info",
) -> FeatureSnapshot:
    return FeatureSnapshot(
        market=market,
        as_of_ms=as_of_ms,
        source_received_at_ms=received_at_ms,
        schema_version=1,
        day_return=Decimal("0"),
        funding=Decimal("0"),
        open_interest=Decimal("100"),
        day_notional_volume=Decimal("1000000"),
        oi_change_fraction=None,
        funding_change=None,
        mark_oracle_dislocation_bps=None,
        return_5m=None if return_5m is None else Decimal(return_5m),
        return_15m=None if return_15m is None else Decimal(return_15m),
        return_1h=None if return_1h is None else Decimal(return_1h),
        return_4h=None if return_4h is None else Decimal(return_4h),
        realized_vol_15m=None,
        range_expansion_15m=None,
        relative_volume_15m=None,
        spread_bps=None,
        bid_depth_25bps=None,
        ask_depth_25bps=None,
        book_imbalance=None,
        book_age_ms=None,
        trend_regime=TrendRegime.UNKNOWN,
        volatility_regime=VolatilityRegime.UNKNOWN,
        provenance=(source,),
    )


def test_live_cross_market_math_matches_historical_semantics() -> None:
    snapshots = (
        _snapshot(
            BTC,
            return_5m="0.02",
            return_15m="0.03",
            return_1h="0.04",
            return_4h="0.05",
            source="btc",
        ),
        _snapshot(
            ETH,
            return_5m="-0.01",
            return_15m="0",
            return_1h="0.02",
            return_4h="0.01",
            source="eth",
            received_at_ms=9_500,
        ),
        _snapshot(
            SOL,
            return_5m="0.04",
            return_15m="0.06",
            return_1h="0.08",
            return_4h="0.10",
            source="sol",
        ),
    )

    contexts = build_cross_market_contexts(snapshots)
    sol = next(item for item in contexts if item.market == SOL)
    five = sol.for_window("5m")

    assert five.btc_return == Decimal("0.02")
    assert five.eth_return == Decimal("-0.01")
    assert five.basket_median_return == Decimal("0.02")
    assert five.basket_breadth_positive == Decimal("2") / Decimal("3")
    assert five.relative_return_vs_basket == Decimal("0.02")
    assert five.basket_return_count == Decimal("3")
    observed = (Decimal("0.02"), Decimal("-0.01"), Decimal("0.04"))
    mean = sum(observed, Decimal("0")) / Decimal("3")
    dispersion = (
        sum(((value - mean) ** 2 for value in observed), Decimal("0"))
        / Decimal("3")
    ).sqrt()
    assert five.basket_return_dispersion == dispersion
    assert five.relative_return_zscore_vs_basket == Decimal("0.02") / dispersion
    assert sol.for_window("1h").basket_median_return == Decimal("0.04")
    assert sol.for_window("4h").relative_return_vs_basket == Decimal("0.05")
    assert sol.source_received_at_ms == 9_500
    assert sol.provenance == ("btc", "eth", "sol")


def test_live_hype_context_reproduces_discovered_bucket_definition() -> None:
    contexts = build_cross_market_contexts(
        (
            _snapshot(BTC, return_1h="-0.02"),
            _snapshot(ETH, return_1h="-0.01"),
            _snapshot(SOL, return_1h="-0.03"),
            _snapshot(HYPE, return_1h="-0.015"),
        )
    )

    hype = next(item for item in contexts if item.market == HYPE).for_window("1h")

    assert hype.basket_median_return == Decimal("-0.0175")
    assert hype.basket_breadth_positive == Decimal("0")
    assert hype.context_state == "down/bearish/near_basket"


def test_live_cross_market_context_is_deterministic_under_input_reordering() -> None:
    snapshots = (
        _snapshot(BTC, return_1h="0.01", source="btc"),
        _snapshot(ETH, return_1h="-0.01", source="eth"),
        _snapshot(HYPE, return_1h="0", source="hype"),
    )

    first = build_cross_market_contexts(snapshots)
    second = build_cross_market_contexts(tuple(reversed(snapshots)))

    assert first == second
    assert [item.snapshot_id for item in first] == [
        item.snapshot_id for item in second
    ]


def test_live_cross_market_context_rejects_mixed_anchor_times() -> None:
    with pytest.raises(CrossMarketFeatureError, match="MIXED_AS_OF_MS"):
        build_cross_market_contexts(
            (
                _snapshot(BTC, as_of_ms=10_000, return_1h="0.01"),
                _snapshot(ETH, as_of_ms=11_000, return_1h="0.02"),
            )
        )


def test_live_cross_market_context_rejects_duplicate_market() -> None:
    with pytest.raises(CrossMarketFeatureError, match="DUPLICATE_MARKET"):
        build_cross_market_contexts(
            (
                _snapshot(BTC, return_1h="0.01"),
                _snapshot(BTC, return_1h="0.02"),
            )
        )


def test_sparse_live_context_matches_historical_missing_semantics() -> None:
    contexts = build_cross_market_contexts(
        (_snapshot(SOL, return_1h="0.08"),)
    )
    one_hour = contexts[0].for_window("1h")

    assert one_hour.btc_return is None
    assert one_hour.eth_return is None
    assert one_hour.basket_return_count == Decimal("1")
    assert one_hour.basket_median_return is None
    assert one_hour.basket_breadth_positive is None
    assert one_hour.relative_return_vs_basket is None
    assert one_hour.basket_return_dispersion is None
    assert one_hour.relative_return_zscore_vs_basket is None
    assert one_hour.context_state == "missing/missing/missing"


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        (None, "missing"),
        (Decimal("-0.01"), "down"),
        (Decimal("0"), "flat"),
        (Decimal("0.01"), "up"),
    ),
)
def test_direction_bucket_contract(value: Decimal | None, expected: str) -> None:
    assert basket_direction_bucket(value) == expected


def test_breadth_and_relative_strength_bucket_boundaries_are_frozen() -> None:
    assert basket_breadth_bucket(Decimal("0.25")) == "bearish"
    assert basket_breadth_bucket(Decimal("0.75")) == "bullish"
    assert basket_breadth_bucket(Decimal("0.5")) == "mixed"
    assert relative_strength_bucket(Decimal("-1")) == "lagging_1sd"
    assert relative_strength_bucket(Decimal("1")) == "leading_1sd"
    assert relative_strength_bucket(Decimal("0")) == "near_basket"
