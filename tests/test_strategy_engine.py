from dataclasses import replace
from decimal import Decimal

from cocomelon.strategies.engine import StrategyEvaluation, evaluate_strategies
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


AS_OF_MS = 30_000


def _feature(**overrides: object) -> FeatureSnapshot:
    snapshot = FeatureSnapshot(
        market=MarketId("", "BTC"),
        as_of_ms=AS_OF_MS,
        source_received_at_ms=29_000,
        schema_version=1,
        day_return=Decimal("0.02"),
        funding=Decimal("0"),
        open_interest=Decimal("1000"),
        day_notional_volume=Decimal("1000000"),
        oi_change_fraction=Decimal("0.01"),
        funding_change=None,
        mark_oracle_dislocation_bps=None,
        return_5m=Decimal("0.005"),
        return_15m=Decimal("0.01"),
        return_1h=Decimal("0.02"),
        return_4h=Decimal("0.03"),
        realized_vol_15m=Decimal("0.005"),
        range_expansion_15m=Decimal("1.2"),
        relative_volume_15m=Decimal("1.3"),
        spread_bps=Decimal("2"),
        bid_depth_25bps=Decimal("100000"),
        ask_depth_25bps=Decimal("100000"),
        book_imbalance=Decimal("0.2"),
        book_age_ms=100,
        trend_regime=TrendRegime.UP,
        volatility_regime=VolatilityRegime.NORMAL,
        provenance=("test",),
    )
    return replace(snapshot, **overrides)


def _market_snapshot(feature: FeatureSnapshot) -> PerpMarketSnapshot:
    market = feature.market
    return PerpMarketSnapshot(
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
            funding=feature.funding,
            open_interest=feature.open_interest,
            day_ntl_vlm=feature.day_notional_volume,
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
    low: str,
    high: str,
    close: str,
) -> Candle:
    end_ms = (index + 1) * 1_000
    return Candle(
        market=MarketId("", "BTC"),
        interval="15m",
        start_ms=index * 1_000,
        end_ms=end_ms,
        open_px=Decimal(close),
        high_px=Decimal(high),
        low_px=Decimal(low),
        close_px=Decimal(close),
        volume=Decimal("100"),
        trade_count=10,
        source="test",
        received_at_ms=end_ms,
        schema_version=1,
    )


def _long_candles() -> tuple[Candle, ...]:
    prior = tuple(_candle(i, low="90", high="100", close="95") for i in range(20))
    trigger = _candle(20, low="96", high="120", close="101")
    return (*prior, trigger)


def _short_candles() -> tuple[Candle, ...]:
    prior = tuple(_candle(i, low="100", high="110", close="105") for i in range(20))
    trigger = _candle(20, low="80", high="104", close="99")
    return (*prior, trigger)


def _context(
    *,
    feature: FeatureSnapshot | None = None,
    candles: tuple[Candle, ...] | None = None,
    rankable: bool = True,
    deep_ready: bool = True,
) -> StrategyContext:
    selected = _feature() if feature is None else feature
    return StrategyContext(
        market_snapshot=_market_snapshot(selected),
        feature_snapshot=selected,
        eligibility=EligibilityDecision(
            market=selected.market,
            rankable=rankable,
            deep_ready=deep_ready,
            reasons=(),
        ),
        candles_5m=(),
        candles_15m=_long_candles() if candles is None else candles,
        microstructure=None,
        as_of_ms=AS_OF_MS,
    )


def test_engine_runs_all_five_families_in_deterministic_name_order() -> None:
    context = _context()
    first = evaluate_strategies(context)
    second = evaluate_strategies(context)

    assert isinstance(first, StrategyEvaluation)
    assert first == second
    assert tuple(signal.strategy for signal in first.signals) == (
        "breakout",
        "funding_oi",
        "mean_reversion",
        "order_flow",
        "trend",
    )
    assert all(
        signal.feature_snapshot_id == context.feature_snapshot.snapshot_id
        for signal in first.signals
    )
    assert first.decision.direction is Direction.LONG
    assert first.decision.score == Decimal("100")


def test_engine_produces_short_from_aligned_trend_and_breakout() -> None:
    feature = _feature(
        day_return=Decimal("-0.02"),
        return_5m=Decimal("-0.005"),
        return_15m=Decimal("-0.01"),
        return_1h=Decimal("-0.02"),
        return_4h=Decimal("-0.03"),
        book_imbalance=Decimal("-0.2"),
        trend_regime=TrendRegime.DOWN,
    )
    evaluation = evaluate_strategies(_context(feature=feature, candles=_short_candles()))

    assert evaluation.decision.direction is Direction.SHORT
    assert evaluation.decision.score == Decimal("100")
    assert evaluation.decision.lead_strategy == "trend"


def test_engine_preserves_deep_readiness_as_hard_no_trade_gate() -> None:
    evaluation = evaluate_strategies(_context(deep_ready=False))

    assert len(evaluation.signals) == 5
    assert evaluation.decision.direction is Direction.NO_TRADE
    assert evaluation.decision.score == Decimal("0")
    assert evaluation.decision.reason_codes == ("not_deep_ready",)


def test_engine_context_veto_blocks_otherwise_strong_long_thesis() -> None:
    feature = _feature(
        funding=Decimal("0.0002"),
        oi_change_fraction=Decimal("0.03"),
    )
    evaluation = evaluate_strategies(_context(feature=feature))

    funding_signal = next(
        signal for signal in evaluation.signals if signal.strategy == "funding_oi"
    )
    assert funding_signal.veto_directions == (Direction.LONG,)
    assert evaluation.decision.direction is Direction.NO_TRADE
    assert evaluation.decision.reason_codes == ("context_veto",)
