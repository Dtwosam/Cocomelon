from __future__ import annotations

from decimal import Decimal

import pytest

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
from cocomelon.research.learning_shadow_strategy import (
    LearningShadowStrategyError,
    build_learning_shadow_strategy_evaluator,
    resolve_learning_shadow_feature_values,
)
from cocomelon.strategies.engine import evaluate_strategies
from tests.test_learning_shadow_evidence import _shadow_inputs


def _feature(*, as_of_ms: int, short: bool = False) -> FeatureSnapshot:
    sign = Decimal("-1") if short else Decimal("1")
    return FeatureSnapshot(
        market=MarketId("", "HYPE"),
        as_of_ms=as_of_ms,
        source_received_at_ms=as_of_ms - 1,
        schema_version=1,
        day_return=sign * Decimal("0.02"),
        funding=Decimal("0"),
        open_interest=Decimal("1000"),
        day_notional_volume=Decimal("1000000"),
        oi_change_fraction=sign * Decimal("0.01"),
        funding_change=None,
        mark_oracle_dislocation_bps=None,
        return_5m=sign * Decimal("0.005"),
        return_15m=sign * Decimal("0.01"),
        return_1h=sign * Decimal("0.02"),
        return_4h=sign * Decimal("0.03"),
        realized_vol_15m=Decimal("0.005"),
        range_expansion_15m=Decimal("1.2"),
        relative_volume_15m=Decimal("1.3"),
        spread_bps=Decimal("2"),
        bid_depth_25bps=Decimal("100000"),
        ask_depth_25bps=Decimal("100000"),
        book_imbalance=sign * Decimal("0.2"),
        book_age_ms=100,
        trend_regime=TrendRegime.DOWN if short else TrendRegime.UP,
        volatility_regime=VolatilityRegime.NORMAL,
        provenance=("shadow-test",),
    )


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
        received_at_ms=feature.source_received_at_ms,
        schema_version=1,
    )


def _candle(
    market: MarketId,
    *,
    index: int,
    base_ms: int,
    low: str,
    high: str,
    close: str,
) -> Candle:
    end_ms = base_ms - (21 - index) * 1_000
    return Candle(
        market=market,
        interval="15m",
        start_ms=end_ms - 1_000,
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


def _candles(
    market: MarketId,
    *,
    as_of_ms: int,
    short: bool,
) -> tuple[Candle, ...]:
    if short:
        prior = tuple(
            _candle(
                market,
                index=index,
                base_ms=as_of_ms,
                low="100",
                high="110",
                close="105",
            )
            for index in range(20)
        )
        trigger = _candle(
            market,
            index=20,
            base_ms=as_of_ms,
            low="80",
            high="104",
            close="99",
        )
    else:
        prior = tuple(
            _candle(
                market,
                index=index,
                base_ms=as_of_ms,
                low="90",
                high="100",
                close="95",
            )
            for index in range(20)
        )
        trigger = _candle(
            market,
            index=20,
            base_ms=as_of_ms,
            low="96",
            high="120",
            close="101",
        )
    return (*prior, trigger)


def _context(*, as_of_ms: int, short: bool = False) -> StrategyContext:
    feature = _feature(as_of_ms=as_of_ms, short=short)
    return StrategyContext(
        market_snapshot=_market_snapshot(feature),
        feature_snapshot=feature,
        eligibility=EligibilityDecision(
            market=feature.market,
            rankable=True,
            deep_ready=True,
            reasons=(),
        ),
        candles_5m=(),
        candles_15m=_candles(
            feature.market,
            as_of_ms=as_of_ms,
            short=short,
        ),
        microstructure=None,
        as_of_ms=as_of_ms,
    )


def _evaluator(tmp_path):
    (
        package_root,
        spec_path,
        clean_evidence_root,
        score_path,
        finalization_path,
        dossier_path,
        _decision,
        decision_path,
        admission,
        admission_path,
    ) = _shadow_inputs(tmp_path)
    evaluator = build_learning_shadow_strategy_evaluator(
        package_root=package_root,
        validation_spec_path=spec_path,
        shadow_admission_path=admission_path,
        review_decision_path=decision_path,
        review_dossier_path=dossier_path,
        validation_score_path=score_path,
        finalization_path=finalization_path,
        clean_evidence_root=clean_evidence_root,
    )
    return evaluator, admission


def test_shadow_strategy_preserves_trusted_directional_risk_geometry_when_accepted(
    tmp_path,
) -> None:
    evaluator, admission = _evaluator(tmp_path)
    context = _context(as_of_ms=admission.shadow_start_ms + 10_000)
    source = evaluate_strategies(context).decision
    assert source.direction is Direction.LONG

    decision = evaluator.evaluate(context)

    assert decision.direction is Direction.LONG
    assert decision.score == source.score
    assert decision.lead_strategy == source.lead_strategy
    assert decision.invalidation_price == source.invalidation_price
    assert decision.signal_ids == source.signal_ids
    assert "learned_shadow_filter_accept" in decision.reason_codes
    assert (
        f"learned_shadow_admission:{admission.shadow_admission_id}"
        in decision.reason_codes
    )


def test_shadow_strategy_abstains_when_frozen_learner_has_no_directional_model(
    tmp_path,
) -> None:
    evaluator, admission = _evaluator(tmp_path)
    context = _context(
        as_of_ms=admission.shadow_start_ms + 10_000,
        short=True,
    )
    source = evaluate_strategies(context).decision
    assert source.direction is Direction.SHORT

    decision = evaluator.evaluate(context)

    assert decision.direction is Direction.NO_TRADE
    assert decision.invalidation_price is None
    assert decision.lead_strategy is None
    assert decision.signal_ids == source.signal_ids
    assert "learned_shadow_filter_reject" in decision.reason_codes


def test_shadow_strategy_abstains_before_human_review_admission(tmp_path) -> None:
    evaluator, admission = _evaluator(tmp_path)
    context = _context(as_of_ms=admission.shadow_start_ms - 1)
    decision = evaluator.evaluate(context)

    assert decision.direction is Direction.NO_TRADE
    assert "learned_shadow_before_admission" in decision.reason_codes


def test_shadow_feature_resolver_rejects_record_only_features(tmp_path) -> None:
    _evaluator_value, admission = _evaluator(tmp_path)
    context = _context(as_of_ms=admission.shadow_start_ms + 10_000)

    with pytest.raises(
        LearningShadowStrategyError,
        match="FEATURE_UNSUPPORTED",
    ):
        resolve_learning_shadow_feature_values(
            context,
            direction=Direction.LONG,
            feature_registry=("candidate_id",),
        )


def test_shadow_feature_resolver_uses_exact_snapshot_values(tmp_path) -> None:
    evaluator, admission = _evaluator(tmp_path)
    context = _context(as_of_ms=admission.shadow_start_ms + 10_000)

    values = resolve_learning_shadow_feature_values(
        context,
        direction=Direction.LONG,
        feature_registry=evaluator.feature_registry,
    )

    assert values == ("HYPE", "long")
