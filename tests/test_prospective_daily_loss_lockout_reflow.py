from __future__ import annotations

from decimal import Decimal

from cocomelon.domain.market import MarketId
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
from cocomelon.research.continuous_paper_opening_opportunity import (
    ContinuousPaperOpeningOpportunityEvidence,
    _risk_request_payload,
)
from cocomelon.research.continuous_paper_opening_rank import (
    ContinuousPaperOpeningRankStore,
)
from cocomelon.research.prospective_combined_entry_filter import (
    ProspectiveCombinedEntryFilterState,
)
from cocomelon.research.prospective_daily_loss_lockout_reflow import (
    prospective_daily_loss_lockout_reflow_summary,
)
from tests.test_prospective_combined_entry_filter import (
    _fact,
    _rank,
    _trade,
)

DAY_MS = 86_400_000


def _market(name: str) -> MarketId:
    return MarketId.from_wire_name("", name)


def _opportunity(
    *,
    timestamp_ms: int,
    daily_realized_pnl: str,
    open_positions=(),
) -> ContinuousPaperOpeningOpportunityEvidence:
    decision = StrategyDecision(
        market=_market("XRP"),
        direction=Direction.SHORT,
        score=Decimal("0.7"),
        timestamp_ms=timestamp_ms,
        feature_snapshot_id="feature-opportunity",
        lead_strategy="breakout",
        invalidation_price=Decimal("110"),
        signal_ids=("signal-opportunity",),
        reason_codes=("strategy_directional",),
    )
    request = RiskRequest(
        strategy_decision=decision,
        entry_reference_price=Decimal("100"),
        correlation_bucket="majors",
        account_state=RiskAccountState(
            equity=Decimal("9880"),
            day_start_equity=Decimal("10000"),
            daily_realized_pnl=Decimal(daily_realized_pnl),
            rolling_7d_peak_equity=Decimal("10000"),
            available_margin=Decimal("9880"),
            gross_open_notional=Decimal("0"),
            consecutive_losses=2,
            last_closed_trade_ms=timestamp_ms - 1_000,
            as_of_ms=timestamp_ms,
        ),
        open_positions=tuple(open_positions),
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
    return ContinuousPaperOpeningOpportunityEvidence(
        strategy_decision_id=decision.decision_id,
        feature_snapshot_id=decision.feature_snapshot_id,
        market=decision.market.canonical,
        direction=decision.direction.value,
        lead_strategy=decision.lead_strategy or "",
        opportunity_timestamp_ms=timestamp_ms,
        baseline_risk_approved=False,
        baseline_risk_reason_codes=("daily_loss_lockout",),
        baseline_risk_decision_id="risk-lockout",
        equity_before=request.account_state.equity,
        risk_request=_risk_request_payload(request),
        instrument={"market": decision.market.canonical},
        book={"event_key": "book-opportunity"},
        rank_observed_at_ms=timestamp_ms - 100,
        rank_ordinal=4,
        rank_score=Decimal("0.8"),
        rank_pool_size=20,
        rank_reason_codes=("fixture",),
    )


def test_daily_loss_reflow_exactly_unlocks_from_blocked_same_day_loss(
    tmp_path,
) -> None:
    opportunity_ms = DAY_MS + 200_000
    blocked = _trade(
        suffix="blocked-daily",
        direction=Direction.LONG,
        opened_at_ms=DAY_MS + 10_000,
        pnl="-120",
    )
    opportunity = _opportunity(
        timestamp_ms=opportunity_ms,
        daily_realized_pnl="-120",
    )
    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    ranks = ContinuousPaperOpeningRankStore(tmp_path / "ranks")
    try:
        facts.record_decision_fact(
            _fact(blocked, lead_strategy="trend")
        )
        ranks.record(_rank(blocked, ordinal=5))
        result = prospective_daily_loss_lockout_reflow_summary(
            (opportunity,),
            (blocked,),
            facts,
            ranks,
            ProspectiveCombinedEntryFilterState(started_at_ms=0),
        )
    finally:
        facts.close()

    assert result["daily_loss_lockout_opportunities"] == 1
    assert result["candidate_eligible_lockout_opportunities"] == 1
    assert result["exact_cash_scope_opportunities"] == 1
    assert result["baseline_cash_reconciliation_misses"] == 0
    assert result["baseline_cash_reconciliation_clean"] is True
    assert result["exact_candidate_unlock_opportunities"] == 1
    assert result["closed_trade_adjusted_unlock_opportunities"] == 1
    assert result["same_day_closed_trade_instances"] == 1
    assert result["candidate_blocked_closed_trade_instances"] == 1
    assert result["distinct_candidate_blocked_trade_ids"] == 1
    assert result["baseline_daily_realized_pnl_min"] == "-120"
    assert result["candidate_daily_realized_pnl_min"] == "0"
    assert result["daily_loss_threshold_min"] == "-100.00"
    assert result["by_removed_trade_block_reason"] == {
        "long_trend": 1
    }
    assert result["open_position_cash_effects_modeled"] is False
    assert result["cross_day_trade_cash_effects_modeled"] is False
    assert result["replacement_trades_modeled"] is False
    assert result["pnl_modeled"] is False


def test_daily_loss_reflow_marks_cross_day_and_open_cash_scope_incomplete(
    tmp_path,
) -> None:
    opportunity_ms = 2 * DAY_MS + 200_000
    cross_day = _trade(
        suffix="cross-day",
        direction=Direction.LONG,
        opened_at_ms=2 * DAY_MS - 10_000,
        pnl="-120",
    )
    opportunity = _opportunity(
        timestamp_ms=opportunity_ms,
        daily_realized_pnl="-120",
        open_positions=(
            OpenPositionRisk(
                market=_market("BTC"),
                direction=Direction.LONG,
                planned_risk=Decimal("25"),
                notional=Decimal("1000"),
                correlation_bucket="majors",
                entry_price=Decimal("100"),
                stop_price=Decimal("90"),
            ),
        ),
    )
    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    ranks = ContinuousPaperOpeningRankStore(tmp_path / "ranks")
    try:
        result = prospective_daily_loss_lockout_reflow_summary(
            (opportunity,),
            (cross_day,),
            facts,
            ranks,
            ProspectiveCombinedEntryFilterState(started_at_ms=0),
        )
    finally:
        facts.close()

    assert result["cross_day_closed_trade_instances"] == 1
    assert result["exact_cash_scope_opportunities"] == 0
    assert result["exact_candidate_unlock_opportunities"] == 0


def test_daily_loss_reflow_refuses_exact_scope_when_cash_does_not_reconcile(
    tmp_path,
) -> None:
    opportunity = _opportunity(
        timestamp_ms=DAY_MS + 200_000,
        daily_realized_pnl="-120",
    )
    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    ranks = ContinuousPaperOpeningRankStore(tmp_path / "ranks")
    try:
        result = prospective_daily_loss_lockout_reflow_summary(
            (opportunity,),
            (),
            facts,
            ranks,
            ProspectiveCombinedEntryFilterState(started_at_ms=0),
        )
    finally:
        facts.close()

    assert result["cross_day_closed_trade_instances"] == 0
    assert result["open_position_instances"] == 0
    assert result["baseline_cash_reconciliation_misses"] == 1
    assert result["baseline_cash_reconciliation_clean"] is False
    assert result["exact_cash_scope_opportunities"] == 0
    assert result["exact_candidate_unlock_opportunities"] == 0
