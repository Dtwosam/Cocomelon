from dataclasses import replace
from decimal import Decimal

from cocomelon.domain.features import (
    EligibilityDecision,
    FeatureSnapshot,
    TrendRegime,
    VolatilityRegime,
)
from cocomelon.domain.market import (
    MarketId,
    PerpMarketContext,
    PerpMarketMeta,
    PerpMarketSnapshot,
)
from cocomelon.domain.strategy import Direction, StrategyContext, StrategyRole
from cocomelon.strategies.funding_oi import evaluate_funding_oi


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
        return_15m=Decimal("0.01"),
        return_1h=Decimal("0.02"),
        return_4h=None,
        realized_vol_15m=None,
        range_expansion_15m=None,
        relative_volume_15m=None,
        spread_bps=None,
        bid_depth_25bps=None,
        ask_depth_25bps=None,
        book_imbalance=None,
        book_age_ms=None,
        trend_regime=TrendRegime.UP,
        volatility_regime=VolatilityRegime.NORMAL,
        provenance=("test",),
    )
    return replace(snapshot, **overrides)


def _context(feature: FeatureSnapshot | None = None) -> StrategyContext:
    selected = _feature() if feature is None else feature
    market = selected.market
    snapshot = PerpMarketSnapshot(
        meta=PerpMarketMeta(
            market=market,
            wire_name=market.wire_name,
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
            funding=selected.funding,
            open_interest=selected.open_interest,
            day_ntl_vlm=selected.day_notional_volume,
            premium=Decimal("0"),
            prev_day_px=Decimal("99"),
        ),
        source="test",
        received_at_ms=9_000,
        schema_version=1,
    )
    return StrategyContext(
        market_snapshot=snapshot,
        feature_snapshot=selected,
        eligibility=EligibilityDecision(
            market=market,
            rankable=True,
            deep_ready=True,
            reasons=(),
        ),
        candles_5m=(),
        candles_15m=(),
        microstructure=None,
        as_of_ms=10_000,
    )


def test_supportive_oi_expansion_and_uncrowded_funding_supports_long() -> None:
    signal = evaluate_funding_oi(_context())
    assert signal.role is StrategyRole.CONTEXT
    assert signal.direction is Direction.LONG
    assert signal.score == Decimal("70")
    assert signal.veto_directions == ()


def test_supportive_negative_returns_support_short() -> None:
    feature = _feature(return_15m=Decimal("-0.01"), return_1h=Decimal("-0.02"))
    signal = evaluate_funding_oi(_context(feature))
    assert signal.direction is Direction.SHORT
    assert signal.score == Decimal("70")


def test_extreme_positive_crowding_vetoes_long_without_creating_short() -> None:
    feature = _feature(
        funding=Decimal("0.0002"),
        oi_change_fraction=Decimal("0.03"),
    )
    signal = evaluate_funding_oi(_context(feature))
    assert signal.direction is Direction.NO_TRADE
    assert signal.score == Decimal("100")
    assert signal.veto_directions == (Direction.LONG,)


def test_extreme_negative_crowding_vetoes_short_without_creating_long() -> None:
    feature = _feature(
        funding=Decimal("-0.0002"),
        oi_change_fraction=Decimal("0.03"),
        return_15m=Decimal("-0.01"),
        return_1h=Decimal("-0.02"),
    )
    signal = evaluate_funding_oi(_context(feature))
    assert signal.direction is Direction.NO_TRADE
    assert signal.score == Decimal("100")
    assert signal.veto_directions == (Direction.SHORT,)


def test_missing_or_non_positive_oi_change_is_neutral_zero() -> None:
    missing = evaluate_funding_oi(_context(_feature(oi_change_fraction=None)))
    non_positive = evaluate_funding_oi(
        _context(_feature(oi_change_fraction=Decimal("0")))
    )
    assert missing.direction is Direction.NO_TRADE
    assert missing.score == Decimal("0")
    assert non_positive.score == Decimal("0")


def test_crowded_but_non_veto_context_is_neutral_fifty() -> None:
    feature = _feature(
        funding=Decimal("0.00015"),
        oi_change_fraction=Decimal("0.02"),
    )
    signal = evaluate_funding_oi(_context(feature))
    assert signal.direction is Direction.NO_TRADE
    assert signal.score == Decimal("50")
    assert signal.veto_directions == ()


def test_extreme_funding_without_extreme_oi_does_not_veto() -> None:
    feature = _feature(
        funding=Decimal("0.00025"),
        oi_change_fraction=Decimal("0.02"),
    )
    signal = evaluate_funding_oi(_context(feature))
    assert signal.direction is Direction.NO_TRADE
    assert signal.score == Decimal("50")
    assert signal.veto_directions == ()


def test_mixed_price_direction_is_neutral_when_not_crowded() -> None:
    feature = _feature(return_15m=Decimal("0.01"), return_1h=Decimal("-0.01"))
    signal = evaluate_funding_oi(_context(feature))
    assert signal.direction is Direction.NO_TRADE
    assert signal.score == Decimal("0")
