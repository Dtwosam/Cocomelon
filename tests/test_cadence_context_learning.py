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
from cocomelon.research.cadence_context_learning import (
    evaluate_cadence_context_learning,
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


def _feature(
    market: MarketId,
    *,
    as_of_ms: int,
    trend: TrendRegime,
    volatility: VolatilityRegime,
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


def _outcome(
    store: LearningFeatureSnapshotStore,
    *,
    index: int,
    market_name: str,
    direction: Direction,
    trend: TrendRegime,
    volatility: VolatilityRegime,
    net: str,
    boundary_index: int,
) -> ShadowCadenceOutcome:
    market = MarketId("", market_name)
    boundary = 1_000_000 + boundary_index * FIFTEEN_MINUTES_MS
    evaluated = boundary + 1_000
    feature = _feature(
        market,
        as_of_ms=evaluated,
        trend=trend,
        volatility=volatility,
    )
    store.record(feature)
    sample = ShadowCadenceDecision(
        cadence_ms=FIFTEEN_MINUTES_MS,
        boundary_ms=boundary,
        evaluated_at_ms=evaluated,
        market=market,
        direction=direction,
        score=Decimal("82"),
        lead_strategy="trend",
        decision_id=f"{market_name}-{index}",
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


def _config() -> CadenceOpportunityLearningConfig:
    return CadenceOpportunityLearningConfig(
        min_train_rows=16,
        validation_rows=8,
        min_group_rows=2,
        stability_blocks=2,
        min_validation_admitted=4,
        min_block_admitted=2,
        min_validation_per_direction=2,
        min_admitted_per_direction=1,
    )


def test_context_learner_admits_good_regimes_on_both_sides(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    training: list[ShadowCadenceOutcome] = []
    for index in range(4):
        training.append(
            _outcome(
                store,
                index=index,
                market_name=f"LGOOD{index}",
                direction=Direction.LONG,
                trend=TrendRegime.UP,
                volatility=VolatilityRegime.NORMAL,
                net="0.01",
                boundary_index=index,
            )
        )
        training.append(
            _outcome(
                store,
                index=10 + index,
                market_name=f"LBAD{index}",
                direction=Direction.LONG,
                trend=TrendRegime.MIXED,
                volatility=VolatilityRegime.HIGH,
                net="-0.01",
                boundary_index=4 + index,
            )
        )
        training.append(
            _outcome(
                store,
                index=20 + index,
                market_name=f"SGOOD{index}",
                direction=Direction.SHORT,
                trend=TrendRegime.DOWN,
                volatility=VolatilityRegime.NORMAL,
                net="0.008",
                boundary_index=8 + index,
            )
        )
        training.append(
            _outcome(
                store,
                index=30 + index,
                market_name=f"SBAD{index}",
                direction=Direction.SHORT,
                trend=TrendRegime.UP,
                volatility=VolatilityRegime.HIGH,
                net="-0.009",
                boundary_index=12 + index,
            )
        )

    validation = (
        _outcome(
            store,
            index=100,
            market_name="VAL1",
            direction=Direction.LONG,
            trend=TrendRegime.UP,
            volatility=VolatilityRegime.NORMAL,
            net="0.012",
            boundary_index=20,
        ),
        _outcome(
            store,
            index=101,
            market_name="VAL2",
            direction=Direction.LONG,
            trend=TrendRegime.MIXED,
            volatility=VolatilityRegime.HIGH,
            net="-0.02",
            boundary_index=21,
        ),
        _outcome(
            store,
            index=102,
            market_name="VAL3",
            direction=Direction.SHORT,
            trend=TrendRegime.DOWN,
            volatility=VolatilityRegime.NORMAL,
            net="0.01",
            boundary_index=22,
        ),
        _outcome(
            store,
            index=103,
            market_name="VAL4",
            direction=Direction.SHORT,
            trend=TrendRegime.UP,
            volatility=VolatilityRegime.HIGH,
            net="-0.015",
            boundary_index=23,
        ),
        _outcome(
            store,
            index=104,
            market_name="VAL5",
            direction=Direction.LONG,
            trend=TrendRegime.UP,
            volatility=VolatilityRegime.NORMAL,
            net="0.009",
            boundary_index=24,
        ),
        _outcome(
            store,
            index=105,
            market_name="VAL6",
            direction=Direction.LONG,
            trend=TrendRegime.MIXED,
            volatility=VolatilityRegime.HIGH,
            net="-0.012",
            boundary_index=25,
        ),
        _outcome(
            store,
            index=106,
            market_name="VAL7",
            direction=Direction.SHORT,
            trend=TrendRegime.DOWN,
            volatility=VolatilityRegime.NORMAL,
            net="0.007",
            boundary_index=26,
        ),
        _outcome(
            store,
            index=107,
            market_name="VAL8",
            direction=Direction.SHORT,
            trend=TrendRegime.UP,
            volatility=VolatilityRegime.HIGH,
            net="-0.011",
            boundary_index=27,
        ),
    )

    result = evaluate_cadence_context_learning(
        tuple(training) + validation,
        store,
        config=_config(),
    )

    assert result["status"] == "completed"
    assert result["admitted_rows"] == 4
    assert result["development_qualified"] is True
    assert Decimal(result["candidate_net_return_sum"]) > Decimal("0")
    direction = result["by_direction"]
    assert direction["long"]["admitted_rows"] == 2
    assert direction["short"]["admitted_rows"] == 2
    assert all(
        block["passes"] is True
        for block in result["stability_blocks"]
    )

    admitted = result["admitted_cohorts"]
    admitted_keys = {
        (
            item["direction"],
            item["trend_regime"],
            item["volatility_regime"],
        )
        for item in admitted
    }
    assert admitted_keys == {
        ("long", "up", "normal"),
        ("short", "down", "normal"),
    }
    skipped = result["skipped_cohorts"]
    skipped_keys = {
        (
            item["direction"],
            item["trend_regime"],
            item["volatility_regime"],
        )
        for item in skipped
    }
    assert skipped_keys == {
        ("long", "mixed", "high"),
        ("short", "up", "high"),
    }


def test_context_learner_falls_back_when_regime_cell_is_sparse(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    rows: list[ShadowCadenceOutcome] = []
    for index in range(16):
        rows.append(
            _outcome(
                store,
                index=index,
                market_name=f"TRAIN{index}",
                direction=(
                    Direction.LONG
                    if index % 2 == 0
                    else Direction.SHORT
                ),
                trend=(
                    TrendRegime.UP
                    if index % 3
                    else TrendRegime.MIXED
                ),
                volatility=VolatilityRegime.NORMAL,
                net="0.01",
                boundary_index=index,
            )
        )
    for index in range(8):
        rows.append(
            _outcome(
                store,
                index=100 + index,
                market_name=f"VAL{index}",
                direction=(
                    Direction.LONG
                    if index % 2 == 0
                    else Direction.SHORT
                ),
                trend=TrendRegime.UNKNOWN,
                volatility=VolatilityRegime.UNKNOWN,
                net="0.005",
                boundary_index=20 + index,
            )
        )

    result = evaluate_cadence_context_learning(
        tuple(rows),
        store,
        config=_config(),
    )

    assert result["status"] == "completed"
    counts = result["prediction_specificity_counts"]
    assert sum(counts.values()) == 8
    assert any(
        key in counts
        for key in (
            "direction_strategy_score",
            "direction_strategy",
            "direction_score",
            "direction",
            "global",
        )
    )


def test_context_learner_fails_closed_on_missing_snapshot(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    rows: list[ShadowCadenceOutcome] = []
    for index in range(24):
        outcome = _outcome(
            store,
            index=index,
            market_name=f"M{index}",
            direction=(
                Direction.LONG
                if index % 2 == 0
                else Direction.SHORT
            ),
            trend=TrendRegime.UP,
            volatility=VolatilityRegime.NORMAL,
            net="0.005",
            boundary_index=(
                index
                if index < 16
                else index + 4
            ),
        )
        rows.append(outcome)

    missing_id = rows[-1].sample.feature_snapshot_id
    path = store.records_root / f"{missing_id}.json"
    path.unlink()

    result = evaluate_cadence_context_learning(
        tuple(rows),
        store,
        config=_config(),
    )

    assert result["status"] == "not_ready"
    assert result["reason"] == "feature_snapshot_missing"
    assert result["missing_validation_feature_snapshots"] == 1
