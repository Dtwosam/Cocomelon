from dataclasses import replace
from decimal import Decimal

from cocomelon.domain.features import (
    EligibilityDecision,
    FeatureSnapshot,
    TrendRegime,
    VolatilityRegime,
)
from cocomelon.domain.market import (
    Candle,
    MarketId,
    PerpMarketContext,
    PerpMarketMeta,
    PerpMarketSnapshot,
)
from cocomelon.domain.strategy import Direction, StrategyContext, StrategyRole
from cocomelon.strategies.trend import evaluate_trend


def _feature(**overrides: object) -> FeatureSnapshot:
    snapshot = FeatureSnapshot(
        market=MarketId("", "BTC"),
        as_of_ms=10_000,
        source_received_at_ms=9_000,
        schema_version=1,
        day_return=Decimal("0.02"),
        funding=Decimal("0"),
        open_interest=Decimal("1000"),
        day_notional_volume=Decimal("1000000"),
        oi_change_fraction=Decimal("0.01"),
        funding_change=None,
        mark_oracle_dislocation_bps=None,
        return_5m=None,
        return_15m=Decimal("0.01"),
        return_1h=Decimal("0.02"),
        return_4h=None,
        realized_vol_15m=Decimal("0.005"),
        range_expansion_15m=Decimal("1"),
        relative_volume_15m=None,
        spread_bps=Decimal("2"),
        bid_depth_25bps=Decimal("100000"),
        ask_depth_25bps=Decimal("100000"),
        book_imbalance=None,
        book_age_ms=100,
        trend_regime=TrendRegime.UP,
        volatility_regime=VolatilityRegime.NORMAL,
        provenance=("test",),
    )
    return replace(snapshot, **overrides)


def _market_snapshot() -> PerpMarketSnapshot:
    market = MarketId("", "BTC")
    return PerpMarketSnapshot(
        meta=PerpMarketMeta(
            market=market,
            wire_name="BTC",
            sz_decimals=5,
            max_leverage=40,
            margin_table_id=1,
            only_isolated=False,
            is_delisted=False,
            margin_mode=None,
        ),
        context=PerpMarketContext(
            market=market,
            mark_px=Decimal("100"),
            mid_px=Decimal("100.5"),
            oracle_px=Decimal("100"),
            funding=Decimal("0"),
            open_interest=Decimal("1000"),
            day_ntl_vlm=Decimal("1000000"),
            premium=Decimal("0"),
            prev_day_px=Decimal("99"),
        ),
        source="test",
        received_at_ms=9_000,
        schema_version=1,
    )


def _candles(*, low: str = "97", high: str = "103") -> tuple[Candle, ...]:
    return tuple(
        Candle(
            market=MarketId("", "BTC"),
            interval="15m",
            start_ms=i * 1_000,
            end_ms=(i + 1) * 1_000,
            open_px=Decimal("100"),
            high_px=Decimal(high),
            low_px=Decimal(low),
            close_px=Decimal("101"),
            volume=Decimal("100"),
            trade_count=10,
            source="test",
            received_at_ms=(i + 1) * 1_000,
            schema_version=1,
        )
        for i in range(4)
    )


def _context(
    *,
    feature: FeatureSnapshot | None = None,
    candles: tuple[Candle, ...] | None = None,
    rankable: bool = True,
    deep_ready: bool = True,
) -> StrategyContext:
    selected_feature = _feature() if feature is None else feature
    return StrategyContext(
        market_snapshot=_market_snapshot(),
        feature_snapshot=selected_feature,
        eligibility=EligibilityDecision(
            market=selected_feature.market,
            rankable=rankable,
            deep_ready=deep_ready,
            reasons=(),
        ),
        candles_5m=(),
        candles_15m=_candles() if candles is None else candles,
        microstructure=None,
        as_of_ms=10_000,
    )


def test_aligned_uptrend_emits_long_with_exact_full_score() -> None:
    feature = _feature(
        return_5m=Decimal("0.005"),
        return_4h=Decimal("0.03"),
        relative_volume_15m=Decimal("1.2"),
        book_imbalance=Decimal("0.2"),
    )
    signal = evaluate_trend(_context(feature=feature))

    assert signal.role is StrategyRole.PRIMARY
    assert signal.direction is Direction.LONG
    assert signal.score == Decimal("90")
    assert signal.invalidation_price == Decimal("97")
    assert signal.feature_snapshot_id == feature.snapshot_id


def test_aligned_downtrend_emits_short_at_base_threshold() -> None:
    feature = _feature(
        trend_regime=TrendRegime.DOWN,
        return_15m=Decimal("-0.01"),
        return_1h=Decimal("-0.02"),
    )
    signal = evaluate_trend(_context(feature=feature))

    assert signal.direction is Direction.SHORT
    assert signal.score == Decimal("65")
    assert signal.invalidation_price == Decimal("103")


def test_opposing_primary_returns_block_directional_trend() -> None:
    feature = _feature(return_1h=Decimal("-0.02"))
    signal = evaluate_trend(_context(feature=feature))

    assert signal.direction is Direction.NO_TRADE
    assert "return_1h_opposes" in signal.reason_codes


def test_optional_trend_features_add_only_documented_points() -> None:
    base = evaluate_trend(_context(feature=_feature()))
    full = evaluate_trend(
        _context(
            feature=_feature(
                return_5m=Decimal("0.001"),
                return_4h=Decimal("0.02"),
                relative_volume_15m=Decimal("1"),
                book_imbalance=Decimal("0.1"),
            )
        )
    )
    assert base.score == Decimal("65")
    assert full.score == Decimal("90")


def test_insufficient_candles_or_deep_readiness_returns_no_trade() -> None:
    short_history = _candles()[:3]
    assert evaluate_trend(_context(candles=short_history)).direction is Direction.NO_TRADE
    assert evaluate_trend(_context(deep_ready=False)).direction is Direction.NO_TRADE


def test_wrong_side_trend_invalidation_fails_closed() -> None:
    signal = evaluate_trend(_context(candles=_candles(low="101", high="110")))
    assert signal.direction is Direction.NO_TRADE
    assert "invalid_invalidation" in signal.reason_codes
