from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from cocomelon.domain.evaluation import DecisionEvaluationFact
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
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.research.continuous_paper_learning import (
    ContinuousPaperOpeningLineage,
    ContinuousPaperRuntimeIdentity,
)
from cocomelon.research.continuous_paper_opening_opportunity import (
    ContinuousPaperOpeningOpportunityEvidence,
    _risk_request_payload,
)
from cocomelon.research.continuous_paper_opening_rank import (
    ContinuousPaperOpeningRankEvidence,
    ContinuousPaperOpeningRankStore,
)
from cocomelon.research.historical_discovery_freeze import (
    MIN_PROSPECTIVE_EMBARGO_MS,
)
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotStore,
)
from cocomelon.research.loss_context_candidate import (
    LossContextCandidateFreeze,
)
from cocomelon.research.loss_context_capacity_reflow import (
    loss_context_capacity_reflow,
)
from cocomelon.risk.engine import evaluate_risk


def _market(name: str) -> MarketId:
    return MarketId.from_wire_name("", name)


def _freeze() -> LossContextCandidateFreeze:
    frozen_at_ms = 1_000_000
    return LossContextCandidateFreeze(
        source_audit_digest="b" * 64,
        source_max_timestamp_ms=900_000,
        source_paper_run_id=1,
        source_paper_run_attempt=1,
        source_paper_head_sha="a" * 40,
        dimensions=("lead_strategy", "trend_regime"),
        values=("mean_reversion", "down"),
        discovery_rows=20,
        discovery_markets=5,
        discovery_loss_share=Decimal("0.7"),
        discovery_filter_delta_pnl=Decimal("30"),
        validation_rows=12,
        validation_markets=4,
        validation_loss_share=Decimal("0.75"),
        validation_filter_delta_pnl=Decimal("20"),
        validation_leave_one_trade_min_delta_pnl=Decimal("12"),
        validation_leave_one_market_min_delta_pnl=Decimal("6"),
        frozen_at_ms=frozen_at_ms,
        prospective_not_before_ms=(
            frozen_at_ms + MIN_PROSPECTIVE_EMBARGO_MS
        ),
    )


def _readiness(
    freeze: LossContextCandidateFreeze,
    *,
    ready: bool = True,
) -> dict[str, object]:
    return {
        "candidate_id": freeze.candidate_id,
        "prospective_filter_review_ready": ready,
        "fixed_schedule_economics_ready": ready,
        "source_complete": True,
        "ready_for_capacity_reflow_investigation": ready,
        "capacity_reflow_modeled": False,
        "capacity_reflow_required_before_strategy_use": True,
        "changes_strategy": False,
        "changes_risk_limits": False,
        "promotion_authority": False,
        "execution_authority": False,
    }


def _feature(
    market: str,
    *,
    as_of_ms: int,
    trend: TrendRegime,
) -> FeatureSnapshot:
    return FeatureSnapshot(
        market=_market(market),
        as_of_ms=as_of_ms,
        source_received_at_ms=as_of_ms,
        schema_version=1,
        day_return=Decimal("-0.03"),
        funding=Decimal("0"),
        open_interest=Decimal("100"),
        day_notional_volume=Decimal("1000000"),
        oi_change_fraction=None,
        funding_change=None,
        mark_oracle_dislocation_bps=Decimal("0"),
        return_5m=None,
        return_15m=Decimal("-0.01"),
        return_1h=Decimal("-0.02"),
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
        volatility_regime=VolatilityRegime.NORMAL,
        provenance=("test",),
    )


def _trade(
    suffix: str,
    *,
    market: str,
    opened_at_ms: int,
    closed_at_ms: int,
    feature_snapshot_id: str,
) -> TradeJournalEntry:
    return TradeJournalEntry(
        market=_market(market),
        direction=Direction.SHORT,
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
        initial_stop=Decimal("110"),
        initial_risk_amount=Decimal("25"),
        entry_price=Decimal("100"),
        exit_price=Decimal("101"),
        filled_quantity=Decimal("1"),
        gross_realized_pnl=Decimal("-1"),
        entry_fees=Decimal("0"),
        exit_fees=Decimal("0"),
        funding_cash_pnl=Decimal("0"),
        net_pnl=Decimal("-1"),
        entry_slippage_amount=Decimal("0"),
        exit_slippage_amount=Decimal("0"),
        entry_slippage_fraction=Decimal("0"),
        exit_slippage_fraction=Decimal("0"),
        holding_duration_ms=closed_at_ms - opened_at_ms,
        mfe=None,
        mae=None,
        net_r=Decimal("-0.04"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("9999"),
        exit_reason="MARK_STOP_TRIGGERED",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id="continuous-paper-mainnet-v1",
    )


def _record_holder(
    trade: TradeJournalEntry,
    feature: FeatureSnapshot,
    *,
    strategy: str,
    facts: EvaluationFactStore,
    features: LearningFeatureSnapshotStore,
    ranks: ContinuousPaperOpeningRankStore,
) -> None:
    features.record(feature)
    facts.record_decision_fact(
        DecisionEvaluationFact(
            strategy_decision_id=trade.strategy_decision_id,
            feature_snapshot_id=trade.feature_snapshot_id,
            replay_run_id="continuous-paper-mainnet-v1",
            market=trade.market,
            direction=trade.direction,
            timestamp_ms=trade.opened_at_ms - 1,
            score=Decimal("0.8"),
            lead_strategy=strategy,
            signal_ids=(f"signal-{trade.trade_id}",),
            reason_codes=("decision_threshold_met",),
            trend_regime=feature.trend_regime,
            volatility_regime=feature.volatility_regime,
        )
    )
    ranks.record(
        ContinuousPaperOpeningRankEvidence(
            opening_plan_id=trade.opening_plan_id,
            market=trade.market.canonical,
            opened_at_ms=trade.opened_at_ms,
            rank_observed_at_ms=trade.opened_at_ms - 100,
            rank_age_ms=100,
            ordinal=2,
            score=Decimal("0.9"),
            rank_pool_size=20,
            reason_codes=("ranked",),
        )
    )


def _request(
    *,
    timestamp_ms: int,
    feature_snapshot_id: str,
    lead_strategy: str = "trend",
) -> RiskRequest:
    decision = StrategyDecision(
        market=_market("SOL"),
        direction=Direction.SHORT,
        score=Decimal("0.7"),
        timestamp_ms=timestamp_ms,
        feature_snapshot_id=feature_snapshot_id,
        lead_strategy=lead_strategy,
        invalidation_price=Decimal("110"),
        signal_ids=("signal-sol",),
        reason_codes=("decision_threshold_met",),
    )
    positions = tuple(
        OpenPositionRisk(
            market=_market(market),
            direction=Direction.SHORT,
            planned_risk=Decimal("25"),
            notional=Decimal("1000"),
            correlation_bucket="majors",
            entry_price=Decimal("100"),
            stop_price=Decimal("110"),
        )
        for market in ("BTC", "ETH")
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


def _runtime() -> ContinuousPaperRuntimeIdentity:
    return ContinuousPaperRuntimeIdentity(
        worker_run_id=123,
        worker_run_attempt=1,
        worker_head_sha="c" * 40,
    )


def _fixture(
    tmp_path: Path,
    *,
    newcomer_strategy: str = "trend",
):
    freeze = _freeze()
    start = freeze.prospective_not_before_ms
    features = LearningFeatureSnapshotStore(tmp_path / "features")
    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    ranks = ContinuousPaperOpeningRankStore(tmp_path / "ranks")

    btc_feature = _feature(
        "BTC",
        as_of_ms=start + 999,
        trend=TrendRegime.DOWN,
    )
    eth_feature = _feature(
        "ETH",
        as_of_ms=start + 1_999,
        trend=TrendRegime.DOWN,
    )
    btc = _trade(
        "btc",
        market="BTC",
        opened_at_ms=start + 1_000,
        closed_at_ms=start + 200_000,
        feature_snapshot_id=btc_feature.snapshot_id,
    )
    eth = _trade(
        "eth",
        market="ETH",
        opened_at_ms=start + 2_000,
        closed_at_ms=start + 200_000,
        feature_snapshot_id=eth_feature.snapshot_id,
    )
    _record_holder(
        btc,
        btc_feature,
        strategy="mean_reversion",
        facts=facts,
        features=features,
        ranks=ranks,
    )
    _record_holder(
        eth,
        eth_feature,
        strategy="trend",
        facts=facts,
        features=features,
        ranks=ranks,
    )

    sol_feature = _feature(
        "SOL",
        as_of_ms=start + 99_999,
        trend=TrendRegime.DOWN,
    )
    features.record(sol_feature)
    opportunity = _opportunity(
        _request(
            timestamp_ms=start + 100_000,
            feature_snapshot_id=sol_feature.snapshot_id,
            lead_strategy=newcomer_strategy,
        )
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
    return (
        freeze,
        (opportunity,),
        lineages,
        (btc, eth),
        features,
        facts,
        ranks,
    )


def test_reflow_credits_only_frozen_context_holder(tmp_path: Path) -> None:
    (
        freeze,
        opportunities,
        lineages,
        trades,
        features,
        facts,
        ranks,
    ) = _fixture(tmp_path)
    try:
        result = loss_context_capacity_reflow(
            opportunities,
            lineages,
            trades,
            features,
            facts,
            ranks,
            freeze=freeze,
            account_readiness=_readiness(freeze),
        )
    finally:
        facts.close()

    assert result.summary["gate_open"] is True
    assert result.summary["baseline_capacity_rejections"] == 1
    assert result.summary["single_position_release_options"] == 2
    assert result.summary["candidate_allowed_release_options"] == 1
    assert result.summary["candidate_blocked_release_options"] == 1
    assert result.summary["candidate_capacity_release_opportunities"] == 1
    assert result.summary["integrity_clean"] is True
    assert result.summary["ready_for_replacement_fill_investigation"] is True
    assert len(result.releases) == 1
    assert result.releases[0].release_market == "BTC"
    assert result.releases[0].opportunity_market == "SOL"
    assert result.summary["replacement_entries_modeled"] is False
    assert result.summary["replacement_pnl_modeled"] is False


def test_reflow_does_not_replace_with_same_bad_context(tmp_path: Path) -> None:
    (
        freeze,
        opportunities,
        lineages,
        trades,
        features,
        facts,
        ranks,
    ) = _fixture(tmp_path, newcomer_strategy="mean_reversion")
    try:
        result = loss_context_capacity_reflow(
            opportunities,
            lineages,
            trades,
            features,
            facts,
            ranks,
            freeze=freeze,
            account_readiness=_readiness(freeze),
        )
    finally:
        facts.close()

    assert result.summary["candidate_blocked_newcomers"] == 1
    assert result.summary["candidate_eligible_capacity_rejections"] == 0
    assert result.summary["candidate_blocked_release_options"] == 0
    assert result.releases == ()


def test_reflow_stays_disabled_until_d041_is_ready(tmp_path: Path) -> None:
    (
        freeze,
        opportunities,
        lineages,
        trades,
        features,
        facts,
        ranks,
    ) = _fixture(tmp_path)
    try:
        result = loss_context_capacity_reflow(
            opportunities,
            lineages,
            trades,
            features,
            facts,
            ranks,
            freeze=freeze,
            account_readiness=_readiness(freeze, ready=False),
        )
    finally:
        facts.close()

    assert result.summary["enabled"] is False
    assert result.summary["gate_open"] is False
    assert result.summary["replacement_entries_modeled"] is False
    assert result.releases == ()
