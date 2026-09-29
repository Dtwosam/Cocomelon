from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from cocomelon.domain.execution import (
    InstrumentExecutionSpec,
    PaperExecutionConfig,
)
from cocomelon.domain.market import MarketId
from cocomelon.domain.risk import (
    LiquidityRiskState,
    OpenPositionRisk,
    RiskAccountState,
    RiskHealthState,
    RiskLimits,
    RiskRequest,
)
from cocomelon.domain.strategy import Direction, StrategyDecision
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.evidence.openings import conservative_cost_estimate
from cocomelon.execution.accounting import (
    PaperPosition,
    PositionSide,
)
from cocomelon.research.continuous_paper_opening_opportunity import (
    ContinuousPaperOpeningOpportunityEvidence,
    _book_payload,
    _instrument_payload,
    _risk_request_payload,
)
from cocomelon.research.prospective_capacity_reflow_fill_feasibility import (
    ProspectiveCapacityReflowFillFeasibilityError,
    prospective_capacity_reflow_fill_feasibility_summary,
)
from cocomelon.research.prospective_capacity_reflow_release_lineage import (
    CandidateCausedCapacityRelease,
)
from cocomelon.risk.engine import evaluate_risk


def _market(name: str) -> MarketId:
    return MarketId.from_wire_name("", name)


def _evidence() -> ContinuousPaperOpeningOpportunityEvidence:
    config = PaperExecutionConfig()
    decision = StrategyDecision(
        market=_market("SOL"),
        direction=Direction.SHORT,
        score=Decimal("0.7"),
        timestamp_ms=9_700,
        feature_snapshot_id="feature-sol",
        lead_strategy="breakout",
        invalidation_price=Decimal("110"),
        signal_ids=("signal-sol",),
        reason_codes=("strategy_directional",),
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
    request = RiskRequest(
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
            as_of_ms=10_000,
        ),
        open_positions=positions,
        health_state=RiskHealthState(
            market_data_fresh=True,
            account_state_fresh=True,
            execution_health_ok=True,
            state_consistent=True,
            as_of_ms=10_000,
        ),
        cost_estimate=conservative_cost_estimate(config),
        liquidity_state=LiquidityRiskState(
            entry_side_visible_notional_25bps=Decimal("1000000"),
            exit_side_visible_notional_25bps=Decimal("1000000"),
            venue_max_leverage=Decimal("5"),
            liquidation_price=Decimal("150"),
            venue_min_notional=Decimal("10"),
            as_of_ms=9_990,
        ),
        limits=RiskLimits(),
        timestamp_ms=10_000,
    )
    baseline = evaluate_risk(request)
    assert baseline.approved is False
    assert baseline.reason_codes == ("correlation_bucket_exhausted",)

    instrument = InstrumentExecutionSpec(
        market=request.market,
        sz_decimals=2,
        venue_max_leverage=Decimal("5"),
        minimum_order_notional=Decimal("10"),
        metadata_received_at_ms=9_000,
        metadata_source="fixture",
    )
    book = StreamEvent(
        kind=StreamKind.L2_BOOK,
        market=request.market,
        exchange_time_ms=9_990,
        receive_time=datetime.fromtimestamp(9.99, tz=UTC),
        schema_version=1,
        source="fixture",
        event_key="book-sol-9990",
        payload={
            "bids": (
                {"px": Decimal("99.95"), "sz": Decimal("100"), "n": 1},
                {"px": Decimal("99.90"), "sz": Decimal("100"), "n": 1},
            ),
            "asks": (
                {"px": Decimal("100.05"), "sz": Decimal("100"), "n": 1},
                {"px": Decimal("100.10"), "sz": Decimal("100"), "n": 1},
            ),
        },
    )
    return ContinuousPaperOpeningOpportunityEvidence(
        strategy_decision_id=request.strategy_decision_id,
        feature_snapshot_id=request.feature_snapshot_id,
        market=request.market.canonical,
        direction=request.direction.value,
        lead_strategy=decision.lead_strategy or "",
        opportunity_timestamp_ms=request.timestamp_ms,
        baseline_risk_approved=False,
        baseline_risk_reason_codes=baseline.reason_codes,
        baseline_risk_decision_id=baseline.risk_decision_id,
        equity_before=request.account_state.equity,
        risk_request=_risk_request_payload(request),
        instrument=_instrument_payload(instrument),
        book=_book_payload(book),
        rank_observed_at_ms=9_900,
        rank_ordinal=4,
        rank_score=Decimal("0.8"),
        rank_pool_size=20,
        rank_reason_codes=("fixture",),
    )


def _release(
    evidence: ContinuousPaperOpeningOpportunityEvidence,
) -> CandidateCausedCapacityRelease:
    return CandidateCausedCapacityRelease(
        opportunity_id=evidence.opportunity_id,
        opportunity_timestamp_ms=evidence.opportunity_timestamp_ms,
        opportunity_market=evidence.market,
        release_market="BTC",
        release_correlation_bucket="majors",
        release_opening_plan_id="release-plan-btc",
        release_block_reason="long_trend",
    )


def _history(
    _opening_plan_id: str,
    _through_ms: int,
) -> tuple[PaperPosition, ...]:
    return (
        PaperPosition(
            market=_market("BTC"),
            side=PositionSide.LONG,
            quantity=Decimal("10"),
            average_entry_price=Decimal("100"),
            stop_price=Decimal("90"),
            opening_plan_id="release-plan-btc",
            opened_at_ms=9_800,
            updated_at_ms=10_000,
            initial_risk_decision_id="risk-btc",
            correlation_bucket="majors",
            cost_buffer_fraction=Decimal("0.0034"),
            planned_risk=Decimal("25"),
            cumulative_realized_gross_pnl=Decimal("0"),
            cumulative_fees=Decimal("1"),
            cumulative_funding=Decimal("0"),
            venue_max_leverage=Decimal("5"),
            latest_mark=Decimal("100"),
        ),
    )


def test_fill_feasibility_replays_conservative_risk_and_exact_ioc() -> None:
    evidence = _evidence()
    result = prospective_capacity_reflow_fill_feasibility_summary(
        (evidence,),
        (_release(evidence),),
        PaperExecutionConfig(),
        position_history_loader=_history,
    )

    assert result["candidate_caused_release_options"] == 1
    assert result["candidate_caused_release_opportunities"] == 1
    assert result["conservative_risk_approvals"] == 1
    assert result["planning_approvals"] == 1
    assert result["fillable_options"] == 1
    assert result["full_fill_options"] == 0
    assert result["partial_fill_options"] == 1
    assert result["no_fill_options"] == 0
    assert result["execution_rejected_options"] == 0
    assert Decimal(str(result["gross_fill_notional"])) > Decimal("0")
    assert Decimal(str(result["taker_fees"])) > Decimal("0")
    assert result["by_opportunity_market"] == {"SOL": 1}
    assert result["by_release_market"] == {"BTC": 1}
    assert result["by_execution_result"] == {"partial": 1}
    assert result["portfolio_counterfactual"] is False
    assert result["other_baseline_positions_held_fixed"] is True
    assert result["other_positions_replayed"] is False
    assert result["account_capacity_credit_mode"] == (
        "exact_single_release_accounting_other_positions_fixed"
    )
    assert result["counterfactual_equity_delta_min"] == "1"
    assert result["counterfactual_equity_delta_max"] == "1"
    assert result["replacement_entry_fills_modeled"] is True
    assert result["replacement_exits_modeled"] is False
    assert result["replacement_trades_modeled"] is False
    assert result["pnl_modeled"] is False
    assert result["execution_authority"] is False
    assert result["promotion_authority"] is False


def test_fill_feasibility_refuses_execution_config_drift() -> None:
    evidence = _evidence()

    with pytest.raises(
        ProspectiveCapacityReflowFillFeasibilityError,
        match="execution config does not match captured cost estimate",
    ):
        prospective_capacity_reflow_fill_feasibility_summary(
            (evidence,),
            (_release(evidence),),
            PaperExecutionConfig(max_ioc_slippage_bps=Decimal("20")),
            position_history_loader=_history,
        )


def test_fill_feasibility_refuses_ambiguous_decision_time_position_state() -> None:
    evidence = _evidence()
    current = _history("release-plan-btc", 10_000)[0]
    ambiguous = (
        replace(
            current,
            cumulative_fees=Decimal("0.5"),
        ),
        current,
    )

    with pytest.raises(
        ProspectiveCapacityReflowFillFeasibilityError,
        match="decision-time history is missing or ambiguous",
    ):
        prospective_capacity_reflow_fill_feasibility_summary(
            (evidence,),
            (_release(evidence),),
            PaperExecutionConfig(),
            position_history_loader=lambda _plan_id, _through_ms: ambiguous,
        )
