from decimal import Decimal

import pytest

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
    StrategyDecision,
    StrategyRole,
    StrategySignal,
)


def _market(coin: str = "BTC") -> MarketId:
    return MarketId("", coin)


def _market_snapshot(market: MarketId | None = None) -> PerpMarketSnapshot:
    selected = _market() if market is None else market
    return PerpMarketSnapshot(
        meta=PerpMarketMeta(
            market=selected,
            wire_name=selected.wire_name,
            sz_decimals=5,
            max_leverage=40,
            margin_table_id=1,
            only_isolated=False,
            is_delisted=False,
            margin_mode=None,
        ),
        context=PerpMarketContext(
            market=selected,
            mark_px=Decimal("100"),
            mid_px=Decimal("100.5"),
            oracle_px=Decimal("100"),
            funding=Decimal("0.00001"),
            open_interest=Decimal("1000"),
            day_ntl_vlm=Decimal("10000000"),
            premium=Decimal("0"),
            prev_day_px=Decimal("99"),
        ),
        source="hyperliquid-mainnet-info",
        received_at_ms=900,
        schema_version=1,
    )


def _feature_snapshot(market: MarketId | None = None) -> FeatureSnapshot:
    selected = _market() if market is None else market
    return FeatureSnapshot(
        market=selected,
        as_of_ms=1_000,
        source_received_at_ms=900,
        schema_version=1,
        day_return=Decimal("0.01"),
        funding=Decimal("0.00001"),
        open_interest=Decimal("1000"),
        day_notional_volume=Decimal("10000000"),
        oi_change_fraction=Decimal("0.02"),
        funding_change=Decimal("0.000001"),
        mark_oracle_dislocation_bps=Decimal("1"),
        return_5m=Decimal("0.002"),
        return_15m=Decimal("0.01"),
        return_1h=Decimal("0.02"),
        return_4h=Decimal("0.03"),
        realized_vol_15m=Decimal("0.005"),
        range_expansion_15m=Decimal("1.2"),
        relative_volume_15m=Decimal("1.3"),
        spread_bps=Decimal("2"),
        bid_depth_25bps=Decimal("100000"),
        ask_depth_25bps=Decimal("90000"),
        book_imbalance=Decimal("0.1"),
        book_age_ms=100,
        trend_regime=TrendRegime.UP,
        volatility_regime=VolatilityRegime.NORMAL,
        provenance=("hyperliquid-mainnet-info",),
    )


def _signal(**overrides: object) -> StrategySignal:
    feature = _feature_snapshot()
    values: dict[str, object] = {
        "strategy": "trend",
        "role": StrategyRole.PRIMARY,
        "market": feature.market,
        "direction": Direction.LONG,
        "score": Decimal("75"),
        "timestamp_ms": 1_000,
        "reason_codes": ("trend_up", "return_15m_aligned"),
        "feature_snapshot_id": feature.snapshot_id,
        "invalidation_price": Decimal("99"),
        "veto_directions": (),
    }
    values.update(overrides)
    return StrategySignal(**values)  # type: ignore[arg-type]


def test_directional_primary_uses_decimal_and_deterministic_signal_id() -> None:
    first = _signal(reason_codes=("trend_up", "trend_up", "return_15m_aligned"))
    second = _signal(reason_codes=("trend_up", "return_15m_aligned"))

    assert first.score == Decimal("75")
    assert first.invalidation_price == Decimal("99")
    assert first.reason_codes == ("trend_up", "return_15m_aligned")
    assert first.signal_id == second.signal_id
    assert len(first.signal_id) == 24


def test_primary_direction_requires_positive_finite_invalidation() -> None:
    with pytest.raises(ValueError, match="invalidation"):
        _signal(invalidation_price=None)
    with pytest.raises(ValueError, match="invalidation"):
        _signal(invalidation_price=Decimal("0"))


def test_primary_signal_cannot_set_context_vetoes() -> None:
    with pytest.raises(ValueError, match="veto"):
        _signal(veto_directions=(Direction.SHORT,))


def test_context_signal_cannot_set_invalidation() -> None:
    with pytest.raises(ValueError, match="context"):
        _signal(
            strategy="order_flow",
            role=StrategyRole.CONTEXT,
            invalidation_price=Decimal("99"),
        )


def test_context_veto_cannot_include_no_trade() -> None:
    with pytest.raises(ValueError, match="veto"):
        _signal(
            strategy="funding_oi",
            role=StrategyRole.CONTEXT,
            direction=Direction.NO_TRADE,
            score=Decimal("100"),
            invalidation_price=None,
            veto_directions=(Direction.NO_TRADE,),
        )


def test_microstructure_window_bounds_and_imbalance_are_validated() -> None:
    window = MicrostructureWindow(
        market=_market(),
        start_ms=0,
        as_of_ms=1_000,
        trade_count=10,
        buy_notional=Decimal("60"),
        sell_notional=Decimal("40"),
        trade_flow_imbalance=Decimal("0.2"),
        latest_book_imbalance=Decimal("0.1"),
        book_imbalance_change=None,
        latest_event_age_ms=50,
        event_keys=("event-2", "event-1", "event-1"),
    )
    assert window.event_keys == ("event-1", "event-2")

    with pytest.raises(ValueError, match="imbalance"):
        MicrostructureWindow(
            market=_market(),
            start_ms=0,
            as_of_ms=1_000,
            trade_count=1,
            buy_notional=Decimal("1"),
            sell_notional=Decimal("0"),
            trade_flow_imbalance=Decimal("1.1"),
            latest_book_imbalance=None,
            book_imbalance_change=None,
            latest_event_age_ms=0,
            event_keys=("event",),
        )


def test_strategy_context_requires_matching_markets() -> None:
    feature = _feature_snapshot(_market("BTC"))
    with pytest.raises(ValueError, match="market"):
        StrategyContext(
            market_snapshot=_market_snapshot(_market("ETH")),
            feature_snapshot=feature,
            eligibility=EligibilityDecision(
                market=feature.market,
                rankable=True,
                deep_ready=True,
                reasons=(),
            ),
            candles_5m=(),
            candles_15m=(),
            microstructure=None,
            as_of_ms=1_000,
        )


def test_strategy_decision_id_is_deterministic_and_has_no_risk_or_order_fields() -> None:
    signal = _signal()
    first = StrategyDecision(
        market=signal.market,
        direction=Direction.LONG,
        score=Decimal("70"),
        timestamp_ms=1_000,
        feature_snapshot_id=signal.feature_snapshot_id,
        lead_strategy="trend",
        invalidation_price=Decimal("99"),
        signal_ids=(signal.signal_id,),
        reason_codes=("trend",),
    )
    second = StrategyDecision(
        market=signal.market,
        direction=Direction.LONG,
        score=Decimal("70"),
        timestamp_ms=1_000,
        feature_snapshot_id=signal.feature_snapshot_id,
        lead_strategy="trend",
        invalidation_price=Decimal("99"),
        signal_ids=(signal.signal_id,),
        reason_codes=("trend",),
    )

    assert first.decision_id == second.decision_id
    assert len(first.decision_id) == 24
    forbidden = {"quantity", "leverage", "risk_budget", "order_type", "wallet"}
    assert forbidden.isdisjoint(StrategyDecision.__dataclass_fields__)


def test_directional_decision_requires_lead_strategy_and_invalidation() -> None:
    with pytest.raises(ValueError, match="lead_strategy"):
        StrategyDecision(
            market=_market(),
            direction=Direction.SHORT,
            score=Decimal("70"),
            timestamp_ms=1_000,
            feature_snapshot_id="feature-1",
            lead_strategy=None,
            invalidation_price=Decimal("101"),
            signal_ids=("signal-1",),
            reason_codes=("candidate",),
        )
