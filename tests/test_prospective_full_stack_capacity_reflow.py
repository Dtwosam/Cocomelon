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
from cocomelon.research.continuous_paper_learning import (
    ContinuousPaperOpeningLineage,
    ContinuousPaperRuntimeIdentity,
)
from cocomelon.research.continuous_paper_opening_opportunity import (
    ContinuousPaperOpeningOpportunityEvidence,
    _risk_request_payload,
)
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotStore,
)
from cocomelon.research.prospective_combined_entry_filter import (
    ProspectiveCombinedEntryFilterState,
)
from cocomelon.research.prospective_full_stack_capacity_reflow import (
    prospective_full_stack_capacity_reflow,
)
from cocomelon.research.prospective_momentum_band_entry import (
    ProspectiveMomentumBandEntryState,
)
from cocomelon.research.prospective_two_strike_stop_filter import (
    ProspectiveTwoStrikeStopFilterState,
)
from cocomelon.risk.engine import evaluate_risk


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
    suffix: str,
    *,
    market: str,
    direction: Direction,
    opened_at_ms: int,
    closed_at_ms: int,
    feature_snapshot_id: str,
    pnl: str,
) -> TradeJournalEntry:
    net = Decimal(pnl)
    return TradeJournalEntry(
        market=_market(market),
        direction=direction,
        opened_at_ms=opened_at_ms,
        closed_at_ms=closed_at_ms,
        feature_snapshot_id=feature_snapshot_id,
        strategy_decision_id=f"strategy-{suffix}",
        risk_decision_id=f"risk-{suffix}",
        opening_plan_id=f"plan-{suffix}",
        opening_attempt_id=f"attempt-{suffix}",
        exit_plan_ids=(f"exit-plan-{suffix}",),
        exit_attempt_ids=(f"exit-attempt-{suffix}",),
        fill_ids=(f"open-{suffix}", f"close-{suffix}"),
        position_action_ids=(f"action-{suffix}",),
        funding_event_ids=(),
        initial_stop=(
            Decimal("90")
            if direction is Direction.LONG
            else Decimal("110")
        ),
        initial_risk_amount=Decimal("10"),
        entry_price=Decimal("100"),
        exit_price=Decimal("100") + net,
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
        net_r=net / Decimal("10"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10000") + net,
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
    *,
    rank_ordinal: int = 5,
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
        rank_ordinal=rank_ordinal,
        rank_score=Decimal("0.8"),
        rank_pool_size=20,
        rank_reason_codes=("ranked",),
    )


def _runtime() -> ContinuousPaperRuntimeIdentity:
    return ContinuousPaperRuntimeIdentity(
        worker_run_id=123,
        worker_run_attempt=1,
        worker_head_sha="a" * 40,
    )


def _states() -> tuple[
    ProspectiveCombinedEntryFilterState,
    ProspectiveTwoStrikeStopFilterState,
    ProspectiveMomentumBandEntryState,
]:
    return (
        ProspectiveCombinedEntryFilterState(started_at_ms=20_000_000),
        ProspectiveTwoStrikeStopFilterState(frozen_at_ms=0),
        ProspectiveMomentumBandEntryState(frozen_at_ms=0),
    )


def _summaries(
    btc: TradeJournalEntry,
    eth: TradeJournalEntry,
    *,
    omit_btc_two: bool = False,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    combined = {
        "decision_block_reason_by_trade_id": {
            btc.trade_id: "long_trend",
            eth.trade_id: None,
        }
    }
    two_map: dict[str, object] = {
        eth.trade_id: 0,
    }
    if not omit_btc_two:
        two_map[btc.trade_id] = 0
    two = {"decision_prior_strikes": two_map}
    momentum = {
        "decision_details": {
            btc.trade_id: {
                "decision": "ADMIT",
                "reason": "momentum_band_pass",
            },
            eth.trade_id: {
                "decision": "ADMIT",
                "reason": "momentum_band_pass",
            },
        }
    }
    return combined, two, momentum


def _fixture(
    tmp_path: Path,
    *,
    opportunity_return_1h: str = "-0.02",
    omit_btc_two: bool = False,
    include_btc_close: bool = True,
) -> tuple[
    tuple[ContinuousPaperOpeningOpportunityEvidence, ...],
    tuple[ContinuousPaperOpeningLineage, ...],
    tuple[TradeJournalEntry, ...],
    LearningFeatureSnapshotStore,
    ProspectiveCombinedEntryFilterState,
    ProspectiveTwoStrikeStopFilterState,
    ProspectiveMomentumBandEntryState,
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    feature_store = LearningFeatureSnapshotStore(tmp_path / "features")
    combined_state, two_state, momentum_state = _states()
    start = max(
        combined_state.started_at_ms,
        two_state.started_at_ms,
        momentum_state.started_at_ms,
    )
    btc_feature = _record_feature(
        feature_store,
        "BTC",
        as_of_ms=start + 999,
        return_1h="0.02",
        day_return="0.08",
    )
    eth_feature = _record_feature(
        feature_store,
        "ETH",
        as_of_ms=start + 1_999,
        return_1h="-0.02",
        day_return="-0.08",
    )
    opportunity_feature = _record_feature(
        feature_store,
        "SOL",
        as_of_ms=start + 99_999,
        return_1h=opportunity_return_1h,
        day_return="-0.08",
    )
    btc = _trade(
        "btc-release",
        market="BTC",
        direction=Direction.LONG,
        opened_at_ms=start + 1_000,
        closed_at_ms=start + 200_000,
        feature_snapshot_id=btc_feature,
        pnl="-5",
    )
    eth = _trade(
        "eth-release",
        market="ETH",
        direction=Direction.SHORT,
        opened_at_ms=start + 2_000,
        closed_at_ms=start + 200_000,
        feature_snapshot_id=eth_feature,
        pnl="-4",
    )
    lineages = (
        ContinuousPaperOpeningLineage(
            opening_plan_id=btc.opening_plan_id,
            feature_snapshot_id=btc.feature_snapshot_id,
            market="BTC",
            opened_at_ms=btc.opened_at_ms,
            runtime=_runtime(),
        ),
        ContinuousPaperOpeningLineage(
            opening_plan_id=eth.opening_plan_id,
            feature_snapshot_id=eth.feature_snapshot_id,
            market="ETH",
            opened_at_ms=eth.opened_at_ms,
            runtime=_runtime(),
        ),
    )
    opportunity_ms = start + 100_000
    opportunity = _opportunity(
        _request(
            timestamp_ms=opportunity_ms,
            feature_snapshot_id=opportunity_feature,
        )
    )
    trades = (eth,) if not include_btc_close else (btc, eth)
    combined, two, momentum = _summaries(
        btc,
        eth,
        omit_btc_two=omit_btc_two,
    )
    return (
        (opportunity,),
        lineages,
        trades,
        feature_store,
        combined_state,
        two_state,
        momentum_state,
        combined,
        two,
        momentum,
    )


def test_full_stack_reflow_proves_only_stack_blocked_release(
    tmp_path: Path,
) -> None:
    args = _fixture(tmp_path)

    result = prospective_full_stack_capacity_reflow(*args)

    assert result.summary["observed_opportunities"] == 1
    assert result.summary["baseline_capacity_rejections"] == 1
    assert result.summary["full_stack_eligible_opportunities"] == 1
    assert result.summary["single_position_release_options"] == 2
    assert result.summary["candidate_blocked_release_options"] == 1
    assert result.summary["candidate_capacity_release_opportunities"] == 1
    assert result.summary["integrity_clean"] is True
    assert result.summary["by_release_position_block_reason"] == {
        "combined:long_trend": 1
    }
    assert len(result.releases) == 1
    release = result.releases[0]
    assert release.release_market == "BTC"
    assert release.opportunity_market == "SOL"
    assert release.release_block_reason == "combined:long_trend"
    assert result.summary["portfolio_counterfactual"] is False
    assert result.summary["recursive_replacements_modeled"] is False


def test_full_stack_reflow_rejects_replacement_blocked_by_momentum(
    tmp_path: Path,
) -> None:
    args = _fixture(
        tmp_path,
        opportunity_return_1h="0.005",
    )

    result = prospective_full_stack_capacity_reflow(*args)

    assert result.summary["full_stack_blocked_opportunities"] == 1
    assert result.summary["full_stack_eligible_opportunities"] == 0
    assert result.summary["single_position_release_options"] == 0
    assert result.summary["candidate_blocked_release_options"] == 0
    assert result.summary["by_opportunity_block_reason"] == {
        "momentum:momentum_band": 1
    }
    assert result.releases == ()


def test_full_stack_reflow_marks_missing_release_decision_map(
    tmp_path: Path,
) -> None:
    args = _fixture(tmp_path, omit_btc_two=True)

    result = prospective_full_stack_capacity_reflow(*args)

    assert result.summary["single_position_release_options"] == 2
    assert result.summary["release_decision_map_misses"] == 1
    assert result.summary["candidate_blocked_release_options"] == 0
    assert result.summary["integrity_clean"] is False


def test_full_stack_reflow_does_not_guess_still_open_release_position(
    tmp_path: Path,
) -> None:
    args = _fixture(tmp_path, include_btc_close=False)

    result = prospective_full_stack_capacity_reflow(*args)

    assert result.summary["single_position_release_options"] == 2
    assert result.summary["unresolved_release_positions"] == 1
    assert result.summary["candidate_blocked_release_options"] == 0
    assert result.summary["integrity_clean"] is False
