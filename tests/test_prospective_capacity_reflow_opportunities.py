from __future__ import annotations

from dataclasses import replace
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
from cocomelon.research.continuous_paper_opening_opportunity import (
    ContinuousPaperOpeningOpportunityEvidence,
    _risk_request_payload,
)
from cocomelon.research.prospective_capacity_reflow_opportunities import (
    candidate_eligible_capacity_release_options,
    prospective_capacity_reflow_opportunity_summary,
    single_position_capacity_release_options,
)
from cocomelon.research.prospective_combined_entry_filter import (
    ProspectiveCombinedEntryFilterState,
)
from cocomelon.risk.engine import evaluate_risk


def _market(name: str) -> MarketId:
    return MarketId.from_wire_name("", name)


def _request(
    *,
    market: str,
    direction: Direction,
    lead_strategy: str,
    timestamp_ms: int,
) -> RiskRequest:
    decision = StrategyDecision(
        market=_market(market),
        direction=direction,
        score=Decimal("0.6"),
        timestamp_ms=timestamp_ms,
        feature_snapshot_id=f"feature-{market}-{timestamp_ms}",
        lead_strategy=lead_strategy,
        invalidation_price=(
            Decimal("90")
            if direction is Direction.LONG
            else Decimal("110")
        ),
        signal_ids=(f"signal-{market}",),
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


def _evidence(
    request: RiskRequest,
    *,
    rank_ordinal: int | None,
    rank_observed_at_ms: int | None,
    expected_reason: str = "correlation_bucket_exhausted",
) -> ContinuousPaperOpeningOpportunityEvidence:
    decision = evaluate_risk(request)
    assert decision.approved is False
    assert decision.reason_codes == (expected_reason,)
    return ContinuousPaperOpeningOpportunityEvidence(
        strategy_decision_id=request.strategy_decision_id,
        feature_snapshot_id=request.feature_snapshot_id,
        market=request.market.canonical,
        direction=request.direction.value,
        lead_strategy=request.strategy_decision.lead_strategy or "",
        opportunity_timestamp_ms=request.timestamp_ms,
        baseline_risk_approved=False,
        baseline_risk_reason_codes=decision.reason_codes,
        baseline_risk_decision_id=decision.risk_decision_id,
        equity_before=request.account_state.equity,
        risk_request=_risk_request_payload(request),
        instrument={"market": request.market.canonical},
        book={"event_key": f"book-{request.strategy_decision_id}"},
        rank_observed_at_ms=rank_observed_at_ms,
        rank_ordinal=rank_ordinal,
        rank_score=(
            None if rank_ordinal is None else Decimal("0.8")
        ),
        rank_pool_size=None if rank_ordinal is None else 20,
        rank_reason_codes=(
            () if rank_ordinal is None else ("ranked",)
        ),
    )


def test_capacity_reflow_summary_finds_candidate_eligible_rejections() -> None:
    allowed_request = _request(
        market="SOL",
        direction=Direction.SHORT,
        lead_strategy="trend",
        timestamp_ms=10_000,
    )
    blocked_request = _request(
        market="DOGE",
        direction=Direction.LONG,
        lead_strategy="trend",
        timestamp_ms=11_000,
    )
    missing_rank_request = _request(
        market="XRP",
        direction=Direction.SHORT,
        lead_strategy="mean_reversion",
        timestamp_ms=12_000,
    )
    summary = prospective_capacity_reflow_opportunity_summary(
        (
            _evidence(
                allowed_request,
                rank_ordinal=5,
                rank_observed_at_ms=9_900,
            ),
            _evidence(
                blocked_request,
                rank_ordinal=4,
                rank_observed_at_ms=10_900,
            ),
            _evidence(
                missing_rank_request,
                rank_ordinal=None,
                rank_observed_at_ms=None,
            ),
        ),
        ProspectiveCombinedEntryFilterState(started_at_ms=0),
    )

    assert summary["opportunities"] == 3
    assert summary["baseline_rejections"] == 3
    assert summary["candidate_eligible_rejections"] == 1
    assert summary["candidate_blocked_rejections"] == 1
    assert summary["missing_rank_evidence"] == 1
    assert summary["stale_rank_evidence"] == 0
    assert summary["candidate_eligible_capacity_rejections"] == 1
    assert summary["single_position_release_unblocked"] == 1
    assert summary["single_position_release_options"] == 2
    assert summary["by_baseline_rejection_reason"] == {
        "correlation_bucket_exhausted": 3
    }
    assert summary["by_candidate_block_reason"] == {
        "long_trend": 1
    }
    assert summary["by_release_market"] == {
        "BTC": 1,
        "ETH": 1,
    }
    assert summary["replacement_trades_modeled"] is False
    assert summary["pnl_modeled"] is False
    assert summary["execution_authority"] is False
    assert summary["promotion_authority"] is False


    options = candidate_eligible_capacity_release_options(
        (
            _evidence(
                allowed_request,
                rank_ordinal=5,
                rank_observed_at_ms=9_900,
            ),
            _evidence(
                blocked_request,
                rank_ordinal=4,
                rank_observed_at_ms=10_900,
            ),
        ),
        ProspectiveCombinedEntryFilterState(started_at_ms=0),
    )
    assert tuple(
        (
            option.opportunity_market,
            option.release_market,
            option.release_correlation_bucket,
        )
        for option in options
    ) == (
        ("SOL", "BTC", "majors"),
        ("SOL", "ETH", "majors"),
    )


def test_capacity_reflow_summary_rejects_stale_rank_from_candidate_cohort() -> None:
    request = _request(
        market="SOL",
        direction=Direction.SHORT,
        lead_strategy="trend",
        timestamp_ms=1_000_000,
    )
    summary = prospective_capacity_reflow_opportunity_summary(
        (
            _evidence(
                request,
                rank_ordinal=2,
                rank_observed_at_ms=600_000,
            ),
        ),
        ProspectiveCombinedEntryFilterState(started_at_ms=0),
    )

    assert summary["candidate_eligible_rejections"] == 0
    assert summary["stale_rank_evidence"] == 1
    assert summary["integrity_clean"] is False


def test_single_position_capacity_release_options_are_strategy_agnostic() -> None:
    request = _request(
        market="SOL",
        direction=Direction.SHORT,
        lead_strategy="trend",
        timestamp_ms=12_000,
    )
    evidence = _evidence(
        request,
        rank_ordinal=18,
        rank_observed_at_ms=11_900,
    )

    options = single_position_capacity_release_options(evidence)

    assert tuple(
        (
            option.opportunity_market,
            option.release_market,
            option.release_correlation_bucket,
        )
        for option in options
    ) == (
        ("SOL", "BTC", "majors"),
        ("SOL", "ETH", "majors"),
    )


def test_capacity_reflow_attributes_minimum_notional_safety_caps() -> None:
    liquidity_limited_base = _request(
        market="SOL",
        direction=Direction.SHORT,
        lead_strategy="trend",
        timestamp_ms=20_000,
    )
    liquidity_limited = replace(
        liquidity_limited_base,
        open_positions=(),
        account_state=replace(
            liquidity_limited_base.account_state,
            gross_open_notional=Decimal("0"),
        ),
        liquidity_state=replace(
            liquidity_limited_base.liquidity_state,
            entry_side_visible_notional_25bps=Decimal("50"),
            exit_side_visible_notional_25bps=Decimal("50"),
        ),
    )

    risk_limited_base = _request(
        market="XRP",
        direction=Direction.SHORT,
        lead_strategy="trend",
        timestamp_ms=21_000,
    )
    low_equity = Decimal("100")
    risk_limited = replace(
        risk_limited_base,
        open_positions=(),
        account_state=replace(
            risk_limited_base.account_state,
            equity=low_equity,
            day_start_equity=low_equity,
            rolling_7d_peak_equity=low_equity,
            available_margin=low_equity,
            gross_open_notional=Decimal("0"),
        ),
    )

    summary = prospective_capacity_reflow_opportunity_summary(
        (
            _evidence(
                liquidity_limited,
                rank_ordinal=4,
                rank_observed_at_ms=19_900,
                expected_reason="below_venue_min_notional",
            ),
            _evidence(
                risk_limited,
                rank_ordinal=5,
                rank_observed_at_ms=20_900,
                expected_reason="below_venue_min_notional",
            ),
        ),
        ProspectiveCombinedEntryFilterState(started_at_ms=0),
    )

    assert summary["candidate_eligible_min_notional_rejections"] == 2
    factors = summary["by_min_notional_limiting_factor"]
    assert isinstance(factors, dict)
    assert factors["visible_depth_capacity"] == 1
    assert factors["target_trade_risk"] == 1
    assert factors["aggregate_or_bucket_risk_capacity"] == 1

    markets = summary["by_min_notional_market"]
    assert isinstance(markets, dict)
    assert markets == {"SOL": 1, "XRP": 1}
    assert Decimal(
        str(summary["min_notional_notional_shortfall_sum"])
    ) > 0
    assert Decimal(
        str(summary["min_notional_forced_risk_overage_sum"])
    ) > 0
    assert summary["min_notional_safe_round_up"] == 0
    assert summary["execution_authority"] is False
    assert summary["promotion_authority"] is False


def test_capacity_reflow_minimum_notional_rejects_are_not_release_options() -> None:
    base = _request(
        market="SOL",
        direction=Direction.SHORT,
        lead_strategy="trend",
        timestamp_ms=22_000,
    )
    request = replace(
        base,
        open_positions=(),
        account_state=replace(
            base.account_state,
            gross_open_notional=Decimal("0"),
        ),
        liquidity_state=replace(
            base.liquidity_state,
            entry_side_visible_notional_25bps=Decimal("50"),
            exit_side_visible_notional_25bps=Decimal("50"),
        ),
    )
    evidence = _evidence(
        request,
        rank_ordinal=3,
        rank_observed_at_ms=21_900,
        expected_reason="below_venue_min_notional",
    )

    assert single_position_capacity_release_options(evidence) == ()
    summary = prospective_capacity_reflow_opportunity_summary(
        (evidence,),
        ProspectiveCombinedEntryFilterState(started_at_ms=0),
    )
    assert summary["candidate_eligible_capacity_rejections"] == 0
    assert summary["candidate_eligible_min_notional_rejections"] == 1
