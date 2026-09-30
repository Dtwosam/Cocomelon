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
from cocomelon.research.cadence_context_walkforward import (
    CadenceContextWalkForwardConfig,
    evaluate_cadence_context_walk_forward,
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


def _row(
    store: LearningFeatureSnapshotStore,
    *,
    index: int,
    boundary_index: int,
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
        open_interest=Decimal("1"),
        day_notional_volume=Decimal("1"),
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
        trend_regime=TrendRegime.UP,
        volatility_regime=VolatilityRegime.NORMAL,
        provenance=("test",),
    )
    store.record(feature)
    sample = ShadowCadenceDecision(
        cadence_ms=FIFTEEN_MINUTES_MS,
        boundary_ms=boundary,
        evaluated_at_ms=evaluated,
        market=market,
        direction=Direction.LONG,
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
    net_value = Decimal(net)
    return ShadowCadenceOutcome(
        sample=sample,
        exit_px=Decimal("101"),
        gross_return=net_value + Decimal("0.001"),
        net_return=net_value,
    )


def _config(
    *,
    validation_rows: int = 4,
) -> CadenceOpportunityLearningConfig:
    return CadenceOpportunityLearningConfig(
        min_train_rows=8,
        validation_rows=validation_rows,
        min_group_rows=2,
        stability_blocks=2,
        min_validation_admitted=1,
        min_block_admitted=1,
        min_validation_per_direction=1,
        min_admitted_per_direction=1,
    )


def test_walk_forward_forgets_stale_positive_history(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    rows: list[ShadowCadenceOutcome] = []
    for index in range(8):
        rows.append(
            _row(
                store,
                index=index,
                boundary_index=index,
                net="0.02",
            )
        )
    for index in range(8, 16):
        rows.append(
            _row(
                store,
                index=index,
                boundary_index=index,
                net="-0.01",
            )
        )
    for offset in range(4):
        rows.append(
            _row(
                store,
                index=100 + offset,
                boundary_index=20 + offset,
                net="-0.01",
            )
        )

    result = evaluate_cadence_context_walk_forward(
        tuple(rows),
        store,
        learning_config=_config(),
        walk_forward_config=CadenceContextWalkForwardConfig(
            window_rows=8,
        ),
    )

    assert result["status"] == "completed"
    assert result["admitted_rows"] == 0
    assert result["candidate_net_return_sum"] == "0"
    assert (
        result["baseline_context_model"]["admitted_rows"]
        == 4
    )
    assert Decimal(
        result["walk_forward_minus_baseline_net_return_sum"]
    ) > Decimal("0")


def test_walk_forward_uses_only_settled_prior_validation_labels(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    rows: list[ShadowCadenceOutcome] = []
    for index in range(8):
        rows.append(
            _row(
                store,
                index=index,
                boundary_index=index,
                net="-0.001",
            )
        )
    for offset, boundary_index in enumerate((20, 25, 30, 35)):
        rows.append(
            _row(
                store,
                index=100 + offset,
                boundary_index=boundary_index,
                net="0.01",
            )
        )

    result = evaluate_cadence_context_walk_forward(
        tuple(rows),
        store,
        learning_config=_config(),
        walk_forward_config=CadenceContextWalkForwardConfig(
            window_rows=8,
        ),
    )

    assert result["status"] == "completed"
    assert result["admitted_rows"] == 3
    assert result["candidate_net_return_sum"] == "0.03"
    assert result["prior_validation_labels_used_min"] == 0
    assert result["prior_validation_labels_used_max"] == 3
    assert (
        result["baseline_context_model"]["admitted_rows"]
        == 0
    )


def test_walk_forward_window_must_cover_minimum_training() -> None:
    import pytest

    store = LearningFeatureSnapshotStore("/tmp/cocomelon-walkforward-test")
    with pytest.raises(ValueError, match="window must cover"):
        evaluate_cadence_context_walk_forward(
            (),
            store,
            learning_config=_config(),
            walk_forward_config=CadenceContextWalkForwardConfig(
                window_rows=7,
            ),
        )
