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
from cocomelon.research.cadence_walk_forward_confidence import (
    CadenceWalkForwardConfig,
    evaluate_cadence_walk_forward_confidence,
)
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotStore,
)


def _outcome(
    store: LearningFeatureSnapshotStore,
    *,
    index: int,
    boundary_index: int,
    direction: Direction,
    net: str,
) -> ShadowCadenceOutcome:
    market = MarketId("", f"M{index}")
    boundary = 1_000_000 + boundary_index * FIFTEEN_MINUTES_MS
    evaluated = boundary + 1_000
    feature = FeatureSnapshot(
        market=market,
        as_of_ms=evaluated,
        source_received_at_ms=evaluated,
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
        trend_regime=(
            TrendRegime.UP
            if direction is Direction.LONG
            else TrendRegime.DOWN
        ),
        volatility_regime=VolatilityRegime.NORMAL,
        provenance=("test",),
    )
    store.record(feature)
    value = Decimal(net)
    sample = ShadowCadenceDecision(
        cadence_ms=FIFTEEN_MINUTES_MS,
        boundary_ms=boundary,
        evaluated_at_ms=evaluated,
        market=market,
        direction=direction,
        score=Decimal("82"),
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
        gross_return=value + Decimal("0.001"),
        net_return=value,
    )


def _validation_config() -> CadenceOpportunityLearningConfig:
    return CadenceOpportunityLearningConfig(
        min_train_rows=20,
        validation_rows=20,
        min_group_rows=4,
        stability_blocks=2,
        min_validation_admitted=4,
        min_block_admitted=2,
        min_validation_per_direction=4,
        min_admitted_per_direction=2,
    )


def _confidence_config() -> CadenceContextConfidenceConfig:
    return CadenceContextConfidenceConfig(
        min_local_rows=4,
        min_fallback_rows=8,
        standard_error_multiplier=Decimal("0"),
    )


def test_walk_forward_recent_history_can_adapt_both_sides(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    rows: list[ShadowCadenceOutcome] = []

    for index in range(30):
        rows.append(
            _outcome(
                store,
                index=index,
                boundary_index=index,
                direction=(
                    Direction.LONG
                    if index % 2 == 0
                    else Direction.SHORT
                ),
                net=("0.01" if index % 2 == 0 else "-0.02"),
            )
        )

    for index in range(30, 70):
        rows.append(
            _outcome(
                store,
                index=index,
                boundary_index=index,
                direction=(
                    Direction.LONG
                    if index % 2 == 0
                    else Direction.SHORT
                ),
                net="0.02",
            )
        )

    for index in range(70, 90):
        rows.append(
            _outcome(
                store,
                index=index,
                boundary_index=index,
                direction=(
                    Direction.LONG
                    if index % 2 == 0
                    else Direction.SHORT
                ),
                net="0.01",
            )
        )

    report = evaluate_cadence_walk_forward_confidence(
        tuple(rows),
        store,
        validation_config=_validation_config(),
        confidence_config=_confidence_config(),
        walk_forward_config=CadenceWalkForwardConfig(
            lookback_rows=30,
            evaluation_rows=20,
        ),
    )

    assert report["status"] == "completed"
    assert report["admitted_rows"] > 0
    assert report["by_direction"]["long"]["admitted_rows"] > 0
    assert report["by_direction"]["short"]["admitted_rows"] > 0
    assert Decimal(report["candidate_net_return_sum"]) > Decimal("0")


def test_walk_forward_excludes_unsettled_recent_labels(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    rows: list[ShadowCadenceOutcome] = []

    for index in range(30):
        rows.append(
            _outcome(
                store,
                index=index,
                boundary_index=index,
                direction=Direction.SHORT,
                net="-0.02",
            )
        )

    for index in range(30, 34):
        rows.append(
            _outcome(
                store,
                index=index,
                boundary_index=index,
                direction=Direction.SHORT,
                net="0.20",
            )
        )

    for index in range(34, 54):
        rows.append(
            _outcome(
                store,
                index=index,
                boundary_index=index,
                direction=Direction.SHORT,
                net="-0.01",
            )
        )

    report = evaluate_cadence_walk_forward_confidence(
        tuple(rows),
        store,
        validation_config=CadenceOpportunityLearningConfig(
            min_train_rows=12,
            validation_rows=20,
            min_group_rows=4,
            stability_blocks=2,
            min_validation_admitted=2,
            min_block_admitted=1,
            min_validation_per_direction=1,
            min_admitted_per_direction=1,
        ),
        confidence_config=_confidence_config(),
        walk_forward_config=CadenceWalkForwardConfig(
            lookback_rows=20,
            evaluation_rows=20,
        ),
    )

    assert report["status"] == "completed"
    assert report["walk_forward_configuration"]["settlement_rule"] == (
        "history_target_end_ms_strictly_before_decision_boundary"
    )
    assert report["by_direction"]["short"]["validation_rows"] == 20
