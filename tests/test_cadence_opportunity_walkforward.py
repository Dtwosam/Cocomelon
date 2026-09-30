from __future__ import annotations

from decimal import Decimal

from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.research.cadence_opportunity_walkforward import (
    CadenceOpportunityWalkforwardConfig,
    evaluate_cadence_opportunity_walkforward,
)
from cocomelon.research.cadence_shadow import (
    FIFTEEN_MINUTES_MS,
    ONE_HOUR_MS,
    ShadowCadenceDecision,
    ShadowCadenceOutcome,
)


def _row(
    *,
    index: int,
    direction: Direction,
    net: str,
) -> ShadowCadenceOutcome:
    boundary = 1_000_000 + index * FIFTEEN_MINUTES_MS
    sample = ShadowCadenceDecision(
        cadence_ms=FIFTEEN_MINUTES_MS,
        boundary_ms=boundary,
        evaluated_at_ms=boundary + 1_000,
        market=MarketId("", "SOL" if index % 2 == 0 else "BTC"),
        direction=direction,
        score=Decimal("82"),
        lead_strategy="trend",
        decision_id=f"decision-{index}",
        feature_snapshot_id=f"feature-{index}",
        entry_px=Decimal("100"),
        horizon_ms=ONE_HOUR_MS,
        target_end_ms=boundary + ONE_HOUR_MS,
        cost_fraction=Decimal("0.001"),
        off_primary_boundary=False,
    )
    return ShadowCadenceOutcome(
        sample=sample,
        exit_px=Decimal("101"),
        gross_return=Decimal(net) + Decimal("0.001"),
        net_return=Decimal(net),
    )


def test_walkforward_uses_disjoint_purged_windows() -> None:
    config = CadenceOpportunityWalkforwardConfig(
        validation_rows=4,
        folds=2,
        min_train_rows=8,
        min_group_rows=2,
    )
    training = tuple(
        _row(
            index=index,
            direction=(
                Direction.LONG
                if index % 2 == 0
                else Direction.SHORT
            ),
            net="0.01",
        )
        for index in range(12)
    )
    validation = tuple(
        _row(
            index=index,
            direction=(
                Direction.LONG
                if index % 2 == 0
                else Direction.SHORT
            ),
            net=("0.02" if index < 16 else "-0.005"),
        )
        for index in range(12, 20)
    )

    report = evaluate_cadence_opportunity_walkforward(
        training + validation,
        config=config,
    )

    assert report["status"] == "completed"
    assert report["fold_count"] == 2
    assert report["positive_candidate_folds"] == 1
    assert report["negative_candidate_folds"] == 1
    assert report["long_admitted_rows"] == 4
    assert report["short_admitted_rows"] == 4
    folds = report["folds"]
    assert folds[0]["validation_start_index"] == 12
    assert folds[0]["validation_end_index_exclusive"] == 16
    assert folds[1]["validation_start_index"] == 16
    assert folds[1]["validation_end_index_exclusive"] == 20
    assert folds[0]["purged_overlap_rows"] == 4
    assert folds[1]["purged_overlap_rows"] == 4


def test_walkforward_reports_persistent_exact_cohort() -> None:
    config = CadenceOpportunityWalkforwardConfig(
        validation_rows=2,
        folds=2,
        min_train_rows=4,
        min_group_rows=2,
    )
    rows = tuple(
        _row(
            index=index,
            direction=Direction.LONG,
            net="0.01",
        )
        for index in range(12)
    )

    report = evaluate_cadence_opportunity_walkforward(
        rows,
        config=config,
    )

    assert report["status"] == "completed"
    persistence = report["cohort_persistence"]
    assert len(persistence) == 1
    assert persistence[0]["direction"] == "long"
    assert persistence[0]["lead_strategy"] == "trend"
    assert persistence[0]["score_band"] == "80+"
    assert persistence[0]["folds_present"] == 2
    assert persistence[0]["positive_folds"] == 2
    assert persistence[0]["rows"] == 4


def test_walkforward_refuses_insufficient_surface_history() -> None:
    config = CadenceOpportunityWalkforwardConfig(
        validation_rows=4,
        folds=2,
        min_train_rows=8,
        min_group_rows=2,
    )
    rows = tuple(
        _row(index=index, direction=Direction.LONG, net="0.01")
        for index in range(10)
    )

    report = evaluate_cadence_opportunity_walkforward(
        rows,
        config=config,
    )

    assert report["status"] == "not_ready"
    assert report["reason"] == "insufficient_surface_rows"
    assert report["promotion_authority"] is False
