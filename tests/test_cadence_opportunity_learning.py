from __future__ import annotations

from decimal import Decimal

from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.research.cadence_opportunity_learning import (
    CadenceOpportunityLearningConfig,
    evaluate_cadence_opportunity_learning,
)
from cocomelon.research.cadence_shadow import (
    FIFTEEN_MINUTES_MS,
    ONE_HOUR_MS,
    ShadowCadenceDecision,
    ShadowCadenceOutcome,
)

MARKET = MarketId("", "SOL")


def _outcome(
    *,
    index: int,
    direction: Direction,
    lead_strategy: str,
    score: str,
    net: str,
    horizon_ms: int = ONE_HOUR_MS,
    boundary_ms: int | None = None,
) -> ShadowCadenceOutcome:
    boundary = (
        1_000_000 + index * FIFTEEN_MINUTES_MS
        if boundary_ms is None
        else boundary_ms
    )
    sample = ShadowCadenceDecision(
        cadence_ms=FIFTEEN_MINUTES_MS,
        boundary_ms=boundary,
        evaluated_at_ms=boundary + 1_000,
        market=MARKET,
        direction=direction,
        score=Decimal(score),
        lead_strategy=lead_strategy,
        decision_id=f"decision-{index}",
        feature_snapshot_id=f"feature-{index}",
        entry_px=Decimal("100"),
        horizon_ms=horizon_ms,
        target_end_ms=boundary + horizon_ms,
        cost_fraction=Decimal("0.001"),
        off_primary_boundary=False,
    )
    gross = Decimal(net) + sample.cost_fraction
    return ShadowCadenceOutcome(
        sample=sample,
        exit_px=Decimal("101"),
        gross_return=gross,
        net_return=Decimal(net),
    )


def _config() -> CadenceOpportunityLearningConfig:
    return CadenceOpportunityLearningConfig(
        min_train_rows=8,
        validation_rows=8,
        min_group_rows=2,
        stability_blocks=2,
        min_validation_admitted=4,
        min_block_admitted=1,
        min_validation_per_direction=2,
        min_admitted_per_direction=1,
    )


def test_learning_is_side_neutral_and_uses_purged_chronological_holdout() -> None:
    rows = []
    for index in range(8):
        direction = (
            Direction.LONG if index % 2 == 0 else Direction.SHORT
        )
        rows.append(
            _outcome(
                index=index,
                direction=direction,
                lead_strategy="trend",
                score="82",
                net="0.01",
            )
        )
    for index in range(8, 16):
        direction = (
            Direction.LONG if index % 2 == 0 else Direction.SHORT
        )
        rows.append(
            _outcome(
                index=index,
                direction=direction,
                lead_strategy="trend",
                score="82",
                net="0.02",
                boundary_ms=(
                    1_000_000
                    + (index + 4) * FIFTEEN_MINUTES_MS
                ),
            )
        )

    report = evaluate_cadence_opportunity_learning(
        tuple(rows),
        config=_config(),
    )
    surface = report["surfaces"][f"{FIFTEEN_MINUTES_MS}:{ONE_HOUR_MS}"]

    assert surface["status"] == "completed"
    assert surface["training_rows"] == 8
    assert surface["validation_rows"] == 8
    assert surface["purged_overlap_rows"] == 0
    assert surface["admitted_rows"] == 8
    assert surface["development_qualified"] is True
    assert report["development_qualified"] is False

    by_direction = surface["by_direction"]
    assert by_direction["long"]["admitted_rows"] == 4
    assert by_direction["short"]["admitted_rows"] == 4


def test_negative_training_bucket_is_skipped_without_banning_direction() -> None:
    rows = []
    for index in range(8):
        if index % 2 == 0:
            rows.append(
                _outcome(
                    index=index,
                    direction=Direction.LONG,
                    lead_strategy="trend",
                    score="82",
                    net="0.02",
                )
            )
        else:
            rows.append(
                _outcome(
                    index=index,
                    direction=Direction.SHORT,
                    lead_strategy="trend",
                    score="72",
                    net="-0.02",
                )
            )
    for index in range(8, 16):
        boundary = (
            1_000_000
            + (index + 4) * FIFTEEN_MINUTES_MS
        )
        if index % 2 == 0:
            rows.append(
                _outcome(
                    index=index,
                    direction=Direction.LONG,
                    lead_strategy="trend",
                    score="82",
                    net="0.01",
                    boundary_ms=boundary,
                )
            )
        else:
            rows.append(
                _outcome(
                    index=index,
                    direction=Direction.SHORT,
                    lead_strategy="trend",
                    score="72",
                    net="-0.01",
                    boundary_ms=boundary,
                )
            )

    report = evaluate_cadence_opportunity_learning(
        tuple(rows),
        config=_config(),
    )
    surface = report["surfaces"][f"{FIFTEEN_MINUTES_MS}:{ONE_HOUR_MS}"]
    by_direction = surface["by_direction"]

    assert surface["admitted_rows"] == 4
    assert by_direction["long"]["admitted_rows"] == 4
    assert by_direction["short"]["admitted_rows"] == 0
    assert surface["development_qualified"] is False
    assert Decimal(surface["candidate_net_return_sum"]) > Decimal(
        surface["actual_net_return_sum"]
    )


def test_purge_removes_training_labels_that_overlap_validation_start() -> None:
    config = CadenceOpportunityLearningConfig(
        min_train_rows=3,
        validation_rows=2,
        min_group_rows=1,
        stability_blocks=1,
        min_validation_admitted=1,
        min_block_admitted=1,
        min_validation_per_direction=1,
        min_admitted_per_direction=1,
    )
    rows = (
        _outcome(
            index=0,
            direction=Direction.LONG,
            lead_strategy="trend",
            score="82",
            net="0.01",
            horizon_ms=FIFTEEN_MINUTES_MS,
            boundary_ms=1_000_000,
        ),
        _outcome(
            index=1,
            direction=Direction.SHORT,
            lead_strategy="trend",
            score="82",
            net="0.01",
            horizon_ms=FIFTEEN_MINUTES_MS,
            boundary_ms=2_000_000,
        ),
        _outcome(
            index=2,
            direction=Direction.LONG,
            lead_strategy="trend",
            score="82",
            net="0.01",
            horizon_ms=FIFTEEN_MINUTES_MS,
            boundary_ms=2_900_000,
        ),
        _outcome(
            index=3,
            direction=Direction.LONG,
            lead_strategy="trend",
            score="82",
            net="0.01",
            horizon_ms=FIFTEEN_MINUTES_MS,
            boundary_ms=3_000_000,
        ),
        _outcome(
            index=4,
            direction=Direction.SHORT,
            lead_strategy="trend",
            score="82",
            net="0.01",
            horizon_ms=FIFTEEN_MINUTES_MS,
            boundary_ms=4_000_000,
        ),
    )

    report = evaluate_cadence_opportunity_learning(
        rows,
        config=config,
    )
    surface = report["surfaces"][
        f"{FIFTEEN_MINUTES_MS}:{FIFTEEN_MINUTES_MS}"
    ]

    assert surface["status"] == "not_ready"
    assert surface["training_rows"] == 2
    assert surface["purged_overlap_rows"] == 1
    assert surface["reason"] == "insufficient_purged_training_rows"
