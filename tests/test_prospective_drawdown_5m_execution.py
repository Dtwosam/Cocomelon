from __future__ import annotations

from copy import deepcopy
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
from cocomelon.research.continuous_paper_opening_opportunity_exit_books import (
    OpeningOpportunityExitBookEvidence,
)
from cocomelon.research.prospective_drawdown_5m_execution import (
    ProspectiveDrawdown5mExecutionError,
    prospective_drawdown_5m_execution_summary,
)
from cocomelon.research.prospective_drawdown_5m_execution_source import (
    EXIT_HORIZON_MS,
    ProspectiveDrawdown5mExecutionState,
    prospective_drawdown_5m_execution_source,
)
from cocomelon.risk.engine import evaluate_risk


def _market() -> MarketId:
    return MarketId.from_wire_name("", "SOL")


def _instrument(timestamp_ms: int) -> InstrumentExecutionSpec:
    return InstrumentExecutionSpec(
        market=_market(),
        sz_decimals=2,
        venue_max_leverage=Decimal("5"),
        minimum_order_notional=Decimal("10"),
        metadata_received_at_ms=timestamp_ms - 1_000,
        metadata_source="fixture",
    )


def _book(
    timestamp_ms: int,
    *,
    bid: str,
    ask: str,
    suffix: str,
    size: str = "1000",
) -> StreamEvent:
    return StreamEvent(
        kind=StreamKind.L2_BOOK,
        market=_market(),
        exchange_time_ms=timestamp_ms,
        receive_time=datetime.fromtimestamp(
            timestamp_ms / 1000,
            tz=UTC,
        ),
        schema_version=1,
        source="fixture",
        event_key=f"book-{suffix}-{timestamp_ms}",
        payload={
            "bids": (
                {
                    "px": Decimal(bid),
                    "sz": Decimal(size),
                    "n": 1,
                },
            ),
            "asks": (
                {
                    "px": Decimal(ask),
                    "sz": Decimal(size),
                    "n": 1,
                },
            ),
        },
    )


def _evidence(
    *,
    timestamp_ms: int,
    cooldown_active: bool = False,
    direction: Direction = Direction.LONG,
) -> ContinuousPaperOpeningOpportunityEvidence:
    config = PaperExecutionConfig()
    decision = StrategyDecision(
        market=_market(),
        direction=direction,
        score=Decimal("0.8"),
        timestamp_ms=timestamp_ms - config.latency_ms,
        feature_snapshot_id=f"feature-{timestamp_ms}",
        lead_strategy="trend",
        invalidation_price=(
            Decimal("90")
            if direction is Direction.LONG
            else Decimal("110")
        ),
        signal_ids=(f"signal-{timestamp_ms}",),
        reason_codes=("decision_threshold_met",),
    )
    account = RiskAccountState(
        equity=Decimal("9600"),
        day_start_equity=Decimal("9600"),
        daily_realized_pnl=Decimal("0"),
        rolling_7d_peak_equity=Decimal("10000"),
        available_margin=Decimal("9000"),
        gross_open_notional=Decimal("0"),
        consecutive_losses=(3 if cooldown_active else 0),
        last_closed_trade_ms=(
            timestamp_ms - 60_000 if cooldown_active else None
        ),
        as_of_ms=timestamp_ms,
    )
    request = RiskRequest(
        strategy_decision=decision,
        entry_reference_price=Decimal("100"),
        correlation_bucket="alts",
        account_state=account,
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
    assert baseline.approved is False
    assert baseline.reason_codes == ("weekly_drawdown_lockout",)

    instrument = _instrument(timestamp_ms)
    opening_book = _book(
        timestamp_ms,
        bid="99.95",
        ask="100.05",
        suffix="entry",
    )
    return ContinuousPaperOpeningOpportunityEvidence(
        strategy_decision_id=decision.decision_id,
        feature_snapshot_id=decision.feature_snapshot_id,
        market=_market().canonical,
        direction=direction.value,
        lead_strategy="trend",
        opportunity_timestamp_ms=timestamp_ms,
        baseline_risk_approved=False,
        baseline_risk_reason_codes=baseline.reason_codes,
        baseline_risk_decision_id=baseline.risk_decision_id,
        equity_before=request.account_state.equity,
        risk_request=_risk_request_payload(request),
        instrument=_instrument_payload(instrument),
        book=_book_payload(opening_book),
        rank_observed_at_ms=timestamp_ms - 100,
        rank_ordinal=3,
        rank_score=Decimal("0.9"),
        rank_pool_size=20,
        rank_reason_codes=("fixture",),
    )


def _exit_book(
    evidence: ContinuousPaperOpeningOpportunityEvidence,
    *,
    bid: str = "102",
    ask: str = "102.05",
    size: str = "1000",
) -> OpeningOpportunityExitBookEvidence:
    target = evidence.opportunity_timestamp_ms + EXIT_HORIZON_MS
    observed = target + 100
    return OpeningOpportunityExitBookEvidence(
        opportunity_id=evidence.opportunity_id,
        market=evidence.market,
        direction=evidence.direction,
        opportunity_timestamp_ms=evidence.opportunity_timestamp_ms,
        horizon_ms=EXIT_HORIZON_MS,
        target_at_ms=target,
        observed_at_ms=observed,
        observation_lag_ms=100,
        book_event=_book(
            observed,
            bid=bid,
            ask=ask,
            suffix="exit",
            size=size,
        ),
        instrument=_instrument(observed),
    )


def _summary(
    evidence: ContinuousPaperOpeningOpportunityEvidence,
) -> dict[str, object]:
    return {
        "enabled": True,
        "error": None,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_readiness_gate": False,
        "changes_closed_trade_readiness_gate": False,
        "overlap_started_at_ms": evidence.opportunity_timestamp_ms - 1,
        "risk_rejected_rows": [
            {
                "opportunity_id": evidence.opportunity_id,
                "timestamp_ms": evidence.opportunity_timestamp_ms,
                "market": evidence.market,
                "direction": evidence.direction,
                "lead_strategy": evidence.lead_strategy,
                "rank_ordinal": 3,
                "rank_age_ms": 100,
                "baseline_risk_approved": False,
                "baseline_risk_reason_codes": [
                    "weekly_drawdown_lockout"
                ],
                "stack_decision": "ADMIT",
                "block_layer": "none",
            }
        ],
    }


def _source(
    evidence: ContinuousPaperOpeningOpportunityEvidence,
    *,
    exit_book: OpeningOpportunityExitBookEvidence | None,
) -> dict[str, object]:
    state = ProspectiveDrawdown5mExecutionState(
        started_at_ms=evidence.opportunity_timestamp_ms - 1
    )
    return prospective_drawdown_5m_execution_source(
        _summary(evidence),
        (evidence,),
        (() if exit_book is None else (exit_book,)),
        (),
        PaperExecutionConfig(),
        state,
    )


def test_exact_five_minute_shadow_models_entry_exit_fees() -> None:
    evidence = _evidence(timestamp_ms=10_000_000)
    result = prospective_drawdown_5m_execution_summary(
        _source(evidence, exit_book=_exit_book(evidence))
    )

    assert result["source_opportunities"] == 1
    assert result["counterfactual_risk_approvals"] == 1
    assert result["entry_fillable_opportunities"] == 1
    assert result["exact_realized_pnl_options"] == 1
    option = result["option_results"][0]
    assert option["status"] == "exact"
    assert option["complete_close"] is True
    assert Decimal(option["exact_realized_pnl"]) > 0
    assert Decimal(option["entry_fee"]) > 0
    assert Decimal(option["exit_fee"]) > 0
    assert option["funding_boundary_count"] == 0
    assert option["funding_cash_pnl"] == "0"
    assert result["entry_fees_modeled"] is True
    assert result["exit_fees_modeled"] is True
    assert result["funding_modeled"] is True
    assert result["ready_for_review"] is False
    assert result["missing_exact_options"] == 29
    assert result["execution_authority"] is False
    assert result["promotion_authority"] is False
    assert result["changes_risk_limits"] is False


def test_exact_five_minute_shadow_handles_profitable_short() -> None:
    evidence = _evidence(
        timestamp_ms=15_000_000,
        direction=Direction.SHORT,
    )
    result = prospective_drawdown_5m_execution_summary(
        _source(
            evidence,
            exit_book=_exit_book(
                evidence,
                bid="97.95",
                ask="98",
            ),
        )
    )

    option = result["option_results"][0]
    assert option["status"] == "exact"
    assert option["direction"] == "short"
    assert Decimal(option["exact_realized_pnl"]) > 0


def test_partial_five_minute_close_is_never_exact() -> None:
    evidence = _evidence(timestamp_ms=17_000_000)
    result = prospective_drawdown_5m_execution_summary(
        _source(
            evidence,
            exit_book=_exit_book(
                evidence,
                size="0.01",
            ),
        )
    )

    option = result["option_results"][0]
    assert option["status"] == "incomplete"
    assert option["complete_close"] is False
    assert option["incomplete_reason"] == "exit_partial_fill"
    assert result["exact_realized_pnl_options"] == 0
    assert result["incomplete_reason_counts"] == {
        "exit_partial_fill": 1
    }


def test_missing_hourly_funding_evidence_blocks_exact_pnl() -> None:
    evidence = _evidence(timestamp_ms=3_500_000)
    result = prospective_drawdown_5m_execution_summary(
        _source(evidence, exit_book=_exit_book(evidence))
    )

    option = result["option_results"][0]
    assert option["status"] == "incomplete"
    assert option["funding_boundary_count"] == 1
    assert option["funding_evidence_count"] == 0
    assert option["incomplete_reason"] == "funding_evidence_required"
    assert option["missing_funding_boundaries_ms"] == [3_600_000]
    assert result["exact_realized_pnl_options"] == 0


def test_shadow_preserves_second_risk_veto_after_drawdown_removed() -> None:
    evidence = _evidence(
        timestamp_ms=20_000_000,
        cooldown_active=True,
    )
    result = prospective_drawdown_5m_execution_summary(
        _source(evidence, exit_book=_exit_book(evidence))
    )

    assert result["counterfactual_risk_approvals"] == 0
    assert result["counterfactual_risk_rejections"] == {
        "consecutive_loss_cooldown": 1
    }
    assert result["entry_fillable_opportunities"] == 0
    assert result["exact_realized_pnl_options"] == 0


def test_shadow_keeps_missing_exit_book_incomplete() -> None:
    evidence = _evidence(timestamp_ms=30_000_000)
    result = prospective_drawdown_5m_execution_summary(
        _source(evidence, exit_book=None)
    )

    assert result["entry_fillable_opportunities"] == 1
    assert result["exact_realized_pnl_options"] == 0
    assert result["incomplete_reason_counts"] == {
        "missing_exit_book": 1
    }
    option = result["option_results"][0]
    assert option["status"] == "incomplete"
    assert option["incomplete_reason"] == "missing_exit_book"


def test_shadow_rejects_tampered_source_digest() -> None:
    evidence = _evidence(timestamp_ms=40_000_000)
    source = deepcopy(
        _source(evidence, exit_book=_exit_book(evidence))
    )
    source["source_opportunity_count"] = 2

    with pytest.raises(
        ProspectiveDrawdown5mExecutionError,
        match="digest mismatch",
    ):
        prospective_drawdown_5m_execution_summary(source)
