from dataclasses import replace
from decimal import Decimal

from cocomelon.strategies.mean_reversion import evaluate_mean_reversion

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
from cocomelon.domain.strategy import Direction, StrategyContext


def _feature(**overrides: object) -> FeatureSnapshot:
    snapshot = FeatureSnapshot(
        market=MarketId("", "BTC"),
        as_of_ms=10_000,
        source_received_at_ms=9_000,
        schema_version=1,
        day_return=Decimal("0.01"),
        funding=Decimal("0"),
        open_interest=Decimal("1000"),
        day_notional_volume=Decimal("1000000"),
        oi_change_fraction=Decimal("0.01"),
        funding_change=None,
        mark_oracle_dislocation_bps=None,
        return_5m=None,
        return_15m=Decimal("0.0225"),
        return_1h=None,
        return_4h=None,
        realized_vol_15m=Decimal("0.01"),
        range_expansion_15m=Decimal("1"),
        relative_volume_15m=None,
        spread_bps=Decimal("2"),
        bid_depth_25bps=Decimal("100000"),
        ask_depth_25bps=Decimal("100000"),
        book_imbalance=Decimal("0"),
        book_age_ms=100,
        trend_regime=TrendRegime.MIXED,
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
            close_px=Decimal("100"),
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
    deep_ready: bool = True,
) -> StrategyContext:
    selected = _feature() if feature is None else feature
    return StrategyContext(
        market_snapshot=_market_snapshot(),
        feature_snapshot=selected,
        eligibility=EligibilityDecision(
            market=selected.market,
            rankable=True,
            deep_ready=deep_ready,
            reasons=(),
        ),
        candles_5m=(),
        candles_15m=_candles() if candles is None else candles,
        microstructure=None,
        as_of_ms=10_000,
    )


def test_positive_stretch_emits_short_at_exact_threshold() -> None:
    signal = evaluate_mean_reversion(_context())
    assert signal.direction is Direction.SHORT
    assert signal.score == Decimal("65")
    assert signal.invalidation_price == Decimal("103")


def test_negative_stretch_emits_long_at_exact_threshold() -> None:
    feature = _feature(return_15m=Decimal("-0.0225"))
    signal = evaluate_mean_reversion(_context(feature=feature))
    assert signal.direction is Direction.LONG
    assert signal.score == Decimal("65")
    assert signal.invalidation_price == Decimal("97")


def test_optional_reversion_evidence_reaches_full_score() -> None:
    feature = _feature(
        return_5m=Decimal("-0.002"),
        return_1h=Decimal("-0.01"),
        range_expansion_15m=Decimal("1.2"),
    )
    assert evaluate_mean_reversion(_context(feature=feature)).score == Decimal("100")


def test_moderate_stretch_needs_additional_confirmation() -> None:
    weak = _feature(return_15m=Decimal("0.018"))
    weak_signal = evaluate_mean_reversion(_context(feature=weak))
    assert weak_signal.direction is Direction.NO_TRADE
    assert weak_signal.score == Decimal("45")

    confirmed = _feature(
        return_15m=Decimal("0.018"),
        range_expansion_15m=Decimal("1.2"),
        return_5m=Decimal("-0.001"),
    )
    strong_signal = evaluate_mean_reversion(_context(feature=confirmed))
    assert strong_signal.direction is Direction.SHORT
    assert strong_signal.score == Decimal("70")


def test_directional_or_high_volatility_regime_blocks_mean_reversion() -> None:
    directional = _feature(trend_regime=TrendRegime.UP)
    assert evaluate_mean_reversion(_context(feature=directional)).direction is Direction.NO_TRADE

    high_vol = _feature(volatility_regime=VolatilityRegime.HIGH)
    assert evaluate_mean_reversion(_context(feature=high_vol)).direction is Direction.NO_TRADE

    unknown_vol = _feature(volatility_regime=VolatilityRegime.UNKNOWN)
    assert evaluate_mean_reversion(_context(feature=unknown_vol)).direction is Direction.NO_TRADE


def test_missing_or_zero_realized_volatility_fails_closed() -> None:
    missing = _feature(realized_vol_15m=None)
    assert evaluate_mean_reversion(_context(feature=missing)).direction is Direction.NO_TRADE

    zero = _feature(realized_vol_15m=Decimal("0"))
    assert evaluate_mean_reversion(_context(feature=zero)).direction is Direction.NO_TRADE


def test_stretch_below_one_point_seven_five_is_no_trade() -> None:
    feature = _feature(return_15m=Decimal("0.0174"))
    signal = evaluate_mean_reversion(_context(feature=feature))
    assert signal.direction is Direction.NO_TRADE
    assert "stretch_below_threshold" in signal.reason_codes


def test_invalid_swing_or_missing_deep_readiness_fails_closed() -> None:
    wrong_side = _candles(low="101", high="110")
    long_feature = _feature(return_15m=Decimal("-0.0225"))
    signal = evaluate_mean_reversion(_context(feature=long_feature, candles=wrong_side))
    assert signal.direction is Direction.NO_TRADE
    assert "invalid_invalidation" in signal.reason_codes

    blocked = evaluate_mean_reversion(_context(deep_ready=False))
    assert blocked.direction is Direction.NO_TRADE
    assert blocked.reason_codes == ("not_deep_ready",)
