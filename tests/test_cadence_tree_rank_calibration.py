from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

pytest.importorskip("sklearn")

from cocomelon.domain.features import (
    FeatureSnapshot,
    TrendRegime,
    VolatilityRegime,
)
from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.research.cadence_opportunity_learning import (
    CadenceOpportunityLearningConfig,
)
from cocomelon.research.cadence_shadow import (
    FIFTEEN_MINUTES_MS,
    ONE_HOUR_MS,
    ShadowCadenceDecision,
    ShadowCadenceOutcome,
)
from cocomelon.research.cadence_tree_learning import CadenceTreeConfig
from cocomelon.research.cadence_tree_rank_calibration import (
    CadenceTreeCalibrationConfig,
    evaluate_cadence_tree_rank_calibration,
)
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotStore,
)


def _row(
    store: LearningFeatureSnapshotStore,
    *,
    index: int,
    boundary_index: int,
    direction: Direction,
    signal: Decimal,
    net: Decimal,
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
        return_5m=signal / Decimal("3"),
        return_15m=signal / Decimal("2"),
        return_1h=signal,
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
    sample = ShadowCadenceDecision(
        cadence_ms=FIFTEEN_MINUTES_MS,
        boundary_ms=boundary,
        evaluated_at_ms=evaluated,
        market=market,
        direction=direction,
        score=Decimal("80"),
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
        gross_return=net + Decimal("0.001"),
        net_return=net,
    )


def test_nested_rank_calibration_keeps_final_holdout_separate(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    rows: list[ShadowCadenceOutcome] = []
    for index in range(120):
        direction = (
            Direction.LONG
            if index % 2 == 0
            else Direction.SHORT
        )
        good = index % 4 < 2
        signal = Decimal("0.03") if good else Decimal("-0.03")
        net = Decimal("0.03") if good else Decimal("-0.03")
        rows.append(
            _row(
                store,
                index=index,
                boundary_index=index,
                direction=direction,
                signal=signal,
                net=net,
            )
        )

    report = evaluate_cadence_tree_rank_calibration(
        tuple(rows),
        store,
        validation_config=CadenceOpportunityLearningConfig(
            min_train_rows=40,
            validation_rows=20,
            min_group_rows=4,
            stability_blocks=2,
            min_validation_admitted=4,
            min_block_admitted=1,
            min_validation_per_direction=4,
            min_admitted_per_direction=1,
        ),
        tree_config=CadenceTreeConfig(
            max_leaf_nodes=5,
            min_samples_leaf=5,
            learning_rate=Decimal("0.1"),
            max_iter=80,
            l2_regularization=Decimal("0"),
        ),
        calibration_config=CadenceTreeCalibrationConfig(
            calibration_rows=30,
            band_count=3,
            min_band_rows=6,
            standard_error_multiplier=Decimal("0"),
        ),
    )

    assert report["status"] == "completed"
    assert report["outer_validation_rows"] == 20
    assert report["inner_calibration_rows"] == 30
    assert report["inner_training_rows"] < report["outer_training_rows"]
    assert report["research_only"] is True
    assert report["execution_authority"] is False
    assert report["promotion_authority"] is False
    assert report["selected_band_indices"]
