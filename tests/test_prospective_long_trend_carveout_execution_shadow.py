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
from cocomelon.research.prospective_long_trend_carveout_execution_shadow import (
    ProspectiveLongTrendExecutionShadowError,
    prospective_long_trend_execution_shadow_summary,
)
from cocomelon.research.prospective_long_trend_carveout_execution_shadow_source import (
    prospective_long_trend_execution_shadow_source,
)
from cocomelon.risk.engine import evaluate_risk


def _market(name: str) -> MarketId:
    return MarketId.from_wire_name("", name)


def _evidence(
    *,
    timestamp_ms: int,
    cooldown_active: bool = False,
) -> ContinuousPaperOpeningOpportunityEvidence:
    config = PaperExecutionConfig()
    market = _market("SOL")
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


def _path(
    evidence: ContinuousPaperOpeningOpportunityEvidence,
) -> ContinuousPaperOpeningOpportunityPath:
    return ContinuousPaperOpeningOpportunityPath(
        opportunity_id=evidence.opportunity_id,
        market=evidence.market,
        direction=evidence.direction,
        opportunity_timestamp_ms=evidence.opportunity_timestamp_ms,
        max_path_age_ms=6 * 60 * 60 * 1_000,
        max_completion_lag_ms=120_000,
        marks=(
            ContinuousPaperOpeningOpportunityPathMark(
                observed_at_ms=(
                    evidence.opportunity_timestamp_ms + 5 * 60 * 1_000
                ),
                mark_px=Decimal("102"),
                source="fixture",
            ),
            ContinuousPaperOpeningOpportunityPathMark(
                observed_at_ms=(
                    evidence.opportunity_timestamp_ms + 15 * 60 * 1_000
                ),
                mark_px=Decimal("103"),
                source="fixture",
            ),
            ContinuousPaperOpeningOpportunityPathMark(
                observed_at_ms=(
                    evidence.opportunity_timestamp_ms + 60 * 60 * 1_000
                ),
                mark_px=Decimal("104"),
                source="fixture",
            ),
        ),
    )


def _full_stack_summary(
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
                "direction": "long",
                "lead_strategy": "trend",
                "rank_ordinal": 3,
                "rank_age_ms": 100,
                "baseline_risk_reason_codes": [
                    "weekly_drawdown_lockout"
                ],
                "combined_block_reason": "long_trend",
                "two_strike_prior_strikes": 0,
                "stack_decision": "BLOCK",
                "block_layer": "combined",
                "long_trend_carveout_candidate_id": (
                    "prospective-top10-two-strike-momentum-no-long-trend-v1"
                ),
                "long_trend_carveout_decision": "ADMIT",
                "long_trend_carveout_block_layer": "none",
                "long_trend_carveout_momentum_decision": "ADMIT",
                "long_trend_carveout_momentum_reason": (
                    "momentum_band_admit"
                ),
            }
        ],
    }


def _source(
    evidence: ContinuousPaperOpeningOpportunityEvidence,
    *,
    path: ContinuousPaperOpeningOpportunityPath | None,
) -> dict[str, object]:
    return prospective_long_trend_execution_shadow_source(
        _full_stack_summary(evidence),
        (evidence,),
        (() if path is None else (path,)),
    )


def test_execution_shadow_replays_weekly_lockout_fill() -> None:
    evidence = _evidence(timestamp_ms=10_000_000)
    source = _source(evidence, path=_path(evidence))

    result = prospective_long_trend_execution_shadow_summary(
        source,
        PaperExecutionConfig(),
    )

    assert result["source_opportunities"] == 1
    assert result["counterfactual_risk_approvals"] == 1
    assert result["counterfactual_risk_rejections"] == {}
    assert result["planning_approvals"] == 1
    assert result["fillable_opportunities"] == 1
    option = result["option_results"][0]
    assert option["counterfactual_risk_approved"] is True
    assert option["planning_approved"] is True
    assert option["filled_quantity"] is not None
    for horizon in ("300000", "900000", "3600000"):
        assert option["markouts"][horizon]["status"] == "settled"
        assert Decimal(
            option["markouts"][horizon][
                "entry_fee_adjusted_mark_to_market_pnl"
            ]
        ) > 0
    assert result["by_horizon"]["300000"]["positive"] == 1
    assert result["by_horizon"]["300000"]["profit_factor"] is None
    assert result["changes_risk_limits"] is False
    assert result["execution_authority"] is False
    assert result["realized_pnl_modeled"] is False


def test_execution_shadow_exposes_other_veto_after_weekly_removed() -> None:
    evidence = _evidence(
        timestamp_ms=20_000_000,
        cooldown_active=True,
    )
    result = prospective_long_trend_execution_shadow_summary(
        _source(evidence, path=None),
        PaperExecutionConfig(),
    )

    assert result["counterfactual_risk_approvals"] == 0
    assert result["counterfactual_risk_rejections"] == {
        "consecutive_loss_cooldown": 1
    }
    assert result["planning_approvals"] == 0
    assert result["fillable_opportunities"] == 0


def test_execution_shadow_reports_missing_path_after_fill() -> None:
    evidence = _evidence(timestamp_ms=30_000_000)
    result = prospective_long_trend_execution_shadow_summary(
        _source(evidence, path=None),
        PaperExecutionConfig(),
    )

    assert result["fillable_opportunities"] == 1
    option = result["option_results"][0]
    for horizon in ("300000", "900000", "3600000"):
        assert option["markouts"][horizon]["status"] == "missing_path"


def test_execution_shadow_rejects_tampered_source_digest() -> None:
    evidence = _evidence(timestamp_ms=40_000_000)
    source = _source(evidence, path=_path(evidence))
    source["source_opportunity_count"] = 2

    with pytest.raises(
        ProspectiveLongTrendExecutionShadowError,
        match="digest mismatch",
    ):
        prospective_long_trend_execution_shadow_summary(
            source,
            PaperExecutionConfig(),
        )
