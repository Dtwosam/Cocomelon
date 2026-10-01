from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from cocomelon.domain.execution import (
    InstrumentExecutionSpec,
    PaperExecutionConfig,
)
from cocomelon.domain.features import (
    FeatureSnapshot,
    TrendRegime,
    VolatilityRegime,
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
from cocomelon.research.learning_feature_snapshots import (
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
from cocomelon.risk.engine import evaluate_risk

START = 100_000_000
EMBARGO_MS = 6 * 60 * 60 * 1_000


def _market(name: str) -> MarketId:
    return MarketId.from_wire_name("", name)


def _record_feature(
    store: LearningFeatureSnapshotStore,
    *,
    market: str,
    timestamp_ms: int,
    return_1h: str,
    day_return: str,
) -> str:
    snapshot = FeatureSnapshot(
        market=_market(market),
        as_of_ms=timestamp_ms,
        source_received_at_ms=timestamp_ms,
        schema_version=1,
        day_return=Decimal(day_return),
        funding=Decimal("0"),
        open_interest=Decimal("100"),
        day_notional_volume=Decimal("1000000"),
        oi_change_fraction=None,
        funding_change=None,
        mark_oracle_dislocation_bps=Decimal("0"),
        return_5m=None,
        return_15m=None,
        return_1h=Decimal(return_1h),
        return_4h=None,
        realized_vol_15m=None,
        range_expansion_15m=None,
        relative_volume_15m=None,
        spread_bps=None,
        bid_depth_25bps=None,
        ask_depth_25bps=None,
        book_imbalance=None,
        book_age_ms=None,
        trend_regime=TrendRegime.UNKNOWN,
        volatility_regime=VolatilityRegime.UNKNOWN,
        provenance=("test",),
    )
    store.record(snapshot)
    return snapshot.snapshot_id


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
    market_id = _market(market)
    invalidation = (
        Decimal("90")
        if direction is Direction.LONG
        else Decimal("110")
    )
    decision = StrategyDecision(
        market=market_id,
        direction=direction,
        score=Decimal("0.8"),
        timestamp_ms=timestamp_ms - config.latency_ms,
        feature_snapshot_id=feature_snapshot_id,
        lead_strategy=lead_strategy,
        invalidation_price=invalidation,
        signal_ids=(f"signal-{suffix}",),
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
            available_margin=Decimal("10000"),
            gross_open_notional=Decimal("0"),
            consecutive_losses=(0 if approved else 3),
            last_closed_trade_ms=(
                None if approved else timestamp_ms - 60_000
            ),
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
    assert baseline.approved is approved

    instrument = InstrumentExecutionSpec(
        market=market_id,
        sz_decimals=2,
        venue_max_leverage=Decimal("5"),
        minimum_order_notional=Decimal("10"),
        metadata_received_at_ms=timestamp_ms,
        metadata_source="fixture",
    )
    book = StreamEvent(
        kind=StreamKind.L2_BOOK,
        market=market_id,
        exchange_time_ms=timestamp_ms,
        receive_time=datetime.fromtimestamp(
            timestamp_ms / 1000,
            tz=UTC,
        ),
        schema_version=1,
        source="fixture",
        event_key=f"book-{suffix}",
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
        feature_snapshot_id=feature_snapshot_id,
        market=market_id.canonical,
        direction=direction.value,
        lead_strategy=lead_strategy,
        opportunity_timestamp_ms=timestamp_ms,
        baseline_risk_approved=baseline.approved,
        baseline_risk_reason_codes=baseline.reason_codes,
        baseline_risk_decision_id=baseline.risk_decision_id,
        equity_before=request.account_state.equity,
        risk_request=_risk_request_payload(request),
        instrument=_instrument_payload(instrument),
        book=_book_payload(book),
        rank_observed_at_ms=timestamp_ms - 100,
        rank_ordinal=rank,
        rank_score=Decimal("0.9"),
        rank_pool_size=20,
        rank_reason_codes=("fixture",),
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
                source="fixture",
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


def _states() -> tuple[
    ProspectiveCombinedEntryFilterState,
    ProspectiveTwoStrikeStopFilterState,
    ProspectiveMomentumBandEntryState,
]:
    return (
        ProspectiveCombinedEntryFilterState(started_at_ms=START),
        ProspectiveTwoStrikeStopFilterState(
            frozen_at_ms=START - EMBARGO_MS
        ),
        ProspectiveMomentumBandEntryState(
            frozen_at_ms=START - EMBARGO_MS
        ),
    )


def test_momentum_forward_markout_separates_block_and_admit(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    combined, two_strike, momentum = _states()
    admit_feature = _record_feature(
        store,
        market="SOL",
        timestamp_ms=START + 900,
        return_1h="0.03",
        day_return="0.05",
    )
    block_feature = _record_feature(
        store,
        market="ETH",
        timestamp_ms=START + 1_900,
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
        two_strike,
        momentum,
    )

    assert result["base_stack_risk_approved_evaluated"] == 2
    assert result["momentum_admitted"] == 1
    assert result["momentum_blocked"] == 1
    horizons = result["horizons"]
    assert isinstance(horizons, dict)
    one_hour = horizons["3600000"]
    assert isinstance(one_hour, dict)
    admit_summary = one_hour["admit"]
    block_summary = one_hour["block"]
    robust = one_hour["spread_robustness"]
    assert isinstance(admit_summary, dict)
    assert isinstance(block_summary, dict)
    assert isinstance(robust, dict)
    assert admit_summary["mean_directional_return"] == "0.03"
    assert block_summary["mean_directional_return"] == "-0.03"
    assert robust["admit_minus_block_mean_return"] == "0.06"
    assert result["changes_readiness_gate"] is False


def test_momentum_forward_markout_excludes_base_stack_blocks(
    tmp_path: Path,
) -> None:
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    combined, two_strike, momentum = _states()
    long_feature = _record_feature(
        store,
        market="SOL",
        timestamp_ms=START + 900,
        return_1h="0.03",
        day_return="0.05",
    )
    short_feature = _record_feature(
        store,
        market="ETH",
        timestamp_ms=START + 1_900,
        return_1h="-0.03",
        day_return="-0.05",
    )
    long_trend = _opportunity(
        suffix="long-trend",
        market="SOL",
        direction=Direction.LONG,
        timestamp_ms=START + 1_000,
        feature_snapshot_id=long_feature,
        lead_strategy="trend",
    )
    risk_rejected = _opportunity(
        suffix="risk",
        market="ETH",
        direction=Direction.SHORT,
        timestamp_ms=START + 2_000,
        feature_snapshot_id=short_feature,
        approved=False,
    )

    result = prospective_momentum_band_forward_markout_summary(
        (long_trend, risk_rejected),
        (),
        (),
        store,
        combined,
        two_strike,
        momentum,
    )

    assert result["baseline_risk_rejected"] == 1
    assert result["base_combined_blocked"] == 1
    assert result["base_stack_risk_approved_evaluated"] == 0
