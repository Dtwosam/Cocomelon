from dataclasses import replace
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
    StrategyContext,
    StrategyRole,
    StrategySignal,
)
from cocomelon.strategies.decision import combine_signals


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
        return_5m=Decimal("0.001"),
        return_15m=Decimal("0.01"),
        return_1h=Decimal("0.02"),
        return_4h=Decimal("0.03"),
        realized_vol_15m=Decimal("0.005"),
        range_expansion_15m=Decimal("1.1"),
        relative_volume_15m=Decimal("1.2"),
        spread_bps=Decimal("2"),
        bid_depth_25bps=Decimal("100000"),
        ask_depth_25bps=Decimal("100000"),
        book_imbalance=Decimal("0.1"),
        book_age_ms=100,
        trend_regime=TrendRegime.UP,
        volatility_regime=VolatilityRegime.NORMAL,
        provenance=("test",),
    )
    return replace(snapshot, **overrides)


def _context(
    *,
    feature: FeatureSnapshot | None = None,
    rankable: bool = True,
    deep_ready: bool = True,
) -> StrategyContext:
    selected = _feature() if feature is None else feature
    market = selected.market
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
        market_snapshot=market_snapshot,
        feature_snapshot=selected,
        eligibility=EligibilityDecision(
            market=market,
            rankable=rankable,
            deep_ready=deep_ready,
            reasons=(),
        ),
        candles_5m=(),
        candles_15m=(),
        microstructure=None,
        as_of_ms=10_000,
    )


def _primary(
    context: StrategyContext,
    strategy: str,
    direction: Direction,
    score: str,
    invalidation: str | None = None,
) -> StrategySignal:
    if invalidation is None:
        invalidation = "99" if direction is Direction.LONG else "102"
    return StrategySignal(
        strategy=strategy,
        role=StrategyRole.PRIMARY,
        market=context.feature_snapshot.market,
        direction=direction,
        score=Decimal(score),
        timestamp_ms=context.as_of_ms,
        reason_codes=(f"{strategy}_candidate",),
        feature_snapshot_id=context.feature_snapshot.snapshot_id,
        invalidation_price=Decimal(invalidation),
        veto_directions=(),
    )


def _context_signal(
    context: StrategyContext,
    *,
    strategy: str,
    direction: Direction,
    score: str,
    veto: tuple[Direction, ...] = (),
) -> StrategySignal:
    return StrategySignal(
        strategy=strategy,
        role=StrategyRole.CONTEXT,
        market=context.feature_snapshot.market,
        direction=direction,
        score=Decimal(score),
        timestamp_ms=context.as_of_ms,
        reason_codes=(f"{strategy}_context",),
        feature_snapshot_id=context.feature_snapshot.snapshot_id,
        invalidation_price=None,
        veto_directions=veto,
    )


def test_rankable_and_deep_ready_are_hard_preconditions() -> None:
    rank_blocked = _context(rankable=False, deep_ready=False)
    deep_blocked = _context(deep_ready=False)
    rank_signal = _primary(rank_blocked, "trend", Direction.LONG, "90")
    deep_signal = _primary(deep_blocked, "trend", Direction.LONG, "90")

    first = combine_signals(rank_blocked, [rank_signal])
    second = combine_signals(deep_blocked, [deep_signal])
    assert first.direction is Direction.NO_TRADE
    assert first.score == Decimal("0")
    assert first.reason_codes == ("not_rankable",)
    assert second.reason_codes == ("not_deep_ready",)


def test_context_only_evidence_cannot_originate_trade() -> None:
    context = _context()
    signal = _context_signal(
        context,
        strategy="order_flow",
        direction=Direction.LONG,
        score="100",
        veto=(Direction.SHORT,),
    )
    decision = combine_signals(context, [signal])
    assert decision.direction is Direction.NO_TRADE
    assert decision.score == Decimal("0")
    assert decision.reason_codes == ("no_primary_thesis",)


def test_up_normal_trend_keeps_full_effective_score() -> None:
    context = _context()
    decision = combine_signals(
        context,
        [_primary(context, "trend", Direction.LONG, "80")],
    )
    assert decision.direction is Direction.LONG
    assert decision.score == Decimal("80")
    assert decision.lead_strategy == "trend"


def test_regime_and_volatility_weights_are_exact() -> None:
    mixed = _context(feature=_feature(trend_regime=TrendRegime.MIXED))
    weak_trend = combine_signals(
        mixed,
        [_primary(mixed, "trend", Direction.LONG, "80")],
    )
    assert weak_trend.direction is Direction.NO_TRADE
    assert weak_trend.score == Decimal("40.0")

    high_vol = _context(
        feature=_feature(
            trend_regime=TrendRegime.MIXED,
            volatility_regime=VolatilityRegime.HIGH,
        )
    )
    weak_reversion = combine_signals(
        high_vol,
        [_primary(high_vol, "mean_reversion", Direction.SHORT, "100")],
    )
    assert weak_reversion.direction is Direction.NO_TRADE
    assert weak_reversion.score == Decimal("25.00")

    low_vol = _context(feature=_feature(volatility_regime=VolatilityRegime.LOW))
    breakout = combine_signals(
        low_vol,
        [_primary(low_vol, "breakout", Direction.LONG, "100")],
    )
    assert breakout.direction is Direction.LONG
    assert breakout.score == Decimal("67.500")


def test_same_direction_primary_agreement_adds_five_points_each_capped_at_ten() -> None:
    context = _context()
    signals = [
        _primary(context, "trend", Direction.LONG, "70"),
        _primary(context, "breakout", Direction.LONG, "70"),
        _primary(context, "mean_reversion", Direction.LONG, "70"),
    ]
    decision = combine_signals(context, signals)
    assert decision.direction is Direction.LONG
    assert decision.score == Decimal("80")


def test_close_opposing_primary_candidates_create_no_trade_conflict() -> None:
    context = _context()
    signals = [
        _primary(context, "trend", Direction.LONG, "80"),
        _primary(context, "breakout", Direction.SHORT, "90"),
    ]
    decision = combine_signals(context, signals)
    assert decision.direction is Direction.NO_TRADE
    assert decision.score == Decimal("81.0")
    assert decision.reason_codes == ("primary_conflict",)


def test_clear_primary_dominance_survives_opposition() -> None:
    context = _context()
    signals = [
        _primary(context, "trend", Direction.LONG, "90"),
        _primary(context, "breakout", Direction.SHORT, "70"),
    ]
    decision = combine_signals(context, signals)
    assert decision.direction is Direction.LONG
    assert decision.score == Decimal("90")


def test_context_support_and_opposition_adjust_by_exact_strength() -> None:
    context = _context()
    primary = _primary(context, "trend", Direction.LONG, "65")
    support = _context_signal(
        context,
        strategy="funding_oi",
        direction=Direction.LONG,
        score="70",
    )
    flow = _context_signal(
        context,
        strategy="order_flow",
        direction=Direction.LONG,
        score="75",
    )
    supported = combine_signals(context, [primary, support, flow])
    assert supported.direction is Direction.LONG
    assert supported.score == Decimal("74")

    opposition = _context_signal(
        context,
        strategy="order_flow",
        direction=Direction.SHORT,
        score="75",
    )
    rejected = combine_signals(context, [primary, opposition])
    assert rejected.direction is Direction.NO_TRADE
    assert rejected.score == Decimal("60")
    assert rejected.reason_codes == ("below_decision_threshold",)


def test_context_veto_blocks_candidate_direction() -> None:
    context = _context()
    primary = _primary(context, "trend", Direction.LONG, "90")
    veto = _context_signal(
        context,
        strategy="funding_oi",
        direction=Direction.NO_TRADE,
        score="100",
        veto=(Direction.LONG,),
    )
    decision = combine_signals(context, [primary, veto])
    assert decision.direction is Direction.NO_TRADE
    assert decision.score == Decimal("90")
    assert decision.reason_codes == ("context_veto",)


def test_lead_primary_owns_invalidation_and_permutation_is_deterministic() -> None:
    context = _context()
    trend = _primary(context, "trend", Direction.LONG, "80", invalidation="98")
    breakout = _primary(context, "breakout", Direction.LONG, "80", invalidation="97")
    first = combine_signals(context, [trend, breakout])
    second = combine_signals(context, [breakout, trend])
    assert first == second
    assert first.lead_strategy == "trend"
    assert first.invalidation_price == Decimal("98")
    assert first.decision_id == second.decision_id


def test_wrong_side_lead_invalidation_fails_closed() -> None:
    context = _context()
    bad = _primary(context, "trend", Direction.LONG, "90", invalidation="101")
    decision = combine_signals(context, [bad])
    assert decision.direction is Direction.NO_TRADE
    assert decision.reason_codes == ("invalid_invalidation",)


def test_mismatched_feature_snapshot_signal_is_rejected() -> None:
    context = _context()
    signal = replace(
        _primary(context, "trend", Direction.LONG, "80"),
        feature_snapshot_id="other-feature",
    )
    with pytest.raises(ValueError, match="feature snapshot"):
        combine_signals(context, [signal])
