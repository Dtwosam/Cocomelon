from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from cocomelon.domain.evaluation import DecisionEvaluationFact
from cocomelon.domain.features import FeatureSnapshot, TrendRegime, VolatilityRegime
from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.research.continuous_paper_decision_facts import (
    ContinuousPaperDecisionFactStore,
)
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotStore,
)
from cocomelon.research.no_trade_forward_opportunity import (
    build_no_trade_forward_opportunity_report,
)

MARKET = MarketId("", "HYPE")


def _snapshot(
    *,
    as_of_ms: int,
    return_15m: str,
    return_1h: str,
    funding: str = "0.0001",
    imbalance: str = "0.2",
) -> FeatureSnapshot:
    return FeatureSnapshot(
        market=MARKET,
        as_of_ms=as_of_ms,
        source_received_at_ms=as_of_ms,
        schema_version=1,
        day_return=Decimal("0.01"),
        funding=Decimal(funding),
        open_interest=Decimal("1000000"),
        day_notional_volume=Decimal("5000000"),
        oi_change_fraction=Decimal("0.01"),
        funding_change=Decimal("0"),
        mark_oracle_dislocation_bps=Decimal("1"),
        return_5m=Decimal("0.001"),
        return_15m=Decimal(return_15m),
        return_1h=Decimal(return_1h),
        return_4h=Decimal("0.04"),
        realized_vol_15m=Decimal("0.02"),
        range_expansion_15m=Decimal("1.1"),
        relative_volume_15m=Decimal("1.2"),
        spread_bps=Decimal("2"),
        bid_depth_25bps=Decimal("100000"),
        ask_depth_25bps=Decimal("90000"),
        book_imbalance=Decimal(imbalance),
        book_age_ms=100,
        trend_regime=TrendRegime.UP,
        volatility_regime=VolatilityRegime.NORMAL,
        provenance=("test",),
    )


def _fact(
    feature: FeatureSnapshot,
    *,
    direction: Direction = Direction.NO_TRADE,
    reason: str = "no_primary_thesis",
) -> DecisionEvaluationFact:
    return DecisionEvaluationFact(
        strategy_decision_id=f"strategy-{feature.snapshot_id}",
        feature_snapshot_id=feature.snapshot_id,
        replay_run_id="continuous-paper-mainnet-v1",
        market=feature.market,
        direction=direction,
        timestamp_ms=feature.as_of_ms,
        score=Decimal("0") if direction is Direction.NO_TRADE else Decimal("70"),
        lead_strategy=None if direction is Direction.NO_TRADE else "trend",
        signal_ids=() if direction is Direction.NO_TRADE else ("signal",),
        reason_codes=(reason,),
        trend_regime=feature.trend_regime,
        volatility_regime=feature.volatility_regime,
    )


def test_no_trade_forward_report_uses_exact_future_feature_horizons(
    tmp_path: Path,
) -> None:
    decisions = ContinuousPaperDecisionFactStore(tmp_path / "decisions")
    features = LearningFeatureSnapshotStore(tmp_path / "features")
    current = _snapshot(
        as_of_ms=1_000_000,
        return_15m="-0.01",
        return_1h="-0.02",
    )
    future_15m = _snapshot(
        as_of_ms=current.as_of_ms + 900_000,
        return_15m="0.02",
        return_1h="0.01",
    )
    future_1h = _snapshot(
        as_of_ms=current.as_of_ms + 3_600_000,
        return_15m="-0.01",
        return_1h="-0.03",
    )
    for snapshot in (current, future_15m, future_1h):
        features.record(snapshot)
    decisions.record(_fact(current))

    report = build_no_trade_forward_opportunity_report(
        decisions,
        features,
        as_of_ms=future_1h.as_of_ms,
        min_group_rows=1,
    )
    payload = report.to_dict()

    assert payload["no_trade_decisions"] == 1
    assert payload["resolved_decisions"] == 1
    assert payload["hypothetical_pnl"] is False
    assert payload["cost_complete"] is False
    assert payload["execution_authority"] is False

    outcomes = payload["outcomes"]
    assert isinstance(outcomes, tuple)
    assert len(outcomes) == 2
    by_horizon = {item["horizon_ms"]: item for item in outcomes}
    assert by_horizon[900_000]["forward_mark_return"] == "0.02"
    assert by_horizon[900_000]["favored_direction"] == "long"
    assert by_horizon[900_000]["decision_stage"] == "strategy_abstained"
    assert by_horizon[3_600_000]["forward_mark_return"] == "-0.03"
    assert by_horizon[3_600_000]["favored_direction"] == "short"

    horizons = payload["horizon_summary"]
    assert isinstance(horizons, dict)
    assert horizons["900000"]["favored_long"] == 1
    assert horizons["3600000"]["favored_short"] == 1

    marginal = payload["marginal_summary"]
    assert isinstance(marginal, dict)
    assert marginal["trend_regime"][0]["value"] == "up"
    reasons = payload["reason_summary"]
    assert isinstance(reasons, dict)
    assert reasons["reason_code"][0]["reason_code"] == "no_primary_thesis"
    stages = payload["decision_stage_summary"]
    assert isinstance(stages, tuple)
    assert {
        (item["horizon_ms"], item["decision_stage"], item["outcomes"])
        for item in stages
    } == {
        (900_000, "strategy_abstained", 1),
        (3_600_000, "strategy_abstained", 1),
    }


def test_no_trade_forward_report_keeps_right_censoring_explicit(
    tmp_path: Path,
) -> None:
    decisions = ContinuousPaperDecisionFactStore(tmp_path / "decisions")
    features = LearningFeatureSnapshotStore(tmp_path / "features")
    current = _snapshot(
        as_of_ms=1_000_000,
        return_15m="0.01",
        return_1h="0.02",
    )
    features.record(current)
    decisions.record(_fact(current))

    report = build_no_trade_forward_opportunity_report(
        decisions,
        features,
        as_of_ms=current.as_of_ms + 100_000,
    )

    assert report.outcomes == ()
    assert report.censored_by_horizon == {
        "900000": 1,
        "3600000": 1,
    }


def test_directional_decisions_are_not_labeled_as_no_trade(
    tmp_path: Path,
) -> None:
    decisions = ContinuousPaperDecisionFactStore(tmp_path / "decisions")
    features = LearningFeatureSnapshotStore(tmp_path / "features")
    current = _snapshot(
        as_of_ms=1_000_000,
        return_15m="0.01",
        return_1h="0.02",
    )
    features.record(current)
    decisions.record(_fact(current, direction=Direction.LONG))

    report = build_no_trade_forward_opportunity_report(
        decisions,
        features,
        as_of_ms=current.as_of_ms + 3_600_000,
    )

    assert report.decision_records == 1
    assert report.no_trade_decisions == 0
    assert report.outcomes == ()



def test_no_trade_forward_report_separates_eligibility_blocks(
    tmp_path: Path,
) -> None:
    decisions = ContinuousPaperDecisionFactStore(tmp_path / "decisions")
    features = LearningFeatureSnapshotStore(tmp_path / "features")
    current = _snapshot(
        as_of_ms=1_000_000,
        return_15m="0.01",
        return_1h="0.02",
    )
    future = _snapshot(
        as_of_ms=current.as_of_ms + 900_000,
        return_15m="0.03",
        return_1h="0.01",
    )
    features.record(current)
    features.record(future)
    decisions.record(_fact(current, reason="not_deep_ready"))

    report = build_no_trade_forward_opportunity_report(
        decisions,
        features,
        as_of_ms=future.as_of_ms,
        min_group_rows=1,
    )

    assert len(report.outcomes) == 1
    assert report.outcomes[0].decision_stage == "eligibility_blocked"
    assert report.decision_stage_summary == (
        {
            "horizon_ms": 900_000,
            "decision_stage": "eligibility_blocked",
            "outcomes": 1,
            "favored_long": 1,
            "favored_short": 0,
            "flat": 0,
            "mean_forward_mark_return": "0.03",
            "mean_absolute_forward_mark_return": "0.03",
            "sample_sufficient_for_diagnostics": True,
            "strategy_authority": False,
        },
    )
