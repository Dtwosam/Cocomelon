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
from cocomelon.research.cadence_active_context import (
    CadenceActiveCrossSectionIndex,
)
from cocomelon.research.cadence_active_context_tree import (
    evaluate_cadence_active_context_tree,
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


def _snapshot(
    market: MarketId,
    *,
    as_of_ms: int,
    return_1h: Decimal,
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
        return_5m=Decimal("0"),
        return_15m=Decimal("0"),
        return_1h=return_1h,
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


def _outcome(
    store: LearningFeatureSnapshotStore,
    *,
    index: int,
    direction: Direction,
    good: bool,
    boundary_index: int,
) -> ShadowCadenceOutcome:
    boundary = 1_000_000 + boundary_index * FIFTEEN_MINUTES_MS
    evaluated = boundary + 1_000
    target = MarketId("", f"T{index}")
    target_feature = _snapshot(
        target,
        as_of_ms=evaluated,
        return_1h=Decimal("0"),
    )
    store.record(target_feature)
    peer_return = Decimal("0.03") if good else Decimal("-0.03")
    for peer_index in range(9):
        store.record(
            _snapshot(
                MarketId("", f"P{peer_index}"),
                as_of_ms=evaluated,
                return_1h=peer_return,
            )
        )
    net = Decimal("0.05") if good else Decimal("-0.05")
    sample = ShadowCadenceDecision(
        cadence_ms=FIFTEEN_MINUTES_MS,
        boundary_ms=boundary,
        evaluated_at_ms=evaluated,
        market=target,
        direction=direction,
        score=Decimal("80"),
        lead_strategy="trend",
        decision_id=f"decision-{index}",
        feature_snapshot_id=target_feature.snapshot_id,
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
        max_leaf_nodes=7,
        min_samples_leaf=2,
        learning_rate=Decimal("0.1"),
        max_iter=150,
        l2_regularization=Decimal("0"),
    )


def test_active_context_index_uses_contemporaneous_cross_section(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    target = _snapshot(
        MarketId("", "TARGET"),
        as_of_ms=1000,
        return_1h=Decimal("0.01"),
    )
    store.record(target)
    for index in range(9):
        store.record(
            _snapshot(
                MarketId("", f"P{index}"),
                as_of_ms=1000,
                return_1h=(
                    Decimal("0.02")
                    if index < 6
                    else Decimal("-0.01")
                ),
            )
        )

    context = CadenceActiveCrossSectionIndex(
        store,
        min_context_markets=10,
    ).resolve(
        target,
        decision_evaluated_at_ms=1000,
    )

    assert context.market_count == 10
    assert context.return_1h_count == 10
    assert context.breadth_positive_1h == Decimal("0.7")
    assert context.target_market == "TARGET"


def test_active_context_tree_learns_market_regime_on_both_sides(
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
        for index in range(32)
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
            boundary_index=36 + index,
        )
        for index in range(16)
    )

    report = evaluate_cadence_active_context_tree(
        training + validation,
        store,
        validation_config=_validation_config(),
        tree_config=_tree_config(),
        min_context_markets=10,
    )

    assert report["status"] == "completed"
    assert report["admitted_rows"] >= 8
    assert report["by_direction"]["long"]["admitted_rows"] >= 2
    assert report["by_direction"]["short"]["admitted_rows"] >= 2
    assert Decimal(report["candidate_net_return_sum"]) > Decimal("0")
    assert all(
        block["passes"] is True
        for block in report["stability_blocks"]
    )
