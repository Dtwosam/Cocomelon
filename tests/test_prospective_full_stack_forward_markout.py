from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from cocomelon.domain.execution import (
    InstrumentExecutionSpec,
    PaperExecutionConfig,
)
from cocomelon.domain.features import (
    FeatureSnapshot,
    TrendRegime,
    VolatilityRegime,
)
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.risk import (
    LiquidityRiskState,
    RiskAccountState,
    RiskHealthState,
    RiskLimits,
    RiskRequest,
)
from cocomelon.domain.strategy import Direction, StrategyDecision
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.evidence.openings import conservative_cost_estimate
from cocomelon.research.continuous_paper_opening_opportunity import (
    ContinuousPaperOpeningOpportunityEvidence,
    _book_payload,
    _instrument_payload,
    _risk_request_payload,
)
from cocomelon.research.continuous_paper_opening_opportunity_paths import (
    ContinuousPaperOpeningOpportunityPath,
    ContinuousPaperOpeningOpportunityPathMark,
)
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotStore,
)
from cocomelon.research.prospective_combined_entry_filter import (
    ProspectiveCombinedEntryFilterState,
)
from cocomelon.research.prospective_full_stack_forward_markout import (
    prospective_full_stack_forward_markout_summary,
)
from cocomelon.research.prospective_momentum_band_entry import (
    ProspectiveMomentumBandEntryState,
)
from cocomelon.research.prospective_two_strike_stop_filter import (
    ProspectiveTwoStrikeStopFilterState,
)
from cocomelon.risk.engine import evaluate_risk

START = 100_000_000
EMBARGO_MS = 6 * 60 * 60 * 1_000


def _market(name: str) -> MarketId:
    return MarketId.from_wire_name("", name)


def _record_feature(
    store: LearningFeatureSnapshotStore,
    *,
    market: str,
    timestamp_ms: int,
    return_1h: str,
    day_return: str,
) -> str:
    snapshot = FeatureSnapshot(
        market=_market(market),
        as_of_ms=timestamp_ms,
        source_received_at_ms=timestamp_ms,
        schema_version=1,
        day_return=Decimal(day_return),
        funding=Decimal("0"),
        open_interest=Decimal("100"),
        day_notional_volume=Decimal("1000000"),
        oi_change_fraction=None,
        funding_change=None,
        mark_oracle_dislocation_bps=Decimal("0"),
        return_5m=None,
        return_15m=None,
        return_1h=Decimal(return_1h),
        return_4h=None,
        realized_vol_15m=None,
        range_expansion_15m=None,
        relative_volume_15m=None,
        spread_bps=None,
        bid_depth_25bps=None,
        ask_depth_25bps=None,
        book_imbalance=None,
        book_age_ms=None,
        trend_regime=TrendRegime.UNKNOWN,
        volatility_regime=VolatilityRegime.UNKNOWN,
        provenance=("test",),
    )
    store.record(snapshot)
    return snapshot.snapshot_id


def _opportunity(
    *,
    suffix: str,
    market: str,
    direction: Direction,
    timestamp_ms: int,
    feature_snapshot_id: str,
    rank: int = 3,
    lead_strategy: str = "breakout",
    approved: bool = True,
) -> ContinuousPaperOpeningOpportunityEvidence:
    config = PaperExecutionConfig()
    market_id = _market(market)
    invalidation = (
        Decimal("90")
        if direction is Direction.LONG
        else Decimal("110")
    )
    decision = StrategyDecision(
        market=market_id,
        direction=direction,
        score=Decimal("0.8"),
        timestamp_ms=timestamp_ms - config.latency_ms,
        feature_snapshot_id=feature_snapshot_id,
        lead_strategy=lead_strategy,
        invalidation_price=invalidation,
        signal_ids=(f"signal-{suffix}",),
        reason_codes=("decision_threshold_met",),
    )
    request = RiskRequest(
        strategy_decision=decision,
        entry_reference_price=Decimal("100"),
        correlation_bucket="alts",
        account_state=RiskAccountState(
            equity=Decimal("10000"),
            day_start_equity=Decimal("10000"),
            daily_realized_pnl=Decimal("0"),
            rolling_7d_peak_equity=Decimal("10000"),
            available_margin=Decimal("10000"),
            gross_open_notional=Decimal("0"),
            consecutive_losses=(0 if approved else 3),
            last_closed_trade_ms=(
                None if approved else timestamp_ms - 60_000
            ),
            as_of_ms=timestamp_ms,
        ),
        open_positions=(),
        health_state=RiskHealthState(
            market_data_fresh=True,
            account_state_fresh=True,
            execution_health_ok=True,
            state_consistent=True,
            as_of_ms=timestamp_ms,
        ),
        cost_estimate=conservative_cost_estimate(config),
        liquidity_state=LiquidityRiskState(
            entry_side_visible_notional_25bps=Decimal("1000000"),
            exit_side_visible_notional_25bps=Decimal("1000000"),
            venue_max_leverage=Decimal("5"),
            liquidation_price=(
                Decimal("50")
                if direction is Direction.LONG
                else Decimal("150")
            ),
            venue_min_notional=Decimal("10"),
            as_of_ms=timestamp_ms,
        ),
        limits=RiskLimits(),
        timestamp_ms=timestamp_ms,
    )
    baseline = evaluate_risk(request)
    assert baseline.approved is approved
    instrument = InstrumentExecutionSpec(
        market=market_id,
        sz_decimals=2,
        venue_max_leverage=Decimal("5"),
        minimum_order_notional=Decimal("10"),
        metadata_received_at_ms=timestamp_ms,
        metadata_source="fixture",
    )
    book = StreamEvent(
        kind=StreamKind.L2_BOOK,
        market=market_id,
        exchange_time_ms=timestamp_ms,
        receive_time=datetime.fromtimestamp(
            timestamp_ms / 1000,
            tz=UTC,
        ),
        schema_version=1,
        source="fixture",
        event_key=f"book-{suffix}",
        payload={
            "bids": (
                {"px": Decimal("99.95"), "sz": Decimal("1000"), "n": 1},
            ),
            "asks": (
                {"px": Decimal("100.05"), "sz": Decimal("1000"), "n": 1},
            ),
        },
    )
    return ContinuousPaperOpeningOpportunityEvidence(
        strategy_decision_id=decision.decision_id,
        feature_snapshot_id=feature_snapshot_id,
        market=market_id.canonical,
        direction=direction.value,
        lead_strategy=lead_strategy,
        opportunity_timestamp_ms=timestamp_ms,
        baseline_risk_approved=baseline.approved,
        baseline_risk_reason_codes=baseline.reason_codes,
        baseline_risk_decision_id=baseline.risk_decision_id,
        equity_before=request.account_state.equity,
        risk_request=_risk_request_payload(request),
        instrument=_instrument_payload(instrument),
        book=_book_payload(book),
        rank_observed_at_ms=timestamp_ms - 100,
        rank_ordinal=rank,
        rank_score=Decimal("0.9"),
        rank_pool_size=20,
        rank_reason_codes=("fixture",),
    )


def _path(
    evidence: ContinuousPaperOpeningOpportunityEvidence,
    *,
    returns: tuple[str, str, str],
) -> ContinuousPaperOpeningOpportunityPath:
    marks = []
    for horizon_ms, raw_return in zip(
        (300_000, 900_000, 3_600_000),
        returns,
        strict=True,
    ):
        value = Decimal(raw_return)
        price = (
            Decimal("100") * (Decimal("1") + value)
            if evidence.direction == "long"
            else Decimal("100") * (Decimal("1") - value)
        )
        marks.append(
            ContinuousPaperOpeningOpportunityPathMark(
                observed_at_ms=(
                    evidence.opportunity_timestamp_ms + horizon_ms
                ),
                mark_px=price,
                source="fixture",
            )
        )
    return ContinuousPaperOpeningOpportunityPath(
        opportunity_id=evidence.opportunity_id,
        market=evidence.market,
        direction=evidence.direction,
        opportunity_timestamp_ms=evidence.opportunity_timestamp_ms,
        max_path_age_ms=3_600_000,
        max_completion_lag_ms=120_000,
        marks=tuple(marks),
    )


def _trade(
    suffix: str,
    *,
    market: str,
    direction: Direction,
    opened_at_ms: int,
    pnl: str,
) -> TradeJournalEntry:
    net = Decimal(pnl)
    return TradeJournalEntry(
        market=_market(market),
        direction=direction,
        opened_at_ms=opened_at_ms,
        closed_at_ms=opened_at_ms + 60_000,
        feature_snapshot_id=f"trade-feature-{suffix}",
        strategy_decision_id=f"trade-strategy-{suffix}",
        risk_decision_id=f"trade-risk-{suffix}",
        opening_plan_id=f"trade-plan-{suffix}",
        opening_attempt_id=f"trade-attempt-{suffix}",
        exit_plan_ids=(f"trade-exit-plan-{suffix}",),
        exit_attempt_ids=(f"trade-exit-attempt-{suffix}",),
        fill_ids=(f"trade-open-{suffix}", f"trade-close-{suffix}"),
        position_action_ids=(f"trade-action-{suffix}",),
        funding_event_ids=(),
        initial_stop=(
            Decimal("90")
            if direction is Direction.LONG
            else Decimal("110")
        ),
        initial_risk_amount=Decimal("10"),
        entry_price=Decimal("100"),
        exit_price=Decimal("99"),
        filled_quantity=Decimal("1"),
        gross_realized_pnl=net,
        entry_fees=Decimal("0"),
        exit_fees=Decimal("0"),
        funding_cash_pnl=Decimal("0"),
        net_pnl=net,
        entry_slippage_amount=Decimal("0"),
        exit_slippage_amount=Decimal("0"),
        entry_slippage_fraction=Decimal("0"),
        exit_slippage_fraction=Decimal("0"),
        holding_duration_ms=60_000,
        mfe=None,
        mae=None,
        net_r=net / Decimal("10"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10000") + net,
        exit_reason="MARK_STOP_TRIGGERED",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id="continuous-paper-mainnet-v1",
    )


def _states() -> tuple[
    ProspectiveCombinedEntryFilterState,
    ProspectiveTwoStrikeStopFilterState,
    ProspectiveMomentumBandEntryState,
]:
    return (
        ProspectiveCombinedEntryFilterState(started_at_ms=START),
        ProspectiveTwoStrikeStopFilterState(
            frozen_at_ms=START - EMBARGO_MS
        ),
        ProspectiveMomentumBandEntryState(
            frozen_at_ms=START - EMBARGO_MS
        ),
    )


def test_full_stack_markout_separates_final_admit_and_blocks(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    combined, two_strike, momentum = _states()
    combined_feature = _record_feature(
        store,
        market="SOL",
        timestamp_ms=START + 900,
        return_1h="0.03",
        day_return="0.05",
    )
    momentum_block_feature = _record_feature(
        store,
        market="ETH",
        timestamp_ms=START + 1_900,
        return_1h="0.005",
        day_return="0.03",
    )
    admit_feature = _record_feature(
        store,
        market="BTC",
        timestamp_ms=START + 2_900,
        return_1h="-0.03",
        day_return="-0.05",
    )
    combined_block = _opportunity(
        suffix="combined",
        market="SOL",
        direction=Direction.LONG,
        timestamp_ms=START + 1_000,
        feature_snapshot_id=combined_feature,
        lead_strategy="trend",
    )
    momentum_block = _opportunity(
        suffix="momentum",
        market="ETH",
        direction=Direction.LONG,
        timestamp_ms=START + 2_000,
        feature_snapshot_id=momentum_block_feature,
    )
    admit = _opportunity(
        suffix="admit",
        market="BTC",
        direction=Direction.SHORT,
        timestamp_ms=START + 3_000,
        feature_snapshot_id=admit_feature,
    )

    result = prospective_full_stack_forward_markout_summary(
        (combined_block, momentum_block, admit),
        (
            _path(combined_block, returns=("-0.01", "-0.02", "-0.03")),
            _path(momentum_block, returns=("-0.02", "-0.03", "-0.04")),
            _path(admit, returns=("0.01", "0.02", "0.03")),
        ),
        (),
        store,
        combined,
        two_strike,
        momentum,
    )

    assert result["stack_risk_approved_evaluated"] == 3
    assert result["stack_admitted"] == 1
    assert result["stack_blocked"] == 2
    layers = result["block_layer_counts"]
    assert layers == {"combined": 1, "momentum": 1, "none": 1}
    rows = result["rows"]
    assert isinstance(rows, list)
    decisions = {
        row["market"]: (row["stack_decision"], row["block_layer"])
        for row in rows
    }
    assert decisions["SOL"] == ("BLOCK", "combined")
    assert decisions["ETH"] == ("BLOCK", "momentum")
    assert decisions["BTC"] == ("ADMIT", "none")

    carveout = result["long_trend_carveout"]
    assert isinstance(carveout, dict)
    assert carveout["evaluated"] == 3
    assert carveout["admitted"] == 2
    assert carveout["blocked"] == 1
    assert carveout["block_layer_counts"] == {
        "momentum": 1,
        "none": 2,
    }
    carveout_decisions = {
        row["market"]: (
            row["long_trend_carveout_decision"],
            row["long_trend_carveout_block_layer"],
        )
        for row in rows
    }
    assert carveout_decisions["SOL"] == ("ADMIT", "none")
    assert carveout_decisions["ETH"] == ("BLOCK", "momentum")
    assert carveout_decisions["BTC"] == ("ADMIT", "none")

    horizons = result["horizons"]
    assert isinstance(horizons, dict)
    one_hour = horizons["3600000"]
    assert isinstance(one_hour, dict)
    admit_summary = one_hour["admit"]
    block_summary = one_hour["block"]
    robustness = one_hour["spread_robustness"]
    assert isinstance(admit_summary, dict)
    assert isinstance(block_summary, dict)
    assert isinstance(robustness, dict)
    assert admit_summary["mean_directional_return"] == "0.03"
    assert block_summary["mean_directional_return"] == "-0.035"
    assert robustness["admit_minus_block_mean_return"] == "0.065"
    assert result["changes_closed_trade_readiness_gate"] is False


def test_full_stack_markout_applies_two_strike_layer(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    combined, two_strike, momentum = _states()
    feature = _record_feature(
        store,
        market="SOL",
        timestamp_ms=START + 3_000_900,
        return_1h="0.03",
        day_return="0.05",
    )
    first = _trade(
        "first",
        market="SOL",
        direction=Direction.LONG,
        opened_at_ms=START + 100_000,
        pnl="-4",
    )
    second = _trade(
        "second",
        market="SOL",
        direction=Direction.LONG,
        opened_at_ms=START + 1_000_000,
        pnl="-5",
    )
    opportunity = _opportunity(
        suffix="two-strike",
        market="SOL",
        direction=Direction.LONG,
        timestamp_ms=START + 3_001_000,
        feature_snapshot_id=feature,
    )

    result = prospective_full_stack_forward_markout_summary(
        (opportunity,),
        (_path(opportunity, returns=("-0.01", "-0.02", "-0.03")),),
        (first, second),
        store,
        combined,
        two_strike,
        momentum,
    )

    rows = result["rows"]
    assert isinstance(rows, list)
    assert len(rows) == 1
    assert rows[0]["two_strike_prior_strikes"] == 2
    assert rows[0]["stack_decision"] == "BLOCK"
    assert rows[0]["block_layer"] == "two_strike"
    assert rows[0]["momentum_decision"] is None


def test_full_stack_markout_reports_integrity_and_risk_exclusions(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    combined, two_strike, momentum = _states()
    feature = _record_feature(
        store,
        market="ETH",
        timestamp_ms=START + 900,
        return_1h="-0.03",
        day_return="-0.05",
    )
    risk_rejected = _opportunity(
        suffix="risk",
        market="ETH",
        direction=Direction.SHORT,
        timestamp_ms=START + 1_000,
        feature_snapshot_id=feature,
        approved=False,
    )

    risk_rejected = replace(
        risk_rejected,
        baseline_risk_reason_codes=("weekly_drawdown_lockout",),
    )
    result = prospective_full_stack_forward_markout_summary(
        (risk_rejected,),
        (_path(risk_rejected, returns=("0.01", "0.02", "0.03")),),
        (),
        store,
        combined,
        two_strike,
        momentum,
    )

    assert result["prospective_opportunities"] == 1
    assert result["baseline_risk_rejected"] == 1
    assert result["stack_risk_approved_evaluated"] == 0
    assert result["integrity_clean"] is True
    assert result["risk_rejected_stack_evaluated"] == 1
    assert result["risk_rejected_stack_admitted"] == 1
    assert result["risk_rejected_stack_blocked"] == 0
    assert result["risk_rejected_reason_counts"] == {
        "weekly_drawdown_lockout": 1
    }
    assert result["risk_rejected_integrity_clean"] is True
    rejected_horizons = result["risk_rejected_horizons"]
    assert isinstance(rejected_horizons, dict)
    one_hour = rejected_horizons["3600000"]
    assert isinstance(one_hour, dict)
    admit = one_hour["admit"]
    assert isinstance(admit, dict)
    assert admit["settled"] == 1
    assert admit["mean_directional_return"] == "0.03"
    by_reason = one_hour["by_risk_reason"]
    assert isinstance(by_reason, dict)
    weekly = by_reason["weekly_drawdown_lockout"]
    assert weekly["settled"] == 1
    assert weekly["mean_directional_return"] == "0.03"
    assert one_hour["changes_readiness_gate"] is False


def test_risk_rejected_long_trend_carveout_runs_downstream_stack(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    combined, two_strike, momentum = _states()
    feature = _record_feature(
        store,
        market="SOL",
        timestamp_ms=START + 900,
        return_1h="0.03",
        day_return="0.05",
    )
    rejected = _opportunity(
        suffix="risk-long-trend",
        market="SOL",
        direction=Direction.LONG,
        timestamp_ms=START + 1_000,
        feature_snapshot_id=feature,
        lead_strategy="trend",
        approved=False,
    )
    rejected = replace(
        rejected,
        baseline_risk_reason_codes=("weekly_drawdown_lockout",),
    )

    result = prospective_full_stack_forward_markout_summary(
        (rejected,),
        (_path(rejected, returns=("0.01", "0.02", "0.03")),),
        (),
        store,
        combined,
        two_strike,
        momentum,
    )

    rows = result["risk_rejected_rows"]
    assert isinstance(rows, list)
    assert len(rows) == 1
    row = rows[0]
    assert row["stack_decision"] == "BLOCK"
    assert row["block_layer"] == "combined"
    assert row["combined_block_reason"] == "long_trend"
    assert row["momentum_decision"] is None
    assert row["long_trend_carveout_decision"] == "ADMIT"
    assert row["long_trend_carveout_block_layer"] == "none"
    assert (
        row["long_trend_carveout_momentum_decision"]
        == "ADMIT"
    )
    assert (
        row["long_trend_carveout_momentum_reason"]
        == "momentum_band_pass"
    )
    stop_path = row["long_trend_carveout_stop_path"]
    assert stop_path["original_stop_price"] == "90"
    assert stop_path["entry_reference_price"] == "100"
    assert (
        stop_path["horizons"]["300000"]["status"]
        == "observed_path_survivor"
    )
    assert (
        stop_path["horizons"]["3600000"][
            "survived_observed_marks_to_horizon"
        ]
        is True
    )

    carveout = result["risk_rejected_long_trend_carveout"]
    assert isinstance(carveout, dict)
    assert carveout["evaluated"] == 1
    assert carveout["admitted"] == 1
    assert carveout["blocked"] == 0
    assert carveout["integrity_clean"] is True
    one_hour = carveout["horizons"]["3600000"]
    assert one_hour["admit"]["settled"] == 1
    assert one_hour["admit"]["mean_directional_return"] == "0.03"
    readiness = one_hour["review_readiness"]
    assert readiness["changes_closed_trade_readiness_gate"] is False


def test_long_trend_carveout_stop_path_records_early_crossing(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    combined, two_strike, momentum = _states()
    feature = _record_feature(
        store,
        market="SOL",
        timestamp_ms=START + 900,
        return_1h="0.03",
        day_return="0.05",
    )
    rejected = _opportunity(
        suffix="risk-long-trend-stop",
        market="SOL",
        direction=Direction.LONG,
        timestamp_ms=START + 1_000,
        feature_snapshot_id=feature,
        lead_strategy="trend",
        approved=False,
    )
    rejected = replace(
        rejected,
        baseline_risk_reason_codes=("weekly_drawdown_lockout",),
    )
    path = _path(rejected, returns=("0.01", "0.02", "0.03"))
    path = replace(
        path,
        marks=(
            ContinuousPaperOpeningOpportunityPathMark(
                observed_at_ms=(
                    rejected.opportunity_timestamp_ms + 60_000
                ),
                mark_px=Decimal("89"),
                source="fixture",
            ),
            *path.marks,
        ),
    )

    result = prospective_full_stack_forward_markout_summary(
        (rejected,),
        (path,),
        (),
        store,
        combined,
        two_strike,
        momentum,
    )

    row = result["risk_rejected_rows"][0]
    stop_path = row["long_trend_carveout_stop_path"]
    for horizon in ("300000", "900000", "3600000"):
        item = stop_path["horizons"][horizon]
        assert item["status"] == "observed_stop_crossing"
        assert item["stop_crossed"] is True
        assert item["first_stop_cross_at_ms"] == (
            rejected.opportunity_timestamp_ms + 60_000
        )
        assert item["first_stop_cross_mark_px"] == "89"
        assert item["time_to_stop_ms"] == 60_000
        assert item["survived_observed_marks_to_horizon"] is False


def test_risk_rejected_integrity_is_isolated_from_candidate_readiness(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    combined, two_strike, momentum = _states()
    approved_feature = _record_feature(
        store,
        market="BTC",
        timestamp_ms=START + 900,
        return_1h="-0.03",
        day_return="-0.05",
    )
    rejected_feature = _record_feature(
        store,
        market="ETH",
        timestamp_ms=START + 1_900,
        return_1h="-0.03",
        day_return="-0.05",
    )
    approved = _opportunity(
        suffix="approved-integrity",
        market="BTC",
        direction=Direction.SHORT,
        timestamp_ms=START + 1_000,
        feature_snapshot_id=approved_feature,
    )
    rejected = _opportunity(
        suffix="rejected-integrity",
        market="ETH",
        direction=Direction.SHORT,
        timestamp_ms=START + 2_000,
        feature_snapshot_id=rejected_feature,
        approved=False,
    )
    rejected = replace(
        rejected,
        rank_observed_at_ms=None,
        rank_ordinal=None,
        rank_score=None,
        rank_pool_size=None,
        rank_reason_codes=(),
    )

    result = prospective_full_stack_forward_markout_summary(
        (approved, rejected),
        (_path(approved, returns=("0.01", "0.02", "0.03")),),
        (),
        store,
        combined,
        two_strike,
        momentum,
    )

    assert result["stack_risk_approved_evaluated"] == 1
    assert result["integrity_clean"] is True
    assert result["risk_rejected_stack_evaluated"] == 0
    assert result["risk_rejected_missing_rank"] == 1
    assert result["risk_rejected_integrity_clean"] is False
    assert result["risk_rejected_integrity_last_miss_at_ms"] == (
        rejected.opportunity_timestamp_ms
    )
    horizons = result["horizons"]
    assert isinstance(horizons, dict)
    one_hour = horizons["3600000"]
    assert isinstance(one_hour, dict)
    readiness = one_hour["review_readiness"]
    assert isinstance(readiness, dict)
    assert readiness["integrity_clean"] is True
