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
from cocomelon.research.cadence_microstructure_tree import (
    MICROSTRUCTURE_FEATURES,
    evaluate_cadence_microstructure_tree,
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
    return FeatureSnapshot(
        market=market,
        as_of_ms=as_of_ms,
        source_received_at_ms=as_of_ms,
        schema_version=1,
        day_return=None,
        funding=Decimal("0.00001"),
        open_interest=Decimal("1000000"),
        day_notional_volume=Decimal("10000000"),
        oi_change_fraction=(
            Decimal("0.002") if good else Decimal("-0.002")
        ),
        funding_change=(
            Decimal("0.000001") if good else Decimal("-0.000001")
        ),
        mark_oracle_dislocation_bps=(
            Decimal("1") if good else Decimal("12")
        ),
        return_5m=Decimal("0"),
        return_15m=Decimal("0"),
        return_1h=Decimal("0"),
        return_4h=None,
        realized_vol_15m=(
            Decimal("0.006") if good else Decimal("0.018")
        ),
        range_expansion_15m=(
            Decimal("1.4") if good else Decimal("0.7")
        ),
        relative_volume_15m=(
            Decimal("2.0") if good else Decimal("0.5")
        ),
        spread_bps=Decimal("1") if good else Decimal("8"),
        bid_depth_25bps=Decimal("100000"),
        ask_depth_25bps=Decimal("100000"),
        book_imbalance=(
            Decimal("0.35")
            if good and direction is Direction.LONG
            else Decimal("-0.35")
            if good
            else Decimal("0")
        ),
        book_age_ms=700 if good else 4500,
        trend_regime=TrendRegime.MIXED,
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
    net = Decimal("0.05") if good else Decimal("-0.05")
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
        min_train_rows=32,
        validation_rows=16,
        min_group_rows=4,
        stability_blocks=4,
        min_validation_admitted=8,
        min_block_admitted=2,
        min_validation_per_direction=4,
        min_admitted_per_direction=2,
    )


def _tree_config() -> CadenceTreeConfig:
    return CadenceTreeConfig(
        max_leaf_nodes=4,
        min_samples_leaf=4,
        learning_rate=Decimal("0.1"),
        max_iter=150,
        l2_regularization=Decimal("0"),
    )


def test_microstructure_tree_selects_good_setups_on_both_sides(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    training = tuple(
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
        for index in range(40)
    )
    validation = tuple(
        _outcome(
            store,
            index=100 + index,
            direction=(
                Direction.LONG
                if index % 2 == 0
                else Direction.SHORT
            ),
            good=index % 4 < 2,
            boundary_index=44 + index,
        )
        for index in range(16)
    )

    report = evaluate_cadence_microstructure_tree(
        training + validation,
        store,
        validation_config=_validation_config(),
        tree_config=_tree_config(),
    )

    assert report["status"] == "completed"
    assert report["admitted_rows"] == 8
    assert report["by_direction"]["long"]["admitted_rows"] == 4
    assert report["by_direction"]["short"]["admitted_rows"] == 4
    assert Decimal(report["candidate_net_return_sum"]) == Decimal(
        "0.40"
    )
    assert all(
        block["passes"] is True
        for block in report["stability_blocks"]
    )


def test_microstructure_registry_avoids_raw_depth_market_proxy() -> None:
    assert "spread_bps" in MICROSTRUCTURE_FEATURES
    assert "book_imbalance" in MICROSTRUCTURE_FEATURES
    assert "relative_volume_15m" in MICROSTRUCTURE_FEATURES
    assert "book_age_ms" in MICROSTRUCTURE_FEATURES
    assert "bid_depth_25bps" not in MICROSTRUCTURE_FEATURES
    assert "ask_depth_25bps" not in MICROSTRUCTURE_FEATURES
