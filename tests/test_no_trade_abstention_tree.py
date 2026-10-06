from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

pytest.importorskip("sklearn")

from cocomelon import no_trade_abstention_tree_cli
from cocomelon.domain.evaluation import DecisionEvaluationFact
from cocomelon.domain.features import (
    FeatureSnapshot,
    TrendRegime,
    VolatilityRegime,
)
from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.research.continuous_paper_decision_facts import (
    ContinuousPaperDecisionFactStore,
)
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotStore,
)
from cocomelon.research.no_trade_abstention_tree import (
    NoTradeAbstentionTreeConfig,
    NoTradeAbstentionTreeError,
    build_no_trade_abstention_tree_report,
)

HORIZON_MS = 900_000


def _feature(
    market: MarketId,
    *,
    as_of_ms: int,
    positive: bool,
) -> FeatureSnapshot:
    sign = Decimal("1") if positive else Decimal("-1")
    momentum = sign * Decimal("0.03")
    return FeatureSnapshot(
        market=market,
        as_of_ms=as_of_ms,
        source_received_at_ms=as_of_ms,
        schema_version=1,
        day_return=momentum * Decimal("2"),
        funding=sign * Decimal("0.0002"),
        open_interest=Decimal("1000000"),
        day_notional_volume=Decimal("10000000"),
        oi_change_fraction=sign * Decimal("0.02"),
        funding_change=sign * Decimal("0.00001"),
        mark_oracle_dislocation_bps=sign * Decimal("2"),
        return_5m=momentum / Decimal("3"),
        return_15m=momentum,
        return_1h=momentum * Decimal("1.5"),
        return_4h=momentum * Decimal("2"),
        realized_vol_15m=Decimal("0.02"),
        range_expansion_15m=Decimal("1.2"),
        relative_volume_15m=Decimal("1.3"),
        spread_bps=Decimal("2"),
        bid_depth_25bps=Decimal("100000"),
        ask_depth_25bps=Decimal("90000"),
        book_imbalance=sign * Decimal("0.3"),
        book_age_ms=100,
        trend_regime=TrendRegime.UP if positive else TrendRegime.DOWN,
        volatility_regime=VolatilityRegime.NORMAL,
        provenance=("test",),
    )


def _add_outcome(
    decisions: ContinuousPaperDecisionFactStore,
    features: LearningFeatureSnapshotStore,
    *,
    index: int,
    positive: bool,
    reason: str = "no_primary_thesis",
    stage: str = "strategy_abstained",
) -> dict[str, object]:
    market = MarketId("", f"M{index:04d}")
    timestamp_ms = 1_000_000 + index * 2_000_000
    feature = _feature(
        market,
        as_of_ms=timestamp_ms,
        positive=positive,
    )
    features.record(feature)
    fact = DecisionEvaluationFact(
        strategy_decision_id=f"decision-{index}",
        feature_snapshot_id=feature.snapshot_id,
        replay_run_id="continuous-paper-mainnet-v1",
        market=market,
        direction=Direction.NO_TRADE,
        timestamp_ms=timestamp_ms,
        score=Decimal("0"),
        lead_strategy=None,
        signal_ids=(),
        reason_codes=(reason,),
        trend_regime=feature.trend_regime,
        volatility_regime=feature.volatility_regime,
    )
    decisions.record(fact)
    forward_return = Decimal("0.02") if positive else Decimal("-0.02")
    return {
        "decision_fact_id": fact.fact_id,
        "strategy_decision_id": fact.strategy_decision_id,
        "market": market.canonical,
        "decision_timestamp_ms": timestamp_ms,
        "feature_snapshot_id": feature.snapshot_id,
        "feature_as_of_ms": feature.as_of_ms,
        "horizon_ms": HORIZON_MS,
        "target_as_of_ms": timestamp_ms + HORIZON_MS,
        "forward_mark_return": str(forward_return),
        "favored_direction": "long" if positive else "short",
        "reason_codes": [reason],
        "decision_stage": stage,
        "trend_regime": feature.trend_regime.value,
        "volatility_regime": feature.volatility_regime.value,
        "return_15m_sign": "positive" if positive else "negative",
        "return_1h_sign": "positive" if positive else "negative",
        "funding_sign": "positive" if positive else "negative",
        "book_imbalance_sign": "positive" if positive else "negative",
    }


def _report(
    decisions: ContinuousPaperDecisionFactStore,
    features: LearningFeatureSnapshotStore,
    *,
    rows: int = 80,
) -> dict[str, object]:
    outcomes = [
        _add_outcome(
            decisions,
            features,
            index=index,
            positive=index % 2 == 0,
        )
        for index in range(rows)
    ]
    return {
        "decision_state_digest": decisions.state_digest,
        "feature_state_digest": features.state_digest,
        "diagnostic_only": True,
        "hypothetical_pnl": False,
        "execution_authority": False,
        "schema_version": 2,
        "outcomes": outcomes,
    }


def _config() -> NoTradeAbstentionTreeConfig:
    return NoTradeAbstentionTreeConfig(
        max_leaf_nodes=7,
        min_samples_leaf=2,
        learning_rate=Decimal("0.1"),
        max_iter=100,
        l2_regularization=Decimal("0"),
    )


def test_abstention_tree_learns_both_sides_on_later_holdout(
    tmp_path: Path,
) -> None:
    decisions = ContinuousPaperDecisionFactStore(tmp_path / "decisions")
    features = LearningFeatureSnapshotStore(tmp_path / "features")
    source = _report(decisions, features)

    report = build_no_trade_abstention_tree_report(
        source,
        decisions,
        features,
        split_fraction=Decimal("0.70"),
        min_training_rows=40,
        min_validation_rows=20,
        validation_blocks=4,
        tree_config=_config(),
    )

    assert report["research_only"] is True
    assert report["development_qualification_authority"] is False
    assert report["prospective_shadow_authority"] is False
    assert report["promotion_authority"] is False
    assert report["execution_authority"] is False
    assert report["completed_horizons"] == 1

    evaluations = report["evaluations"]
    assert isinstance(evaluations, tuple)
    evaluation = evaluations[0]
    assert evaluation["status"] == "completed"
    assert evaluation["purged_overlap_rows"] == 0
    validation = evaluation["validation"]
    assert validation["predicted_long"] > 0
    assert validation["predicted_short"] > 0
    assert Decimal(validation["direction_hit_rate"]) > Decimal("0.90")
    assert (
        Decimal(validation["mean_directional_mark_return"])
        > Decimal("0")
    )
    assert len(evaluation["validation_blocks"]) == 4
    assert len(evaluation["prediction_sha256"]) == 64


def test_abstention_tree_excludes_tradeability_blocks(
    tmp_path: Path,
) -> None:
    decisions = ContinuousPaperDecisionFactStore(tmp_path / "decisions")
    features = LearningFeatureSnapshotStore(tmp_path / "features")
    source = _report(decisions, features, rows=40)
    blocked = [
        {
            **item,
            "decision_stage": "eligibility_blocked",
        }
        for item in source["outcomes"]
    ]
    source["outcomes"] = [*source["outcomes"], *blocked]

    report = build_no_trade_abstention_tree_report(
        source,
        decisions,
        features,
        min_training_rows=20,
        min_validation_rows=10,
        tree_config=_config(),
    )

    assert report["strategy_abstention_rows"] == 40


def test_abstention_tree_fails_closed_on_relabelled_safety_block(
    tmp_path: Path,
) -> None:
    decisions = ContinuousPaperDecisionFactStore(tmp_path / "decisions")
    features = LearningFeatureSnapshotStore(tmp_path / "features")
    outcome = _add_outcome(
        decisions,
        features,
        index=1,
        positive=True,
        reason="not_deep_ready",
        stage="strategy_abstained",
    )
    source = {
        "decision_state_digest": decisions.state_digest,
        "feature_state_digest": features.state_digest,
        "diagnostic_only": True,
        "hypothetical_pnl": False,
        "execution_authority": False,
        "schema_version": 2,
        "outcomes": [outcome],
    }

    with pytest.raises(
        NoTradeAbstentionTreeError,
        match="NO_TRADE_TREE_NON_STRATEGY_ABSTENTION",
    ):
        build_no_trade_abstention_tree_report(
            source,
            decisions,
            features,
            min_training_rows=1,
            min_validation_rows=1,
            tree_config=_config(),
        )


def test_abstention_tree_cli_emits_authority_negative_report(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    decisions_root = tmp_path / "decisions"
    features_root = tmp_path / "features"
    decisions = ContinuousPaperDecisionFactStore(decisions_root)
    features = LearningFeatureSnapshotStore(features_root)
    source = _report(decisions, features, rows=40)
    path = tmp_path / "forward.json"
    path.write_text(json.dumps(source), encoding="utf-8")

    assert (
        no_trade_abstention_tree_cli.main(
            [
                "--input",
                str(path),
                "--decision-store-dir",
                str(decisions_root),
                "--feature-store-dir",
                str(features_root),
                "--min-training-rows",
                "20",
                "--min-validation-rows",
                "10",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "no-trade-abstention-tree"
    assert payload["model_family"] == (
        "no_trade_abstention_fixed_shallow_tree_v1"
    )
    assert payload["research_only"] is True
    assert payload["promotion_authority"] is False
    assert payload["execution_authority"] is False



def test_abstention_tree_rejects_mismatched_source_digests(
    tmp_path: Path,
) -> None:
    decisions = ContinuousPaperDecisionFactStore(tmp_path / "decisions")
    features = LearningFeatureSnapshotStore(tmp_path / "features")
    source = _report(decisions, features, rows=40)
    source["feature_state_digest"] = "0" * 64

    with pytest.raises(
        NoTradeAbstentionTreeError,
        match="NO_TRADE_TREE_FEATURE_STATE_DIGEST_MISMATCH",
    ):
        build_no_trade_abstention_tree_report(
            source,
            decisions,
            features,
            min_training_rows=20,
            min_validation_rows=10,
            tree_config=_config(),
        )
