from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from cocomelon.domain.features import (
    FeatureSnapshot,
    TrendRegime,
    VolatilityRegime,
)
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.risk import (
    ExecutionCostEstimate,
    LiquidityRiskState,
    OpenPositionRisk,
    RiskAccountState,
    RiskHealthState,
    RiskLimits,
    RiskRequest,
)
from cocomelon.domain.strategy import Direction, StrategyDecision
from cocomelon.research.continuous_paper_opening_opportunity import (
    ContinuousPaperOpeningOpportunityEvidence,
    _risk_request_payload,
)
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotStore,
)
from cocomelon.research.profit_lock_execution_shadow import (
    ProfitLockExecutionOutcome,
)
from cocomelon.research.prospective_breakeven_profit_lock import (
    RULE_ID as BREAKEVEN_RULE_ID,
)
from cocomelon.research.prospective_combined_entry_filter import (
    ProspectiveCombinedEntryFilterState,
)
from cocomelon.research.prospective_full_stack_exit_capacity_reflow import (
    prospective_full_stack_exit_capacity_reflow,
)
from cocomelon.research.prospective_momentum_band_entry import (
    EMBARGO_MS as MOMENTUM_EMBARGO_MS,
)
from cocomelon.research.prospective_momentum_band_entry import (
    ProspectiveMomentumBandEntryState,
)
from cocomelon.research.prospective_two_strike_stop_filter import (
    EMBARGO_MS as TWO_STRIKE_EMBARGO_MS,
)
from cocomelon.research.prospective_two_strike_stop_filter import (
    ProspectiveTwoStrikeStopFilterState,
)
from cocomelon.risk.engine import evaluate_risk

START = 30_000_000


def _market(name: str) -> MarketId:
    return MarketId.from_wire_name("", name)


def _feature(
    market: str,
    *,
    as_of_ms: int,
    return_1h: str,
    day_return: str,
) -> FeatureSnapshot:
    return FeatureSnapshot(
        market=_market(market),
        as_of_ms=as_of_ms,
        source_received_at_ms=as_of_ms,
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


def _record_feature(
    store: LearningFeatureSnapshotStore,
    market: str,
    *,
    as_of_ms: int,
    return_1h: str,
    day_return: str,
) -> str:
    snapshot = _feature(
        market,
        as_of_ms=as_of_ms,
        return_1h=return_1h,
        day_return=day_return,
    )
    store.record(snapshot)
    return snapshot.snapshot_id


def _trade(
    feature_snapshot_id: str,
    *,
    opened_at_ms: int,
    closed_at_ms: int,
) -> TradeJournalEntry:
    net = Decimal("-5")
    return TradeJournalEntry(
        market=_market("BTC"),
        direction=Direction.LONG,
        opened_at_ms=opened_at_ms,
        closed_at_ms=closed_at_ms,
        feature_snapshot_id=feature_snapshot_id,
        strategy_decision_id="strategy-btc",
        risk_decision_id="risk-btc",
        opening_plan_id="plan-btc",
        opening_attempt_id="attempt-btc",
        exit_plan_ids=("exit-plan-btc",),
        exit_attempt_ids=("exit-attempt-btc",),
        fill_ids=("open-btc", "close-btc"),
        position_action_ids=("action-btc",),
        funding_event_ids=(),
        initial_stop=Decimal("90"),
        initial_risk_amount=Decimal("10"),
        entry_price=Decimal("100"),
        exit_price=Decimal("95"),
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
        holding_duration_ms=closed_at_ms - opened_at_ms,
        mfe=None,
        mae=None,
        net_r=Decimal("-0.5"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("9995"),
        exit_reason="MARK_STOP_TRIGGERED",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id="continuous-paper-mainnet-v1",
    )


def _request(
    *,
    timestamp_ms: int,
    feature_snapshot_id: str,
) -> RiskRequest:
    decision = StrategyDecision(
        market=_market("SOL"),
        direction=Direction.SHORT,
        score=Decimal("0.7"),
        timestamp_ms=timestamp_ms,
        feature_snapshot_id=feature_snapshot_id,
        lead_strategy="trend",
        invalidation_price=Decimal("110"),
        signal_ids=("signal-sol",),
        reason_codes=("decision_threshold_met",),
    )
    positions = (
        OpenPositionRisk(
            market=_market("BTC"),
            direction=Direction.LONG,
            planned_risk=Decimal("25"),
            notional=Decimal("1000"),
            correlation_bucket="majors",
            entry_price=Decimal("100"),
            stop_price=Decimal("90"),
        ),
        OpenPositionRisk(
            market=_market("ETH"),
            direction=Direction.SHORT,
            planned_risk=Decimal("25"),
            notional=Decimal("1000"),
            correlation_bucket="majors",
            entry_price=Decimal("100"),
            stop_price=Decimal("110"),
        ),
    )
    return RiskRequest(
        strategy_decision=decision,
        entry_reference_price=Decimal("100"),
        correlation_bucket="majors",
        account_state=RiskAccountState(
            equity=Decimal("10000"),
            day_start_equity=Decimal("10000"),
            daily_realized_pnl=Decimal("0"),
            rolling_7d_peak_equity=Decimal("10000"),
            available_margin=Decimal("8000"),
            gross_open_notional=Decimal("2000"),
            consecutive_losses=0,
            last_closed_trade_ms=None,
            as_of_ms=timestamp_ms,
        ),
        open_positions=positions,
        health_state=RiskHealthState(
            market_data_fresh=True,
            account_state_fresh=True,
            execution_health_ok=True,
            state_consistent=True,
            as_of_ms=timestamp_ms,
        ),
        cost_estimate=ExecutionCostEstimate(
            entry_slippage_fraction=Decimal("0.0005"),
            stop_slippage_fraction=Decimal("0.001"),
            round_trip_fee_fraction=Decimal("0.0007"),
        ),
        liquidity_state=LiquidityRiskState(
            entry_side_visible_notional_25bps=Decimal("1000000"),
            exit_side_visible_notional_25bps=Decimal("1000000"),
            venue_max_leverage=Decimal("5"),
            liquidation_price=Decimal("150"),
            venue_min_notional=Decimal("10"),
            as_of_ms=timestamp_ms,
        ),
        limits=RiskLimits(),
        timestamp_ms=timestamp_ms,
    )


def _opportunity(
    request: RiskRequest,
) -> ContinuousPaperOpeningOpportunityEvidence:
    risk = evaluate_risk(request)
    assert risk.approved is False
    assert risk.reason_codes == ("correlation_bucket_exhausted",)
    return ContinuousPaperOpeningOpportunityEvidence(
        strategy_decision_id=request.strategy_decision_id,
        feature_snapshot_id=request.feature_snapshot_id,
        market=request.market.canonical,
        direction=request.direction.value,
        lead_strategy=request.strategy_decision.lead_strategy or "",
        opportunity_timestamp_ms=request.timestamp_ms,
        baseline_risk_approved=False,
        baseline_risk_reason_codes=risk.reason_codes,
        baseline_risk_decision_id=risk.risk_decision_id,
        equity_before=request.account_state.equity,
        risk_request=_risk_request_payload(request),
        instrument={"market": request.market.canonical},
        book={"event_key": "book-sol"},
        rank_observed_at_ms=request.timestamp_ms - 100,
        rank_ordinal=5,
        rank_score=Decimal("0.8"),
        rank_pool_size=20,
        rank_reason_codes=("ranked",),
    )


def _outcome(
    trade: TradeJournalEntry,
    *,
    completion_timestamp_ms: int,
    exact: bool = True,
) -> ProfitLockExecutionOutcome:
    triggered = True
    complete = exact
    candidate_pnl = Decimal("-0.2") if exact else None
    candidate_r = Decimal("-0.02") if exact else None
    return ProfitLockExecutionOutcome(
        trade_id=trade.trade_id,
        opening_plan_id=trade.opening_plan_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        rule_id=BREAKEVEN_RULE_ID,
        activated=True,
        triggered=triggered,
        simulated_close_complete=complete,
        activation_timestamp_ms=trade.opened_at_ms + 20_000,
        trigger_timestamp_ms=trade.opened_at_ms + 30_000,
        completion_timestamp_ms=(
            completion_timestamp_ms if complete else None
        ),
        simulated_filled_quantity=(
            trade.filled_quantity if complete else Decimal("0.5")
        ),
        simulated_average_exit_price=(
            Decimal("100") if complete else None
        ),
        simulated_exit_fees=(
            Decimal("0.2") if complete else Decimal("0.1")
        ),
        attempt_count=1,
        planning_rejection_count=0,
        no_fill_count=0,
        actual_net_pnl=trade.net_pnl,
        actual_net_r=trade.net_r,
        candidate_net_pnl_estimate=candidate_pnl,
        candidate_net_r_estimate=candidate_r,
        delta_net_pnl_estimate=(
            None
            if candidate_pnl is None
            else candidate_pnl - trade.net_pnl
        ),
        delta_net_r_estimate=(
            None
            if candidate_r is None
            else candidate_r - trade.net_r
        ),
        candidate_source=(
            "visible_book_ioc"
            if exact
            else "triggered_incomplete"
        ),
    )


def _states() -> tuple[
    ProspectiveCombinedEntryFilterState,
    ProspectiveTwoStrikeStopFilterState,
    ProspectiveMomentumBandEntryState,
]:
    return (
        ProspectiveCombinedEntryFilterState(started_at_ms=START),
        ProspectiveTwoStrikeStopFilterState(
            frozen_at_ms=START - TWO_STRIKE_EMBARGO_MS
        ),
        ProspectiveMomentumBandEntryState(
            frozen_at_ms=START - MOMENTUM_EMBARGO_MS
        ),
    )


def _run(
    tmp_path: Path,
    *,
    completion_offset_ms: int,
    exact: bool = True,
    entry_decision: str = "ADMIT",
    opportunity_return_1h: str = "-0.02",
) -> object:
    feature_store = LearningFeatureSnapshotStore(tmp_path / "features")
    combined_state, two_state, momentum_state = _states()
    btc_feature = _record_feature(
        feature_store,
        "BTC",
        as_of_ms=START + 999,
        return_1h="0.02",
        day_return="0.08",
    )
    opportunity_ms = START + 150_000
    opportunity_feature = _record_feature(
        feature_store,
        "SOL",
        as_of_ms=opportunity_ms - 1,
        return_1h=opportunity_return_1h,
        day_return="-0.08",
    )
    trade = _trade(
        btc_feature,
        opened_at_ms=START + 1_000,
        closed_at_ms=START + 300_000,
    )
    opportunity = _opportunity(
        _request(
            timestamp_ms=opportunity_ms,
            feature_snapshot_id=opportunity_feature,
        )
    )
    outcome = _outcome(
        trade,
        completion_timestamp_ms=(
            trade.opened_at_ms + completion_offset_ms
        ),
        exact=exact,
    )
    full_stack_summary = {
        "overlap_started_at_ms": START,
        "breakeven_started_at_ms": START,
        "decision_by_trade_id": {
            trade.trade_id: {
                "entry_decision": entry_decision,
                "exit_evaluation": (
                    "EVALUATED"
                    if entry_decision == "ADMIT"
                    else "NOT_APPLICABLE"
                ),
            }
        },
    }
    execution_shadow_state = {
        "outcomes": [outcome.payload()],
    }
    return prospective_full_stack_exit_capacity_reflow(
        (opportunity,),
        (trade,),
        feature_store,
        combined_state,
        two_state,
        momentum_state,
        full_stack_summary,
        execution_shadow_state,
    )


def test_exact_completed_breakeven_releases_capacity(
    tmp_path: Path,
) -> None:
    result = _run(
        tmp_path,
        completion_offset_ms=80_000,
    )

    assert result.summary["baseline_capacity_rejections"] == 1
    assert result.summary["entry_stack_eligible_opportunities"] == 1
    assert result.summary["candidate_early_release_options"] == 1
    assert result.summary["candidate_capacity_release_opportunities"] == 1
    assert result.summary["candidate_early_released_positions"] == 1
    assert result.summary["integrity_clean"] is True
    assert result.release_terminal_contributions == (
        ("plan-btc", Decimal("-0.2")),
    )
    assert result.summary[
        "release_terminal_contribution_by_opening_plan"
    ] == {"plan-btc": "-0.2"}
    assert len(result.releases) == 1
    release = result.releases[0]
    assert release.opportunity_market == "SOL"
    assert release.release_market == "BTC"
    assert release.release_opening_plan_id == "plan-btc"
    assert release.release_block_reason == "breakeven_exact_early_close"


def test_breakeven_close_after_opportunity_does_not_release_capacity(
    tmp_path: Path,
) -> None:
    result = _run(
        tmp_path,
        completion_offset_ms=200_000,
    )

    assert result.summary["candidate_early_release_options"] == 0
    assert result.summary["not_yet_released_positions"] == 1
    assert result.releases == ()


def test_incomplete_breakeven_does_not_release_capacity(
    tmp_path: Path,
) -> None:
    result = _run(
        tmp_path,
        completion_offset_ms=80_000,
        exact=False,
    )

    assert result.summary["candidate_early_release_options"] == 0
    assert result.summary["non_exact_breakeven_outcomes"] == 1
    assert result.summary["integrity_clean"] is True


def test_entry_blocked_position_stays_out_of_exit_release_path(
    tmp_path: Path,
) -> None:
    result = _run(
        tmp_path,
        completion_offset_ms=80_000,
        entry_decision="BLOCK",
    )

    assert result.summary["candidate_early_release_options"] == 0
    assert result.summary["non_admitted_release_positions"] == 1


def test_replacement_opportunity_must_pass_entry_stack(
    tmp_path: Path,
) -> None:
    result = _run(
        tmp_path,
        completion_offset_ms=80_000,
        opportunity_return_1h="-0.005",
    )

    assert result.summary["entry_stack_blocked_opportunities"] == 1
    assert result.summary["entry_stack_eligible_opportunities"] == 0
    assert result.summary["candidate_early_release_options"] == 0
