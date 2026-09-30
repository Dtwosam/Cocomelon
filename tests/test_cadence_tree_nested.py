from __future__ import annotations

from dataclasses import replace
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
from cocomelon.research.cadence_tree_nested import (
    CadenceTreeNestedConfig,
    evaluate_cadence_tree_nested,
)
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotStore,
)


def _feature(
    market: MarketId,
    *,
    as_of_ms: int,
    good: bool,
) -> FeatureSnapshot:
    momentum = Decimal("0.04") if good else Decimal("-0.04")
    return FeatureSnapshot(
        market=market,
        as_of_ms=as_of_ms,
        source_received_at_ms=as_of_ms,
        schema_version=1,
        day_return=None,
        funding=Decimal("0.00001"),
        open_interest=Decimal("1000000"),
        day_notional_volume=Decimal("10000000"),
        oi_change_fraction=None,
        funding_change=None,
        mark_oracle_dislocation_bps=None,
        return_5m=momentum / Decimal("4"),
        return_15m=momentum / Decimal("2"),
        return_1h=momentum,
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
            TrendRegime.UP if good else TrendRegime.MIXED
        ),
        volatility_regime=VolatilityRegime.NORMAL,
        provenance=("test",),
    )


def _outcome(
    store: LearningFeatureSnapshotStore,
    *,
    index: int,
    direction: Direction,
    good: bool,
    boundary_index: int,
    realized_good: bool | None = None,
) -> ShadowCadenceOutcome:
    market = MarketId("", f"M{index}")
    boundary = 1_000_000 + boundary_index * FIFTEEN_MINUTES_MS
    evaluated = boundary + 1_000
    feature = _feature(
        market,
        as_of_ms=evaluated,
        good=good,
    )
    store.record(feature)
    result_good = good if realized_good is None else realized_good
    net = Decimal("0.05") if result_good else Decimal("-0.05")
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


def _validation_config() -> CadenceOpportunityLearningConfig:
    return CadenceOpportunityLearningConfig(
        min_train_rows=16,
        validation_rows=8,
        min_group_rows=4,
        stability_blocks=2,
        min_validation_admitted=2,
        min_block_admitted=1,
        min_validation_per_direction=2,
        min_admitted_per_direction=1,
    )


def _tree_config() -> CadenceTreeConfig:
    return CadenceTreeConfig(
        max_leaf_nodes=7,
        min_samples_leaf=2,
        learning_rate=Decimal("0.1"),
        max_iter=150,
        l2_regularization=Decimal("0"),
    )


def _nested_config() -> CadenceTreeNestedConfig:
    return CadenceTreeNestedConfig(
        inner_calibration_rows=4,
        min_inner_train_rows=16,
        threshold_candidates=(
            Decimal("0"),
            Decimal("0.005"),
            Decimal("0.02"),
        ),
    )


def _dataset(
    store: LearningFeatureSnapshotStore,
    *,
    flip_outer_outcomes: bool,
) -> tuple[ShadowCadenceOutcome, ...]:
    rows: list[ShadowCadenceOutcome] = []
    for index in range(16):
        rows.append(
            _outcome(
                store,
                index=index,
                direction=(
                    Direction.LONG
                    if index % 2 == 0
                    else Direction.SHORT
                ),
                good=index % 4 < 2,
                boundary_index=index,
            )
        )
    for index in range(4):
        rows.append(
            _outcome(
                store,
                index=40 + index,
                direction=(
                    Direction.LONG
                    if index % 2 == 0
                    else Direction.SHORT
                ),
                good=index % 2 == 0,
                boundary_index=20 + index,
            )
        )
    for index in range(8):
        feature_good = index % 2 == 0
        rows.append(
            _outcome(
                store,
                index=100 + index,
                direction=(
                    Direction.LONG
                    if index % 2 == 0
                    else Direction.SHORT
                ),
                good=feature_good,
                realized_good=(
                    not feature_good
                    if flip_outer_outcomes
                    else feature_good
                ),
                boundary_index=28 + index,
            )
        )
    return tuple(rows)


def test_outer_outcomes_cannot_change_selected_threshold(
    tmp_path: Path,
) -> None:
    left_store = LearningFeatureSnapshotStore(tmp_path / "left")
    right_store = LearningFeatureSnapshotStore(tmp_path / "right")

    left = evaluate_cadence_tree_nested(
        _dataset(left_store, flip_outer_outcomes=False),
        left_store,
        validation_config=_validation_config(),
        tree_config=_tree_config(),
        nested_config=_nested_config(),
    )
    right = evaluate_cadence_tree_nested(
        _dataset(right_store, flip_outer_outcomes=True),
        right_store,
        validation_config=_validation_config(),
        tree_config=_tree_config(),
        nested_config=_nested_config(),
    )

    assert left["selected_threshold"] == right["selected_threshold"]
    assert left["calibration_results"] == right["calibration_results"]
    assert left["candidate_net_return_sum"] != right[
        "candidate_net_return_sum"
    ]


def test_nested_report_remains_research_only(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    report = evaluate_cadence_tree_nested(
        _dataset(store, flip_outer_outcomes=False),
        store,
        validation_config=_validation_config(),
        tree_config=_tree_config(),
        nested_config=_nested_config(),
    )

    assert report["status"] == "completed"
    assert report["research_only"] is True
    assert report["execution_authority"] is False
    assert report["promotion_authority"] is False
    assert report["model_family"] == (
        "cadence_fixed_shallow_tree_nested_v1"
    )
