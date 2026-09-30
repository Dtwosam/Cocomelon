from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from cocomelon.domain.features import (
    FeatureSnapshot,
    TrendRegime,
    VolatilityRegime,
)
from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.research.cadence_context_confidence import (
    CadenceContextConfidenceConfig,
    evaluate_cadence_context_confidence,
)
from cocomelon.research.cadence_opportunity_learning import (
    CadenceOpportunityLearningConfig,
)
from cocomelon.research.cadence_shadow import (
    FIFTEEN_MINUTES_MS,
    ONE_HOUR_MS,
    ShadowCadenceDecision,
    ShadowCadenceOutcome,
)
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotStore,
)


def _feature(
    market: MarketId,
    *,
    as_of_ms: int,
    trend: TrendRegime,
    volatility: VolatilityRegime,
) -> FeatureSnapshot:
    return FeatureSnapshot(
        market=market,
        as_of_ms=as_of_ms,
        source_received_at_ms=as_of_ms,
        schema_version=1,
        day_return=None,
        funding=Decimal("0"),
        open_interest=Decimal("1000000"),
        day_notional_volume=Decimal("10000000"),
        oi_change_fraction=None,
        funding_change=None,
        mark_oracle_dislocation_bps=None,
        return_5m=None,
        return_15m=None,
        return_1h=None,
        return_4h=None,
        realized_vol_15m=None,
        range_expansion_15m=None,
        relative_volume_15m=None,
        spread_bps=None,
        bid_depth_25bps=None,
        ask_depth_25bps=None,
        book_imbalance=None,
        book_age_ms=None,
        trend_regime=trend,
        volatility_regime=volatility,
        provenance=("test",),
    )


def _outcome(
    store: LearningFeatureSnapshotStore,
    *,
    index: int,
    direction: Direction,
    trend: TrendRegime,
    volatility: VolatilityRegime,
    net: str,
    boundary_index: int,
    score: str = "82",
) -> ShadowCadenceOutcome:
    market = MarketId("", f"M{index}")
    boundary = 1_000_000 + boundary_index * FIFTEEN_MINUTES_MS
    evaluated = boundary + 1_000
    feature = _feature(
        market,
        as_of_ms=evaluated,
        trend=trend,
        volatility=volatility,
    )
    store.record(feature)
    net_value = Decimal(net)
    sample = ShadowCadenceDecision(
        cadence_ms=FIFTEEN_MINUTES_MS,
        boundary_ms=boundary,
        evaluated_at_ms=evaluated,
        market=market,
        direction=direction,
        score=Decimal(score),
        lead_strategy="trend",
        decision_id=f"decision-{index}",
        feature_snapshot_id=feature.snapshot_id,
        entry_px=Decimal("100"),
        horizon_ms=ONE_HOUR_MS,
        target_end_ms=boundary + ONE_HOUR_MS,
        cost_fraction=Decimal("0.001"),
        off_primary_boundary=False,
    )
    return ShadowCadenceOutcome(
        sample=sample,
        exit_px=Decimal("101"),
        gross_return=net_value + Decimal("0.001"),
        net_return=net_value,
    )


def _validation_config() -> CadenceOpportunityLearningConfig:
    return CadenceOpportunityLearningConfig(
        min_train_rows=20,
        validation_rows=8,
        min_group_rows=5,
        stability_blocks=2,
        min_validation_admitted=2,
        min_block_admitted=1,
        min_validation_per_direction=2,
        min_admitted_per_direction=1,
    )


def _confidence_config() -> CadenceContextConfidenceConfig:
    return CadenceContextConfidenceConfig(
        min_local_rows=5,
        min_fallback_rows=10,
        standard_error_multiplier=Decimal("1"),
    )


def test_supported_negative_local_regime_vetoes_positive_parent(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    rows: list[ShadowCadenceOutcome] = []

    for index in range(20):
        rows.append(
            _outcome(
                store,
                index=index,
                direction=Direction.LONG,
                trend=(
                    TrendRegime.UP
                    if index < 6
                    else TrendRegime.MIXED
                ),
                volatility=(
                    VolatilityRegime.LOW
                    if index < 6
                    else VolatilityRegime.NORMAL
                ),
                net=("-0.01" if index < 6 else "0.02"),
                boundary_index=index,
            )
        )

    validation = (
        _outcome(
            store,
            index=100,
            direction=Direction.LONG,
            trend=TrendRegime.UP,
            volatility=VolatilityRegime.LOW,
            net="-0.02",
            boundary_index=24,
        ),
        _outcome(
            store,
            index=101,
            direction=Direction.SHORT,
            trend=TrendRegime.DOWN,
            volatility=VolatilityRegime.NORMAL,
            net="0.01",
            boundary_index=25,
        ),
        _outcome(
            store,
            index=102,
            direction=Direction.LONG,
            trend=TrendRegime.UP,
            volatility=VolatilityRegime.LOW,
            net="-0.01",
            boundary_index=26,
        ),
        _outcome(
            store,
            index=103,
            direction=Direction.SHORT,
            trend=TrendRegime.DOWN,
            volatility=VolatilityRegime.NORMAL,
            net="0.01",
            boundary_index=27,
        ),
        _outcome(
            store,
            index=104,
            direction=Direction.LONG,
            trend=TrendRegime.MIXED,
            volatility=VolatilityRegime.NORMAL,
            net="0.01",
            boundary_index=28,
        ),
        _outcome(
            store,
            index=105,
            direction=Direction.SHORT,
            trend=TrendRegime.DOWN,
            volatility=VolatilityRegime.NORMAL,
            net="0.01",
            boundary_index=29,
        ),
        _outcome(
            store,
            index=106,
            direction=Direction.LONG,
            trend=TrendRegime.MIXED,
            volatility=VolatilityRegime.NORMAL,
            net="0.01",
            boundary_index=30,
        ),
        _outcome(
            store,
            index=107,
            direction=Direction.SHORT,
            trend=TrendRegime.DOWN,
            volatility=VolatilityRegime.NORMAL,
            net="0.01",
            boundary_index=31,
        ),
    )

    result = evaluate_cadence_context_confidence(
        tuple(rows) + validation,
        store,
        validation_config=_validation_config(),
        confidence_config=_confidence_config(),
    )

    skipped = result["skipped_cohorts"]
    assert any(
        item["direction"] == "long"
        and item["trend_regime"] == "up"
        and item["volatility_regime"] == "low"
        and Decimal(item["training_lower_bound"]) < Decimal("0")
        for item in skipped
    )


def test_tiny_positive_training_mean_fails_confidence_hurdle(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    rows: list[ShadowCadenceOutcome] = []
    training_values = (
        "0.01",
        "-0.0098",
        "0.011",
        "-0.0107",
        "0.0095",
        "-0.0092",
        "0.0105",
        "-0.0101",
        "0.0097",
        "-0.0094",
        "0.0102",
        "-0.0099",
    )
    for index, net in enumerate(training_values):
        rows.append(
            _outcome(
                store,
                index=index,
                direction=Direction.SHORT,
                trend=TrendRegime.DOWN,
                volatility=VolatilityRegime.LOW,
                net=net,
                boundary_index=index,
                score="72",
            )
        )
    for index in range(8):
        rows.append(
            _outcome(
                store,
                index=30 + index,
                direction=Direction.LONG,
                trend=TrendRegime.UP,
                volatility=VolatilityRegime.NORMAL,
                net="0.01",
                boundary_index=12 + index,
            )
        )

    validation: list[ShadowCadenceOutcome] = []
    for index in range(8):
        validation.append(
            _outcome(
                store,
                index=100 + index,
                direction=(
                    Direction.SHORT
                    if index % 2 == 0
                    else Direction.LONG
                ),
                trend=(
                    TrendRegime.DOWN
                    if index % 2 == 0
                    else TrendRegime.UP
                ),
                volatility=(
                    VolatilityRegime.LOW
                    if index % 2 == 0
                    else VolatilityRegime.NORMAL
                ),
                net=("-0.005" if index % 2 == 0 else "0.01"),
                boundary_index=24 + index,
                score=("72" if index % 2 == 0 else "82"),
            )
        )

    result = evaluate_cadence_context_confidence(
        tuple(rows) + tuple(validation),
        store,
        validation_config=_validation_config(),
        confidence_config=_confidence_config(),
    )

    skipped = result["skipped_cohorts"]
    short = next(
        item
        for item in skipped
        if item["direction"] == "short"
        and item["score_band"] == "70-<75"
    )
    assert Decimal(short["training_mean_net_return"]) > Decimal("0")
    assert Decimal(short["training_lower_bound"]) < Decimal("0")


def test_strong_local_edges_can_admit_long_and_short(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    rows: list[ShadowCadenceOutcome] = []
    for index in range(10):
        rows.append(
            _outcome(
                store,
                index=index,
                direction=Direction.LONG,
                trend=TrendRegime.UP,
                volatility=VolatilityRegime.HIGH,
                net="0.02",
                boundary_index=index,
            )
        )
        rows.append(
            _outcome(
                store,
                index=20 + index,
                direction=Direction.SHORT,
                trend=TrendRegime.DOWN,
                volatility=VolatilityRegime.NORMAL,
                net="0.015",
                boundary_index=10 + index,
            )
        )

    validation: list[ShadowCadenceOutcome] = []
    for index in range(8):
        validation.append(
            _outcome(
                store,
                index=100 + index,
                direction=(
                    Direction.LONG
                    if index % 2 == 0
                    else Direction.SHORT
                ),
                trend=(
                    TrendRegime.UP
                    if index % 2 == 0
                    else TrendRegime.DOWN
                ),
                volatility=(
                    VolatilityRegime.HIGH
                    if index % 2 == 0
                    else VolatilityRegime.NORMAL
                ),
                net="0.01",
                boundary_index=24 + index,
            )
        )

    result = evaluate_cadence_context_confidence(
        tuple(rows) + tuple(validation),
        store,
        validation_config=_validation_config(),
        confidence_config=_confidence_config(),
    )

    assert result["status"] == "completed"
    assert result["admitted_rows"] == 8
    assert result["by_direction"]["long"]["admitted_rows"] == 4
    assert result["by_direction"]["short"]["admitted_rows"] == 4
    assert Decimal(result["candidate_net_return_sum"]) > Decimal("0")
