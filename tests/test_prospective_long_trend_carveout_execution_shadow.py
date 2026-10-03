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
    _neutralize_weekly_drawdown_only,
    evaluate_long_trend_carveout_execution_shadow,
)
from cocomelon.research.prospective_long_trend_carveout_execution_shadow_source import (
    prospective_long_trend_execution_shadow_source,
)
from cocomelon.risk.engine import evaluate_risk

TIMESTAMP_MS = 2_000_000_000


def _market() -> MarketId:
    return MarketId.from_wire_name("", "SOL")


def _evidence(
    *,
    daily_realized_pnl: Decimal = Decimal("0"),
) -> ContinuousPaperOpeningOpportunityEvidence:
    config = PaperExecutionConfig()
    decision = StrategyDecision(
        market=_market(),
        direction=Direction.LONG,
        score=Decimal("0.8"),
        timestamp_ms=TIMESTAMP_MS - config.latency_ms,
        feature_snapshot_id="feature-long-trend-shadow",
        lead_strategy="trend",
        invalidation_price=Decimal("90"),
        signal_ids=("signal-long-trend-shadow",),
        reason_codes=("decision_threshold_met",),
    )
    request = RiskRequest(
        strategy_decision=decision,
        entry_reference_price=Decimal("100"),
        correlation_bucket="alts",
        account_state=RiskAccountState(
            equity=Decimal("9600"),
            day_start_equity=Decimal("10000"),
            daily_realized_pnl=daily_realized_pnl,
            rolling_7d_peak_equity=Decimal("10000"),
            available_margin=Decimal("9600"),
            gross_open_notional=Decimal("0"),
            consecutive_losses=0,
            last_closed_trade_ms=None,
            as_of_ms=TIMESTAMP_MS,
        ),
        open_positions=(),
        health_state=RiskHealthState(
            market_data_fresh=True,
            account_state_fresh=True,
            execution_health_ok=True,
            state_consistent=True,
            as_of_ms=TIMESTAMP_MS,
        ),
        cost_estimate=conservative_cost_estimate(config),
        liquidity_state=LiquidityRiskState(
            entry_side_visible_notional_25bps=Decimal("1000000"),
            exit_side_visible_notional_25bps=Decimal("1000000"),
            venue_max_leverage=Decimal("5"),
            liquidation_price=Decimal("50"),
            venue_min_notional=Decimal("10"),
            as_of_ms=TIMESTAMP_MS,
        ),
        limits=RiskLimits(),
        timestamp_ms=TIMESTAMP_MS,
    )
    baseline = evaluate_risk(request)
    instrument = InstrumentExecutionSpec(
        market=_market(),
        sz_decimals=2,
        venue_max_leverage=Decimal("5"),
        minimum_order_notional=Decimal("10"),
        metadata_received_at_ms=TIMESTAMP_MS - 1_000,
        metadata_source="fixture",
    )
    book = StreamEvent(
        kind=StreamKind.L2_BOOK,
        market=_market(),
        exchange_time_ms=TIMESTAMP_MS,
        receive_time=datetime.fromtimestamp(
            TIMESTAMP_MS / 1000,
            tz=UTC,
        ),
        schema_version=1,
        source="fixture",
        event_key="book-long-trend-shadow",
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
        market=_market().canonical,
        direction="long",
        lead_strategy="trend",
        opportunity_timestamp_ms=TIMESTAMP_MS,
        baseline_risk_approved=baseline.approved,
        baseline_risk_reason_codes=baseline.reason_codes,
        baseline_risk_decision_id=baseline.risk_decision_id,
        equity_before=request.account_state.equity,
        risk_request=_risk_request_payload(request),
        instrument=_instrument_payload(instrument),
        book=_book_payload(book),
        rank_observed_at_ms=TIMESTAMP_MS - 100,
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
        max_path_age_ms=3_600_000,
        max_completion_lag_ms=120_000,
        marks=(
            ContinuousPaperOpeningOpportunityPathMark(
                observed_at_ms=TIMESTAMP_MS + 300_000,
                mark_px=Decimal("101"),
                source="fixture",
            ),
            ContinuousPaperOpeningOpportunityPathMark(
                observed_at_ms=TIMESTAMP_MS + 900_000,
                mark_px=Decimal("102"),
                source="fixture",
            ),
            ContinuousPaperOpeningOpportunityPathMark(
                observed_at_ms=TIMESTAMP_MS + 3_600_000,
                mark_px=Decimal("103"),
                source="fixture",
            ),
        ),
    )


def _source(
    evidence: ContinuousPaperOpeningOpportunityEvidence,
    path: ContinuousPaperOpeningOpportunityPath,
) -> dict[str, object]:
    assert evidence.baseline_risk_reason_codes == (
        "weekly_drawdown_lockout",
    )
    summary = {
        "enabled": True,
        "error": None,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_readiness_gate": False,
        "changes_closed_trade_readiness_gate": False,
        "overlap_started_at_ms": TIMESTAMP_MS - 1,
        "risk_rejected_rows": [
            {
                "opportunity_id": evidence.opportunity_id,
                "timestamp_ms": TIMESTAMP_MS,
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
                "long_trend_carveout_momentum_reason": "momentum_band_admit",
            }
        ],
    }
    payload = prospective_long_trend_execution_shadow_source(
        summary,
        (evidence,),
        (path,),
    )
    payload["enabled"] = True
    payload["error"] = None
    return payload


def test_shadow_stays_dormant_until_durable_gate_is_ready() -> None:
    evidence = _evidence()
    result = evaluate_long_trend_carveout_execution_shadow(
        _source(evidence, _path(evidence)),
        durable_gate_ready=False,
        durable_gate_ledger_sha256="a" * 64,
    )

    assert result["status"] == "dormant_gate_not_ready"
    assert result["evaluated"] == 0
    assert result["results"] == []
    assert result["execution_authority"] is False
    assert result["changes_risk_limits"] is False


def test_shadow_replays_risk_planner_ioc_and_markouts_when_gated() -> None:
    evidence = _evidence()
    result = evaluate_long_trend_carveout_execution_shadow(
        _source(evidence, _path(evidence)),
        durable_gate_ready=True,
        durable_gate_ledger_sha256="b" * 64,
    )

    assert result["status"] == "evaluated"
    assert result["evaluated"] == 1
    assert result["counterfactual_risk_rejections"] == {}
    assert result["planning_rejections"] == {}
    assert result["fillable"] == 1
    row = result["results"][0]
    assert row["counterfactual_risk_approved"] is True
    assert row["planning_approved"] is True
    assert row["filled_quantity"] is not None
    assert row["markouts"]["300000"]["status"] == "settled"
    assert Decimal(
        row["markouts"]["300000"][
            "entry_fee_adjusted_mark_to_market_pnl"
        ]
    ) > 0
    assert result["realized_pnl_modeled"] is False
    assert result["replacement_exits_modeled"] is False


def test_weekly_neutralization_preserves_unrelated_account_state() -> None:
    evidence = _evidence()
    original = evidence.risk_request_object
    adjusted, drawdown = _neutralize_weekly_drawdown_only(
        evidence
    )

    assert drawdown == Decimal("0.04")
    assert adjusted.account_state.rolling_7d_peak_equity == Decimal(
        "9600"
    )
    assert adjusted.account_state.equity == original.account_state.equity
    assert (
        adjusted.account_state.daily_realized_pnl
        == original.account_state.daily_realized_pnl
    )
    assert adjusted.open_positions == original.open_positions
    assert adjusted.health_state == original.health_state
    assert adjusted.limits == original.limits


def test_shadow_refuses_to_bypass_multiple_risk_vetoes() -> None:
    evidence = _evidence(daily_realized_pnl=Decimal("-150"))
    assert evidence.baseline_risk_reason_codes == (
        "daily_loss_lockout",
        "weekly_drawdown_lockout",
    )

    with pytest.raises(
        ProspectiveLongTrendExecutionShadowError,
        match="requires exact weekly-drawdown rejection",
    ):
        _neutralize_weekly_drawdown_only(evidence)
