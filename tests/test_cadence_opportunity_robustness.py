from __future__ import annotations

from decimal import Decimal

from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.research.cadence_opportunity_learning import (
    CadenceOpportunityLearningConfig,
)
from cocomelon.research.cadence_opportunity_robustness import (
    evaluate_cadence_opportunity_robustness,
)
from cocomelon.research.cadence_shadow import (
    FIFTEEN_MINUTES_MS,
    ONE_HOUR_MS,
    ShadowCadenceDecision,
    ShadowCadenceOutcome,
)


def _outcome(
    *,
    index: int,
    market: str,
    direction: Direction,
    training_net: str,
    boundary_index: int,
) -> ShadowCadenceOutcome:
    boundary = 1_000_000 + boundary_index * FIFTEEN_MINUTES_MS
    sample = ShadowCadenceDecision(
        cadence_ms=FIFTEEN_MINUTES_MS,
        boundary_ms=boundary,
        evaluated_at_ms=boundary + 1_000,
        market=MarketId("", market),
        direction=direction,
        score=Decimal("82"),
        lead_strategy="trend",
        decision_id=f"{market}-{index}",
        feature_snapshot_id=f"feature-{market}-{index}",
        entry_px=Decimal("100"),
        horizon_ms=ONE_HOUR_MS,
        target_end_ms=boundary + ONE_HOUR_MS,
        cost_fraction=Decimal("0.001"),
        off_primary_boundary=False,
    )
    return ShadowCadenceOutcome(
        sample=sample,
        exit_px=Decimal("101"),
        gross_return=Decimal(training_net) + Decimal("0.001"),
        net_return=Decimal(training_net),
    )


def _config() -> CadenceOpportunityLearningConfig:
    return CadenceOpportunityLearningConfig(
        min_train_rows=8,
        validation_rows=4,
        min_group_rows=2,
        stability_blocks=2,
        min_validation_admitted=2,
        min_block_admitted=1,
        min_validation_per_direction=1,
        min_admitted_per_direction=1,
    )


def test_robustness_reports_market_concentration_and_blocks() -> None:
    training = tuple(
        _outcome(
            index=index,
            market=("SOL" if index % 2 == 0 else "BTC"),
            direction=Direction.LONG,
            training_net="0.01",
            boundary_index=index,
        )
        for index in range(8)
    )
    validation = (
        _outcome(
            index=12,
            market="SOL",
            direction=Direction.LONG,
            training_net="0.01",
            boundary_index=12,
        ),
        _outcome(
            index=13,
            market="SOL",
            direction=Direction.LONG,
            training_net="0.01",
            boundary_index=13,
        ),
        _outcome(
            index=14,
            market="BTC",
            direction=Direction.LONG,
            training_net="-0.005",
            boundary_index=14,
        ),
        _outcome(
            index=15,
            market="BTC",
            direction=Direction.LONG,
            training_net="0.01",
            boundary_index=15,
        ),
    )

    result = evaluate_cadence_opportunity_robustness(
        training + validation,
        config=_config(),
    )

    assert result["status"] == "completed"
    assert result["admitted_rows"] == 4
    assert result["candidate_net_return_sum"] == "0.025"
    assert result["market_count"] == 2
    assert result["positive_market_count"] == 2
    assert result["negative_market_count"] == 0
    assert result["largest_abs_market_share"] == "0.8"
    assert (
        result[
            "candidate_net_return_sum_without_largest_positive_market"
        ]
        == "0.005"
    )
    checks = result["diagnostic_checks"]
    assert isinstance(checks, dict)
    assert checks["candidate_sum_positive"] is True
    assert (
        checks["positive_after_removing_largest_positive_market"]
        is True
    )
    assert checks["largest_abs_market_share_lte_half"] is False
    assert checks["all_blocks_have_min_admissions"] is True
    assert checks["all_nonempty_blocks_positive"] is True

    markets = result["markets"]
    assert markets[0]["market"] == "SOL"
    assert markets[0]["net_return_sum"] == "0.02"
    assert markets[1]["market"] == "BTC"
    assert markets[1]["net_return_sum"] == "0.005"


def test_robustness_keeps_negative_training_direction_out() -> None:
    training = tuple(
        _outcome(
            index=index,
            market="SOL",
            direction=(
                Direction.LONG
                if index < 4
                else Direction.SHORT
            ),
            training_net=("0.01" if index < 4 else "-0.01"),
            boundary_index=index,
        )
        for index in range(8)
    )
    validation = (
        _outcome(
            index=12,
            market="SOL",
            direction=Direction.LONG,
            training_net="0.01",
            boundary_index=12,
        ),
        _outcome(
            index=13,
            market="SOL",
            direction=Direction.SHORT,
            training_net="0.02",
            boundary_index=13,
        ),
        _outcome(
            index=14,
            market="BTC",
            direction=Direction.LONG,
            training_net="0.01",
            boundary_index=14,
        ),
        _outcome(
            index=15,
            market="BTC",
            direction=Direction.SHORT,
            training_net="0.02",
            boundary_index=15,
        ),
    )

    result = evaluate_cadence_opportunity_robustness(
        training + validation,
        config=_config(),
    )

    assert result["admitted_rows"] == 2
    cohorts = result["cohorts"]
    assert len(cohorts) == 1
    assert cohorts[0]["direction"] == "long"
    assert cohorts[0]["rows"] == 2
