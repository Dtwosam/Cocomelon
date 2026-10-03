from __future__ import annotations

# ruff: noqa: I001 -- red TDD imports reference modules added next.

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
from cocomelon.research.prospective_weekly_drawdown_5m_exit import (
    ProspectiveWeeklyDrawdown5mExitError,
    prospective_weekly_drawdown_5m_exit_summary,
)
from cocomelon.research.prospective_weekly_drawdown_5m_exit_source import (
    EXIT_HORIZON_MS,
    ProspectiveWeeklyDrawdown5mExitSourceError,
    ProspectiveWeeklyDrawdown5mExitState,
    prospective_weekly_drawdown_5m_exit_source,
)
from cocomelon.risk.engine import evaluate_risk


def _market(name: str = "SOL") -> MarketId:
    return MarketId.from_wire_name("", name)


def _evidence(
    *,
    timestamp_ms: int,
    direction: Direction = Direction.LONG,
    cooldown_active: bool = False,
) -> ContinuousPaperOpeningOpportunityEvidence:
    config = PaperExecutionConfig()
    market = _market()
    invalidation = (
        Decimal("90")
        if direction is Direction.LONG
        else Decimal("110")
    )
    decision = StrategyDecision(
        market=market,
        direction=direction,
        score=Decimal("0.8"),
        timestamp_ms=timestamp_ms - config.latency_ms,
        feature_snapshot_id=f"feature-{timestamp_ms}",
        lead_strategy="trend",
        invalidation_price=invalidation,
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
            liquidation_price=Decimal("50"),
            venue_min_notional=Decimal("10"),
            as_of_ms=timestamp_ms,
        ),
        limits=RiskLimits(),
        timestamp_ms=timestamp_ms,
    )
    baseline = evaluate_risk(request)
    assert baseline.approved is False
    assert baseline.reason_codes == ("weekly_drawdown_lockout",)

    instrument = InstrumentExecutionSpec(
        market=market,
        sz_decimals=2,
        venue_max_leverage=Decimal("5"),
        minimum_order_notional=Decimal("10"),
        metadata_received_at_ms=timestamp_ms - 1_000,
        metadata_source="fixture",
    )
    book = StreamEvent(
        kind=StreamKind.L2_BOOK,
        market=market,
        exchange_time_ms=timestamp_ms,
        receive_time=datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC),
        schema_version=1,
        source="fixture",
        event_key=f"entry-book-{timestamp_ms}",
        payload={
            "bids": (
                {
                    "px": Decimal("99.95"),
                    "sz": Decimal("1000"),
                    "n": 1,
                },
            ),
            "asks": (
                {
                    "px": Decimal("100.05"),
                    "sz": Decimal("1000"),
                    "n": 1,
                },
            ),
        },
    )
    return ContinuousPaperOpeningOpportunityEvidence(
        strategy_decision_id=decision.decision_id,
        feature_snapshot_id=decision.feature_snapshot_id,
        market=market.canonical,
        direction=direction.value,
        lead_strategy="trend",
        opportunity_timestamp_ms=timestamp_ms,
        baseline_risk_approved=False,
        baseline_risk_reason_codes=baseline.reason_codes,
        baseline_risk_decision_id=baseline.risk_decision_id,
        equity_before=request.account_state.equity,
        risk_request=_risk_request_payload(request),
        instrument=_instrument_payload(instrument),
        book=_book_payload(book),
        rank_observed_at_ms=timestamp_ms - 100,
        rank_ordinal=3,
        rank_score=Decimal("0.9"),
        rank_pool_size=20,
        rank_reason_codes=("fixture",),
    )


def _exit_book(
    evidence: ContinuousPaperOpeningOpportunityEvidence,
    *,
    exit_px: str = "102",
) -> OpeningOpportunityExitBookEvidence:
    target = evidence.opportunity_timestamp_ms + EXIT_HORIZON_MS
    market = evidence.instrument_object.market
    px = Decimal(exit_px)
    book = StreamEvent(
        kind=StreamKind.L2_BOOK,
        market=market,
        exchange_time_ms=target,
        receive_time=datetime.fromtimestamp(target / 1000, tz=UTC),
        schema_version=1,
        source="fixture",
        event_key=f"exit-book-{target}",
        payload={
            "bids": (
                {
                    "px": px,
                    "sz": Decimal("1000"),
                    "n": 1,
                },
            ),
            "asks": (
                {
                    "px": px + Decimal("0.1"),
                    "sz": Decimal("1000"),
                    "n": 1,
                },
            ),
        },
    )
    return OpeningOpportunityExitBookEvidence(
        opportunity_id=evidence.opportunity_id,
        market=evidence.market,
        direction=evidence.direction,
        opportunity_timestamp_ms=evidence.opportunity_timestamp_ms,
        horizon_ms=EXIT_HORIZON_MS,
        target_at_ms=target,
        observed_at_ms=target,
        observation_lag_ms=0,
        book_event=book,
        instrument=evidence.instrument_object,
    )


def _full_stack_summary(
    evidence: ContinuousPaperOpeningOpportunityEvidence,
    *,
    integrity_last_miss_at_ms: int | None,
    stack_decision: str = "ADMIT",
) -> dict[str, object]:
    return {
        "enabled": True,
        "error": None,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_readiness_gate": False,
        "changes_closed_trade_readiness_gate": False,
        "overlap_started_at_ms": evidence.opportunity_timestamp_ms - 10_000,
        "risk_rejected_integrity_clean": (
            integrity_last_miss_at_ms is None
        ),
        "risk_rejected_integrity_last_miss_at_ms": (
            integrity_last_miss_at_ms
        ),
        "risk_rejected_rows": [
            {
                "opportunity_id": evidence.opportunity_id,
                "timestamp_ms": evidence.opportunity_timestamp_ms,
                "market": evidence.market,
                "direction": evidence.direction,
                "lead_strategy": evidence.lead_strategy,
                "rank_ordinal": 3,
                "rank_age_ms": 100,
                "baseline_risk_reason_codes": [
                    "weekly_drawdown_lockout"
                ],
                "combined_block_reason": None,
                "two_strike_prior_strikes": 0,
                "momentum_decision": "ADMIT",
                "momentum_reason": "momentum_band_admit",
                "momentum_prior_strikes": 0,
                "stack_decision": stack_decision,
                "block_layer": (
                    "none" if stack_decision == "ADMIT" else "momentum"
                ),
            }
        ],
    }


def _source(
    evidence: ContinuousPaperOpeningOpportunityEvidence,
    *,
    state: ProspectiveWeeklyDrawdown5mExitState,
    exit_book: OpeningOpportunityExitBookEvidence | None,
    cooldown_active: bool = False,
) -> dict[str, object]:
    del cooldown_active
    return prospective_weekly_drawdown_5m_exit_source(
        _full_stack_summary(
            evidence,
            integrity_last_miss_at_ms=state.started_at_ms - 1,
        ),
        (evidence,),
        (() if exit_book is None else (exit_book,)),
        (),
        PaperExecutionConfig(),
        state,
    )


def test_state_round_trip_freezes_post_deploy_five_minute_rule() -> None:
    state = ProspectiveWeeklyDrawdown5mExitState(started_at_ms=10_000)

    restored = ProspectiveWeeklyDrawdown5mExitState.from_payload(
        state.payload()
    )

    assert restored == state
    assert restored.exit_horizon_ms == 300_000
    assert restored.payload()["rule"] == {
        "entry_scope": "weekly_drawdown_only_full_stack_admit",
        "entry_execution": "captured_request_visible_book_ioc",
        "exit_horizon_ms": 300_000,
        "exit_execution": "captured_real_l2_reduce_only_ioc",
        "funding_policy": "exact_captured_hourly_boundaries",
        "cross_horizon_selection": "frozen_single_horizon",
    }


def test_source_exports_only_post_freeze_stack_admit_weekly_lockout() -> None:
    state = ProspectiveWeeklyDrawdown5mExitState(started_at_ms=9_000_000)
    evidence = _evidence(timestamp_ms=10_000_000)
    book = _exit_book(evidence)

    payload = prospective_weekly_drawdown_5m_exit_source(
        _full_stack_summary(
            evidence,
            integrity_last_miss_at_ms=8_999_999,
        ),
        (evidence,),
        (book,),
        (),
        PaperExecutionConfig(),
        state,
    )

    assert payload["source_opportunity_count"] == 1
    assert payload["missing_exit_books"] == 0
    assert payload["discovery_opportunities_excluded"] == 0
    assert payload["execution_authority"] is False
    rows = payload["opportunities"]
    assert isinstance(rows, list)
    assert rows[0]["opportunity_id"] == evidence.opportunity_id
    assert rows[0]["exit_book"]["horizon_ms"] == EXIT_HORIZON_MS


def test_source_excludes_discovery_rows_before_freeze() -> None:
    evidence = _evidence(timestamp_ms=10_000_000)
    state = ProspectiveWeeklyDrawdown5mExitState(started_at_ms=10_000_001)

    payload = prospective_weekly_drawdown_5m_exit_source(
        _full_stack_summary(
            evidence,
            integrity_last_miss_at_ms=9_000_000,
        ),
        (evidence,),
        (_exit_book(evidence),),
        (),
        PaperExecutionConfig(),
        state,
    )

    assert payload["source_opportunity_count"] == 0
    assert payload["discovery_opportunities_excluded"] == 1


def test_source_fails_closed_if_integrity_break_reaches_candidate_window() -> None:
    evidence = _evidence(timestamp_ms=10_000_000)
    state = ProspectiveWeeklyDrawdown5mExitState(started_at_ms=9_000_000)

    with pytest.raises(
        ProspectiveWeeklyDrawdown5mExitSourceError,
        match="integrity miss overlaps candidate window",
    ):
        prospective_weekly_drawdown_5m_exit_source(
            _full_stack_summary(
                evidence,
                integrity_last_miss_at_ms=9_500_000,
            ),
            (evidence,),
            (_exit_book(evidence),),
            (),
            PaperExecutionConfig(),
            state,
        )


def test_shadow_replays_entry_and_exact_real_l2_five_minute_exit() -> None:
    evidence = _evidence(timestamp_ms=10_000_000)
    state = ProspectiveWeeklyDrawdown5mExitState(started_at_ms=9_000_000)

    result = prospective_weekly_drawdown_5m_exit_summary(
        _source(
            evidence,
            state=state,
            exit_book=_exit_book(evidence),
        )
    )

    assert result["source_opportunities"] == 1
    assert result["counterfactual_risk_approvals"] == 1
    assert result["planning_approvals"] == 1
    assert result["entry_fills"] == 1
    assert result["complete_five_minute_exits"] == 1
    assert result["exact_realized_pnl_options"] == 1
    assert Decimal(result["total_exact_realized_pnl"]) > 0
    option = result["option_results"][0]
    assert option["entry_execution_result"] == "full"
    assert option["exit_execution_result"] == "full"
    assert option["complete_close"] is True
    assert option["funding_boundary_count"] == 0
    assert option["funding_evidence_count"] == 0
    assert Decimal(option["exact_realized_pnl"]) > 0
    assert result["execution_authority"] is False
    assert result["promotion_authority"] is False
    assert result["changes_risk_limits"] is False


def test_shadow_exposes_other_veto_after_weekly_drawdown_removed() -> None:
    evidence = _evidence(
        timestamp_ms=20_000_000,
        cooldown_active=True,
    )
    state = ProspectiveWeeklyDrawdown5mExitState(started_at_ms=19_000_000)

    result = prospective_weekly_drawdown_5m_exit_summary(
        _source(
            evidence,
            state=state,
            exit_book=_exit_book(evidence),
        )
    )

    assert result["counterfactual_risk_approvals"] == 0
    assert result["counterfactual_risk_rejections"] == {
        "consecutive_loss_cooldown": 1
    }
    assert result["entry_fills"] == 0
    assert result["exact_realized_pnl_options"] == 0


def test_shadow_keeps_missing_five_minute_exit_book_incomplete() -> None:
    evidence = _evidence(timestamp_ms=30_000_000)
    state = ProspectiveWeeklyDrawdown5mExitState(started_at_ms=29_000_000)

    result = prospective_weekly_drawdown_5m_exit_summary(
        _source(
            evidence,
            state=state,
            exit_book=None,
        )
    )

    assert result["entry_fills"] == 1
    assert result["complete_five_minute_exits"] == 0
    assert result["exact_realized_pnl_options"] == 0
    option = result["option_results"][0]
    assert option["incomplete_reason"] == "missing_exit_book"


def test_shadow_rejects_tampered_source_digest() -> None:
    evidence = _evidence(timestamp_ms=40_000_000)
    state = ProspectiveWeeklyDrawdown5mExitState(started_at_ms=39_000_000)
    source = _source(
        evidence,
        state=state,
        exit_book=_exit_book(evidence),
    )
    source["source_opportunity_count"] = 2

    with pytest.raises(
        ProspectiveWeeklyDrawdown5mExitError,
        match="source digest mismatch",
    ):
        prospective_weekly_drawdown_5m_exit_summary(source)
