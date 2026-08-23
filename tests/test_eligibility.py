import importlib
from decimal import Decimal

import pytest

from cocomelon.domain.features import FeatureSnapshot, TrendRegime, VolatilityRegime
from cocomelon.domain.market import (
    MarketId,
    PerpMarketContext,
    PerpMarketMeta,
    PerpMarketSnapshot,
)

eligibility_module = importlib.import_module("cocomelon.scanner.eligibility")
EligibilityConfig = eligibility_module.EligibilityConfig
derive_eligibility_thresholds = eligibility_module.derive_eligibility_thresholds
evaluate_eligibility = eligibility_module.evaluate_eligibility

BTC = MarketId("", "BTC")


def _market_snapshot(
    *,
    market: MarketId = BTC,
    received_at_ms: int = 950,
    is_delisted: bool = False,
    max_leverage: int = 20,
    mark_px: Decimal | None = Decimal("100"),
    mid_px: Decimal | None = Decimal("100"),
    oracle_px: Decimal | None = Decimal("100"),
    prev_day_px: Decimal = Decimal("99"),
    volume: Decimal = Decimal("1000000"),
    open_interest: Decimal = Decimal("1000"),
) -> PerpMarketSnapshot:
    return PerpMarketSnapshot(
        meta=PerpMarketMeta(
            market=market,
            wire_name=market.wire_name,
            sz_decimals=4,
            max_leverage=max_leverage,
            margin_table_id=None,
            only_isolated=False,
            is_delisted=is_delisted,
            margin_mode=None,
        ),
        context=PerpMarketContext(
            market=market,
            mark_px=mark_px,
            mid_px=mid_px,
            oracle_px=oracle_px,
            funding=Decimal("0.0001"),
            open_interest=open_interest,
            day_ntl_vlm=volume,
            premium=None,
            prev_day_px=prev_day_px,
        ),
        source="hyperliquid-mainnet-info",
        received_at_ms=received_at_ms,
        schema_version=1,
    )


def _features(
    *,
    market: MarketId = BTC,
    as_of_ms: int = 1_000,
    volume: Decimal = Decimal("1000000"),
    open_interest: Decimal = Decimal("1000"),
    spread_bps: Decimal | None = None,
    bid_depth: Decimal | None = None,
    ask_depth: Decimal | None = None,
    book_age_ms: int | None = None,
) -> FeatureSnapshot:
    return FeatureSnapshot(
        market=market,
        as_of_ms=as_of_ms,
        source_received_at_ms=950,
        schema_version=1,
        day_return=Decimal("0.01"),
        funding=Decimal("0.0001"),
        open_interest=open_interest,
        day_notional_volume=volume,
        oi_change_fraction=None,
        funding_change=None,
        mark_oracle_dislocation_bps=Decimal("1"),
        return_5m=Decimal("0.01"),
        return_15m=Decimal("0.01"),
        return_1h=Decimal("0.01"),
        return_4h=Decimal("0.01"),
        realized_vol_15m=Decimal("0.01"),
        range_expansion_15m=Decimal("1"),
        relative_volume_15m=Decimal("1"),
        spread_bps=spread_bps,
        bid_depth_25bps=bid_depth,
        ask_depth_25bps=ask_depth,
        book_imbalance=None,
        book_age_ms=book_age_ms,
        trend_regime=TrendRegime.UP,
        volatility_regime=VolatilityRegime.NORMAL,
        provenance=("hyperliquid-mainnet-info",),
    )


def test_thresholds_use_observed_cross_section_and_hard_caps() -> None:
    peers = tuple(
        _features(
            market=MarketId("", f"M{index}"),
            volume=Decimal(index * 100),
            open_interest=Decimal(index * 10),
            spread_bps=Decimal(index),
            bid_depth=Decimal(index * 1000),
            ask_depth=Decimal(index * 900),
        )
        for index in range(1, 11)
    )
    config = EligibilityConfig(hard_max_spread_bps=Decimal("8.5"))

    thresholds = derive_eligibility_thresholds(peers, config)

    assert thresholds.min_day_notional_volume == Decimal("190")
    assert thresholds.min_open_interest == Decimal("19")
    assert thresholds.max_spread_bps == Decimal("8.5")
    assert thresholds.min_side_depth == Decimal("1710")


def test_thresholds_fall_back_to_absolute_deep_limits_with_few_books() -> None:
    peers = (
        _features(spread_bps=Decimal("5"), bid_depth=Decimal("100"), ask_depth=Decimal("90")),
        _features(
            market=MarketId("", "ETH"),
            spread_bps=None,
            bid_depth=None,
            ask_depth=None,
        ),
    )
    config = EligibilityConfig(
        hard_max_spread_bps=Decimal("50"),
        absolute_min_side_depth=Decimal("25"),
    )

    thresholds = derive_eligibility_thresholds(peers, config)

    assert thresholds.max_spread_bps == Decimal("50")
    assert thresholds.min_side_depth == Decimal("25")


@pytest.mark.parametrize(
    ("market_snapshot", "expected_reason"),
    [
        (_market_snapshot(is_delisted=True), "delisted"),
        (_market_snapshot(mark_px=None), "invalid_price_state"),
        (_market_snapshot(mid_px=Decimal("0")), "invalid_price_state"),
        (_market_snapshot(oracle_px=Decimal("-1")), "invalid_price_state"),
        (_market_snapshot(prev_day_px=Decimal("0")), "invalid_price_state"),
        (_market_snapshot(max_leverage=0), "unsupported_leverage"),
        (_market_snapshot(received_at_ms=0), "stale_context"),
        (_market_snapshot(received_at_ms=1_001), "stale_context"),
    ],
)
def test_coarse_eligibility_fails_closed(
    market_snapshot: PerpMarketSnapshot,
    expected_reason: str,
) -> None:
    config = EligibilityConfig(max_context_age_ms=100)
    thresholds = derive_eligibility_thresholds((_features(),), config)

    decision = evaluate_eligibility(
        market_snapshot,
        _features(),
        thresholds,
        config,
    )

    assert decision.rankable is False
    assert decision.deep_ready is False
    assert expected_reason in decision.reasons


def test_coarse_eligibility_enforces_observed_volume_and_oi_floors() -> None:
    peers = tuple(
        _features(
            market=MarketId("", f"P{index}"),
            volume=Decimal(1000 + index * 100),
            open_interest=Decimal(100 + index * 10),
        )
        for index in range(5)
    )
    config = EligibilityConfig()
    thresholds = derive_eligibility_thresholds(peers, config)
    features = _features(volume=Decimal("1"), open_interest=Decimal("1"))

    decision = evaluate_eligibility(_market_snapshot(), features, thresholds, config)

    assert decision.rankable is False
    assert "below_volume_floor" in decision.reasons
    assert "below_oi_floor" in decision.reasons


def test_missing_l2_keeps_market_rankable_but_not_deep_ready() -> None:
    config = EligibilityConfig()
    features = _features()
    thresholds = derive_eligibility_thresholds((features,), config)

    decision = evaluate_eligibility(_market_snapshot(), features, thresholds, config)

    assert decision.rankable is True
    assert decision.deep_ready is False
    assert decision.reasons == ("missing_deep_data",)


@pytest.mark.parametrize(
    ("features", "expected_reason"),
    [
        (
            _features(
                spread_bps=Decimal("5"),
                bid_depth=Decimal("1000"),
                ask_depth=Decimal("1000"),
                book_age_ms=5_001,
            ),
            "stale_book",
        ),
        (
            _features(
                spread_bps=Decimal("51"),
                bid_depth=Decimal("1000"),
                ask_depth=Decimal("1000"),
                book_age_ms=100,
            ),
            "excessive_spread",
        ),
        (
            _features(
                spread_bps=Decimal("5"),
                bid_depth=Decimal("10"),
                ask_depth=Decimal("1000"),
                book_age_ms=100,
            ),
            "insufficient_depth",
        ),
    ],
)
def test_deep_readiness_fails_on_book_quality(
    features: FeatureSnapshot,
    expected_reason: str,
) -> None:
    config = EligibilityConfig(absolute_min_side_depth=Decimal("100"))
    thresholds = derive_eligibility_thresholds((features,), config)

    decision = evaluate_eligibility(_market_snapshot(), features, thresholds, config)

    assert decision.rankable is True
    assert decision.deep_ready is False
    assert expected_reason in decision.reasons


def test_deep_readiness_passes_when_coarse_and_book_quality_pass() -> None:
    config = EligibilityConfig(absolute_min_side_depth=Decimal("100"))
    features = _features(
        spread_bps=Decimal("5"),
        bid_depth=Decimal("1000"),
        ask_depth=Decimal("900"),
        book_age_ms=100,
    )
    thresholds = derive_eligibility_thresholds((features,), config)

    decision = evaluate_eligibility(_market_snapshot(), features, thresholds, config)

    assert decision.rankable is True
    assert decision.deep_ready is True
    assert decision.reasons == ()
