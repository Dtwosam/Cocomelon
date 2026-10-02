from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

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
from cocomelon.research.continuous_paper_opening_opportunity_paths import (
    ContinuousPaperOpeningOpportunityPath,
    ContinuousPaperOpeningOpportunityPathMark,
)
from cocomelon.research.prospective_weekly_drawdown_lockout_shadow import (
    EMBARGO_MS,
    FORWARD_HORIZONS_MS,
    ProspectiveWeeklyDrawdownLockoutShadowState,
    prospective_weekly_drawdown_lockout_shadow_summary,
)
from cocomelon.risk.engine import evaluate_risk


def _market(name: str) -> MarketId:
    return MarketId.from_wire_name("", name)


def _evidence(
    *,
    timestamp_ms: int,
    direction: Direction = Direction.SHORT,
    consecutive_losses: int = 0,
    last_closed_trade_ms: int | None = None,
) -> ContinuousPaperOpeningOpportunityEvidence:
    config = PaperExecutionConfig()
    decision = StrategyDecision(
        market=_market("SOL"),
        direction=direction,
        score=Decimal("0.8"),
        timestamp_ms=timestamp_ms - config.latency_ms,
        feature_snapshot_id=f"feature-{timestamp_ms}-{direction.value}",
        lead_strategy="breakout",
        invalidation_price=(
            Decimal("90")
            if direction is Direction.LONG
            else Decimal("110")
        ),
        signal_ids=(f"signal-{timestamp_ms}",),
        reason_codes=("decision_threshold_met",),
    )
    request = RiskRequest(
        strategy_decision=decision,
        entry_reference_price=Decimal("100"),
        correlation_bucket="alts",
        account_state=RiskAccountState(
            equity=Decimal("9600"),
            day_start_equity=Decimal("9600"),
            daily_realized_pnl=Decimal("0"),
            rolling_7d_peak_equity=Decimal("10000"),
            available_margin=Decimal("9000"),
            gross_open_notional=Decimal("0"),
            consecutive_losses=consecutive_losses,
            last_closed_trade_ms=last_closed_trade_ms,
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
    assert baseline.approved is False
    assert baseline.reason_codes == ("weekly_drawdown_lockout",)

    instrument = InstrumentExecutionSpec(
        market=request.market,
        sz_decimals=2,
        venue_max_leverage=Decimal("5"),
        minimum_order_notional=Decimal("10"),
        metadata_received_at_ms=timestamp_ms - 1_000,
        metadata_source="fixture",
    )
    book = StreamEvent(
        kind=StreamKind.L2_BOOK,
        market=request.market,
        exchange_time_ms=timestamp_ms,
        receive_time=datetime.fromtimestamp(
            timestamp_ms / 1000,
            tz=UTC,
        ),
        schema_version=1,
        source="fixture",
        event_key=f"book-{timestamp_ms}",
        payload={
            "bids": (
                {"px": Decimal("99.95"), "sz": Decimal("1000"), "n": 1},
                {"px": Decimal("99.90"), "sz": Decimal("1000"), "n": 1},
            ),
            "asks": (
                {"px": Decimal("100.05"), "sz": Decimal("1000"), "n": 1},
                {"px": Decimal("100.10"), "sz": Decimal("1000"), "n": 1},
            ),
        },
    )
    return ContinuousPaperOpeningOpportunityEvidence(
        strategy_decision_id=decision.decision_id,
        feature_snapshot_id=decision.feature_snapshot_id,
        market=decision.market.canonical,
        direction=decision.direction.value,
        lead_strategy="breakout",
        opportunity_timestamp_ms=timestamp_ms,
        baseline_risk_approved=False,
        baseline_risk_reason_codes=baseline.reason_codes,
        baseline_risk_decision_id=baseline.risk_decision_id,
        equity_before=request.account_state.equity,
        risk_request=_risk_request_payload(request),
        instrument=_instrument_payload(instrument),
        book=_book_payload(book),
        rank_observed_at_ms=timestamp_ms - 100,
        rank_ordinal=4,
        rank_score=Decimal("0.9"),
        rank_pool_size=20,
        rank_reason_codes=("fixture",),
    )


def _path(
    evidence: ContinuousPaperOpeningOpportunityEvidence,
) -> ContinuousPaperOpeningOpportunityPath:
    prices = ("99", "100.5", "98")
    return ContinuousPaperOpeningOpportunityPath(
        opportunity_id=evidence.opportunity_id,
        market=evidence.market,
        direction=evidence.direction,
        opportunity_timestamp_ms=evidence.opportunity_timestamp_ms,
        max_path_age_ms=21_600_000,
        max_completion_lag_ms=120_000,
        marks=tuple(
            ContinuousPaperOpeningOpportunityPathMark(
                observed_at_ms=(
                    evidence.opportunity_timestamp_ms + horizon_ms
                ),
                mark_px=Decimal(price),
                source="fixture",
            )
            for horizon_ms, price in zip(
                FORWARD_HORIZONS_MS,
                prices,
                strict=True,
            )
        ),
    )


def _full_stack(
    evidence: ContinuousPaperOpeningOpportunityEvidence,
    *,
    decision: str = "ADMIT",
) -> dict[str, object]:
    return {
        "enabled": True,
        "error": None,
        "candidate_stack": "combined+two_strike+momentum",
        "risk_rejected_stack_evaluated": 1,
        "risk_rejected_integrity_clean": True,
        "risk_rejected_rows": [
            {
                "opportunity_id": evidence.opportunity_id,
                "baseline_risk_reason_codes": [
                    "weekly_drawdown_lockout"
                ],
                "stack_decision": decision,
            }
        ],
    }


def test_weekly_drawdown_shadow_replays_full_stack_admitted_entry() -> None:
    timestamp_ms = EMBARGO_MS + 10_000_000
    evidence = _evidence(timestamp_ms=timestamp_ms)
    state = ProspectiveWeeklyDrawdownLockoutShadowState(
        frozen_at_ms=timestamp_ms - EMBARGO_MS
    )

    result = prospective_weekly_drawdown_lockout_shadow_summary(
        (evidence,),
        (_path(evidence),),
        _full_stack(evidence),
        state,
        PaperExecutionConfig(),
    )

    assert result["observed_weekly_drawdown_rejections"] == 1
    assert result["full_stack_admitted_weekly_rejections"] == 1
    assert result["clean_admitted_weekly_rejections"] == 1
    assert result["counterfactual_risk_rejections"] == {}
    assert result["planning_rejections"] == {}
    assert sum(result["execution_results"].values()) == 1
    option = result["option_results"][0]
    assert option["counterfactual_risk_approved"] is True
    assert option["planning_approved"] is True
    assert option["filled_quantity"] is not None
    assert Decimal(option["baseline_weekly_drawdown_fraction"]) == Decimal(
        "0.04"
    )
    assert option["markouts"]["300000"]["status"] == "settled"
    assert option["markouts"]["900000"]["status"] == "settled"
    assert option["markouts"]["3600000"]["status"] == "settled"
    assert result["changes_risk_limits"] is False
    assert result["realized_pnl_modeled"] is False


def test_weekly_drawdown_shadow_excludes_full_stack_block() -> None:
    timestamp_ms = EMBARGO_MS + 20_000_000
    evidence = _evidence(timestamp_ms=timestamp_ms)
    state = ProspectiveWeeklyDrawdownLockoutShadowState(
        frozen_at_ms=timestamp_ms - EMBARGO_MS
    )

    result = prospective_weekly_drawdown_lockout_shadow_summary(
        (evidence,),
        (_path(evidence),),
        _full_stack(evidence, decision="BLOCK"),
        state,
        PaperExecutionConfig(),
    )

    assert result["observed_weekly_drawdown_rejections"] == 1
    assert result["full_stack_admitted_weekly_rejections"] == 0
    assert result["clean_admitted_weekly_rejections"] == 0
    assert result["option_results"] == []


def test_weekly_drawdown_shadow_preserves_other_risk_vetoes() -> None:
    timestamp_ms = EMBARGO_MS + 30_000_000
    evidence = _evidence(
        timestamp_ms=timestamp_ms,
        consecutive_losses=3,
        last_closed_trade_ms=timestamp_ms - 60_000,
    )
    state = ProspectiveWeeklyDrawdownLockoutShadowState(
        frozen_at_ms=timestamp_ms - EMBARGO_MS
    )

    result = prospective_weekly_drawdown_lockout_shadow_summary(
        (evidence,),
        (),
        _full_stack(evidence),
        state,
        PaperExecutionConfig(),
    )

    assert result["counterfactual_risk_rejections"] == {
        "consecutive_loss_cooldown": 1
    }
    option = result["option_results"][0]
    assert option["counterfactual_risk_approved"] is False
    assert option["planning_approved"] is False
    assert option["filled_quantity"] is None


def test_weekly_drawdown_shadow_quarantines_touched_evidence() -> None:
    started_at_ms = EMBARGO_MS + 40_000_000
    evidence = _evidence(timestamp_ms=started_at_ms - 1)
    state = ProspectiveWeeklyDrawdownLockoutShadowState(
        frozen_at_ms=started_at_ms - EMBARGO_MS
    )

    result = prospective_weekly_drawdown_lockout_shadow_summary(
        (evidence,),
        (_path(evidence),),
        _full_stack(evidence),
        state,
        PaperExecutionConfig(),
    )

    assert result["full_stack_admitted_weekly_rejections"] == 1
    assert result["pre_clean_touched_admitted_rejections"] == 1
    assert result["clean_admitted_weekly_rejections"] == 0
    assert result["option_results"] == []


def test_weekly_drawdown_shadow_state_round_trip() -> None:
    state = ProspectiveWeeklyDrawdownLockoutShadowState(
        frozen_at_ms=123
    )
    restored = ProspectiveWeeklyDrawdownLockoutShadowState.from_payload(
        state.payload()
    )
    assert restored == state
