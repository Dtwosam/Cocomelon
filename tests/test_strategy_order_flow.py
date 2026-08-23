from dataclasses import replace
from decimal import Decimal

from cocomelon.strategies.order_flow import evaluate_order_flow

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
from cocomelon.domain.strategy import (
    Direction,
    MicrostructureWindow,
    StrategyContext,
    StrategyRole,
)


def _feature() -> FeatureSnapshot:
    return FeatureSnapshot(
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
        spread_bps=Decimal("2"),
        bid_depth_25bps=Decimal("100000"),
        ask_depth_25bps=Decimal("100000"),
        book_imbalance=Decimal("0"),
        book_age_ms=100,
        trend_regime=TrendRegime.UP,
        volatility_regime=VolatilityRegime.NORMAL,
        provenance=("test",),
    )


def _window(**overrides: object) -> MicrostructureWindow:
    window = MicrostructureWindow(
        market=MarketId("", "BTC"),
        start_ms=0,
        as_of_ms=10_000,
        trade_count=5,
        buy_notional=Decimal("80"),
        sell_notional=Decimal("20"),
        trade_flow_imbalance=Decimal("0.6"),
        latest_book_imbalance=Decimal("0.3"),
        book_imbalance_change=None,
        latest_event_age_ms=100,
        event_keys=("event-1",),
    )
    return replace(window, **overrides)


def _context(window: MicrostructureWindow | None) -> StrategyContext:
    feature = _feature()
    market = feature.market
    market_snapshot = PerpMarketSnapshot(
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
    return StrategyContext(
        market_snapshot=market_snapshot,
        feature_snapshot=feature,
        eligibility=EligibilityDecision(
            market=market,
            rankable=True,
            deep_ready=True,
            reasons=(),
        ),
        candles_5m=(),
        candles_15m=(),
        microstructure=window,
        as_of_ms=10_000,
    )


def test_strong_buy_flow_supports_long_and_vetoes_short() -> None:
    signal = evaluate_order_flow(_context(_window()))
    assert signal.role is StrategyRole.CONTEXT
    assert signal.direction is Direction.LONG
    assert signal.score == Decimal("100")
    assert signal.veto_directions == (Direction.SHORT,)


def test_strong_sell_flow_supports_short_and_vetoes_long() -> None:
    signal = evaluate_order_flow(
        _context(
            _window(
                buy_notional=Decimal("20"),
                sell_notional=Decimal("80"),
                trade_flow_imbalance=Decimal("-0.6"),
                latest_book_imbalance=Decimal("-0.3"),
            )
        )
    )
    assert signal.direction is Direction.SHORT
    assert signal.score == Decimal("100")
    assert signal.veto_directions == (Direction.LONG,)


def test_medium_flow_supports_direction_without_veto() -> None:
    long_signal = evaluate_order_flow(
        _context(
            _window(
                trade_flow_imbalance=Decimal("0.35"),
                latest_book_imbalance=Decimal("0.15"),
            )
        )
    )
    short_signal = evaluate_order_flow(
        _context(
            _window(
                buy_notional=Decimal("30"),
                sell_notional=Decimal("70"),
                trade_flow_imbalance=Decimal("-0.35"),
                latest_book_imbalance=Decimal("-0.15"),
            )
        )
    )
    assert long_signal.direction is Direction.LONG
    assert long_signal.score == Decimal("75")
    assert long_signal.veto_directions == ()
    assert short_signal.direction is Direction.SHORT
    assert short_signal.score == Decimal("75")
    assert short_signal.veto_directions == ()


def test_missing_stale_or_sparse_microstructure_is_neutral_zero() -> None:
    missing = evaluate_order_flow(_context(None))
    stale = evaluate_order_flow(_context(_window(latest_event_age_ms=2_001)))
    sparse = evaluate_order_flow(_context(_window(trade_count=4)))
    assert missing.direction is Direction.NO_TRADE
    assert missing.score == Decimal("0")
    assert stale.score == Decimal("0")
    assert "stale_microstructure" in stale.reason_codes
    assert sparse.score == Decimal("0")


def test_missing_flow_or_book_imbalance_is_neutral_zero() -> None:
    no_flow = evaluate_order_flow(_context(_window(trade_flow_imbalance=None)))
    no_book = evaluate_order_flow(_context(_window(latest_book_imbalance=None)))
    assert no_flow.score == Decimal("0")
    assert no_book.score == Decimal("0")


def test_conflicting_real_flow_and_book_state_is_neutral() -> None:
    signal = evaluate_order_flow(
        _context(
            _window(
                trade_flow_imbalance=Decimal("0.7"),
                latest_book_imbalance=Decimal("-0.3"),
            )
        )
    )
    assert signal.direction is Direction.NO_TRADE
    assert signal.score == Decimal("0")
    assert signal.veto_directions == ()
