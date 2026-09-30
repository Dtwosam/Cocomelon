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
from cocomelon.research.cadence_microstructure_prospective import (
    evaluate_cadence_microstructure_prospective,
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
from cocomelon.research.cadence_tree_learning import CadenceTreeConfig
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotStore,
)


def _feature(
    market: MarketId,
    *,
    as_of_ms: int,
    direction: Direction,
    good: bool,
) -> FeatureSnapshot:
    sign = Decimal("1") if direction is Direction.LONG else Decimal("-1")
    aligned = sign if good else -sign
    return FeatureSnapshot(
        market=market,
        as_of_ms=as_of_ms,
        source_received_at_ms=as_of_ms,
        schema_version=1,
        day_return=None,
        funding=Decimal("0.00001") * aligned,
        open_interest=Decimal("1000000"),
        day_notional_volume=Decimal("10000000"),
        oi_change_fraction=Decimal("0.001") * aligned,
        funding_change=Decimal("0.000001") * aligned,
        mark_oracle_dislocation_bps=Decimal("2"),
        return_5m=Decimal("0.005") * aligned,
        return_15m=Decimal("0.01") * aligned,
        return_1h=Decimal("0.02") * aligned,
        return_4h=None,
        realized_vol_15m=Decimal("0.006"),
        range_expansion_15m=(
            Decimal("1.4") if good else Decimal("0.7")
        ),
        relative_volume_15m=(
            Decimal("2.0") if good else Decimal("0.5")
        ),
        spread_bps=(
            Decimal("1.0") if good else Decimal("7.0")
        ),
        bid_depth_25bps=(
            Decimal("150000") if good else Decimal("10000")
        ),
        ask_depth_25bps=(
            Decimal("140000") if good else Decimal("12000")
        ),
        book_imbalance=Decimal("0.4") * aligned,
        book_age_ms=800 if good else 4200,
        trend_regime=(
            TrendRegime.UP
            if direction is Direction.LONG
            else TrendRegime.DOWN
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
    net: str | None = None,
) -> ShadowCadenceOutcome:
    market = MarketId("", f"M{index}")
    boundary = 1_000_000 + boundary_index * FIFTEEN_MINUTES_MS
    evaluated = boundary + 1_000
    feature = _feature(
        market,
        as_of_ms=evaluated,
        direction=direction,
        good=good,
    )
    store.record(feature)
    net_value = Decimal(
        net
        if net is not None
        else ("0.03" if good else "-0.03")
    )
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
        gross_return=net_value + Decimal("0.001"),
        net_return=net_value,
    )


def _validation_config() -> CadenceOpportunityLearningConfig:
    return CadenceOpportunityLearningConfig(
        min_train_rows=24,
        validation_rows=8,
        min_group_rows=4,
        stability_blocks=2,
        min_validation_admitted=4,
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


def _dataset(
    root: Path,
    *,
    future_flip: bool = False,
) -> tuple[
    tuple[ShadowCadenceOutcome, ...],
    LearningFeatureSnapshotStore,
    int,
]:
    store = LearningFeatureSnapshotStore(root)
    training: list[ShadowCadenceOutcome] = []
    for index in range(32):
        direction = (
            Direction.LONG
            if index % 2 == 0
            else Direction.SHORT
        )
        good = index % 4 < 2
        training.append(
            _outcome(
                store,
                index=index,
                direction=direction,
                good=good,
                boundary_index=index,
            )
        )

    prospective_start_ms = (
        1_000_000 + 40 * FIFTEEN_MINUTES_MS
    )
    future: list[ShadowCadenceOutcome] = []
    for index in range(8):
        direction = (
            Direction.LONG
            if index % 2 == 0
            else Direction.SHORT
        )
        good = index % 4 < 2
        future.append(
            _outcome(
                store,
                index=100 + index,
                direction=direction,
                good=good,
                boundary_index=40 + index,
                net=(
                    ("-0.07" if good else "0.07")
                    if future_flip
                    else None
                ),
            )
        )
    return tuple(training + future), store, prospective_start_ms


def test_prospective_tree_can_admit_good_long_and_short(
    tmp_path: Path,
) -> None:
    rows, store, start = _dataset(tmp_path / "features")

    report = evaluate_cadence_microstructure_prospective(
        rows,
        store,
        prospective_start_ms=start,
        validation_config=_validation_config(),
        tree_config=_tree_config(),
    )

    assert report["status"] == "completed"
    assert report["development_qualified"] is True
    assert report["by_direction"]["long"]["admitted_rows"] >= 1
    assert report["by_direction"]["short"]["admitted_rows"] >= 1
    assert Decimal(report["candidate_net_return_sum"]) > Decimal("0")
    assert all(
        block["passes"] is True
        for block in report["stability_blocks"]
    )


def test_post_freeze_labels_cannot_change_predictions(
    tmp_path: Path,
) -> None:
    rows_a, store_a, start_a = _dataset(tmp_path / "a")
    rows_b, store_b, start_b = _dataset(
        tmp_path / "b",
        future_flip=True,
    )

    report_a = evaluate_cadence_microstructure_prospective(
        rows_a,
        store_a,
        prospective_start_ms=start_a,
        validation_config=_validation_config(),
        tree_config=_tree_config(),
    )
    report_b = evaluate_cadence_microstructure_prospective(
        rows_b,
        store_b,
        prospective_start_ms=start_b,
        validation_config=_validation_config(),
        tree_config=_tree_config(),
    )

    scored_a = tuple(
        (
            row["decision_id"],
            row["prediction_net_return"],
            row["admitted"],
        )
        for row in report_a["scored_rows"]
    )
    scored_b = tuple(
        (
            row["decision_id"],
            row["prediction_net_return"],
            row["admitted"],
        )
        for row in report_b["scored_rows"]
    )
    assert scored_a == scored_b
    assert (
        report_a["frozen_training_last_target_end_ms"]
        < start_a
    )
    assert (
        report_b["frozen_training_last_target_end_ms"]
        < start_b
    )


def test_pre_freeze_rows_never_count_as_prospective(
    tmp_path: Path,
) -> None:
    rows, store, start = _dataset(tmp_path / "features")

    report = evaluate_cadence_microstructure_prospective(
        rows,
        store,
        prospective_start_ms=start,
        validation_config=_validation_config(),
        tree_config=_tree_config(),
    )

    assert report["prospective_rows"] == 8
    assert all(
        row["boundary_ms"] >= start
        for row in report["scored_rows"]
    )
    assert report["research_only"] is True
    assert report["execution_authority"] is False
    assert report["promotion_authority"] is False
