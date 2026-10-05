from __future__ import annotations

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
from cocomelon.execution.funding import FUNDING_INTERVAL_MS
from cocomelon.research.continuous_paper_opening_opportunity import (
    ContinuousPaperOpeningOpportunityEvidence,
    _book_payload,
    _instrument_payload,
    _risk_request_payload,
)
from cocomelon.research.continuous_paper_opening_opportunity_exit_books import (
    OpeningOpportunityExitBookEvidence,
)
from cocomelon.research.continuous_paper_replacement_funding import (
    ReplacementFundingBoundaryEvidence,
)
from cocomelon.research.prospective_full_stack_forward_markout import (
    LONG_TREND_CARVEOUT_CANDIDATE_ID,
)
from cocomelon.research.prospective_long_trend_15m_exit import (
    ProspectiveLongTrend15mExitError,
    _exact_pnl_robustness,
    prospective_long_trend_15m_exit_summary,
)
from cocomelon.research.prospective_long_trend_15m_exit_source import (
    EXIT_HORIZON_MS,
    FROZEN_STARTED_AT_MS,
    ProspectiveLongTrend15mExitSourceError,
    ProspectiveLongTrend15mExitState,
    prospective_long_trend_15m_exit_source,
)
from cocomelon.risk.engine import evaluate_risk


def _market(name: str = "SOL") -> MarketId:
    return MarketId.from_wire_name("", name)


def _evidence(
    *,
    timestamp_ms: int,
    market_name: str = "SOL",
) -> ContinuousPaperOpeningOpportunityEvidence:
    config = PaperExecutionConfig()
    market = _market(market_name)
    decision = StrategyDecision(
        market=market,
        direction=Direction.LONG,
        score=Decimal("0.8"),
        timestamp_ms=timestamp_ms - config.latency_ms,
        feature_snapshot_id=f"feature-{timestamp_ms}",
        lead_strategy="trend",
        invalidation_price=Decimal("90"),
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
        consecutive_losses=0,
        last_closed_trade_ms=None,
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
                {"px": Decimal("99.95"), "sz": Decimal("1000"), "n": 1},
            ),
            "asks": (
                {"px": Decimal("100.05"), "sz": Decimal("1000"), "n": 1},
            ),
        },
    )
    return ContinuousPaperOpeningOpportunityEvidence(
        strategy_decision_id=decision.decision_id,
        feature_snapshot_id=decision.feature_snapshot_id,
        market=market.canonical,
        direction="long",
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
                {"px": px, "sz": Decimal("1000"), "n": 1},
            ),
            "asks": (
                {"px": px + Decimal("0.1"), "sz": Decimal("1000"), "n": 1},
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


def _funding_evidence(
    evidence: ContinuousPaperOpeningOpportunityEvidence,
) -> tuple[ReplacementFundingBoundaryEvidence, ...]:
    opened_at_ms = evidence.opportunity_timestamp_ms
    closed_at_ms = opened_at_ms + EXIT_HORIZON_MS
    first_boundary_ms = (
        (opened_at_ms // FUNDING_INTERVAL_MS) + 1
    ) * FUNDING_INTERVAL_MS
    if first_boundary_ms > closed_at_ms:
        return ()
    return tuple(
        ReplacementFundingBoundaryEvidence(
            market=evidence.market,
            boundary_ms=boundary_ms,
            oracle_px=Decimal("100"),
            oracle_observed_at_ms=boundary_ms - 100,
            oracle_age_ms=100,
            oracle_source="fixture",
            oracle_schema_version=1,
            funding_rate=Decimal("0"),
            premium=Decimal("0"),
            funding_time_ms=boundary_ms,
            funding_received_at_ms=boundary_ms,
            funding_source="fixture",
            funding_schema_version=1,
        )
        for boundary_ms in range(
            first_boundary_ms,
            closed_at_ms + 1,
            FUNDING_INTERVAL_MS,
        )
    )


def _full_stack_summary(
    evidence: ContinuousPaperOpeningOpportunityEvidence,
    *,
    started_at_ms: int,
    long_trend_decision: str = "ADMIT",
    stop_status: str = "observed_path_survivor",
) -> dict[str, object]:
    stop_crossed = stop_status == "observed_stop_crossing"
    survived = stop_status == "observed_path_survivor"
    return {
        "enabled": True,
        "error": None,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_readiness_gate": False,
        "changes_closed_trade_readiness_gate": False,
        "overlap_started_at_ms": started_at_ms - 10_000,
        "risk_rejected_integrity_clean": True,
        "risk_rejected_integrity_last_miss_at_ms": None,
        "risk_rejected_rows": [
            {
                "opportunity_id": evidence.opportunity_id,
                "timestamp_ms": evidence.opportunity_timestamp_ms,
                "market": evidence.market,
                "direction": evidence.direction,
                "lead_strategy": evidence.lead_strategy,
                "rank_ordinal": 3,
                "rank_age_ms": 100,
                "baseline_risk_reason_codes": ["weekly_drawdown_lockout"],
                "combined_block_reason": "long_trend",
                "two_strike_prior_strikes": 0,
                "momentum_decision": None,
                "momentum_reason": None,
                "momentum_prior_strikes": None,
                "stack_decision": "BLOCK",
                "block_layer": "combined",
                "long_trend_carveout_candidate_id": (
                    LONG_TREND_CARVEOUT_CANDIDATE_ID
                ),
                "long_trend_carveout_decision": long_trend_decision,
                "long_trend_carveout_block_layer": (
                    "none"
                    if long_trend_decision == "ADMIT"
                    else "momentum"
                ),
                "long_trend_carveout_momentum_decision": (
                    long_trend_decision
                ),
                "long_trend_carveout_momentum_reason": "fixture",
                "long_trend_carveout_momentum_prior_strikes": 0,
                "long_trend_carveout_stop_path": {
                    "claim_scope": "observed_mark_stop_crossing_only",
                    "original_stop_price": "90",
                    "entry_reference_price": "100",
                    "changes_execution": False,
                    "changes_risk_limits": False,
                    "changes_candidate_readiness": False,
                    "horizons": {
                        str(EXIT_HORIZON_MS): {
                            "status": stop_status,
                            "target_at_ms": (
                                evidence.opportunity_timestamp_ms
                                + EXIT_HORIZON_MS
                            ),
                            "observed_mark_count": 3,
                            "stop_crossed": (
                                stop_crossed
                                if stop_status
                                in {
                                    "observed_stop_crossing",
                                    "observed_path_survivor",
                                }
                                else None
                            ),
                            "first_stop_cross_at_ms": (
                                evidence.opportunity_timestamp_ms + 120_000
                                if stop_crossed
                                else None
                            ),
                            "first_stop_cross_mark_px": (
                                "89" if stop_crossed else None
                            ),
                            "time_to_stop_ms": (
                                120_000 if stop_crossed else None
                            ),
                            "survived_observed_marks_to_horizon": (
                                survived
                                if stop_status
                                in {
                                    "observed_stop_crossing",
                                    "observed_path_survivor",
                                }
                                else None
                            ),
                        }
                    },
                },
            }
        ],
    }


def _source(
    evidence: ContinuousPaperOpeningOpportunityEvidence,
    *,
    state: ProspectiveLongTrend15mExitState,
    exit_book: OpeningOpportunityExitBookEvidence | None,
    long_trend_decision: str = "ADMIT",
    stop_status: str = "observed_path_survivor",
) -> dict[str, object]:
    return prospective_long_trend_15m_exit_source(
        _full_stack_summary(
            evidence,
            started_at_ms=state.started_at_ms,
            long_trend_decision=long_trend_decision,
            stop_status=stop_status,
        ),
        (evidence,),
        (() if exit_book is None else (exit_book,)),
        _funding_evidence(evidence),
        PaperExecutionConfig(),
        state,
    )


def test_frozen_start_is_after_discovery_evidence() -> None:
    assert FROZEN_STARTED_AT_MS == 1_791_193_533_061


def test_state_freezes_pure_long_trend_fixed_15m_rule() -> None:
    state = ProspectiveLongTrend15mExitState(
        started_at_ms=FROZEN_STARTED_AT_MS
    )

    restored = ProspectiveLongTrend15mExitState.from_payload(
        state.payload()
    )

    assert restored == state
    assert restored.payload()["rule"] == {
        "entry_scope": "weekly_drawdown_only_reopened_pure_long_trend",
        "entry_execution": "captured_request_visible_book_ioc",
        "exit_horizon_ms": 900_000,
        "exit_execution": "captured_real_l2_reduce_only_ioc",
        "funding_policy": "exact_captured_hourly_boundaries",
        "cross_horizon_selection": "frozen_single_horizon",
    }


def test_source_exports_only_post_freeze_reopened_pure_long_trend() -> None:
    state = ProspectiveLongTrend15mExitState(
        started_at_ms=FROZEN_STARTED_AT_MS
    )
    evidence = _evidence(timestamp_ms=FROZEN_STARTED_AT_MS + 1_000)

    payload = prospective_long_trend_15m_exit_source(
        _full_stack_summary(
            evidence,
            started_at_ms=state.started_at_ms,
        ),
        (evidence,),
        (_exit_book(evidence),),
        (),
        PaperExecutionConfig(),
        state,
    )

    assert payload["source_opportunity_count"] == 1
    assert payload["discovery_opportunities_excluded"] == 0
    assert payload["missing_exit_books"] == 0
    row = payload["opportunities"][0]
    assert row["lineage"]["combined_block_reason"] == "long_trend"
    assert row["lineage"]["stack_decision"] == "BLOCK"
    assert row["lineage"]["long_trend_carveout_decision"] == "ADMIT"
    assert row["lineage"]["long_trend_carveout_block_layer"] == "none"
    assert payload["execution_authority"] is False
    assert payload["changes_risk_limits"] is False


def test_source_excludes_pre_freeze_discovery_row() -> None:
    state = ProspectiveLongTrend15mExitState(
        started_at_ms=FROZEN_STARTED_AT_MS
    )
    evidence = _evidence(timestamp_ms=FROZEN_STARTED_AT_MS - 1)

    payload = prospective_long_trend_15m_exit_source(
        _full_stack_summary(
            evidence,
            started_at_ms=state.started_at_ms,
        ),
        (evidence,),
        (_exit_book(evidence),),
        (),
        PaperExecutionConfig(),
        state,
    )

    assert payload["source_opportunity_count"] == 0
    assert payload["discovery_opportunities_excluded"] == 1


def test_source_rejects_non_reopened_long_trend_row() -> None:
    state = ProspectiveLongTrend15mExitState(
        started_at_ms=FROZEN_STARTED_AT_MS
    )
    evidence = _evidence(timestamp_ms=FROZEN_STARTED_AT_MS + 2_000)

    payload = prospective_long_trend_15m_exit_source(
        _full_stack_summary(
            evidence,
            started_at_ms=state.started_at_ms,
            long_trend_decision="BLOCK",
        ),
        (evidence,),
        (_exit_book(evidence),),
        (),
        PaperExecutionConfig(),
        state,
    )

    assert payload["source_opportunity_count"] == 0


def test_exact_fifteen_minute_replay_is_research_only() -> None:
    state = ProspectiveLongTrend15mExitState(
        started_at_ms=FROZEN_STARTED_AT_MS
    )
    evidence = _evidence(timestamp_ms=FROZEN_STARTED_AT_MS + 3_000)

    result = prospective_long_trend_15m_exit_summary(
        _source(
            evidence,
            state=state,
            exit_book=_exit_book(evidence),
        )
    )

    assert result["source_opportunities"] == 1
    assert result["counterfactual_risk_approvals"] == 1
    assert result["entry_fills"] == 1
    assert result["complete_fifteen_minute_exits"] == 1
    assert result["exact_realized_pnl_options"] == 1
    assert Decimal(result["total_gross_realized_pnl"]) > 0
    assert Decimal(result["total_fee_drag"]) > 0
    assert Decimal(result["total_exact_realized_pnl"]) > 0
    assert result["gross_return_on_entry_notional"] is not None
    assert result["fee_drag_fraction_of_entry_notional"] is not None
    assert result["net_return_on_entry_notional"] is not None
    assert result["candidate_investigation_ready"] is False
    assert result["execution_authority"] is False
    assert result["promotion_authority"] is False
    assert result["changes_risk_limits"] is False


def test_observed_stop_crossing_blocks_fifteen_minute_credit() -> None:
    state = ProspectiveLongTrend15mExitState(
        started_at_ms=FROZEN_STARTED_AT_MS
    )
    evidence = _evidence(timestamp_ms=FROZEN_STARTED_AT_MS + 4_000)

    result = prospective_long_trend_15m_exit_summary(
        _source(
            evidence,
            state=state,
            exit_book=_exit_book(evidence),
            stop_status="observed_stop_crossing",
        )
    )

    assert result["exact_realized_pnl_options"] == 0
    option = result["option_results"][0]
    assert option["incomplete_reason"] == "observed_stop_crossing_before_15m"


def test_robustness_gate_requires_sample_and_diversification() -> None:
    rows = tuple(
        {
            "opportunity_id": f"op-{index}",
            "timestamp_ms": 1_000 + index,
            "market": ("SOL", "BTC", "ETH", "HYPE")[index % 4],
            "exact_realized_pnl": "1",
        }
        for index in range(12)
    )

    robustness = _exact_pnl_robustness(rows)

    assert robustness["minimum_sample_met"] is True
    assert robustness["positive_after_removing_any_one_option"] is True
    assert robustness["positive_after_removing_any_one_market"] is True
    assert robustness["chronological_halves_positive"] is True
    assert robustness["investigation_ready"] is True


def test_source_fails_closed_on_integrity_miss_after_freeze() -> None:
    state = ProspectiveLongTrend15mExitState(
        started_at_ms=FROZEN_STARTED_AT_MS
    )
    evidence = _evidence(timestamp_ms=FROZEN_STARTED_AT_MS + 5_000)
    summary = _full_stack_summary(
        evidence,
        started_at_ms=state.started_at_ms,
    )
    summary["risk_rejected_integrity_clean"] = False
    summary["risk_rejected_integrity_last_miss_at_ms"] = (
        state.started_at_ms + 1
    )

    with pytest.raises(
        ProspectiveLongTrend15mExitSourceError,
        match="integrity miss overlaps candidate window",
    ):
        prospective_long_trend_15m_exit_source(
            summary,
            (evidence,),
            (_exit_book(evidence),),
            (),
            PaperExecutionConfig(),
            state,
        )


def test_tampered_source_digest_is_rejected() -> None:
    state = ProspectiveLongTrend15mExitState(
        started_at_ms=FROZEN_STARTED_AT_MS
    )
    evidence = _evidence(timestamp_ms=FROZEN_STARTED_AT_MS + 6_000)
    source = _source(
        evidence,
        state=state,
        exit_book=_exit_book(evidence),
    )
    source["source_opportunity_count"] = 2

    with pytest.raises(
        ProspectiveLongTrend15mExitError,
        match="source digest mismatch",
    ):
        prospective_long_trend_15m_exit_summary(source)
