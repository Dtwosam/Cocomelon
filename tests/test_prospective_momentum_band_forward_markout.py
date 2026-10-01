from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from cocomelon.domain.execution import PaperExecutionConfig
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.evidence.openings import conservative_cost_estimate
from cocomelon.research.continuous_paper_opening_opportunity import (
    ContinuousPaperOpeningOpportunityEvidence,
    instrument_payload,
    risk_request_payload,
)
from cocomelon.research.continuous_paper_opening_opportunity_paths import (
    ContinuousPaperOpeningOpportunityPath,
    ContinuousPaperOpeningOpportunityPathMark,
)
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshot,
    LearningFeatureSnapshotStore,
)
from cocomelon.research.prospective_combined_entry_filter import (
    ProspectiveCombinedEntryFilterState,
)
from cocomelon.research.prospective_momentum_band_entry import (
    ProspectiveMomentumBandEntryState,
)
from cocomelon.research.prospective_momentum_band_forward_markout import (
    prospective_momentum_band_forward_markout_summary,
)
from cocomelon.research.prospective_two_strike_stop_filter import (
    ProspectiveTwoStrikeStopFilterState,
)
from cocomelon.domain.execution import InstrumentExecutionSpec
from cocomelon.domain.health import ExecutionHealthState
from cocomelon.domain.risk import (
    AccountRiskState,
    LiquidityState,
    RiskLimits,
    RiskRequest,
)
from cocomelon.domain.strategy import StrategyDecision


START = 100_000_000


def _trade(
    suffix: str,
    *,
    market: str,
    direction: Direction,
    opened_at_ms: int,
    pnl: str,
) -> TradeJournalEntry:
    net = Decimal(pnl)
    return TradeJournalEntry(
        market=MarketId("", market),
        direction=direction,
        opened_at_ms=opened_at_ms,
        closed_at_ms=opened_at_ms + 60_000,
        feature_snapshot_id=f"feature-{suffix}",
        strategy_decision_id=f"strategy-{suffix}",
        risk_decision_id=f"risk-{suffix}",
        opening_plan_id=f"plan-{suffix}",
        opening_attempt_id=f"attempt-{suffix}",
        exit_plan_ids=(f"exit-plan-{suffix}",),
        exit_attempt_ids=(f"exit-attempt-{suffix}",),
        fill_ids=(f"open-{suffix}", f"close-{suffix}"),
        position_action_ids=(f"action-{suffix}",),
        funding_event_ids=(),
        initial_stop=Decimal("90"),
        initial_risk_amount=Decimal("10"),
        entry_price=Decimal("100"),
        exit_price=Decimal("100") + net,
        filled_quantity=Decimal("1"),
        gross_realized_pnl=net,
        entry_fees=Decimal("0"),
        exit_fees=Decimal("0"),
        funding_cash_pnl=Decimal("0"),
        net_pnl=net,
        entry_slippage_amount=Decimal("0"),
        exit_slippage_amount=Decimal("0"),
        entry_slippage_fraction=Decimal("0"),
        exit_slippage_fraction=Decimal("0"),
        holding_duration_ms=60_000,
        mfe=None,
        mae=None,
        net_r=net / Decimal("10"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10000") + net,
        exit_reason="OPPOSITE_FRESH_THESIS",
        health_refs=("healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id="paper",
    )


def _feature(
    store: LearningFeatureSnapshotStore,
    *,
    suffix: str,
    market: str,
    timestamp_ms: int,
    return_1h: str,
    day_return: str,
) -> str:
    snapshot = LearningFeatureSnapshot(
        market=MarketId("", market),
        as_of_ms=timestamp_ms,
        return_1h=Decimal(return_1h),
        day_return=Decimal(day_return),
        realized_volatility_1h=None,
        relative_volume=None,
        spread_fraction=None,
        depth_25bps=None,
        funding_rate=None,
        open_interest=None,
        source_event_keys=(f"source-{suffix}",),
    )
    return store.record(snapshot).snapshot.snapshot_id


def _opportunity(
    *,
    suffix: str,
    market: str,
    direction: Direction,
    timestamp_ms: int,
    feature_snapshot_id: str,
    rank: int = 3,
    lead_strategy: str = "breakout",
    approved: bool = True,
) -> ContinuousPaperOpeningOpportunityEvidence:
    config = PaperExecutionConfig()
    market_id = MarketId("", market)
    decision = StrategyDecision(
        market=market_id,
        direction=direction,
        score=Decimal("0.8"),
        timestamp_ms=timestamp_ms - config.latency_ms,
        feature_snapshot_id=feature_snapshot_id,
        lead_strategy=lead_strategy,
        invalidation_price=Decimal("90"),
        signal_ids=(f"signal-{suffix}",),
        reason_codes=("decision_threshold_met",),
    )
    request = RiskRequest(
        strategy_decision=decision,
        entry_reference_price=Decimal("100"),
        correlation_bucket="majors",
        account_state=AccountRiskState(
            equity=Decimal("10000"),
            day_start_equity=Decimal("10000"),
            daily_realized_pnl=Decimal("0"),
            rolling_7d_peak_equity=Decimal("10000"),
            available_margin=Decimal("10000"),
            gross_open_notional=Decimal("0"),
            consecutive_losses=0,
            last_closed_trade_ms=None,
            as_of_ms=timestamp_ms,
        ),
        open_positions=(),
        health_state=ExecutionHealthState(
            market_data_fresh=True,
            account_state_fresh=True,
            execution_health_ok=True,
            state_consistent=True,
            as_of_ms=timestamp_ms,
        ),
        cost_estimate=conservative_cost_estimate(config),
        liquidity_state=LiquidityState(
            entry_side_visible_notional_25bps=Decimal("100000"),
            exit_side_visible_notional_25bps=Decimal("100000"),
        ),
        limits=RiskLimits(),
        timestamp_ms=timestamp_ms,
    )
    instrument = InstrumentExecutionSpec(
        market=market_id,
        sz_decimals=3,
        venue_max_leverage=Decimal("20"),
        minimum_order_notional=Decimal("10"),
        metadata_received_at_ms=timestamp_ms,
        metadata_source="test",
    )
    return ContinuousPaperOpeningOpportunityEvidence(
        strategy_decision_id=decision.decision_id,
        feature_snapshot_id=feature_snapshot_id,
        market=market,
        direction=direction.value,
        lead_strategy=lead_strategy,
        opportunity_timestamp_ms=timestamp_ms,
        baseline_risk_approved=approved,
        baseline_risk_reason_codes=(
            () if approved else ("consecutive_loss_cooldown",)
        ),
        baseline_risk_decision_id=f"risk-{suffix}",
        equity_before=Decimal("10000"),
        risk_request=risk_request_payload(request),
        instrument=instrument_payload(instrument),
        book={
            "event_key": f"book-{suffix}",
            "exchange_time_ms": timestamp_ms,
            "receive_time": "1970-01-02T03:46:40+00:00",
            "source": "test",
            "bids": [["99.9", "100"]],
            "asks": [["100.1", "100"]],
        },
        rank_observed_at_ms=timestamp_ms,
        rank_ordinal=rank,
        rank_score=Decimal("0.9"),
        rank_pool_size=20,
        rank_reason_codes=(),
    )


def _path(
    evidence: ContinuousPaperOpeningOpportunityEvidence,
    *,
    returns: tuple[str, str, str],
) -> ContinuousPaperOpeningOpportunityPath:
    marks = []
    for horizon_ms, raw_return in zip(
        (300_000, 900_000, 3_600_000),
        returns,
        strict=True,
    ):
        value = Decimal(raw_return)
        price = (
            Decimal("100") * (Decimal("1") + value)
            if evidence.direction == "long"
            else Decimal("100") * (Decimal("1") - value)
        )
        marks.append(
            ContinuousPaperOpeningOpportunityPathMark(
                observed_at_ms=(
                    evidence.opportunity_timestamp_ms + horizon_ms
                ),
                mark_px=price,
                source="test",
            )
        )
    return ContinuousPaperOpeningOpportunityPath(
        opportunity_id=evidence.opportunity_id,
        market=evidence.market,
        direction=evidence.direction,
        opportunity_timestamp_ms=evidence.opportunity_timestamp_ms,
        max_path_age_ms=3_600_000,
        max_completion_lag_ms=120_000,
        marks=tuple(marks),
    )


def test_momentum_forward_markout_separates_block_and_admit(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    combined = ProspectiveCombinedEntryFilterState(
        started_at_ms=START
    )
    two = ProspectiveTwoStrikeStopFilterState(
        frozen_at_ms=START - 21_600_000
    )
    momentum = ProspectiveMomentumBandEntryState(
        frozen_at_ms=START - 21_600_000
    )

    admit_feature = _feature(
        store,
        suffix="admit",
        market="SOL",
        timestamp_ms=START + 1_000,
        return_1h="0.03",
        day_return="0.05",
    )
    block_feature = _feature(
        store,
        suffix="block",
        market="ETH",
        timestamp_ms=START + 2_000,
        return_1h="0.005",
        day_return="0.03",
    )
    admit = _opportunity(
        suffix="admit",
        market="SOL",
        direction=Direction.LONG,
        timestamp_ms=START + 1_000,
        feature_snapshot_id=admit_feature,
    )
    block = _opportunity(
        suffix="block",
        market="ETH",
        direction=Direction.LONG,
        timestamp_ms=START + 2_000,
        feature_snapshot_id=block_feature,
    )

    result = prospective_momentum_band_forward_markout_summary(
        (admit, block),
        (
            _path(admit, returns=("0.01", "0.02", "0.03")),
            _path(block, returns=("-0.01", "-0.02", "-0.03")),
        ),
        (),
        store,
        combined,
        two,
        momentum,
    )

    assert result["base_stack_risk_approved_evaluated"] == 2
    assert result["momentum_admitted"] == 1
    assert result["momentum_blocked"] == 1
    horizons = result["horizons"]
    assert isinstance(horizons, dict)
    one_hour = horizons["3600000"]
    assert one_hour["admit"]["mean_directional_return"] == "0.03"
    assert one_hour["block"]["mean_directional_return"] == "-0.03"
    robust = one_hour["spread_robustness"]
    assert robust["admit_minus_block_mean_return"] == "0.06"
    assert result["changes_readiness_gate"] is False


def test_momentum_forward_markout_excludes_base_stack_blocks(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    combined = ProspectiveCombinedEntryFilterState(
        started_at_ms=START
    )
    two = ProspectiveTwoStrikeStopFilterState(
        frozen_at_ms=START - 21_600_000
    )
    momentum = ProspectiveMomentumBandEntryState(
        frozen_at_ms=START - 21_600_000
    )
    feature = _feature(
        store,
        suffix="base-blocked",
        market="SOL",
        timestamp_ms=START + 1_000,
        return_1h="0.03",
        day_return="0.05",
    )
    long_trend = _opportunity(
        suffix="long-trend",
        market="SOL",
        direction=Direction.LONG,
        timestamp_ms=START + 1_000,
        feature_snapshot_id=feature,
        lead_strategy="trend",
    )
    risk_rejected = _opportunity(
        suffix="risk",
        market="SOL",
        direction=Direction.SHORT,
        timestamp_ms=START + 2_000,
        feature_snapshot_id=feature,
        approved=False,
    )

    result = prospective_momentum_band_forward_markout_summary(
        (long_trend, risk_rejected),
        (),
        (),
        store,
        combined,
        two,
        momentum,
    )

    assert result["baseline_risk_rejected"] == 1
    assert result["base_combined_blocked"] == 1
    assert result["base_stack_risk_approved_evaluated"] == 0
