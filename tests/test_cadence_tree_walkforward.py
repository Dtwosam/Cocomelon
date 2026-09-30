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
from cocomelon.research.cadence_shadow import (
    FIFTEEN_MINUTES_MS,
    ONE_HOUR_MS,
    ShadowCadenceDecision,
    ShadowCadenceOutcome,
)
from cocomelon.research.cadence_tree_learning import CadenceTreeConfig
from cocomelon.research.cadence_tree_walkforward import (
    CadenceTreeWalkforwardConfig,
    evaluate_cadence_tree_walkforward,
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
    signal = Decimal("0.03") if good else Decimal("-0.03")
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
        trend_regime=TrendRegime.MIXED,
        volatility_regime=VolatilityRegime.NORMAL,
        provenance=("test",),
    )


def _row(
    store: LearningFeatureSnapshotStore,
    *,
    index: int,
    direction: Direction,
    good: bool,
) -> ShadowCadenceOutcome:
    boundary = 1_000_000 + index * FIFTEEN_MINUTES_MS
    evaluated = boundary + 1_000
    market = MarketId("", f"M{index}")
    feature = _feature(
        market,
        as_of_ms=evaluated,
        good=good,
    )
    store.record(feature)
    net = Decimal("0.04") if good else Decimal("-0.04")
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


def _tree_config() -> CadenceTreeConfig:
    return CadenceTreeConfig(
        max_leaf_nodes=4,
        min_samples_leaf=2,
        learning_rate=Decimal("0.1"),
        max_iter=150,
        l2_regularization=Decimal("0"),
    )


def test_tree_walkforward_keeps_stable_signal_across_folds(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    rows = tuple(
        _row(
            store,
            index=index,
            direction=(
                Direction.LONG
                if index % 2 == 0
                else Direction.SHORT
            ),
            good=index % 4 < 2,
        )
        for index in range(28)
    )
    config = CadenceTreeWalkforwardConfig(
        validation_rows=4,
        folds=2,
        min_train_rows=8,
    )

    report = evaluate_cadence_tree_walkforward(
        rows,
        store,
        config=config,
        tree_config=_tree_config(),
    )

    assert report["status"] == "completed"
    assert report["fold_count"] == 2
    assert report["positive_candidate_folds"] == 2
    assert report["negative_candidate_folds"] == 0
    assert report["long_admitted_rows"] == 4
    assert report["short_admitted_rows"] == 4
    assert Decimal(report["candidate_net_return_sum"]) == Decimal(
        "0.32"
    )
    assert all(
        fold["purged_overlap_rows"] == 4
        for fold in report["folds"]
    )


def test_tree_walkforward_refuses_insufficient_history(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    rows = tuple(
        _row(
            store,
            index=index,
            direction=Direction.LONG,
            good=True,
        )
        for index in range(10)
    )
    config = CadenceTreeWalkforwardConfig(
        validation_rows=4,
        folds=2,
        min_train_rows=8,
    )

    report = evaluate_cadence_tree_walkforward(
        rows,
        store,
        config=config,
        tree_config=_tree_config(),
    )

    assert report["status"] == "not_ready"
    assert report["reason"] == "insufficient_surface_rows"
    assert report["promotion_authority"] is False
