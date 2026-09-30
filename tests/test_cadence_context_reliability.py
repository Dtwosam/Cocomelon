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
from cocomelon.research.cadence_context_reliability import (
    CadenceContextReliabilityConfig,
    evaluate_cadence_context_reliability,
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
    direction: Direction,
    score: str,
    trend: TrendRegime,
    volatility: VolatilityRegime,
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
        trend_regime=trend,
        volatility_regime=volatility,
        provenance=("test",),
    )
    store.record(feature)
    sample = ShadowCadenceDecision(
        cadence_ms=FIFTEEN_MINUTES_MS,
        boundary_ms=boundary,
        evaluated_at_ms=evaluated,
        market=market,
        direction=direction,
        score=Decimal(score),
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


def _learning_config() -> CadenceOpportunityLearningConfig:
    return CadenceOpportunityLearningConfig(
        min_train_rows=32,
        validation_rows=8,
        min_group_rows=25,
        stability_blocks=2,
        min_validation_admitted=4,
        min_block_admitted=2,
        min_validation_per_direction=2,
        min_admitted_per_direction=1,
    )


def test_reliability_policy_uses_sparse_exact_context_and_edge_margin(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    rows: list[ShadowCadenceOutcome] = []

    training_specs = (
        (Direction.LONG, "82", TrendRegime.UP, VolatilityRegime.HIGH, "0.01"),
        (Direction.LONG, "82", TrendRegime.UP, VolatilityRegime.LOW, "-0.004"),
        (Direction.SHORT, "82", TrendRegime.DOWN, VolatilityRegime.LOW, "0.0002"),
        (Direction.SHORT, "72", TrendRegime.DOWN, VolatilityRegime.LOW, "0.00005"),
    )
    index = 0
    for direction, score, trend, volatility, net in training_specs:
        for _ in range(8):
            rows.append(
                _row(
                    store,
                    index=index,
                    boundary_index=index,
                    direction=direction,
                    score=score,
                    trend=trend,
                    volatility=volatility,
                    net=net,
                )
            )
            index += 1

    validation_specs = (
        (Direction.LONG, "82", TrendRegime.UP, VolatilityRegime.HIGH, "0.02"),
        (Direction.LONG, "82", TrendRegime.UP, VolatilityRegime.LOW, "-0.01"),
        (Direction.SHORT, "82", TrendRegime.DOWN, VolatilityRegime.LOW, "0.01"),
        (Direction.SHORT, "72", TrendRegime.DOWN, VolatilityRegime.LOW, "-0.01"),
        (Direction.LONG, "82", TrendRegime.UP, VolatilityRegime.HIGH, "0.02"),
        (Direction.LONG, "82", TrendRegime.UP, VolatilityRegime.LOW, "-0.01"),
        (Direction.SHORT, "82", TrendRegime.DOWN, VolatilityRegime.LOW, "0.01"),
        (Direction.SHORT, "72", TrendRegime.DOWN, VolatilityRegime.LOW, "-0.01"),
    )
    for offset, spec in enumerate(validation_specs):
        direction, score, trend, volatility, net = spec
        rows.append(
            _row(
                store,
                index=100 + offset,
                boundary_index=36 + offset,
                direction=direction,
                score=score,
                trend=trend,
                volatility=volatility,
                net=net,
            )
        )

    result = evaluate_cadence_context_reliability(
        tuple(rows),
        store,
        learning_config=_learning_config(),
        reliability_config=CadenceContextReliabilityConfig(
            min_exact_context_rows=8,
            admission_margin=Decimal("0.0001"),
        ),
    )

    assert result["status"] == "completed"
    assert result["admitted_rows"] == 4
    assert result["development_qualified"] is True
    assert Decimal(result["candidate_net_return_sum"]) == Decimal("0.06")
    assert (
        Decimal(result["reliability_minus_baseline_net_return_sum"])
        > Decimal("0")
    )

    direction = result["by_direction"]
    assert direction["long"]["admitted_rows"] == 2
    assert direction["short"]["admitted_rows"] == 2

    admitted = result["admitted_cohorts"]
    assert {
        (
            item["direction"],
            item["score"],
            item["trend_regime"],
            item["volatility_regime"],
        )
        for item in admitted
    } == {
        ("long", "82", "up", "high"),
        ("short", "82", "down", "low"),
    }

    skipped = result["skipped_cohorts"]
    assert {
        (
            item["direction"],
            item["score"],
            item["trend_regime"],
            item["volatility_regime"],
        )
        for item in skipped
    } == {
        ("long", "82", "up", "low"),
        ("short", "72", "down", "low"),
    }


def test_reliability_config_rejects_invalid_values() -> None:
    import pytest

    with pytest.raises(ValueError, match="min_exact_context_rows"):
        CadenceContextReliabilityConfig(min_exact_context_rows=0)
    with pytest.raises(ValueError, match="admission_margin"):
        CadenceContextReliabilityConfig(
            admission_margin=Decimal("-0.0001")
        )
