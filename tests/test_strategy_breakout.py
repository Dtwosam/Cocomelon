from dataclasses import replace
from decimal import Decimal

from cocomelon.strategies.breakout import evaluate_breakout

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
        as_of_ms=30_000,
        source_received_at_ms=29_000,
        schema_version=1,
        day_return=Decimal("0.01"),
        funding=Decimal("0"),
        open_interest=Decimal("1000"),
        day_notional_volume=Decimal("1000000"),
        oi_change_fraction=Decimal("0.01"),
        funding_change=None,
        mark_oracle_dislocation_bps=None,
        return_5m=None,
        return_15m=Decimal("0.01"),
        return_1h=None,
        return_4h=None,
        realized_vol_15m=Decimal("0.005"),
        range_expansion_15m=Decimal("1"),
        relative_volume_15m=Decimal("1"),
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
        received_at_ms=29_000,
        schema_version=1,
    )


def _candle(
    index: int,
    *,
    low: str = "90",
    high: str = "100",
    close: str = "95",
    received_at_ms: int | None = None,
) -> Candle:
    end_ms = (index + 1) * 1_000
    return Candle(
        market=MarketId("", "BTC"),
        interval="15m",
        start_ms=index * 1_000,
        end_ms=end_ms,
        open_px=Decimal("95"),
        high_px=Decimal(high),
        low_px=Decimal(low),
        close_px=Decimal(close),
        volume=Decimal("100"),
        trade_count=10,
        source="test",
        received_at_ms=end_ms if received_at_ms is None else received_at_ms,
        schema_version=1,
    )


def _up_breakout(
    *,
    trigger_low: str = "96",
    received_at_ms: int | None = None,
) -> tuple[Candle, ...]:
    prior = tuple(_candle(i) for i in range(20))
    trigger = _candle(
        20,
        low=trigger_low,
        high="120",
        close="101",
        received_at_ms=received_at_ms,
    )
    return (*prior, trigger)


def _down_breakout() -> tuple[Candle, ...]:
    prior = tuple(_candle(i) for i in range(20))
    return (*prior, _candle(20, low="80", high="101", close="89"))


def _context(
    *,
    feature: FeatureSnapshot | None = None,
    candles: tuple[Candle, ...] | None = None,
    deep_ready: bool = True,
) -> StrategyContext:
    selected_feature = _feature() if feature is None else feature
    return StrategyContext(
        market_snapshot=_market_snapshot(),
        feature_snapshot=selected_feature,
        eligibility=EligibilityDecision(
            market=selected_feature.market,
            rankable=True,
            deep_ready=deep_ready,
            reasons=(),
        ),
        candles_5m=(),
        candles_15m=_up_breakout() if candles is None else candles,
        microstructure=None,
        as_of_ms=30_000,
    )


def test_trigger_is_excluded_from_prior_twenty_candle_range() -> None:
    signal = evaluate_breakout(
        _context(feature=_feature(relative_volume_15m=Decimal("1.2")))
    )
    assert signal.direction is Direction.LONG
    assert signal.score == Decimal("70")
    assert signal.invalidation_price == Decimal("96")


def test_confirmed_downside_breakout_emits_short() -> None:
    feature = _feature(range_expansion_15m=Decimal("1.1"), return_1h=Decimal("-0.02"))
    signal = evaluate_breakout(_context(feature=feature, candles=_down_breakout()))
    assert signal.direction is Direction.SHORT
    assert signal.score == Decimal("80")
    assert signal.invalidation_price == Decimal("101")


def test_both_confirmations_and_aligned_hour_score_full_one_hundred() -> None:
    feature = _feature(
        relative_volume_15m=Decimal("1.3"),
        range_expansion_15m=Decimal("1.2"),
        return_1h=Decimal("0.02"),
    )
    assert evaluate_breakout(_context(feature=feature)).score == Decimal("100")


def test_boundary_break_without_expansion_confirmation_is_no_trade() -> None:
    signal = evaluate_breakout(_context(feature=_feature()))
    assert signal.direction is Direction.NO_TRADE
    assert "missing_expansion_confirmation" in signal.reason_codes


def test_no_structural_breakout_is_no_trade() -> None:
    candles = (*tuple(_candle(i) for i in range(20)), _candle(20, close="99"))
    signal = evaluate_breakout(
        _context(feature=_feature(relative_volume_15m=Decimal("1.5")), candles=candles)
    )
    assert signal.direction is Direction.NO_TRADE
    assert "no_breakout" in signal.reason_codes


def test_future_received_trigger_cannot_leak_into_breakout() -> None:
    candles = _up_breakout(received_at_ms=30_001)
    signal = evaluate_breakout(
        _context(feature=_feature(relative_volume_15m=Decimal("1.5")), candles=candles)
    )
    assert signal.direction is Direction.NO_TRADE
    assert "insufficient_15m_candles" in signal.reason_codes


def test_wrong_side_breakout_invalidation_fails_closed() -> None:
    signal = evaluate_breakout(
        _context(
            feature=_feature(relative_volume_15m=Decimal("1.5")),
            candles=_up_breakout(trigger_low="101"),
        )
    )
    assert signal.direction is Direction.NO_TRADE
    assert "invalid_invalidation" in signal.reason_codes


def test_not_deep_ready_cannot_emit_breakout_trade() -> None:
    signal = evaluate_breakout(
        _context(feature=_feature(relative_volume_15m=Decimal("1.5")), deep_ready=False)
    )
    assert signal.direction is Direction.NO_TRADE
    assert signal.reason_codes == ("not_deep_ready",)
