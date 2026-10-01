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
    OpenPositionRisk,
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
from cocomelon.research.prospective_consecutive_loss_cooldown_shadow import (
    EMBARGO_MS,
    FORWARD_HORIZONS_MS,
    ProspectiveConsecutiveLossCooldownShadowError,
    ProspectiveConsecutiveLossCooldownShadowState,
    prospective_consecutive_loss_cooldown_shadow_summary,
)
from cocomelon.risk.engine import evaluate_risk


def _market(name: str) -> MarketId:
    return MarketId.from_wire_name("", name)


def _evidence(
    *,
    timestamp_ms: int,
    elapsed_ms: int,
    direction: Direction = Direction.SHORT,
    lead_strategy: str = "breakout",
    rank_ordinal: int | None = 4,
    open_positions: tuple[OpenPositionRisk, ...] = (),
) -> ContinuousPaperOpeningOpportunityEvidence:
    config = PaperExecutionConfig()
    decision = StrategyDecision(
        market=_market("SOL"),
        direction=direction,
        score=Decimal("0.8"),
        timestamp_ms=timestamp_ms - config.latency_ms,
        feature_snapshot_id=f"feature-{timestamp_ms}-{direction.value}",
        lead_strategy=lead_strategy,
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
            equity=Decimal("10000"),
            day_start_equity=Decimal("10000"),
            daily_realized_pnl=Decimal("0"),
            rolling_7d_peak_equity=Decimal("10000"),
            available_margin=Decimal("9000"),
            gross_open_notional=sum(
                (position.notional for position in open_positions),
                Decimal("0"),
            ),
            consecutive_losses=3,
            last_closed_trade_ms=timestamp_ms - elapsed_ms,
            as_of_ms=timestamp_ms,
        ),
        open_positions=open_positions,
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
    assert baseline.reason_codes == ("consecutive_loss_cooldown",)

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
        lead_strategy=lead_strategy,
        opportunity_timestamp_ms=timestamp_ms,
        baseline_risk_approved=False,
        baseline_risk_reason_codes=baseline.reason_codes,
        baseline_risk_decision_id=baseline.risk_decision_id,
        equity_before=request.account_state.equity,
        risk_request=_risk_request_payload(request),
        instrument=_instrument_payload(instrument),
        book=_book_payload(book),
        rank_observed_at_ms=(
            None if rank_ordinal is None else timestamp_ms - 100
        ),
        rank_ordinal=rank_ordinal,
        rank_score=(
            None if rank_ordinal is None else Decimal("0.9")
        ),
        rank_pool_size=(
            None if rank_ordinal is None else 20
        ),
        rank_reason_codes=(
            () if rank_ordinal is None else ("fixture",)
        ),
    )


def _path(
    evidence: ContinuousPaperOpeningOpportunityEvidence,
    *,
    marks: tuple[tuple[int, str], ...],
) -> ContinuousPaperOpeningOpportunityPath:
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
                    evidence.opportunity_timestamp_ms + offset_ms
                ),
                mark_px=Decimal(price),
                source="fixture",
            )
            for offset_ms, price in marks
        ),
    )


def test_cooldown_shadow_replays_fill_and_forward_markouts() -> None:
    timestamp_ms = EMBARGO_MS + 10_000_000
    evidence = _evidence(
        timestamp_ms=timestamp_ms,
        elapsed_ms=20 * 60 * 1_000,
    )
    path = _path(
        evidence,
        marks=(
            (5 * 60 * 1_000, "99"),
            (15 * 60 * 1_000, "100.5"),
            (60 * 60 * 1_000, "98"),
        ),
    )
    state = ProspectiveConsecutiveLossCooldownShadowState(
        frozen_at_ms=timestamp_ms - EMBARGO_MS
    )

    result = prospective_consecutive_loss_cooldown_shadow_summary(
        (evidence,),
        (path,),
        state,
        PaperExecutionConfig(),
    )

    assert result["observed_cooldown_rejections"] == 1
    assert result["pre_clean_touched_cooldown_rejections"] == 0
    assert result["clean_cooldown_rejections"] == 1
    assert result["candidate_eligible_cooldown_rejections"] == 1
    assert result["counterfactual_risk_rejections"] == {}
    assert result["planning_rejections"] == {}
    assert sum(result["execution_results"].values()) == 1

    option = result["option_results"][0]
    assert option["baseline_elapsed_since_last_close_ms"] == 1_200_000
    assert option["counterfactual_risk_approved"] is True
    assert option["planning_approved"] is True
    assert option["filled_quantity"] is not None
    markouts = option["markouts"]
    assert markouts["300000"]["status"] == "settled"
    assert Decimal(
        markouts["300000"][
            "entry_fee_adjusted_mark_to_market_pnl"
        ]
    ) > 0
    assert markouts["900000"]["status"] == "settled"
    assert Decimal(
        markouts["900000"][
            "entry_fee_adjusted_mark_to_market_pnl"
        ]
    ) < 0
    assert markouts["3600000"]["status"] == "settled"
    assert Decimal(
        markouts["3600000"][
            "entry_fee_adjusted_mark_to_market_pnl"
        ]
    ) > 0

    relaxation = result["relaxation_windows"]
    assert relaxation["900000"]["would_unblock_opportunities"] == 1
    assert relaxation["1800000"]["would_unblock_opportunities"] == 0
    assert relaxation["2700000"]["would_unblock_opportunities"] == 0
    assert result["by_direction"]["short"]["settled_1h"] == 1
    assert result["changes_risk_limits"] is False
    assert result["realized_pnl_modeled"] is False


def test_cooldown_shadow_quarantines_touched_and_candidate_blocked() -> None:
    started_at_ms = EMBARGO_MS + 20_000_000
    state = ProspectiveConsecutiveLossCooldownShadowState(
        frozen_at_ms=started_at_ms - EMBARGO_MS
    )
    touched = _evidence(
        timestamp_ms=started_at_ms - 1,
        elapsed_ms=10 * 60 * 1_000,
    )
    long_trend = _evidence(
        timestamp_ms=started_at_ms + 1_000,
        elapsed_ms=10 * 60 * 1_000,
        direction=Direction.LONG,
        lead_strategy="trend",
    )
    low_rank = _evidence(
        timestamp_ms=started_at_ms + 2_000,
        elapsed_ms=10 * 60 * 1_000,
        rank_ordinal=11,
    )
    missing_rank = _evidence(
        timestamp_ms=started_at_ms + 3_000,
        elapsed_ms=10 * 60 * 1_000,
        rank_ordinal=None,
    )

    result = prospective_consecutive_loss_cooldown_shadow_summary(
        (touched, long_trend, low_rank, missing_rank),
        (),
        state,
        PaperExecutionConfig(),
    )

    assert result["observed_cooldown_rejections"] == 4
    assert result["pre_clean_touched_cooldown_rejections"] == 1
    assert result["clean_cooldown_rejections"] == 3
    assert result["candidate_eligible_cooldown_rejections"] == 0
    assert result["missing_rank_evidence"] == 1
    assert result["candidate_blocked"] == {
        "long_trend": 1,
        "rank_above_10": 1,
    }
    assert result["option_results"] == []


def test_cooldown_shadow_exposes_other_risk_rejection_after_expiry() -> None:
    timestamp_ms = EMBARGO_MS + 30_000_000
    position = OpenPositionRisk(
        market=_market("BTC"),
        direction=Direction.LONG,
        planned_risk=Decimal("50"),
        notional=Decimal("1000"),
        correlation_bucket="alts",
        entry_price=Decimal("100"),
        stop_price=Decimal("90"),
    )
    evidence = _evidence(
        timestamp_ms=timestamp_ms,
        elapsed_ms=40 * 60 * 1_000,
        open_positions=(position,),
    )
    state = ProspectiveConsecutiveLossCooldownShadowState(
        frozen_at_ms=timestamp_ms - EMBARGO_MS
    )

    result = prospective_consecutive_loss_cooldown_shadow_summary(
        (evidence,),
        (),
        state,
        PaperExecutionConfig(),
    )

    assert result["candidate_eligible_cooldown_rejections"] == 1
    assert result["counterfactual_risk_rejections"] == {
        "correlation_bucket_exhausted": 1
    }
    option = result["option_results"][0]
    assert option["counterfactual_risk_approved"] is False
    assert option["filled_quantity"] is None


def test_cooldown_shadow_reports_missing_forward_path() -> None:
    timestamp_ms = EMBARGO_MS + 40_000_000
    evidence = _evidence(
        timestamp_ms=timestamp_ms,
        elapsed_ms=40 * 60 * 1_000,
    )
    state = ProspectiveConsecutiveLossCooldownShadowState(
        frozen_at_ms=timestamp_ms - EMBARGO_MS
    )

    result = prospective_consecutive_loss_cooldown_shadow_summary(
        (evidence,),
        (),
        state,
        PaperExecutionConfig(),
    )

    for horizon_ms in FORWARD_HORIZONS_MS:
        horizon = result["by_horizon"][str(horizon_ms)]
        assert horizon["missing_path"] == 1
        assert horizon["settled"] == 0
    assert (
        result["relaxation_windows"]["1800000"][
            "would_unblock_opportunities"
        ]
        == 1
    )


def test_cooldown_shadow_state_round_trip_and_tamper() -> None:
    state = ProspectiveConsecutiveLossCooldownShadowState(
        frozen_at_ms=123
    )
    restored = ProspectiveConsecutiveLossCooldownShadowState.from_payload(
        state.payload()
    )
    assert restored == state

    payload = state.payload()
    payload["relaxed_cooldown_windows_ms"] = [600_000]
    with pytest.raises(
        ProspectiveConsecutiveLossCooldownShadowError,
        match="does not match frozen candidate",
    ):
        ProspectiveConsecutiveLossCooldownShadowState.from_payload(
            payload
        )
