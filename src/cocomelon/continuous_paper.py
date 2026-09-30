from __future__ import annotations

import asyncio
import json
import os
from collections import deque
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

from cocomelon.config import ExecutionMode, Settings
from cocomelon.domain.execution import (
    ExecutionAttempt,
    InstrumentExecutionSpec,
    PaperExecutionConfig,
    PaperFill,
    PaperOrderPlan,
    PositionAction,
    PositionActionType,
)
from cocomelon.domain.journal import JournalObservation, TradeJournalEntry
from cocomelon.domain.market import (
    Candle,
    FundingRate,
    MarketId,
    PerpMarketSnapshot,
)
from cocomelon.domain.replay import EvidenceClass, ReplayRecord, SourceRecordKind
from cocomelon.domain.risk import RiskLimits
from cocomelon.domain.stream import DataGap, StreamEvent
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.evidence.lifecycle import (
    BaselineReplayPipeline,
    OpeningResearchObserver,
    OpenLifecycleCheckpoint,
    OpenLifecycleMarkPath,
    PositionResearchObserver,
)
from cocomelon.evidence.openings import BaselineOpeningTrace
from cocomelon.evidence.recording import (
    RecordedPublicEvent,
    _startup_ranks,
    candle_record_event,
    funding_rate_record_event,
    market_snapshot_record_event,
)
from cocomelon.evidence.redundant_stream import RedundantStreamMux
from cocomelon.execution.accounting import PaperPosition
from cocomelon.execution.funding import (
    FundingAccrual,
    funding_boundary_for_record_time,
)
from cocomelon.execution.paper import PaperExecutionAdapter
from cocomelon.hyperliquid.client import INTERVAL_MS, InfoClient
from cocomelon.hyperliquid.normalize import (
    normalize_candles,
    normalize_funding_history,
    normalize_l2_book_snapshot,
    normalize_meta_and_asset_ctxs,
)
from cocomelon.hyperliquid.watchlist import DeepWatchlistManager
from cocomelon.hyperliquid.ws_client import connect_mainnet_ws
from cocomelon.hyperliquid.ws_supervisor import WebSocketSupervisor
from cocomelon.journal.store import JournalStore
from cocomelon.research.account_lifecycle_bridge import (
    account_lifecycle_bridge,
)
from cocomelon.research.adaptive_delay_selector import (
    AdaptiveDelaySelectorState,
    adaptive_delay_selector_summary,
)
from cocomelon.research.cadence_opportunity_learning import (
    evaluate_cadence_opportunity_learning,
)
from cocomelon.research.cadence_shadow import CadenceShadowComparator
from cocomelon.research.closed_trade_concentration import (
    closed_trade_concentration_summary,
)
from cocomelon.research.closed_trade_friction import (
    closed_trade_friction_summary,
)
from cocomelon.research.closed_trade_robustness import (
    closed_trade_robustness,
)
from cocomelon.research.closed_trade_stability import (
    closed_trade_stability,
)
from cocomelon.research.closed_trade_utc_hour import (
    closed_trade_utc_hour_summary,
)
from cocomelon.research.continuous_paper_drawdown import (
    ContinuousPaperDrawdownTracker,
    drawdown_summary,
)
from cocomelon.research.continuous_paper_learning import (
    CONTINUOUS_PAPER_REPLAY_RUN_ID,
    ContinuousPaperOpeningLineage,
    ContinuousPaperOpeningLineageStore,
    ContinuousPaperRuntimeIdentity,
)
from cocomelon.research.continuous_paper_opening_opportunity import (
    ContinuousPaperOpeningOpportunityStore,
)
from cocomelon.research.continuous_paper_opening_opportunity import (
    evidence_from_opening_trace as opportunity_evidence_from_trace,
)
from cocomelon.research.continuous_paper_opening_opportunity_exit_books import (
    ContinuousPaperOpeningOpportunityExitBookStore,
)
from cocomelon.research.continuous_paper_opening_opportunity_paths import (
    DEFAULT_MAX_COMPLETION_LAG_MS,
    DEFAULT_MAX_PATH_AGE_MS,
    ContinuousPaperOpeningOpportunityPathStore,
)
from cocomelon.research.continuous_paper_opening_rank import (
    ContinuousPaperOpeningRankStore,
    LatestCoarseRankTracker,
    opening_rank_attribution,
)
from cocomelon.research.continuous_paper_replacement_funding import (
    ContinuousPaperReplacementFundingStore,
    ReplacementFundingBoundaryRequest,
)
from cocomelon.research.continuous_paper_trade_paths import (
    ContinuousPaperTradePathStore,
)
from cocomelon.research.delay_selector_comparison import (
    DelaySelectorComparisonState,
    delay_selector_comparison_summary,
)
from cocomelon.research.delayed_entry_contribution_decomposition import (
    delayed_entry_contribution_decomposition,
)
from cocomelon.research.delayed_entry_contribution_decomposition_funding import (
    delayed_entry_funding_decomposition,
)
from cocomelon.research.delayed_entry_execution_shadow import (
    DELAY_MS,
    MAX_DELAY_OBSERVATION_LAG_MS,
    DelayedEntryExecutionShadow,
)
from cocomelon.research.delayed_entry_fill_capacity import (
    delayed_entry_fill_capacity_summary,
)
from cocomelon.research.delayed_entry_fill_weighted import (
    delayed_entry_fill_weighted_contribution,
)
from cocomelon.research.delayed_entry_fill_weighted_funding import (
    delayed_entry_funding_corrected_fill_weighted,
)
from cocomelon.research.delayed_entry_fixed_schedule_portfolio import (
    delayed_entry_fixed_schedule_portfolio,
)
from cocomelon.research.delayed_entry_mtm_portfolio import (
    delayed_entry_mtm_portfolio,
)
from cocomelon.research.delayed_entry_pair import (
    CHALLENGER_DELAY_MS,
    delayed_entry_pair_summary,
)
from cocomelon.research.delayed_entry_pair_fill_weighted import (
    delayed_entry_pair_fill_weighted_summary,
)
from cocomelon.research.delayed_entry_portfolio_capacity import (
    delayed_entry_portfolio_capacity_overlay,
)
from cocomelon.research.delayed_entry_risk_geometry import (
    delayed_entry_risk_geometry_summary,
)
from cocomelon.research.delayed_entry_same_exit import (
    delayed_entry_same_exit_contribution,
)
from cocomelon.research.delayed_entry_same_exit_stop_validity import (
    delayed_entry_same_exit_stop_validity,
)
from cocomelon.research.delayed_entry_stop_exit_proxy import (
    delayed_entry_stop_exit_proxy_range,
)
from cocomelon.research.delayed_entry_stop_l2_replay import (
    delayed_entry_stop_l2_replay,
)
from cocomelon.research.delayed_entry_stop_survivability import (
    delayed_entry_stop_survivability,
)
from cocomelon.research.entry_decision_age import entry_decision_age_summary
from cocomelon.research.entry_markout import entry_markout_summary
from cocomelon.research.entry_markout_predictiveness import (
    entry_markout_predictiveness,
)
from cocomelon.research.entry_markout_readiness import (
    MIN_OBSERVATIONS_PER_HORIZON,
    entry_markout_readiness,
)
from cocomelon.research.entry_mid_markout_readiness import (
    MAX_NON_FRESH_FRACTION,
    MIN_FRESH_OBSERVATIONS_PER_HORIZON,
    entry_mid_markout_readiness,
)
from cocomelon.research.entry_mid_markout_shadow import (
    EntryMidMarkoutShadow,
)
from cocomelon.research.excursion_timing import excursion_timing_summary
from cocomelon.research.fill_aware_delay_selector import (
    FillAwareDelaySelectorState,
    fill_aware_delay_selector_summary,
)
from cocomelon.research.learning_feature_snapshots import LearningFeatureSnapshotStore
from cocomelon.research.opening_fill_liquidity import (
    OpeningFillLiquidityStore,
    evidence_from_opening_trace,
    opening_fill_liquidity_attribution,
)
from cocomelon.research.original_stop_book_evidence import (
    OriginalStopBookCapture,
    OriginalStopBookEvidenceStore,
)
from cocomelon.research.profit_lock_counterfactual import evaluate_profit_lock_state
from cocomelon.research.profit_lock_execution_readiness import (
    MIN_ACTIVATED_TRADES_PER_RULE as EXECUTION_MIN_ACTIVATED_TRADES_PER_RULE,
)
from cocomelon.research.profit_lock_execution_readiness import (
    MIN_ECONOMICALLY_EVALUATED_TRADES_PER_RULE,
    MIN_SIMULATED_FULL_CLOSES_PER_RULE,
    profit_lock_execution_readiness,
)
from cocomelon.research.profit_lock_execution_readiness import (
    MIN_TRIGGERED_TRADES_PER_RULE as EXECUTION_MIN_TRIGGERED_TRADES_PER_RULE,
)
from cocomelon.research.profit_lock_execution_shadow import (
    ProfitLockExecutionShadow,
)
from cocomelon.research.profit_lock_readiness import (
    MIN_ACTIVATED_TRADES_PER_RULE,
    MIN_COMPLETE_PATHS,
    MIN_TRIGGERED_TRADES_PER_RULE,
    profit_lock_readiness,
)
from cocomelon.research.prospective_capacity_reflow_exit_fill import (
    evaluate_prospective_capacity_reflow_exit_fill,
)
from cocomelon.research.prospective_capacity_reflow_fill_feasibility import (
    evaluate_prospective_capacity_reflow_fill_feasibility,
)
from cocomelon.research.prospective_capacity_reflow_forward_excursion import (
    evaluate_prospective_capacity_reflow_forward_excursion,
)
from cocomelon.research.prospective_capacity_reflow_forward_markout import (
    DEFAULT_FORWARD_MARKOUT_HORIZONS_MS,
    MAX_FORWARD_MARKOUT_LAG_MS,
    evaluate_prospective_capacity_reflow_forward_markout,
)
from cocomelon.research.prospective_capacity_reflow_opportunities import (
    evaluate_prospective_capacity_reflow_opportunities,
)
from cocomelon.research.prospective_capacity_reflow_realized_pnl import (
    evaluate_prospective_capacity_reflow_realized_pnl,
)
from cocomelon.research.prospective_capacity_reflow_release_lineage import (
    evaluate_prospective_capacity_reflow_release_lineage,
)
from cocomelon.research.prospective_combined_entry_filter import (
    ProspectiveCombinedEntryFilterState,
    evaluate_prospective_combined_entry_filter,
    evaluate_prospective_combined_matched_overlap,
)
from cocomelon.research.prospective_daily_loss_lockout_reflow import (
    evaluate_prospective_daily_loss_lockout_reflow,
)
from cocomelon.research.prospective_delayed_price_confirmation import (
    ProspectiveDelayedPriceConfirmationState,
    prospective_delayed_price_confirmation_summary,
)
from cocomelon.research.prospective_entry_filter import (
    ProspectiveEntryFilterState,
    evaluate_prospective_entry_filter,
)
from cocomelon.research.prospective_replacement_exit_policy import (
    ProspectiveReplacementExitPolicyState,
    prospective_replacement_exit_policy_summary,
)
from cocomelon.research.prospective_replacement_exit_readiness import (
    prospective_replacement_exit_readiness,
)
from cocomelon.research.prospective_replacement_exit_robustness import (
    prospective_replacement_exit_robustness,
)
from cocomelon.research.prospective_top10_rank_filter import (
    ProspectiveTop10RankFilterState,
    evaluate_prospective_top10_rank_filter,
)
from cocomelon.research.prospective_trade_quality import (
    ProspectiveTradeQualityState,
    prospective_trade_quality_summary,
)
from cocomelon.research.prospective_side_conditioned_delay import (
    ProspectiveSideConditionedDelayState,
)
from cocomelon.util.time import utc_now_ms

RUN_ID = CONTINUOUS_PAPER_REPLAY_RUN_ID


def _stop_requested(stop_path: Path | None) -> bool:
    return stop_path is not None and stop_path.exists()


def _iter_until_stop[T](
    items: Iterable[T],
    stop_path: Path | None,
) -> Iterator[T]:
    for item in items:
        if _stop_requested(stop_path):
            return
        yield item


CHECKPOINT_FILENAME = "runtime-state.json"
SUMMARY_FILENAME = "session-summary.json"
CADENCE_SHADOW_FILENAME = "cadence-shadow-summary.json"
CADENCE_SHADOW_STATE_FILENAME = "cadence-shadow-state.json"
PROFIT_LOCK_EXECUTION_SHADOW_STATE_FILENAME = (
    "profit-lock-execution-shadow-state.json"
)
PROSPECTIVE_ENTRY_FILTER_STATE_FILENAME = (
    "prospective-entry-filter-state.json"
)
PROSPECTIVE_DELAYED_PRICE_CONFIRM_STATE_FILENAME = (
    "prospective-delayed-price-confirm-state.json"
)
PROSPECTIVE_TOP10_RANK_FILTER_STATE_FILENAME = (
    "prospective-top10-rank-filter-state.json"
)
PROSPECTIVE_TRADE_QUALITY_STATE_FILENAME = (
    "prospective-trade-quality-state.json"
)
PROSPECTIVE_SIDE_CONDITIONED_DELAY_STATE_FILENAME = (
    "prospective-side-conditioned-delay-state.json"
)
PROSPECTIVE_COMBINED_ENTRY_FILTER_STATE_FILENAME = (
    "prospective-top10-no-long-trend-state.json"
)
PROSPECTIVE_REPLACEMENT_EXIT_POLICY_STATE_FILENAME = (
    "prospective-replacement-5m-exit-state.json"
)
ADAPTIVE_DELAY_SELECTOR_STATE_FILENAME = (
    "adaptive-delay-selector-state.json"
)
FILL_AWARE_DELAY_SELECTOR_STATE_FILENAME = (
    "fill-aware-delay-selector-state.json"
)
DELAY_SELECTOR_COMPARISON_STATE_FILENAME = (
    "delay-selector-comparison-state.json"
)
ENTRY_MID_MARKOUT_SHADOW_STATE_FILENAME = (
    "entry-mid-markout-shadow-state.json"
)
DELAYED_ENTRY_EXECUTION_SHADOW_STATE_FILENAME = (
    "delayed-entry-execution-shadow-state.json"
)
DELAYED_ENTRY_120S_EXECUTION_SHADOW_STATE_FILENAME = (
    "delayed-entry-120s-execution-shadow-state.json"
)
DRAWDOWN_STATE_FILENAME = "drawdown-state.json"


@dataclass(frozen=True, slots=True)
class ContinuousPaperConfig:
    duration_seconds: int = 19_800
    deep_limit: int = 20
    context_poll_seconds: int = 60
    selection_refresh_seconds: int = 300
    checkpoint_seconds: int = 30
    warmup_5m_bars: int = 25
    warmup_15m_bars: int = 25

    def __post_init__(self) -> None:
        if self.duration_seconds <= 0:
            raise ValueError("duration_seconds must be positive")
        if self.deep_limit <= 0:
            raise ValueError("deep_limit must be positive")
        if self.context_poll_seconds <= 0:
            raise ValueError("context_poll_seconds must be positive")
        if self.selection_refresh_seconds < self.context_poll_seconds:
            raise ValueError("selection_refresh_seconds must be >= context_poll_seconds")
        if self.selection_refresh_seconds % self.context_poll_seconds:
            raise ValueError("selection_refresh_seconds must be divisible by context_poll_seconds")
        if self.checkpoint_seconds <= 0:
            raise ValueError("checkpoint_seconds must be positive")
        if self.warmup_5m_bars <= 0 or self.warmup_15m_bars <= 0:
            raise ValueError("warmup bar counts must be positive")


class _ContinuousTradePathSink:
    def __init__(self, store: ContinuousPaperTradePathStore) -> None:
        self._store = store
        self.error: str | None = None

    def _capture_error(self, exc: Exception) -> None:
        if self.error is None:
            self.error = f"{type(exc).__name__}: {exc}"

    def record_opening_trace(
        self,
        trace: BaselineOpeningTrace,
    ) -> None:
        plan = trace.submission.plan
        simulation = trace.submission.simulation
        if plan is None or simulation is None or not simulation.fills:
            return
        try:
            matches = tuple(
                position
                for position in trace.submission.account.positions
                if position.opening_plan_id == plan.plan_id
            )
            if len(matches) != 1:
                raise RuntimeError(
                    "trade-path opening position lineage is missing"
                )
            position = matches[0]
            if (
                position.market != plan.market
                or position.venue_max_leverage
                != trace.instrument.venue_max_leverage
            ):
                raise RuntimeError(
                    "trade-path opening instrument lineage mismatch"
                )
            self._store.checkpoint_open_path(
                opening_plan_id=plan.plan_id,
                market=plan.market,
                opened_at_ms=position.opened_at_ms,
                mark_observations=(),
                venue_max_leverage=position.venue_max_leverage,
            )
        except Exception as exc:
            self._capture_error(exc)

    def checkpoint(
        self,
        open_paths: Sequence[OpenLifecycleMarkPath],
    ) -> None:
        for path in open_paths:
            try:
                self._store.checkpoint_open_path(
                    opening_plan_id=path.opening_plan_id,
                    market=path.market,
                    opened_at_ms=path.opened_at_ms,
                    mark_observations=path.mark_observations,
                    venue_max_leverage=path.venue_max_leverage,
                )
            except Exception as exc:
                self._capture_error(exc)

    def record(
        self,
        trade: TradeJournalEntry,
        mark_observations: Sequence[ReplayRecord],
        known_gap_intervals: Sequence[tuple[int, int | None]],
    ) -> bool:
        try:
            return self._store.finalize_trade(
                trade,
                mark_observations,
                known_gap_intervals,
            )
        except Exception as exc:
            self._capture_error(exc)
            return False


class _ContinuousOpeningFillLiquiditySink:
    def __init__(
        self,
        store: OpeningFillLiquidityStore,
    ) -> None:
        self._store = store
        self.error: str | None = None

    def record_opening_trace(
        self,
        trace: BaselineOpeningTrace,
    ) -> None:
        try:
            evidence = evidence_from_opening_trace(trace)
            if evidence is not None:
                self._store.record(evidence)
        except Exception as exc:
            if self.error is None:
                self.error = f"{type(exc).__name__}: {exc}"


class _ContinuousOpeningOpportunitySink:
    def __init__(
        self,
        store: ContinuousPaperOpeningOpportunityStore,
        path_store: ContinuousPaperOpeningOpportunityPathStore,
        exit_book_store: ContinuousPaperOpeningOpportunityExitBookStore,
        replacement_funding_store: ContinuousPaperReplacementFundingStore,
        rank_tracker: LatestCoarseRankTracker,
    ) -> None:
        self._store = store
        self._path_store = path_store
        self._exit_book_store = exit_book_store
        self._replacement_funding_store = replacement_funding_store
        self._rank_tracker = rank_tracker
        self.error: str | None = None
        self.path_error: str | None = None
        self.exit_book_error: str | None = None
        self.funding_error: str | None = None

    def record_opening_trace(
        self,
        trace: BaselineOpeningTrace,
    ) -> None:
        try:
            rank_snapshot = self._rank_tracker.snapshot_for_market(
                trace.evaluation.decision.market,
                at_ms=trace.risk_request.timestamp_ms,
            )
            evidence = opportunity_evidence_from_trace(
                trace,
                rank_snapshot=rank_snapshot,
            )
            self._store.record(evidence)
        except Exception as exc:
            if self.error is None:
                self.error = f"{type(exc).__name__}: {exc}"
            return

        try:
            self._path_store.register(
                opportunity_id=evidence.opportunity_id,
                market=evidence.market,
                direction=evidence.direction,
                opportunity_timestamp_ms=evidence.opportunity_timestamp_ms,
            )
        except Exception as exc:
            if self.path_error is None:
                self.path_error = f"{type(exc).__name__}: {exc}"

        try:
            self._exit_book_store.register(
                opportunity_id=evidence.opportunity_id,
                market=evidence.market,
                direction=evidence.direction,
                opportunity_timestamp_ms=evidence.opportunity_timestamp_ms,
            )
        except Exception as exc:
            if self.exit_book_error is None:
                self.exit_book_error = f"{type(exc).__name__}: {exc}"

        try:
            self._replacement_funding_store.register(
                opportunity_id=evidence.opportunity_id,
                market=evidence.market,
                opportunity_timestamp_ms=evidence.opportunity_timestamp_ms,
            )
        except Exception as exc:
            if self.funding_error is None:
                self.funding_error = f"{type(exc).__name__}: {exc}"

    def observe_snapshots(
        self,
        snapshots: dict[str, PerpMarketSnapshot],
    ) -> None:
        for snapshot in snapshots.values():
            mark_px = snapshot.context.mark_px
            if mark_px is not None:
                try:
                    self._path_store.observe(
                        market=snapshot.meta.market.canonical,
                        observed_at_ms=snapshot.received_at_ms,
                        mark_px=mark_px,
                        source=snapshot.source,
                    )
                except Exception as exc:
                    if self.path_error is None:
                        self.path_error = f"{type(exc).__name__}: {exc}"


class _CompositeOpeningResearchObserver:
    def __init__(
        self,
        *observers: OpeningResearchObserver,
    ) -> None:
        self._observers = observers

    def record_opening_trace(
        self,
        trace: BaselineOpeningTrace,
    ) -> None:
        for observer in self._observers:
            observer.record_opening_trace(trace)


class _CompositePositionResearchObserver:
    def __init__(
        self,
        *observers: PositionResearchObserver,
    ) -> None:
        self._observers = observers

    def observe_mark(
        self,
        positions: Sequence[PaperPosition],
        mark_event: StreamEvent,
        *,
        now_ms: int,
    ) -> None:
        for observer in self._observers:
            observer.observe_mark(
                positions,
                mark_event,
                now_ms=now_ms,
            )

    def observe_book(
        self,
        positions: Sequence[PaperPosition],
        instrument: InstrumentExecutionSpec,
        book: StreamEvent,
        *,
        reference_price: Decimal,
        now_ms: int,
    ) -> None:
        for observer in self._observers:
            observer.observe_book(
                positions,
                instrument,
                book,
                reference_price=reference_price,
                now_ms=now_ms,
            )

    def record_closed_trade(
        self,
        trade: TradeJournalEntry,
    ) -> None:
        for observer in self._observers:
            observer.record_closed_trade(trade)


class _ContinuousDelayedEntryExecutionShadowSink:
    def __init__(
        self,
        shadow: DelayedEntryExecutionShadow,
        *,
        opening_plan_loader: Callable[
            [str],
            PaperOrderPlan | None,
        ],
    ) -> None:
        self.shadow: DelayedEntryExecutionShadow | None = shadow
        self._opening_plan_loader = opening_plan_loader
        self.error: str | None = None

    def _disable(self, exc: Exception) -> None:
        if self.error is None:
            self.error = f"{type(exc).__name__}: {exc}"
        self.shadow = None

    def _position_with_original_stop(
        self,
        position: PaperPosition,
    ) -> PaperPosition:
        plan = self._opening_plan_loader(
            position.opening_plan_id
        )
        if plan is None:
            raise RuntimeError(
                "delayed-entry opening plan is missing"
            )
        if plan.reduce_only:
            raise RuntimeError(
                "delayed-entry opening plan is reduce-only"
            )
        if plan.market != position.market:
            raise RuntimeError(
                "delayed-entry opening plan market mismatch"
            )
        if plan.stop_price is None:
            raise RuntimeError(
                "delayed-entry opening plan is missing stop"
            )
        return replace(
            position,
            stop_price=plan.stop_price,
        )

    def _positions_with_original_stops(
        self,
        positions: Sequence[PaperPosition],
    ) -> tuple[PaperPosition, ...]:
        return tuple(
            self._position_with_original_stop(position)
            for position in positions
        )

    def reconcile_open_positions(
        self,
        positions: Sequence[PaperPosition],
    ) -> None:
        if self.shadow is None:
            return
        try:
            self.shadow.reconcile_open_positions(
                self._positions_with_original_stops(positions)
            )
        except Exception as exc:
            self._disable(exc)

    def observe_mark(
        self,
        positions: Sequence[PaperPosition],
        mark_event: StreamEvent,
        *,
        now_ms: int,
    ) -> None:
        if self.shadow is None:
            return
        try:
            self.shadow.observe_mark(
                self._positions_with_original_stops(positions),
                mark_event,
                now_ms=now_ms,
            )
        except Exception as exc:
            self._disable(exc)

    def observe_book(
        self,
        positions: Sequence[PaperPosition],
        instrument: InstrumentExecutionSpec,
        book: StreamEvent,
        *,
        reference_price: Decimal,
        now_ms: int,
    ) -> None:
        if self.shadow is None:
            return
        try:
            self.shadow.observe_book(
                self._positions_with_original_stops(positions),
                instrument,
                book,
                reference_price=reference_price,
                now_ms=now_ms,
            )
        except Exception as exc:
            self._disable(exc)

    def record_closed_trade(
        self,
        trade: TradeJournalEntry,
    ) -> None:
        if self.shadow is None:
            return
        try:
            self.shadow.record_closed_trade(trade)
        except Exception as exc:
            self._disable(exc)

    def summary_payload(self) -> dict[str, object]:
        if self.shadow is None:
            return {
                "enabled": False,
                "research_only": True,
                "execution_authority": False,
                "promotion_authority": False,
                "durable_state": True,
                "stop_source": "persisted_opening_plan",
                "error": self.error,
            }
        payload = dict(self.shadow.summary_payload())
        payload["stop_source"] = "persisted_opening_plan"
        payload["error"] = self.error
        return payload


class _ContinuousProfitLockExecutionShadowSink:
    def __init__(
        self,
        shadow: ProfitLockExecutionShadow,
        *,
        opening_plan_loader: Callable[
            [str],
            PaperOrderPlan | None,
        ],
    ) -> None:
        self.shadow: ProfitLockExecutionShadow | None = shadow
        self._opening_plan_loader = opening_plan_loader
        self.error: str | None = None

    def _disable(self, exc: Exception) -> None:
        if self.error is None:
            self.error = f"{type(exc).__name__}: {exc}"
        self.shadow = None

    def _position_with_opening_lineage(
        self,
        position: PaperPosition,
    ) -> PaperPosition:
        plan = self._opening_plan_loader(
            position.opening_plan_id
        )
        if plan is None:
            raise RuntimeError(
                "profit-lock opening plan is missing"
            )
        if plan.reduce_only:
            raise RuntimeError(
                "profit-lock opening plan is reduce-only"
            )
        if plan.market != position.market:
            raise RuntimeError(
                "profit-lock opening plan market mismatch"
            )
        if (
            plan.stop_price is None
            or plan.approved_risk_amount_ceiling is None
        ):
            raise RuntimeError(
                "profit-lock opening plan risk envelope is incomplete"
            )
        return replace(
            position,
            stop_price=plan.stop_price,
            planned_risk=plan.approved_risk_amount_ceiling,
            cost_buffer_fraction=(
                position.cost_buffer_fraction
                if plan.cost_buffer_fraction is None
                else plan.cost_buffer_fraction
            ),
        )

    def _positions_with_opening_lineage(
        self,
        positions: Sequence[PaperPosition],
    ) -> tuple[PaperPosition, ...]:
        return tuple(
            self._position_with_opening_lineage(position)
            for position in positions
        )

    def reconcile_open_positions(
        self,
        positions: Sequence[PaperPosition],
    ) -> None:
        if self.shadow is None:
            return
        try:
            self.shadow.reconcile_open_positions(
                self._positions_with_opening_lineage(positions)
            )
        except Exception as exc:
            self._disable(exc)

    def observe_mark(
        self,
        positions: Sequence[PaperPosition],
        mark_event: StreamEvent,
        *,
        now_ms: int,
    ) -> None:
        if self.shadow is None:
            return
        try:
            self.shadow.observe_mark(
                self._positions_with_opening_lineage(positions),
                mark_event,
                now_ms=now_ms,
            )
        except Exception as exc:
            self._disable(exc)

    def observe_book(
        self,
        positions: Sequence[PaperPosition],
        instrument: InstrumentExecutionSpec,
        book: StreamEvent,
        *,
        reference_price: Decimal,
        now_ms: int,
    ) -> None:
        if self.shadow is None:
            return
        try:
            self.shadow.observe_book(
                self._positions_with_opening_lineage(positions),
                instrument,
                book,
                reference_price=reference_price,
                now_ms=now_ms,
            )
        except Exception as exc:
            self._disable(exc)

    def record_closed_trade(
        self,
        trade: TradeJournalEntry,
    ) -> None:
        if self.shadow is None:
            return
        try:
            self.shadow.record_closed_trade(trade)
        except Exception as exc:
            self._disable(exc)

    def summary_payload(self) -> dict[str, object]:
        if self.shadow is None:
            return {
                "enabled": False,
                "research_only": True,
                "execution_authority": False,
                "durable_state": True,
                "opening_lineage_source": "persisted_opening_plan",
                "error": self.error,
            }
        payload = dict(self.shadow.summary_payload())
        readiness = profit_lock_execution_readiness(payload)
        readiness_by_rule = {
            rule.rule_id: rule
            for rule in readiness.rules
        }
        raw_rules = payload.get("rules", [])
        if not isinstance(raw_rules, list):
            raise ValueError(
                "execution shadow rules must be a list"
            )
        payload["rules"] = [
            {
                **rule,
                "readiness_status": readiness_by_rule[
                    str(rule["rule_id"])
                ].status.value,
                "missing_evaluated_trades": readiness_by_rule[
                    str(rule["rule_id"])
                ].missing_evaluated_trades,
                "missing_activated_trades": readiness_by_rule[
                    str(rule["rule_id"])
                ].missing_activated_trades,
                "missing_triggered_trades": readiness_by_rule[
                    str(rule["rule_id"])
                ].missing_triggered_trades,
                "missing_simulated_full_closes": readiness_by_rule[
                    str(rule["rule_id"])
                ].missing_simulated_full_closes,
            }
            for rule in raw_rules
            if isinstance(rule, dict)
        ]
        payload["readiness"] = {
            "all_rules_ready_for_review": (
                readiness.all_rules_ready_for_review
            ),
            "lineage_mismatch_closed_trades": (
                readiness.lineage_mismatch_closed_trades
            ),
            "orphaned_restored_positions": (
                readiness.orphaned_restored_positions
            ),
            "min_economically_evaluated_trades_per_rule": (
                MIN_ECONOMICALLY_EVALUATED_TRADES_PER_RULE
            ),
            "min_activated_trades_per_rule": (
                EXECUTION_MIN_ACTIVATED_TRADES_PER_RULE
            ),
            "min_triggered_trades_per_rule": (
                EXECUTION_MIN_TRIGGERED_TRADES_PER_RULE
            ),
            "min_simulated_full_closes_per_rule": (
                MIN_SIMULATED_FULL_CLOSES_PER_RULE
            ),
            "promotion_authority": False,
            "execution_authority": False,
        }
        payload["opening_lineage_source"] = (
            "persisted_opening_plan"
        )
        payload["error"] = self.error
        return payload


class _ContinuousEntryMidMarkoutSink:
    def __init__(
        self,
        shadow: EntryMidMarkoutShadow,
        *,
        opening_plan_loader: Callable[
            [str],
            PaperOrderPlan | None,
        ],
    ) -> None:
        self.shadow: EntryMidMarkoutShadow | None = shadow
        self._opening_plan_loader = opening_plan_loader
        self.error: str | None = None

    def _disable(self, exc: Exception) -> None:
        if self.error is None:
            self.error = f"{type(exc).__name__}: {exc}"
        self.shadow = None

    def _position_with_opening_lineage(
        self,
        position: PaperPosition,
    ) -> PaperPosition:
        plan = self._opening_plan_loader(
            position.opening_plan_id
        )
        if plan is None:
            raise RuntimeError(
                "allMids markout opening plan is missing"
            )
        if plan.reduce_only:
            raise RuntimeError(
                "allMids markout opening plan is reduce-only"
            )
        if plan.market != position.market:
            raise RuntimeError(
                "allMids markout opening plan market mismatch"
            )
        if plan.approved_risk_amount_ceiling is None:
            raise RuntimeError(
                "allMids markout opening plan risk ceiling is missing"
            )
        return replace(
            position,
            planned_risk=plan.approved_risk_amount_ceiling,
        )

    def _positions_with_opening_lineage(
        self,
        positions: Sequence[PaperPosition],
    ) -> tuple[PaperPosition, ...]:
        return tuple(
            self._position_with_opening_lineage(position)
            for position in positions
        )

    def reconcile_open_positions(
        self,
        positions: Sequence[PaperPosition],
    ) -> None:
        if self.shadow is None:
            return
        try:
            self.shadow.reconcile_open_positions(
                self._positions_with_opening_lineage(positions)
            )
        except Exception as exc:
            self._disable(exc)

    def observe(
        self,
        record: ReplayRecord,
        positions: Sequence[PaperPosition],
        *,
        now_ms: int,
    ) -> None:
        if self.shadow is None:
            return
        try:
            self.shadow.observe(
                record,
                self._positions_with_opening_lineage(positions),
                now_ms=now_ms,
            )
        except Exception as exc:
            self._disable(exc)

    def record_closed_trade(
        self,
        trade: TradeJournalEntry,
    ) -> None:
        if self.shadow is None:
            return
        try:
            self.shadow.record_closed_trade(trade)
        except Exception as exc:
            self._disable(exc)

    def summary_payload(
        self,
        fact_store: EvaluationFactStore,
    ) -> dict[str, object]:
        def disabled_payload() -> dict[str, object]:
            return {
                "enabled": False,
                "research_only": True,
                "execution_authority": False,
                "promotion_authority": False,
                "durable_state": True,
                "error": self.error,
            }

        if self.shadow is None:
            return disabled_payload()
        try:
            payload = dict(
                self.shadow.summary_payload(fact_store)
            )
            readiness = entry_mid_markout_readiness(payload)
            readiness_by_horizon = {
                item.horizon_ms: item
                for item in readiness.horizons
            }
            raw_horizons = payload.get("by_horizon_ms")
            if not isinstance(raw_horizons, dict):
                raise RuntimeError(
                    "allMids markout summary lost by_horizon_ms"
                )
            for horizon_ms, item in (
                readiness_by_horizon.items()
            ):
                raw = raw_horizons.get(str(horizon_ms))
                if not isinstance(raw, dict):
                    raise RuntimeError(
                        "allMids markout horizon summary disappeared"
                    )
                raw["readiness_status"] = item.status.value
                raw["missing_fresh_observations"] = (
                    item.missing_fresh_observations
                )
                raw["non_fresh_fraction"] = (
                    None
                    if item.non_fresh_fraction is None
                    else str(item.non_fresh_fraction)
                )
                raw["coverage_quality_ready"] = (
                    item.coverage_quality_ready
                )
            payload["readiness"] = {
                "all_horizons_ready_for_review": (
                    readiness.all_horizons_ready_for_review
                ),
                "lineage_mismatch_closed_trades": (
                    readiness.lineage_mismatch_closed_trades
                ),
                "orphaned_restored_positions": (
                    readiness.orphaned_restored_positions
                ),
                "min_fresh_observations_per_horizon": (
                    MIN_FRESH_OBSERVATIONS_PER_HORIZON
                ),
                "max_non_fresh_fraction": str(
                    MAX_NON_FRESH_FRACTION
                ),
                "unmatched_closed_trades": (
                    readiness.unmatched_closed_trades
                ),
                "promotion_authority": False,
                "execution_authority": False,
            }
        except Exception as exc:
            self._disable(exc)
            return disabled_payload()

        payload["enabled"] = True
        payload["opening_lineage_source"] = (
            "persisted_opening_plan_risk_ceiling"
        )
        payload["error"] = self.error
        return payload


class _ContinuousOpeningLineageSink:
    def __init__(
        self,
        store: ContinuousPaperOpeningLineageStore,
        runtime: ContinuousPaperRuntimeIdentity,
        *,
        rank_store: ContinuousPaperOpeningRankStore,
        rank_tracker: LatestCoarseRankTracker,
    ) -> None:
        self._store = store
        self._runtime = runtime
        self._rank_store = rank_store
        self._rank_tracker = rank_tracker
        self.rank_error: str | None = None

    def record(self, checkpoint: OpenLifecycleCheckpoint) -> bool:
        if checkpoint.opened_at_ms is None:
            raise ValueError("fresh paper opening is missing opened_at_ms")
        created = self._store.record(
            ContinuousPaperOpeningLineage(
                opening_plan_id=checkpoint.opening_plan_id,
                feature_snapshot_id=checkpoint.feature_snapshot_id,
                market=checkpoint.market.canonical,
                opened_at_ms=checkpoint.opened_at_ms,
                runtime=self._runtime,
            )
        )
        try:
            evidence = self._rank_tracker.evidence_for_opening(
                opening_plan_id=checkpoint.opening_plan_id,
                market=checkpoint.market,
                opened_at_ms=checkpoint.opened_at_ms,
            )
            if evidence is not None:
                self._rank_store.record(evidence)
        except Exception as exc:
            if self.rank_error is None:
                self.rank_error = f"{type(exc).__name__}: {exc}"
        return created


@dataclass(frozen=True, slots=True)
class ContinuousPaperSummary:
    started_at_ms: int
    ended_at_ms: int
    exit_reason: str
    selected_markets: tuple[str, ...]
    processed_records: int
    journal_observations: int
    closed_trades: int
    session_closed_trades: int
    feature_snapshot_count: int
    feature_snapshot_state_digest: str
    opening_lineage_count: int
    opening_lineage_state_digest: str
    opening_rank_count: int
    opening_rank_state_digest: str
    opening_rank_capture_error: str | None
    opening_fill_liquidity_count: int
    opening_fill_liquidity_state_digest: str
    opening_fill_liquidity_capture_error: str | None
    opening_opportunity_count: int
    opening_opportunity_approved_count: int
    opening_opportunity_rejected_count: int
    opening_opportunity_rank_complete_count: int
    opening_opportunity_state_digest: str
    opening_opportunity_capture_error: str | None
    trade_path_count: int
    trade_path_open_count: int
    trade_path_state_digest: str
    trade_path_capture_error: str | None
    open_positions: int
    equity: Decimal
    execution_healthy: bool
    execution_reason_codes: tuple[str, ...]
    opening_opportunity_path_count: int = 0
    opening_opportunity_path_complete_count: int = 0
    opening_opportunity_path_state_digest: str = ""
    opening_opportunity_path_capture_error: str | None = None
    opening_opportunity_exit_book_registration_count: int = 0
    opening_opportunity_exit_book_capture_count: int = 0
    opening_opportunity_exit_book_pending_count: int = 0
    opening_opportunity_exit_book_missed_count: int = 0
    opening_opportunity_exit_book_state_digest: str = ""
    opening_opportunity_exit_book_capture_error: str | None = None
    replacement_funding_registration_count: int = 0
    replacement_funding_required_boundary_count: int = 0
    replacement_funding_oracle_candidate_count: int = 0
    replacement_funding_capture_count: int = 0
    replacement_funding_pending_count: int = 0
    replacement_funding_missed_count: int = 0
    replacement_funding_state_digest: str = ""
    replacement_funding_capture_error: str | None = None
    network_access: bool = True
    live_orders: bool = False

    def payload(self) -> dict[str, object]:
        return {
            "started_at_ms": self.started_at_ms,
            "ended_at_ms": self.ended_at_ms,
            "exit_reason": self.exit_reason,
            "selected_markets": list(self.selected_markets),
            "processed_records": self.processed_records,
            "journal_observations": self.journal_observations,
            "closed_trades": self.closed_trades,
            "session_closed_trades": self.session_closed_trades,
            "feature_snapshot_count": self.feature_snapshot_count,
            "feature_snapshot_state_digest": self.feature_snapshot_state_digest,
            "opening_lineage_count": self.opening_lineage_count,
            "opening_lineage_state_digest": self.opening_lineage_state_digest,
            "opening_rank_count": self.opening_rank_count,
            "opening_rank_state_digest": self.opening_rank_state_digest,
            "opening_rank_capture_error": self.opening_rank_capture_error,
            "opening_fill_liquidity_count": self.opening_fill_liquidity_count,
            "opening_fill_liquidity_state_digest": (
                self.opening_fill_liquidity_state_digest
            ),
            "opening_fill_liquidity_capture_error": (
                self.opening_fill_liquidity_capture_error
            ),
            "opening_opportunity_count": self.opening_opportunity_count,
            "opening_opportunity_approved_count": (
                self.opening_opportunity_approved_count
            ),
            "opening_opportunity_rejected_count": (
                self.opening_opportunity_rejected_count
            ),
            "opening_opportunity_rank_complete_count": (
                self.opening_opportunity_rank_complete_count
            ),
            "opening_opportunity_state_digest": (
                self.opening_opportunity_state_digest
            ),
            "opening_opportunity_capture_error": (
                self.opening_opportunity_capture_error
            ),
            "trade_path_count": self.trade_path_count,
            "trade_path_open_count": self.trade_path_open_count,
            "trade_path_state_digest": self.trade_path_state_digest,
            "trade_path_capture_error": self.trade_path_capture_error,
            "open_positions": self.open_positions,
            "equity": str(self.equity),
            "execution_healthy": self.execution_healthy,
            "execution_reason_codes": list(self.execution_reason_codes),
            "opening_opportunity_path_count": (
                self.opening_opportunity_path_count
            ),
            "opening_opportunity_path_complete_count": (
                self.opening_opportunity_path_complete_count
            ),
            "opening_opportunity_path_state_digest": (
                self.opening_opportunity_path_state_digest
            ),
            "opening_opportunity_path_capture_error": (
                self.opening_opportunity_path_capture_error
            ),
            "opening_opportunity_exit_book_registration_count": (
                self.opening_opportunity_exit_book_registration_count
            ),
            "opening_opportunity_exit_book_capture_count": (
                self.opening_opportunity_exit_book_capture_count
            ),
            "opening_opportunity_exit_book_pending_count": (
                self.opening_opportunity_exit_book_pending_count
            ),
            "opening_opportunity_exit_book_missed_count": (
                self.opening_opportunity_exit_book_missed_count
            ),
            "opening_opportunity_exit_book_state_digest": (
                self.opening_opportunity_exit_book_state_digest
            ),
            "opening_opportunity_exit_book_capture_error": (
                self.opening_opportunity_exit_book_capture_error
            ),
            "replacement_funding_registration_count": (
                self.replacement_funding_registration_count
            ),
            "replacement_funding_required_boundary_count": (
                self.replacement_funding_required_boundary_count
            ),
            "replacement_funding_oracle_candidate_count": (
                self.replacement_funding_oracle_candidate_count
            ),
            "replacement_funding_capture_count": (
                self.replacement_funding_capture_count
            ),
            "replacement_funding_pending_count": (
                self.replacement_funding_pending_count
            ),
            "replacement_funding_missed_count": (
                self.replacement_funding_missed_count
            ),
            "replacement_funding_state_digest": (
                self.replacement_funding_state_digest
            ),
            "replacement_funding_capture_error": (
                self.replacement_funding_capture_error
            ),
            "network_access": self.network_access,
            "live_orders": self.live_orders,
        }


def _market_from_canonical(value: str) -> MarketId:
    if ":" in value:
        dex = value.split(":", 1)[0]
        return MarketId.from_wire_name(dex, value)
    return MarketId.from_wire_name("", value)


def _canonical(value: object) -> object:
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Decimal values must be finite")
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime values must be timezone-aware")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, MarketId):
        return value.canonical
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")


def _payload_json(value: object) -> str:
    return json.dumps(
        _canonical(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _record_from_public(event: RecordedPublicEvent) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=int(event.receive_time.timestamp() * 1000),
        source=event.source,
        schema_version=event.schema_version,
        market=event.market.canonical,
        exchange_time_ms=event.exchange_time_ms,
        event_key=event.event_key,
        payload_json=_payload_json(event.payload),
        event_kind=event.kind,
    )


def _record_from_stream(event: StreamEvent) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=int(event.receive_time.timestamp() * 1000),
        source=event.source,
        schema_version=event.schema_version,
        market=event.market.canonical,
        exchange_time_ms=event.exchange_time_ms,
        event_key=event.event_key,
        payload_json=_payload_json(event.payload),
        event_kind=event.kind.value,
    )


def _record_from_gap(gap: DataGap) -> ReplayRecord:
    payload = {
        "stream_id": gap.stream_id,
        "started_ms": gap.started_ms,
        "ended_ms": gap.ended_ms,
        "reason": gap.reason,
    }
    return ReplayRecord(
        record_kind=SourceRecordKind.DATA_GAP,
        available_at_ms=gap.started_ms,
        source=gap.source,
        schema_version=gap.schema_version,
        market=None,
        exchange_time_ms=None,
        event_key=f"gap:{gap.stream_id}:{gap.started_ms}:{gap.ended_ms}:{gap.reason}",
        payload_json=_payload_json(payload),
        event_kind=None,
    )


def _record_payload(record: ReplayRecord) -> dict[str, object]:
    return {
        "record_kind": record.record_kind.value,
        "available_at_ms": record.available_at_ms,
        "source": record.source,
        "schema_version": record.schema_version,
        "market": record.market,
        "exchange_time_ms": record.exchange_time_ms,
        "event_key": record.event_key,
        "payload_json": record.payload_json,
        "event_kind": record.event_kind,
    }


def _record_from_payload(raw: object) -> ReplayRecord:
    if not isinstance(raw, dict):
        raise ValueError("checkpoint replay record must be an object")
    return ReplayRecord(
        record_kind=SourceRecordKind(str(raw["record_kind"])),
        available_at_ms=int(raw["available_at_ms"]),
        source=str(raw["source"]),
        schema_version=int(raw["schema_version"]),
        market=None if raw.get("market") is None else str(raw["market"]),
        exchange_time_ms=(
            None if raw.get("exchange_time_ms") is None else int(raw["exchange_time_ms"])
        ),
        event_key=None if raw.get("event_key") is None else str(raw["event_key"]),
        payload_json=str(raw["payload_json"]),
        event_kind=None if raw.get("event_kind") is None else str(raw["event_kind"]),
    )


def _position_action_payload(action: PositionAction) -> dict[str, object]:
    return {
        "action_type": action.action_type.value,
        "market": action.market.canonical,
        "quantity": None if action.quantity is None else str(action.quantity),
        "new_stop_price": (
            None if action.new_stop_price is None else str(action.new_stop_price)
        ),
        "reason_codes": list(action.reason_codes),
        "timestamp_ms": action.timestamp_ms,
    }


def _position_action_from_payload(raw: object) -> PositionAction:
    if not isinstance(raw, dict):
        raise ValueError("position action checkpoint must be an object")
    reason_codes = raw.get("reason_codes")
    if not isinstance(reason_codes, list) or not all(
        isinstance(value, str) for value in reason_codes
    ):
        raise ValueError("position action reason_codes are invalid")
    quantity_raw = raw.get("quantity")
    stop_raw = raw.get("new_stop_price")
    return PositionAction(
        action_type=PositionActionType(str(raw["action_type"])),
        market=_market_from_canonical(str(raw["market"])),
        quantity=None if quantity_raw is None else Decimal(str(quantity_raw)),
        new_stop_price=None if stop_raw is None else Decimal(str(stop_raw)),
        reason_codes=tuple(reason_codes),
        timestamp_ms=int(raw["timestamp_ms"]),
    )

def _checkpoint_payload(
    pipeline: BaselineReplayPipeline,
    *,
    last_available_at_ms: int,
    selected_markets: tuple[MarketId, ...],
) -> dict[str, object]:
    checkpoints = []
    for item in pipeline.open_lifecycle_checkpoints:
        checkpoints.append(
            {
                "market": item.market.canonical,
                "opening_plan_id": item.opening_plan_id,
                "feature_snapshot_id": item.feature_snapshot_id,
                "equity_before": str(item.equity_before),
                "exit_plan_ids": list(item.exit_plan_ids),
                "position_actions": [
                    _position_action_payload(action)
                    for action in item.position_actions
                ],
                "mark_observations": [
                    _record_payload(record) for record in item.mark_observations
                ],
            }
        )
    return {
        "schema_version": 1,
        "run_id": RUN_ID,
        "last_available_at_ms": last_available_at_ms,
        "selected_markets": [market.canonical for market in selected_markets],
        "open_lifecycles": checkpoints,
        "known_gap_intervals": [
            [started_ms, ended_ms]
            for started_ms, ended_ms in pipeline.known_gap_intervals
        ],
        "execution_mode": "paper",
        "live_orders": False,
    }


def _write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    )
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(encoded, encoding="utf-8")
    os.replace(temporary, path)


def _load_checkpoint(path: Path) -> tuple[
    tuple[OpenLifecycleCheckpoint, ...],
    tuple[tuple[int, int | None], ...],
    int,
]:
    if not path.exists():
        return (), (), 0
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise ValueError("continuous paper checkpoint is invalid")
    if raw.get("run_id") != RUN_ID or raw.get("execution_mode") != "paper":
        raise ValueError("continuous paper checkpoint authority mismatch")
    if raw.get("live_orders") is not False:
        raise ValueError("continuous paper checkpoint cannot authorize live orders")
    lifecycle_raw = raw.get("open_lifecycles")
    gap_raw = raw.get("known_gap_intervals")
    if not isinstance(lifecycle_raw, list) or not isinstance(gap_raw, list):
        raise ValueError("continuous paper checkpoint arrays are invalid")
    checkpoints: list[OpenLifecycleCheckpoint] = []
    for item in lifecycle_raw:
        if not isinstance(item, dict):
            raise ValueError("continuous paper lifecycle checkpoint is invalid")
        exit_ids = item.get("exit_plan_ids")
        actions = item.get("position_actions", [])
        marks = item.get("mark_observations")
        if not isinstance(exit_ids, list) or not all(isinstance(v, str) for v in exit_ids):
            raise ValueError("continuous paper exit_plan_ids are invalid")
        if not isinstance(actions, list):
            raise ValueError("continuous paper position actions are invalid")
        if not isinstance(marks, list):
            raise ValueError("continuous paper mark observations are invalid")
        checkpoints.append(
            OpenLifecycleCheckpoint(
                market=_market_from_canonical(str(item["market"])),
                opening_plan_id=str(item["opening_plan_id"]),
                feature_snapshot_id=str(item["feature_snapshot_id"]),
                equity_before=Decimal(str(item["equity_before"])),
                exit_plan_ids=tuple(exit_ids),
                position_actions=tuple(
                    _position_action_from_payload(action) for action in actions
                ),
                mark_observations=tuple(_record_from_payload(record) for record in marks),
            )
        )
    gaps: list[tuple[int, int | None]] = []
    for item in gap_raw:
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError("continuous paper gap interval is invalid")
        gaps.append((int(item[0]), None if item[1] is None else int(item[1])))
    return tuple(checkpoints), tuple(gaps), int(raw.get("last_available_at_ms", 0))


def _restore_cadence_shadow(
    path: Path,
    selected_markets: tuple[MarketId, ...],
    *,
    replay_config: BaselineReplayConfig,
) -> CadenceShadowComparator:
    shadow = CadenceShadowComparator(
        selected_markets,
        replay_config=replay_config,
    )
    if not path.exists():
        return shadow
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        shadow.restore_state(raw)
        shadow.reconcile_markets(selected_markets)
    except Exception as exc:
        shadow = CadenceShadowComparator(
            selected_markets,
            replay_config=replay_config,
        )
        shadow.mark_state_restore_error(
            f"{type(exc).__name__}: {exc}"
        )
    return shadow


def _restore_profit_lock_execution_shadow(
    path: Path,
    execution_config: PaperExecutionConfig,
    *,
    started_at_ms: int,
) -> ProfitLockExecutionShadow:
    shadow = ProfitLockExecutionShadow(
        execution_config,
        started_at_ms=started_at_ms,
    )
    if not path.exists():
        return shadow
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        shadow.restore_state(raw)
    except Exception as exc:
        shadow = ProfitLockExecutionShadow(
            execution_config,
            started_at_ms=started_at_ms,
        )
        shadow.mark_state_restore_error(
            f"{type(exc).__name__}: {exc}"
        )
    return shadow


def _restore_delayed_entry_execution_shadow(
    path: Path,
    execution_config: PaperExecutionConfig,
    *,
    started_at_ms: int,
    delay_ms: int = DELAY_MS,
    max_observation_lag_ms: int = MAX_DELAY_OBSERVATION_LAG_MS,
) -> DelayedEntryExecutionShadow:
    shadow = DelayedEntryExecutionShadow(
        execution_config,
        started_at_ms=started_at_ms,
        delay_ms=delay_ms,
        max_observation_lag_ms=max_observation_lag_ms,
    )
    if not path.exists():
        return shadow
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        shadow.restore_state(raw)
    except Exception as exc:
        shadow = DelayedEntryExecutionShadow(
            execution_config,
            started_at_ms=started_at_ms,
            delay_ms=delay_ms,
            max_observation_lag_ms=max_observation_lag_ms,
        )
        shadow.mark_state_restore_error(
            f"{type(exc).__name__}: {exc}"
        )
    return shadow


def _restore_drawdown_tracker(
    path: Path,
    *,
    started_at_ms: int,
) -> ContinuousPaperDrawdownTracker:
    tracker = ContinuousPaperDrawdownTracker(
        started_at_ms=started_at_ms,
    )
    if not path.exists():
        return tracker
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return ContinuousPaperDrawdownTracker.from_payload(raw)
    except Exception as exc:
        tracker.mark_state_restore_error(
            f"{type(exc).__name__}: {exc}"
        )
        return tracker


def _restore_entry_mid_markout_shadow(
    path: Path,
    *,
    started_at_ms: int,
) -> EntryMidMarkoutShadow:
    shadow = EntryMidMarkoutShadow(
        started_at_ms=started_at_ms,
    )
    if not path.exists():
        return shadow
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        shadow.restore_state(raw)
    except Exception as exc:
        shadow = EntryMidMarkoutShadow(
            started_at_ms=started_at_ms,
        )
        shadow.mark_state_restore_error(
            f"{type(exc).__name__}: {exc}"
        )
    return shadow


def _restore_prospective_entry_filter(
    path: Path,
    *,
    started_at_ms: int,
) -> tuple[ProspectiveEntryFilterState, str | None]:
    if not path.exists():
        return (
            ProspectiveEntryFilterState(
                started_at_ms=started_at_ms
            ),
            None,
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return ProspectiveEntryFilterState.from_payload(raw), None
    except Exception as exc:
        return (
            ProspectiveEntryFilterState(
                started_at_ms=started_at_ms
            ),
            f"{type(exc).__name__}: {exc}",
        )


def _restore_prospective_delayed_price_confirmation(
    path: Path,
    *,
    started_at_ms: int,
) -> tuple[
    ProspectiveDelayedPriceConfirmationState,
    str | None,
]:
    if not path.exists():
        return (
            ProspectiveDelayedPriceConfirmationState(
                started_at_ms=started_at_ms
            ),
            None,
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return (
            ProspectiveDelayedPriceConfirmationState.from_payload(
                raw
            ),
            None,
        )
    except Exception as exc:
        return (
            ProspectiveDelayedPriceConfirmationState(
                started_at_ms=started_at_ms
            ),
            f"{type(exc).__name__}: {exc}",
        )


def _restore_prospective_side_conditioned_delay(
    path: Path,
    *,
    started_at_ms: int,
) -> tuple[ProspectiveSideConditionedDelayState, str | None]:
    if not path.exists():
        return (
            ProspectiveSideConditionedDelayState(
                started_at_ms=started_at_ms
            ),
            None,
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return (
            ProspectiveSideConditionedDelayState.from_payload(raw),
            None,
        )
    except Exception as exc:
        return (
            ProspectiveSideConditionedDelayState(
                started_at_ms=started_at_ms
            ),
            f"{type(exc).__name__}: {exc}",
        )


def _restore_adaptive_delay_selector(
    path: Path,
    *,
    started_at_ms: int,
) -> tuple[AdaptiveDelaySelectorState, str | None]:
    if not path.exists():
        return (
            AdaptiveDelaySelectorState(
                started_at_ms=started_at_ms
            ),
            None,
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return AdaptiveDelaySelectorState.from_payload(raw), None
    except Exception as exc:
        return (
            AdaptiveDelaySelectorState(
                started_at_ms=started_at_ms
            ),
            f"{type(exc).__name__}: {exc}",
        )


def _restore_fill_aware_delay_selector(
    path: Path,
    *,
    started_at_ms: int,
) -> tuple[FillAwareDelaySelectorState, str | None]:
    if not path.exists():
        return (
            FillAwareDelaySelectorState(
                started_at_ms=started_at_ms
            ),
            None,
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return FillAwareDelaySelectorState.from_payload(raw), None
    except Exception as exc:
        return (
            FillAwareDelaySelectorState(
                started_at_ms=started_at_ms
            ),
            f"{type(exc).__name__}: {exc}",
        )


def _restore_delay_selector_comparison(
    path: Path,
    *,
    started_at_ms: int,
) -> tuple[DelaySelectorComparisonState, str | None]:
    if not path.exists():
        return (
            DelaySelectorComparisonState(
                started_at_ms=started_at_ms
            ),
            None,
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return DelaySelectorComparisonState.from_payload(raw), None
    except Exception as exc:
        return (
            DelaySelectorComparisonState(
                started_at_ms=started_at_ms
            ),
            f"{type(exc).__name__}: {exc}",
        )


def _restore_prospective_top10_rank_filter(
    path: Path,
    *,
    started_at_ms: int,
) -> tuple[ProspectiveTop10RankFilterState, str | None]:
    if not path.exists():
        return (
            ProspectiveTop10RankFilterState(
                started_at_ms=started_at_ms
            ),
            None,
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return (
            ProspectiveTop10RankFilterState.from_payload(raw),
            None,
        )
    except Exception as exc:
        return (
            ProspectiveTop10RankFilterState(
                started_at_ms=started_at_ms
            ),
            f"{type(exc).__name__}: {exc}",
        )


def _restore_prospective_replacement_exit_policy(
    path: Path,
    *,
    started_at_ms: int,
) -> tuple[ProspectiveReplacementExitPolicyState, str | None]:
    if not path.exists():
        return (
            ProspectiveReplacementExitPolicyState(
                started_at_ms=started_at_ms
            ),
            None,
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return (
            ProspectiveReplacementExitPolicyState.from_payload(raw),
            None,
        )
    except Exception as exc:
        return (
            ProspectiveReplacementExitPolicyState(
                started_at_ms=started_at_ms
            ),
            f"{type(exc).__name__}: {exc}",
        )


def _restore_prospective_trade_quality(
    path: Path,
    *,
    started_at_ms: int,
) -> tuple[ProspectiveTradeQualityState, str | None]:
    if not path.exists():
        return (
            ProspectiveTradeQualityState(started_at_ms=started_at_ms),
            None,
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return (
            ProspectiveTradeQualityState.from_payload(raw),
            None,
        )
    except Exception as exc:
        return (
            ProspectiveTradeQualityState(started_at_ms=started_at_ms),
            f"{type(exc).__name__}: {exc}",
        )


def _restore_prospective_combined_entry_filter(
    path: Path,
    *,
    started_at_ms: int,
) -> tuple[ProspectiveCombinedEntryFilterState, str | None]:
    if not path.exists():
        return (
            ProspectiveCombinedEntryFilterState(
                started_at_ms=started_at_ms
            ),
            None,
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return (
            ProspectiveCombinedEntryFilterState.from_payload(raw),
            None,
        )
    except Exception as exc:
        return (
            ProspectiveCombinedEntryFilterState(
                started_at_ms=started_at_ms
            ),
            f"{type(exc).__name__}: {exc}",
        )


def _prospective_combined_entry_filter_payload(
    journal: JournalStore,
    fact_store: EvaluationFactStore,
    opening_rank_store: ContinuousPaperOpeningRankStore,
    entry_filter_state: ProspectiveEntryFilterState,
    top10_rank_filter_state: ProspectiveTop10RankFilterState,
    state: ProspectiveCombinedEntryFilterState,
    *,
    restore_error: str | None,
) -> dict[str, object]:
    try:
        payload = evaluate_prospective_combined_entry_filter(
            journal,
            fact_store,
            opening_rank_store,
            state,
        )
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "candidate_id": state.candidate_id,
            "started_at_ms": state.started_at_ms,
            "state_restore_error": restore_error,
            "error": f"{type(exc).__name__}: {exc}",
        }

    try:
        matched_overlap = evaluate_prospective_combined_matched_overlap(
            journal,
            fact_store,
            opening_rank_store,
            entry_filter_state,
            top10_rank_filter_state,
        )
    except Exception as exc:
        matched_overlap = {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "descriptive_only": True,
            "changes_readiness_gate": False,
            "fresh_combined_gate_credit": 0,
            "error": f"{type(exc).__name__}: {exc}",
        }
    else:
        matched_overlap = dict(matched_overlap)
        matched_overlap["enabled"] = True
        matched_overlap["error"] = None

    payload = dict(payload)
    payload["matched_standalone_overlap"] = matched_overlap
    payload["enabled"] = True
    payload["state_restore_error"] = restore_error
    payload["error"] = None
    return payload


def _prospective_top10_rank_filter_payload(
    journal: JournalStore,
    opening_rank_store: ContinuousPaperOpeningRankStore,
    state: ProspectiveTop10RankFilterState,
    *,
    restore_error: str | None,
) -> dict[str, object]:
    try:
        payload = evaluate_prospective_top10_rank_filter(
            journal,
            opening_rank_store,
            state,
        )
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "candidate_id": state.candidate_id,
            "started_at_ms": state.started_at_ms,
            "state_restore_error": restore_error,
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = dict(payload)
    payload["enabled"] = True
    payload["state_restore_error"] = restore_error
    payload["error"] = None
    return payload


def _prospective_trade_quality_payload(
    journal: JournalStore,
    opening_rank_store: ContinuousPaperOpeningRankStore,
    delayed_shadow: _ContinuousDelayedEntryExecutionShadowSink,
    plan_loader: Callable[[str], PaperOrderPlan | None],
    state: ProspectiveTradeQualityState,
    *,
    restore_error: str | None,
) -> dict[str, object]:
    if delayed_shadow.shadow is None:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "candidate_id": state.candidate_id,
            "started_at_ms": state.started_at_ms,
            "state_restore_error": restore_error,
            "error": delayed_shadow.error,
        }
    try:
        payload = prospective_trade_quality_summary(
            tuple(journal.iter_trades()),
            opening_rank_store,
            delayed_shadow.shadow.outcomes,
            plan_loader,
            state,
        )
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "candidate_id": state.candidate_id,
            "started_at_ms": state.started_at_ms,
            "state_restore_error": restore_error,
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = dict(payload)
    payload["enabled"] = True
    payload["state_restore_error"] = restore_error
    payload["error"] = None
    return payload


def _prospective_delayed_price_confirmation_payload(
    journal: JournalStore,
    delayed_shadow: _ContinuousDelayedEntryExecutionShadowSink,
    plan_loader: Callable[[str], PaperOrderPlan | None],
    state: ProspectiveDelayedPriceConfirmationState,
    *,
    restore_error: str | None,
) -> dict[str, object]:
    if delayed_shadow.shadow is None:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "candidate_id": state.candidate_id,
            "started_at_ms": state.started_at_ms,
            "state_restore_error": restore_error,
            "error": delayed_shadow.error,
        }
    try:
        payload = prospective_delayed_price_confirmation_summary(
            journal,
            delayed_shadow.shadow.outcomes,
            plan_loader,
            state,
        )
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "candidate_id": state.candidate_id,
            "started_at_ms": state.started_at_ms,
            "state_restore_error": restore_error,
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = dict(payload)
    payload["enabled"] = True
    payload["state_restore_error"] = restore_error
    payload["error"] = None
    return payload


def _prospective_capacity_reflow_opportunity_payload(
    store: ContinuousPaperOpeningOpportunityStore,
    state: ProspectiveCombinedEntryFilterState,
) -> dict[str, object]:
    try:
        payload = evaluate_prospective_capacity_reflow_opportunities(
            store,
            state,
        )
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "candidate_id": state.candidate_id,
            "started_at_ms": state.started_at_ms,
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = dict(payload)
    payload["enabled"] = True
    payload["error"] = None
    return payload


def _prospective_capacity_reflow_fill_feasibility_payload(
    opportunity_store: ContinuousPaperOpeningOpportunityStore,
    lineage_store: ContinuousPaperOpeningLineageStore,
    journal: JournalStore,
    *,
    plan_loader: Callable[[str], PaperOrderPlan | None],
    fact_store: EvaluationFactStore,
    rank_store: ContinuousPaperOpeningRankStore,
    state: ProspectiveCombinedEntryFilterState,
    config: PaperExecutionConfig,
    position_history_loader: Callable[
        [str, int],
        tuple[PaperPosition, ...],
    ],
) -> dict[str, object]:
    try:
        payload = (
            evaluate_prospective_capacity_reflow_fill_feasibility(
                opportunity_store,
                lineage_store,
                journal,
                plan_loader=plan_loader,
                fact_store=fact_store,
                rank_store=rank_store,
                state=state,
                config=config,
                position_history_loader=position_history_loader,
            )
        )
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "candidate_id": state.candidate_id,
            "started_at_ms": state.started_at_ms,
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = dict(payload)
    payload["enabled"] = True
    payload["candidate_id"] = state.candidate_id
    payload["started_at_ms"] = state.started_at_ms
    payload["error"] = None
    return payload


def _prospective_capacity_reflow_exit_fill_payload(
    fill_feasibility: dict[str, object],
    exit_book_store: ContinuousPaperOpeningOpportunityExitBookStore,
    state: ProspectiveCombinedEntryFilterState,
    config: PaperExecutionConfig,
) -> dict[str, object]:
    try:
        payload = evaluate_prospective_capacity_reflow_exit_fill(
            fill_feasibility,
            exit_book_store,
            config,
        )
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "candidate_id": state.candidate_id,
            "started_at_ms": state.started_at_ms,
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = dict(payload)
    payload["enabled"] = True
    payload["candidate_id"] = state.candidate_id
    payload["started_at_ms"] = state.started_at_ms
    payload["error"] = None
    return payload


def _prospective_capacity_reflow_realized_pnl_payload(
    exit_fill: dict[str, object],
    funding_store: ContinuousPaperReplacementFundingStore,
    state: ProspectiveCombinedEntryFilterState,
) -> dict[str, object]:
    try:
        payload = evaluate_prospective_capacity_reflow_realized_pnl(
            exit_fill,
            funding_store,
        )
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "candidate_id": state.candidate_id,
            "started_at_ms": state.started_at_ms,
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = dict(payload)
    payload["enabled"] = True
    payload["candidate_id"] = state.candidate_id
    payload["started_at_ms"] = state.started_at_ms
    payload["error"] = None
    return payload


def _prospective_replacement_exit_policy_payload(
    realized_pnl: dict[str, object],
    state: ProspectiveReplacementExitPolicyState,
    *,
    restore_error: str | None,
) -> dict[str, object]:
    try:
        payload = prospective_replacement_exit_policy_summary(
            realized_pnl,
            state,
        )
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "candidate_id": state.candidate_id,
            "started_at_ms": state.started_at_ms,
            "exit_horizon_ms": state.exit_horizon_ms,
            "state_restore_error": restore_error,
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = dict(payload)
    payload["enabled"] = True
    payload["state_restore_error"] = restore_error
    payload["error"] = None
    return payload


def _prospective_replacement_exit_robustness_payload(
    policy: dict[str, object],
) -> dict[str, object]:
    try:
        payload = prospective_replacement_exit_robustness(policy)
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "candidate_id": policy.get("candidate_id"),
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = dict(payload)
    payload["enabled"] = True
    payload["error"] = None
    return payload


def _prospective_replacement_exit_readiness_payload(
    robustness: dict[str, object],
) -> dict[str, object]:
    try:
        payload = prospective_replacement_exit_readiness(
            robustness
        )
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "candidate_id": robustness.get("candidate_id"),
            "ready_for_review": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = dict(payload)
    payload["enabled"] = True
    payload["error"] = None
    return payload


def _prospective_capacity_reflow_forward_markout_payload(
    fill_feasibility: dict[str, object],
    path_store: ContinuousPaperOpeningOpportunityPathStore,
    state: ProspectiveCombinedEntryFilterState,
) -> dict[str, object]:
    try:
        payload = evaluate_prospective_capacity_reflow_forward_markout(
            fill_feasibility,
            path_store,
        )
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "candidate_id": state.candidate_id,
            "started_at_ms": state.started_at_ms,
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = dict(payload)
    payload["enabled"] = True
    payload["candidate_id"] = state.candidate_id
    payload["started_at_ms"] = state.started_at_ms
    payload["error"] = None
    return payload


def _prospective_capacity_reflow_forward_excursion_payload(
    forward_markout: dict[str, object],
    path_store: ContinuousPaperOpeningOpportunityPathStore,
    state: ProspectiveCombinedEntryFilterState,
) -> dict[str, object]:
    try:
        payload = evaluate_prospective_capacity_reflow_forward_excursion(
            forward_markout,
            path_store,
        )
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "candidate_id": state.candidate_id,
            "started_at_ms": state.started_at_ms,
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = dict(payload)
    payload["enabled"] = True
    payload["candidate_id"] = state.candidate_id
    payload["started_at_ms"] = state.started_at_ms
    payload["error"] = None
    return payload


def _prospective_capacity_reflow_release_lineage_payload(
    opportunity_store: ContinuousPaperOpeningOpportunityStore,
    lineage_store: ContinuousPaperOpeningLineageStore,
    journal: JournalStore,
    *,
    plan_loader: Callable[[str], PaperOrderPlan | None],
    fact_store: EvaluationFactStore,
    rank_store: ContinuousPaperOpeningRankStore,
    state: ProspectiveCombinedEntryFilterState,
) -> dict[str, object]:
    try:
        payload = evaluate_prospective_capacity_reflow_release_lineage(
            opportunity_store,
            lineage_store,
            journal,
            plan_loader=plan_loader,
            fact_store=fact_store,
            rank_store=rank_store,
            state=state,
        )
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "candidate_id": state.candidate_id,
            "started_at_ms": state.started_at_ms,
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = dict(payload)
    payload["enabled"] = True
    payload["error"] = None
    return payload


def _prospective_daily_loss_lockout_reflow_payload(
    opportunity_store: ContinuousPaperOpeningOpportunityStore,
    journal: JournalStore,
    fact_store: EvaluationFactStore,
    rank_store: ContinuousPaperOpeningRankStore,
    state: ProspectiveCombinedEntryFilterState,
    *,
    exit_fill_loader: Callable[[str], tuple[PaperFill, ...]],
    funding_loader: Callable[
        [MarketId, int],
        tuple[FundingAccrual, ...],
    ],
) -> dict[str, object]:
    try:
        payload = evaluate_prospective_daily_loss_lockout_reflow(
            opportunity_store,
            tuple(journal.iter_trades()),
            fact_store,
            rank_store,
            state,
            exit_fill_loader=exit_fill_loader,
            funding_loader=funding_loader,
        )
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "candidate_id": state.candidate_id,
            "started_at_ms": state.started_at_ms,
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = dict(payload)
    payload["enabled"] = True
    payload["error"] = None
    return payload


def _prospective_entry_filter_payload(
    journal: JournalStore,
    fact_store: EvaluationFactStore,
    state: ProspectiveEntryFilterState,
    *,
    restore_error: str | None,
) -> dict[str, object]:
    try:
        payload = evaluate_prospective_entry_filter(
            journal,
            fact_store,
            state,
        )
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "candidate_id": state.candidate_id,
            "started_at_ms": state.started_at_ms,
            "state_restore_error": restore_error,
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = dict(payload)
    payload["enabled"] = True
    payload["state_restore_error"] = restore_error
    payload["error"] = None
    return payload


def _native_market_snapshots(
    reader: InfoClient,
    *,
    received_at_ms: int,
) -> dict[str, PerpMarketSnapshot]:
    raw = reader.meta_and_asset_ctxs("")
    snapshots = normalize_meta_and_asset_ctxs("", raw, received_at_ms=received_at_ms)
    return {snapshot.meta.market.canonical: snapshot for snapshot in snapshots}


def _ranked_selection(
    snapshots: dict[str, PerpMarketSnapshot],
    *,
    as_of_ms: int,
    deep_limit: int,
    pinned: tuple[MarketId, ...],
) -> tuple[MarketId, ...]:
    _feature_map, ranks = _startup_ranks(snapshots, as_of_ms=as_of_ms)
    ranked = [rank.market for rank in ranks if rank.market.dex == ""]
    selected = ranked[:deep_limit]
    selected_by_key = {market.canonical: market for market in selected}
    for market in pinned:
        selected_by_key[market.canonical] = market
    return tuple(
        sorted(
            selected_by_key.values(),
            key=lambda market: (
                0 if market.canonical in {item.canonical for item in selected} else 1,
                selected.index(market) if market in selected else deep_limit,
                market.canonical,
            ),
        )
    )


async def _warmup_market(
    reader: InfoClient,
    market: MarketId,
    *,
    end_ms: int,
    config: ContinuousPaperConfig,
) -> tuple[Candle, ...]:
    output: list[Candle] = []
    for interval, bars in (
        ("5m", config.warmup_5m_bars),
        ("15m", config.warmup_15m_bars),
    ):
        start_ms = max(0, end_ms - INTERVAL_MS[interval] * (bars + 2))
        raw = await asyncio.to_thread(
            reader.candles,
            market,
            interval,
            start_ms=start_ms,
            end_ms=end_ms,
        )
        received_at_ms = utc_now_ms()
        output.extend(
            normalize_candles(
                market,
                raw,
                received_at_ms=received_at_ms,
            )
        )
    return tuple(output)


class _RecordPump:
    def __init__(
        self,
        pipeline: BaselineReplayPipeline,
        journal: JournalStore,
        *,
        last_available_at_ms: int,
        cadence_shadow: CadenceShadowComparator | None = None,
        entry_mid_markout_shadow: (
            _ContinuousEntryMidMarkoutSink | None
        ) = None,
        position_provider: (
            Callable[[], Sequence[PaperPosition]] | None
        ) = None,
    ) -> None:
        self.pipeline = pipeline
        self.journal = journal
        self.cadence_shadow = cadence_shadow
        self.cadence_shadow_error: str | None = None
        self.entry_mid_markout_shadow = (
            entry_mid_markout_shadow
        )
        self._position_provider = position_provider
        if (
            self.entry_mid_markout_shadow is not None
            and self._position_provider is None
        ):
            raise ValueError(
                "entry mid markout shadow requires position provider"
            )
        self.last_available_at_ms = last_available_at_ms
        self.processed_records = 0
        self.journal_observations = 0
        existing_trades = tuple(journal.iter_trades())
        self._known_trade_ids = {trade.trade_id for trade in existing_trades}
        self._recent_closed_trades: deque[TradeJournalEntry] = deque(
            existing_trades[-10:],
            maxlen=10,
        )
        self.closed_trades = len(self._known_trade_ids)
        self.session_closed_trades = 0
        self.last_observation: JournalObservation | None = None
        self._lock = asyncio.Lock()

    async def process(self, record: ReplayRecord) -> None:
        async with self._lock:
            available = max(self.last_available_at_ms, record.available_at_ms)
            if available != record.available_at_ms:
                record = ReplayRecord(
                    record_kind=record.record_kind,
                    available_at_ms=available,
                    source=record.source,
                    schema_version=record.schema_version,
                    market=record.market,
                    exchange_time_ms=record.exchange_time_ms,
                    event_key=record.event_key,
                    payload_json=record.payload_json,
                    event_kind=record.event_kind,
                )
            observations: tuple[JournalObservation, ...] = self.pipeline.on_record(
                record,
                available,
            )
            for observation in observations:
                self.journal.record_observation(observation)
            if observations:
                self.last_observation = observations[-1]
            if self.entry_mid_markout_shadow is not None:
                provider = self._position_provider
                if provider is None:
                    raise RuntimeError(
                        "entry mid markout position provider disappeared"
                    )
                self.entry_mid_markout_shadow.observe(
                    record,
                    provider(),
                    now_ms=available,
                )
            for trade in self.pipeline.finalize(available):
                if trade.trade_id in self._known_trade_ids:
                    continue
                self.journal.record_trade(trade)
                if self.entry_mid_markout_shadow is not None:
                    self.entry_mid_markout_shadow.record_closed_trade(
                        trade
                    )
                self._known_trade_ids.add(trade.trade_id)
                self._recent_closed_trades.append(trade)
                self.closed_trades += 1
                self.session_closed_trades += 1
            if self.cadence_shadow is not None:
                try:
                    self.cadence_shadow.observe(record, available)
                except Exception as exc:
                    self.cadence_shadow_error = (
                        f"{type(exc).__name__}: {exc}"
                    )
                    self.cadence_shadow = None
            self.last_available_at_ms = available
            self.processed_records += 1
            self.journal_observations += len(observations)

    @property
    def recent_closed_trades(self) -> tuple[TradeJournalEntry, ...]:
        return tuple(self._recent_closed_trades)

    def cadence_shadow_payload(self) -> dict[str, object]:
        if self.cadence_shadow_error is not None:
            return {
                "shadow_only": True,
                "execution_authority": False,
                "session_only": False,
                "durable_state": True,
                "enabled": False,
                "error": self.cadence_shadow_error,
            }
        if self.cadence_shadow is None:
            return {
                "shadow_only": True,
                "execution_authority": False,
                "session_only": False,
                "durable_state": True,
                "enabled": False,
                "error": None,
            }
        payload = dict(self.cadence_shadow.summary_payload())
        payload["enabled"] = True
        payload["error"] = None
        return payload


    def cadence_opportunity_learning_payload(self) -> dict[str, object]:
        if self.cadence_shadow_error is not None:
            return {
                "enabled": False,
                "research_only": True,
                "execution_authority": False,
                "promotion_authority": False,
                "error": self.cadence_shadow_error,
            }
        if self.cadence_shadow is None:
            return {
                "enabled": False,
                "research_only": True,
                "execution_authority": False,
                "promotion_authority": False,
                "error": None,
            }
        try:
            payload = evaluate_cadence_opportunity_learning(
                self.cadence_shadow.outcomes,
            )
        except Exception as exc:
            return {
                "enabled": False,
                "research_only": True,
                "execution_authority": False,
                "promotion_authority": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
        payload = dict(payload)
        payload["enabled"] = True
        payload["error"] = None
        return payload

    def reconcile_cadence_shadow(
        self,
        selected_markets: tuple[MarketId, ...],
    ) -> None:
        if self.cadence_shadow is None:
            return
        try:
            self.cadence_shadow.reconcile_markets(selected_markets)
        except Exception as exc:
            self.cadence_shadow_error = (
                f"{type(exc).__name__}: {exc}"
            )
            self.cadence_shadow = None


def _closed_trade_status_payload(trade: TradeJournalEntry) -> dict[str, object]:
    return {
        "trade_id": trade.trade_id,
        "market": trade.market.canonical,
        "direction": trade.direction.value,
        "opened_at_ms": trade.opened_at_ms,
        "closed_at_ms": trade.closed_at_ms,
        "holding_duration_ms": trade.holding_duration_ms,
        "entry_price": str(trade.entry_price),
        "exit_price": str(trade.exit_price),
        "filled_quantity": str(trade.filled_quantity),
        "initial_stop": str(trade.initial_stop),
        "initial_risk_amount": str(trade.initial_risk_amount),
        "gross_realized_pnl": str(trade.gross_realized_pnl),
        "entry_fees": str(trade.entry_fees),
        "exit_fees": str(trade.exit_fees),
        "funding_cash_pnl": str(trade.funding_cash_pnl),
        "net_pnl": str(trade.net_pnl),
        "net_r": str(trade.net_r),
        "mfe_r": (
            None
            if trade.mfe is None or trade.mfe.r_multiple is None
            else str(trade.mfe.r_multiple)
        ),
        "mae_r": (
            None
            if trade.mae is None or trade.mae.r_multiple is None
            else str(trade.mae.r_multiple)
        ),
        "excursion_complete": bool(
            trade.mfe is not None
            and trade.mae is not None
            and trade.mfe.complete
            and trade.mae.complete
            and trade.mfe.r_multiple is not None
            and trade.mae.r_multiple is not None
        ),
        "exit_reason": trade.exit_reason,
    }



def _closed_trade_performance(
    trades: tuple[TradeJournalEntry, ...],
    feature_store: LearningFeatureSnapshotStore,
    fact_store: EvaluationFactStore,
) -> dict[str, object]:
    def summarize(items: tuple[TradeJournalEntry, ...]) -> dict[str, object]:
        count = len(items)
        net_pnl = sum((trade.net_pnl for trade in items), Decimal("0"))
        net_r = sum((trade.net_r for trade in items), Decimal("0"))
        complete_excursions = tuple(
            trade
            for trade in items
            if trade.mfe is not None
            and trade.mae is not None
            and trade.mfe.complete
            and trade.mae.complete
            and trade.mfe.r_multiple is not None
            and trade.mae.r_multiple is not None
        )
        mfe_values = tuple(
            trade.mfe.r_multiple
            for trade in complete_excursions
            if trade.mfe is not None and trade.mfe.r_multiple is not None
        )
        mae_values = tuple(
            trade.mae.r_multiple
            for trade in complete_excursions
            if trade.mae is not None and trade.mae.r_multiple is not None
        )
        mfe_sum = sum(mfe_values, Decimal("0"))
        mae_sum = sum(mae_values, Decimal("0"))
        excursion_count = len(complete_excursions)
        giveback_values = tuple(
            max(
                Decimal("0"),
                trade.mfe.r_multiple - trade.net_r,
            )
            for trade in complete_excursions
            if trade.mfe is not None and trade.mfe.r_multiple is not None
        )
        reached_0_5r = tuple(
            trade
            for trade in complete_excursions
            if trade.mfe is not None
            and trade.mfe.r_multiple is not None
            and trade.mfe.r_multiple >= Decimal("0.5")
        )
        reached_1r = tuple(
            trade
            for trade in complete_excursions
            if trade.mfe is not None
            and trade.mfe.r_multiple is not None
            and trade.mfe.r_multiple >= Decimal("1")
        )

        def mean_giveback(
            reached: tuple[TradeJournalEntry, ...],
        ) -> str | None:
            if not reached:
                return None
            values = tuple(
                max(
                    Decimal("0"),
                    trade.mfe.r_multiple - trade.net_r,
                )
                for trade in reached
                if trade.mfe is not None and trade.mfe.r_multiple is not None
            )
            return str(sum(values, Decimal("0")) / len(values))

        def mean_final_net_r(
            reached: tuple[TradeJournalEntry, ...],
        ) -> str | None:
            if not reached:
                return None
            return str(
                sum((trade.net_r for trade in reached), Decimal("0"))
                / len(reached)
            )

        return {
            "trades": count,
            "wins": sum(1 for trade in items if trade.net_pnl > 0),
            "losses": sum(1 for trade in items if trade.net_pnl < 0),
            "breakeven": sum(1 for trade in items if trade.net_pnl == 0),
            "net_pnl": str(net_pnl),
            "mean_net_pnl": None if count == 0 else str(net_pnl / count),
            "mean_net_r": None if count == 0 else str(net_r / count),
            "average_holding_ms": (
                None
                if count == 0
                else sum(trade.holding_duration_ms for trade in items) // count
            ),
            "complete_excursion_trades": excursion_count,
            "incomplete_or_missing_excursion_trades": count - excursion_count,
            "mean_mfe_r": (
                None if excursion_count == 0 else str(mfe_sum / excursion_count)
            ),
            "mean_mae_r": (
                None if excursion_count == 0 else str(mae_sum / excursion_count)
            ),
            "mfe_ge_0_5r": sum(
                1
                for trade in complete_excursions
                if trade.mfe is not None
                and trade.mfe.r_multiple is not None
                and trade.mfe.r_multiple >= Decimal("0.5")
            ),
            "mfe_ge_1r": sum(
                1
                for trade in complete_excursions
                if trade.mfe is not None
                and trade.mfe.r_multiple is not None
                and trade.mfe.r_multiple >= Decimal("1")
            ),
            "losses_with_mfe_lt_0_25r": sum(
                1
                for trade in complete_excursions
                if trade.net_pnl < 0
                and trade.mfe is not None
                and trade.mfe.r_multiple is not None
                and trade.mfe.r_multiple < Decimal("0.25")
            ),
            "losses_after_mfe_ge_0_5r": sum(
                1
                for trade in complete_excursions
                if trade.net_pnl < 0
                and trade.mfe is not None
                and trade.mfe.r_multiple is not None
                and trade.mfe.r_multiple >= Decimal("0.5")
            ),
            "losses_after_mfe_ge_1r": sum(
                1
                for trade in complete_excursions
                if trade.net_pnl < 0
                and trade.mfe is not None
                and trade.mfe.r_multiple is not None
                and trade.mfe.r_multiple >= Decimal("1")
            ),
            "mean_peak_to_close_giveback_r": (
                None
                if excursion_count == 0
                else str(
                    sum(giveback_values, Decimal("0"))
                    / excursion_count
                )
            ),
            "mean_giveback_after_mfe_ge_0_5r": mean_giveback(
                reached_0_5r
            ),
            "mean_giveback_after_mfe_ge_1r": mean_giveback(reached_1r),
            "positive_closes_after_mfe_ge_0_5r": sum(
                1 for trade in reached_0_5r if trade.net_pnl > 0
            ),
            "positive_closes_after_mfe_ge_1r": sum(
                1 for trade in reached_1r if trade.net_pnl > 0
            ),
            "mean_final_net_r_after_mfe_ge_0_5r": mean_final_net_r(
                reached_0_5r
            ),
            "mean_final_net_r_after_mfe_ge_1r": mean_final_net_r(
                reached_1r
            ),
        }

    def grouped(
        labels: dict[str, list[TradeJournalEntry]],
    ) -> dict[str, dict[str, object]]:
        return {
            label: summarize(tuple(items))
            for label, items in sorted(labels.items())
        }

    gross_profit = sum(
        (trade.net_pnl for trade in trades if trade.net_pnl > 0),
        Decimal("0"),
    )
    gross_loss_abs = -sum(
        (trade.net_pnl for trade in trades if trade.net_pnl < 0),
        Decimal("0"),
    )
    profit_factor = (
        None
        if gross_loss_abs == 0
        else (
            "0"
            if gross_profit == 0
            else str(gross_profit / gross_loss_abs)
        )
    )

    def decision_score_band(score: Decimal) -> str:
        if score < Decimal("65"):
            return "<65"
        if score < Decimal("70"):
            return "65-<70"
        if score < Decimal("75"):
            return "70-<75"
        if score < Decimal("80"):
            return "75-<80"
        return "80+"

    by_side: dict[str, list[TradeJournalEntry]] = {}
    by_exit_reason: dict[str, list[TradeJournalEntry]] = {}
    by_lead_strategy: dict[str, list[TradeJournalEntry]] = {}
    by_decision_score_band: dict[str, list[TradeJournalEntry]] = {}
    by_trend_regime: dict[str, list[TradeJournalEntry]] = {}
    by_volatility_regime: dict[str, list[TradeJournalEntry]] = {}
    decision_fact_attributed_trades = 0
    decision_fact_attribution_misses = 0
    feature_snapshot_fallback_trades = 0
    regime_attribution_misses = 0

    for trade in trades:
        by_side.setdefault(trade.direction.value, []).append(trade)
        by_exit_reason.setdefault(trade.exit_reason, []).append(trade)

        lead_strategy = "unknown"
        score_band = "unknown"
        trend_regime = "unknown"
        volatility_regime = "unknown"
        decision_fact = None
        if trade.replay_run_id is not None:
            try:
                decision_fact = fact_store.load_decision_by_strategy_id(
                    trade.strategy_decision_id,
                    trade.replay_run_id,
                )
            except Exception:
                decision_fact = None

        if decision_fact is not None:
            decision_fact_attributed_trades += 1
            lead_strategy = decision_fact.lead_strategy or "unknown"
            score_band = decision_score_band(decision_fact.score)
            trend_regime = decision_fact.trend_regime.value
            volatility_regime = decision_fact.volatility_regime.value
        else:
            decision_fact_attribution_misses += 1
            try:
                verified = feature_store.load(trade.feature_snapshot_id)
                if verified is not None:
                    feature_snapshot_fallback_trades += 1
                    trend_regime = verified.snapshot.trend_regime.value
                    volatility_regime = verified.snapshot.volatility_regime.value
                else:
                    regime_attribution_misses += 1
            except Exception:
                regime_attribution_misses += 1

        by_lead_strategy.setdefault(lead_strategy, []).append(trade)
        by_decision_score_band.setdefault(score_band, []).append(trade)
        by_trend_regime.setdefault(trend_regime, []).append(trade)
        by_volatility_regime.setdefault(volatility_regime, []).append(trade)

    return {
        **summarize(trades),
        "gross_profit": str(gross_profit),
        "gross_loss_abs": str(gross_loss_abs),
        "profit_factor": profit_factor,
        "decision_fact_attributed_trades": decision_fact_attributed_trades,
        "decision_fact_attribution_misses": decision_fact_attribution_misses,
        "feature_snapshot_fallback_trades": feature_snapshot_fallback_trades,
        "regime_attribution_misses": regime_attribution_misses,
        "unattributed_feature_trades": regime_attribution_misses,
        "by_side": grouped(by_side),
        "by_exit_reason": grouped(by_exit_reason),
        "by_lead_strategy": grouped(by_lead_strategy),
        "by_decision_score_band": grouped(by_decision_score_band),
        "by_trend_regime": grouped(by_trend_regime),
        "by_volatility_regime": grouped(by_volatility_regime),
    }


def _position_protection_metrics(
    *,
    side: str,
    quantity: Decimal,
    entry_price: Decimal,
    stop_price: Decimal,
    latest_mark: Decimal | None,
    planned_risk: Decimal,
) -> dict[str, object]:
    if planned_risk < 0:
        raise ValueError("planned_risk must be non-negative")
    if side == "long":
        stop_pnl = (stop_price - entry_price) * quantity
        unrealized = (
            None
            if latest_mark is None
            else (latest_mark - entry_price) * quantity
        )
    elif side == "short":
        stop_pnl = (entry_price - stop_price) * quantity
        unrealized = (
            None
            if latest_mark is None
            else (entry_price - latest_mark) * quantity
        )
    else:
        raise ValueError("position side must be long or short")
    return {
        "unrealized_gross_pnl": (
            None if unrealized is None else str(unrealized)
        ),
        "current_gross_r": (
            None
            if unrealized is None or planned_risk == 0
            else str(unrealized / planned_risk)
        ),
        "stop_trigger_gross_pnl": str(stop_pnl),
        "stop_trigger_gross_r": (
            None if planned_risk == 0 else str(stop_pnl / planned_risk)
        ),
        "stop_protects_profit": stop_pnl > 0,
    }


def _account_lifecycle_bridge_payload(
    execution: PaperExecutionAdapter,
    journal: JournalStore,
) -> dict[str, object]:
    try:
        payload = account_lifecycle_bridge(
            execution.account,
            tuple(journal.iter_trades()),
        )
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = dict(payload)
    payload["enabled"] = True
    payload["error"] = None
    return payload


def _drawdown_payload(
    execution: PaperExecutionAdapter,
    journal: JournalStore,
    tracker: ContinuousPaperDrawdownTracker,
    *,
    checkpoint_seconds: int,
) -> dict[str, object]:
    try:
        payload = drawdown_summary(
            tracker,
            tuple(journal.iter_trades()),
            starting_equity=execution.account.starting_cash,
            checkpoint_seconds=checkpoint_seconds,
        )
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = dict(payload)
    payload["enabled"] = True
    payload["error"] = None
    return payload


def _entry_decision_age_payload(
    journal: JournalStore,
    fact_store: EvaluationFactStore,
) -> dict[str, object]:
    try:
        payload = entry_decision_age_summary(
            journal,
            fact_store,
        )
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = dict(payload)
    payload["enabled"] = True
    payload["error"] = None
    return payload


def _closed_trade_robustness_payload(
    journal: JournalStore,
) -> dict[str, object]:
    try:
        payload = closed_trade_robustness(
            tuple(journal.iter_trades())
        )
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = dict(payload)
    payload["enabled"] = True
    payload["error"] = None
    return payload


def _closed_trade_stability_payload(
    journal: JournalStore,
) -> dict[str, object]:
    try:
        payload = closed_trade_stability(
            tuple(journal.iter_trades())
        )
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = dict(payload)
    payload["enabled"] = True
    payload["error"] = None
    return payload


def _closed_trade_concentration_payload(
    journal: JournalStore,
    fact_store: EvaluationFactStore,
) -> dict[str, object]:
    try:
        payload = closed_trade_concentration_summary(
            tuple(journal.iter_trades()),
            fact_store,
        )
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = dict(payload)
    payload["enabled"] = True
    payload["error"] = None
    return payload


def _closed_trade_utc_hour_payload(
    journal: JournalStore,
    fact_store: EvaluationFactStore,
) -> dict[str, object]:
    try:
        payload = closed_trade_utc_hour_summary(
            tuple(journal.iter_trades()),
            fact_store,
        )
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = dict(payload)
    payload["enabled"] = True
    payload["error"] = None
    return payload


def _closed_trade_friction_payload(
    journal: JournalStore,
    fact_store: EvaluationFactStore,
) -> dict[str, object]:
    try:
        payload = closed_trade_friction_summary(
            tuple(journal.iter_trades()),
            fact_store,
        )
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = dict(payload)
    payload["enabled"] = True
    payload["error"] = None
    return payload


def _profit_lock_counterfactual_payload(
    journal: JournalStore,
    trade_path_store: ContinuousPaperTradePathStore,
) -> dict[str, object]:
    try:
        study = evaluate_profit_lock_state(journal, trade_path_store)
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": f"{type(exc).__name__}: {exc}",
        }

    readiness = profit_lock_readiness(study)
    readiness_by_rule = {
        rule.rule_id: rule
        for rule in readiness.rules
    }

    return {
        "enabled": True,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "error": None,
        "evidence_class": study.evidence_class,
        "readiness": {
            "all_rules_ready_for_review": (
                readiness.all_rules_ready_for_review
            ),
            "min_complete_paths": MIN_COMPLETE_PATHS,
            "min_activated_trades_per_rule": (
                MIN_ACTIVATED_TRADES_PER_RULE
            ),
            "min_triggered_trades_per_rule": (
                MIN_TRIGGERED_TRADES_PER_RULE
            ),
        },
        "fill_model": study.fill_model,
        "path_record_count": study.path_record_count,
        "evaluated_trade_count": study.evaluated_trade_count,
        "skipped_incomplete_paths": study.skipped_incomplete_paths,
        "rules": [
            {
                "rule_id": rule.rule_id,
                "activate_at_r": str(rule.activate_at_r),
                "lock_at_r": str(rule.lock_at_r),
                "evaluated_trades": rule.evaluated_trades,
                "activated_trades": rule.activated_trades,
                "triggered_trades": rule.triggered_trades,
                "actual_positive_trades": rule.actual_positive_trades,
                "candidate_positive_trades_estimate": (
                    rule.candidate_positive_trades_estimate
                ),
                "actual_net_pnl": str(rule.actual_net_pnl),
                "candidate_net_pnl_estimate": str(
                    rule.candidate_net_pnl_estimate
                ),
                "delta_net_pnl_estimate": str(rule.delta_net_pnl_estimate),
                "actual_mean_net_r": (
                    None
                    if rule.actual_mean_net_r is None
                    else str(rule.actual_mean_net_r)
                ),
                "candidate_mean_net_r_estimate": (
                    None
                    if rule.candidate_mean_net_r_estimate is None
                    else str(rule.candidate_mean_net_r_estimate)
                ),
                "delta_mean_net_r_estimate": (
                    None
                    if rule.delta_mean_net_r_estimate is None
                    else str(rule.delta_mean_net_r_estimate)
                ),
                "readiness_status": (
                    readiness_by_rule[rule.rule_id].status.value
                ),
                "missing_complete_paths": (
                    readiness_by_rule[rule.rule_id].missing_complete_paths
                ),
                "missing_activated_trades": (
                    readiness_by_rule[rule.rule_id].missing_activated_trades
                ),
                "missing_triggered_trades": (
                    readiness_by_rule[rule.rule_id].missing_triggered_trades
                ),
            }
            for rule in study.rules
        ],
    }


def _delayed_entry_fill_capacity_payload(
    journal: JournalStore,
    delayed_shadow: _ContinuousDelayedEntryExecutionShadowSink,
) -> dict[str, object]:
    if delayed_shadow.shadow is None:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": delayed_shadow.error,
        }
    try:
        payload = delayed_entry_fill_capacity_summary(
            journal,
            delayed_shadow.shadow.outcomes,
        )
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = dict(payload)
    payload["open_attempts"] = (
        delayed_shadow.shadow.open_attempt_capacity_payload()
    )
    payload["enabled"] = True
    payload["error"] = None
    return payload


def _delayed_entry_contribution_decomposition_payload(
    journal: JournalStore,
    delayed_shadow: _ContinuousDelayedEntryExecutionShadowSink,
) -> dict[str, object]:
    if delayed_shadow.shadow is None:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": delayed_shadow.error,
        }
    try:
        payload = delayed_entry_contribution_decomposition(
            journal,
            delayed_shadow.shadow.outcomes,
        )
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = dict(payload)
    payload["enabled"] = True
    payload["error"] = None
    return payload


def _delayed_entry_contribution_decomposition_funding_payload(
    journal: JournalStore,
    delayed_shadow: _ContinuousDelayedEntryExecutionShadowSink,
    funding_loader: Callable[
        [MarketId, int],
        tuple[FundingAccrual, ...],
    ],
) -> dict[str, object]:
    if delayed_shadow.shadow is None:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": delayed_shadow.error,
        }
    try:
        payload = delayed_entry_funding_decomposition(
            journal,
            delayed_shadow.shadow.outcomes,
            funding_loader,
        )
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = dict(payload)
    payload["enabled"] = True
    payload["error"] = None
    return payload


def _delayed_entry_risk_geometry_payload(
    journal: JournalStore,
    delayed_shadow: _ContinuousDelayedEntryExecutionShadowSink,
    plan_loader: Callable[[str], PaperOrderPlan | None],
) -> dict[str, object]:
    if delayed_shadow.shadow is None:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": delayed_shadow.error,
        }
    try:
        payload = delayed_entry_risk_geometry_summary(
            journal,
            delayed_shadow.shadow.outcomes,
            plan_loader,
        )
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = dict(payload)
    payload["enabled"] = True
    payload["error"] = None
    return payload


def _delayed_entry_fill_weighted_payload(
    journal: JournalStore,
    delayed_shadow: _ContinuousDelayedEntryExecutionShadowSink,
) -> dict[str, object]:
    if delayed_shadow.shadow is None:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": delayed_shadow.error,
        }
    try:
        payload = delayed_entry_fill_weighted_contribution(
            journal,
            delayed_shadow.shadow.outcomes,
        )
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = dict(payload)
    payload["enabled"] = True
    payload["error"] = None
    return payload


def _delayed_entry_fill_weighted_funding_payload(
    journal: JournalStore,
    delayed_shadow: _ContinuousDelayedEntryExecutionShadowSink,
    funding_loader: Callable[
        [MarketId, int],
        tuple[FundingAccrual, ...],
    ],
) -> dict[str, object]:
    if delayed_shadow.shadow is None:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": delayed_shadow.error,
        }
    try:
        payload = delayed_entry_funding_corrected_fill_weighted(
            journal,
            delayed_shadow.shadow.outcomes,
            funding_loader,
        )
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = dict(payload)
    payload["enabled"] = True
    payload["error"] = None
    return payload


def _delayed_entry_fixed_schedule_portfolio_payload(
    journal: JournalStore,
    delayed_shadow: _ContinuousDelayedEntryExecutionShadowSink,
    plan_loader: Callable[[str], PaperOrderPlan | None],
) -> dict[str, object]:
    if delayed_shadow.shadow is None:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": delayed_shadow.error,
        }
    try:
        payload = delayed_entry_fixed_schedule_portfolio(
            journal,
            delayed_shadow.shadow.outcomes,
            plan_loader,
        )
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = dict(payload)
    payload["enabled"] = True
    payload["error"] = None
    return payload


def _delayed_entry_mtm_portfolio_payload(
    journal: JournalStore,
    delayed_shadow: _ContinuousDelayedEntryExecutionShadowSink,
    trade_path_store: ContinuousPaperTradePathStore,
    funding_loader: Callable[
        [MarketId, int],
        tuple[FundingAccrual, ...],
    ],
) -> dict[str, object]:
    if delayed_shadow.shadow is None:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": delayed_shadow.error,
        }
    try:
        payload = delayed_entry_mtm_portfolio(
            journal,
            delayed_shadow.shadow.outcomes,
            trade_path_store,
            funding_loader,
        )
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = dict(payload)
    payload["enabled"] = True
    payload["error"] = None
    return payload


def _delayed_entry_same_exit_stop_validity_payload(
    journal: JournalStore,
    delayed_shadow: _ContinuousDelayedEntryExecutionShadowSink,
    trade_path_store: ContinuousPaperTradePathStore,
    funding_loader: Callable[
        [MarketId, int],
        tuple[FundingAccrual, ...],
    ],
) -> dict[str, object]:
    if delayed_shadow.shadow is None:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": delayed_shadow.error,
        }
    try:
        payload = delayed_entry_same_exit_stop_validity(
            journal,
            delayed_shadow.shadow.outcomes,
            trade_path_store,
            funding_loader,
        )
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = dict(payload)
    payload["enabled"] = True
    payload["error"] = None
    return payload


def _delayed_entry_stop_exit_proxy_payload(
    journal: JournalStore,
    delayed_shadow: _ContinuousDelayedEntryExecutionShadowSink,
    trade_path_store: ContinuousPaperTradePathStore,
    funding_loader: Callable[
        [MarketId, int],
        tuple[FundingAccrual, ...],
    ],
    execution_config: PaperExecutionConfig,
) -> dict[str, object]:
    if delayed_shadow.shadow is None:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": delayed_shadow.error,
        }
    try:
        payload = delayed_entry_stop_exit_proxy_range(
            journal,
            delayed_shadow.shadow.outcomes,
            trade_path_store,
            funding_loader,
            execution_config,
        )
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = dict(payload)
    payload["enabled"] = True
    payload["error"] = None
    return payload


def _delayed_entry_stop_l2_replay_payload(
    journal: JournalStore,
    delayed_shadow: _ContinuousDelayedEntryExecutionShadowSink,
    trade_path_store: ContinuousPaperTradePathStore,
    stop_book_store: OriginalStopBookEvidenceStore,
    funding_loader: Callable[
        [MarketId, int],
        tuple[FundingAccrual, ...],
    ],
    execution_config: PaperExecutionConfig,
    *,
    capture_error: str | None,
) -> dict[str, object]:
    if delayed_shadow.shadow is None:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "capture_error": capture_error,
            "error": delayed_shadow.error,
        }
    try:
        payload = delayed_entry_stop_l2_replay(
            journal,
            delayed_shadow.shadow.outcomes,
            trade_path_store,
            stop_book_store,
            funding_loader,
            execution_config,
            capture_error=capture_error,
        )
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "capture_error": capture_error,
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = dict(payload)
    payload["enabled"] = True
    payload["capture_error"] = capture_error
    payload["error"] = None
    return payload


def _delayed_entry_stop_survivability_payload(
    journal: JournalStore,
    delayed_shadow: _ContinuousDelayedEntryExecutionShadowSink,
    trade_path_store: ContinuousPaperTradePathStore,
) -> dict[str, object]:
    if delayed_shadow.shadow is None:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": delayed_shadow.error,
        }
    try:
        payload = delayed_entry_stop_survivability(
            journal,
            delayed_shadow.shadow.outcomes,
            trade_path_store,
        )
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = dict(payload)
    payload["enabled"] = True
    payload["error"] = None
    return payload


def _delayed_entry_portfolio_capacity_payload(
    journal: JournalStore,
    delayed_shadow: _ContinuousDelayedEntryExecutionShadowSink,
    trade_path_store: ContinuousPaperTradePathStore,
    opening_fill_liquidity_store: OpeningFillLiquidityStore,
    plan_loader: Callable[[str], PaperOrderPlan | None],
    funding_loader: Callable[
        [MarketId, int],
        tuple[FundingAccrual, ...],
    ],
    limits: RiskLimits,
    paper_max_gross_leverage: Decimal,
    native_perp_min_notional: Decimal,
) -> dict[str, object]:
    if delayed_shadow.shadow is None:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": delayed_shadow.error,
        }
    try:
        payload = delayed_entry_portfolio_capacity_overlay(
            journal,
            delayed_shadow.shadow.outcomes,
            trade_path_store,
            plan_loader,
            opening_fill_liquidity_store.load,
            funding_loader,
            limits=limits,
            paper_max_gross_leverage=paper_max_gross_leverage,
            native_perp_min_notional=native_perp_min_notional,
        )
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = dict(payload)
    payload["enabled"] = True
    payload["error"] = None
    return payload


def _delayed_entry_same_exit_payload(
    journal: JournalStore,
    delayed_shadow: _ContinuousDelayedEntryExecutionShadowSink,
) -> dict[str, object]:
    if delayed_shadow.shadow is None:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": delayed_shadow.error,
        }
    try:
        payload = delayed_entry_same_exit_contribution(
            journal,
            delayed_shadow.shadow.outcomes,
        )
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = dict(payload)
    payload["enabled"] = True
    payload["error"] = None
    return payload


def _delayed_entry_pair_payload(
    journal: JournalStore,
    base_shadow: _ContinuousDelayedEntryExecutionShadowSink,
    challenger_shadow: _ContinuousDelayedEntryExecutionShadowSink,
) -> dict[str, object]:
    if base_shadow.shadow is None or challenger_shadow.shadow is None:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "base_error": base_shadow.error,
            "challenger_error": challenger_shadow.error,
            "error": "delayed-entry pair requires both shadows",
        }
    try:
        challenger_summary = challenger_shadow.shadow.summary_payload()
        raw_started_at_ms = challenger_summary.get("started_at_ms")
        if (
            isinstance(raw_started_at_ms, bool)
            or not isinstance(raw_started_at_ms, int)
        ):
            raise ValueError(
                "challenger delayed-entry start must be an integer"
            )
        started_at_ms = raw_started_at_ms
        payload = delayed_entry_pair_summary(
            journal,
            base_shadow.shadow.outcomes,
            challenger_shadow.shadow.outcomes,
            started_at_ms=started_at_ms,
        )
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "base_error": base_shadow.error,
            "challenger_error": challenger_shadow.error,
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = dict(payload)
    payload["enabled"] = True
    payload["base_error"] = base_shadow.error
    payload["challenger_error"] = challenger_shadow.error
    payload["error"] = None
    return payload


def _delayed_entry_pair_fill_weighted_payload(
    journal: JournalStore,
    base_shadow: _ContinuousDelayedEntryExecutionShadowSink,
    challenger_shadow: _ContinuousDelayedEntryExecutionShadowSink,
) -> dict[str, object]:
    if base_shadow.shadow is None or challenger_shadow.shadow is None:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "base_error": base_shadow.error,
            "challenger_error": challenger_shadow.error,
            "error": "fill-weighted delayed-entry pair requires both shadows",
        }
    try:
        challenger_summary = challenger_shadow.shadow.summary_payload()
        raw_started_at_ms = challenger_summary.get("started_at_ms")
        if (
            isinstance(raw_started_at_ms, bool)
            or not isinstance(raw_started_at_ms, int)
        ):
            raise ValueError(
                "challenger delayed-entry start must be an integer"
            )
        payload = delayed_entry_pair_fill_weighted_summary(
            journal,
            base_shadow.shadow.outcomes,
            challenger_shadow.shadow.outcomes,
            started_at_ms=raw_started_at_ms,
        )
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "base_error": base_shadow.error,
            "challenger_error": challenger_shadow.error,
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = dict(payload)
    payload["enabled"] = True
    payload["base_error"] = base_shadow.error
    payload["challenger_error"] = challenger_shadow.error
    payload["error"] = None
    return payload


def _adaptive_delay_selector_payload(
    journal: JournalStore,
    mid_shadow: _ContinuousEntryMidMarkoutSink,
    base_shadow: _ContinuousDelayedEntryExecutionShadowSink,
    challenger_shadow: _ContinuousDelayedEntryExecutionShadowSink,
    state: AdaptiveDelaySelectorState,
    *,
    restore_error: str | None,
) -> dict[str, object]:
    if (
        mid_shadow.shadow is None
        or base_shadow.shadow is None
        or challenger_shadow.shadow is None
    ):
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "candidate_id": state.candidate_id,
            "started_at_ms": state.started_at_ms,
            "state_restore_error": restore_error,
            "error": "adaptive delay requires all three research streams",
        }
    try:
        payload = adaptive_delay_selector_summary(
            journal,
            mid_shadow.shadow.outcomes,
            base_shadow.shadow.outcomes,
            challenger_shadow.shadow.outcomes,
            started_at_ms=state.started_at_ms,
        )
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "candidate_id": state.candidate_id,
            "started_at_ms": state.started_at_ms,
            "state_restore_error": restore_error,
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = dict(payload)
    payload["enabled"] = True
    payload["state_restore_error"] = restore_error
    payload["error"] = None
    return payload


def _fill_aware_delay_selector_payload(
    journal: JournalStore,
    base_shadow: _ContinuousDelayedEntryExecutionShadowSink,
    challenger_shadow: _ContinuousDelayedEntryExecutionShadowSink,
    state: FillAwareDelaySelectorState,
    *,
    restore_error: str | None,
) -> dict[str, object]:
    if base_shadow.shadow is None or challenger_shadow.shadow is None:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "candidate_id": state.candidate_id,
            "started_at_ms": state.started_at_ms,
            "state_restore_error": restore_error,
            "error": "fill-aware delay requires both delayed-entry shadows",
        }
    try:
        payload = fill_aware_delay_selector_summary(
            journal,
            base_shadow.shadow.outcomes,
            challenger_shadow.shadow.outcomes,
            started_at_ms=state.started_at_ms,
        )
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "candidate_id": state.candidate_id,
            "started_at_ms": state.started_at_ms,
            "state_restore_error": restore_error,
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = dict(payload)
    payload["enabled"] = True
    payload["state_restore_error"] = restore_error
    payload["error"] = None
    return payload


def _delay_selector_comparison_payload(
    journal: JournalStore,
    mid_shadow: _ContinuousEntryMidMarkoutSink,
    base_shadow: _ContinuousDelayedEntryExecutionShadowSink,
    challenger_shadow: _ContinuousDelayedEntryExecutionShadowSink,
    state: DelaySelectorComparisonState,
    *,
    restore_error: str | None,
) -> dict[str, object]:
    if (
        mid_shadow.shadow is None
        or base_shadow.shadow is None
        or challenger_shadow.shadow is None
    ):
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "candidate_id": state.candidate_id,
            "started_at_ms": state.started_at_ms,
            "state_restore_error": restore_error,
            "error": (
                "delay selector comparison requires all three "
                "research streams"
            ),
        }
    try:
        payload = delay_selector_comparison_summary(
            journal,
            mid_shadow.shadow.outcomes,
            base_shadow.shadow.outcomes,
            challenger_shadow.shadow.outcomes,
            started_at_ms=state.started_at_ms,
        )
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "candidate_id": state.candidate_id,
            "started_at_ms": state.started_at_ms,
            "state_restore_error": restore_error,
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = dict(payload)
    payload["enabled"] = True
    payload["state_restore_error"] = restore_error
    payload["error"] = None
    return payload


def _opening_rank_attribution_payload(
    journal: JournalStore,
    rank_store: ContinuousPaperOpeningRankStore,
    *,
    capture_error: str | None,
) -> dict[str, object]:
    try:
        payload = opening_rank_attribution(
            tuple(journal.iter_trades()),
            rank_store,
        )
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "capture_error": capture_error,
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = dict(payload)
    payload["enabled"] = True
    payload["capture_error"] = capture_error
    payload["error"] = None
    return payload


def _opening_fill_liquidity_payload(
    journal: JournalStore,
    store: OpeningFillLiquidityStore,
    *,
    capture_error: str | None,
) -> dict[str, object]:
    try:
        payload = opening_fill_liquidity_attribution(
            tuple(journal.iter_trades()),
            store,
        )
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "capture_error": capture_error,
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = dict(payload)
    payload["enabled"] = True
    payload["capture_error"] = capture_error
    payload["error"] = None
    return payload


def _entry_markout_predictiveness_payload(
    journal: JournalStore,
    trade_path_store: ContinuousPaperTradePathStore,
) -> dict[str, object]:
    try:
        payload = entry_markout_predictiveness(
            journal,
            trade_path_store,
        )
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = dict(payload)
    payload["enabled"] = True
    payload["error"] = None
    return payload


def _entry_markout_payload(
    journal: JournalStore,
    fact_store: EvaluationFactStore,
    trade_path_store: ContinuousPaperTradePathStore,
    opening_rank_store: ContinuousPaperOpeningRankStore | None = None,
) -> dict[str, object]:
    try:
        payload = entry_markout_summary(
            journal,
            fact_store,
            trade_path_store,
            opening_rank_store,
        )
        readiness = entry_markout_readiness(payload)
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = dict(payload)
    raw_horizons = payload.get("by_horizon_ms")
    if not isinstance(raw_horizons, dict):
        raise RuntimeError("entry markout horizons disappeared")
    readiness_by_horizon = {
        str(item.horizon_ms): item
        for item in readiness.horizons
    }
    for horizon_ms, raw in raw_horizons.items():
        if not isinstance(raw, dict):
            raise RuntimeError(
                "entry markout horizon summary must be an object"
            )
        horizon_readiness = readiness_by_horizon.get(horizon_ms)
        if horizon_readiness is None:
            raise RuntimeError(
                "entry markout readiness horizon mismatch"
            )
        raw["readiness_status"] = (
            horizon_readiness.status.value
        )
        raw["missing_observations"] = (
            horizon_readiness.missing_observations
        )
    payload["readiness"] = {
        "all_horizons_ready_for_review": (
            readiness.all_horizons_ready_for_review
        ),
        "min_observations_per_horizon": (
            MIN_OBSERVATIONS_PER_HORIZON
        ),
        "promotion_authority": readiness.promotion_authority,
        "execution_authority": readiness.execution_authority,
    }
    payload["enabled"] = True
    payload["error"] = None
    return payload


def _excursion_timing_payload(
    journal: JournalStore,
    fact_store: EvaluationFactStore,
    trade_path_store: ContinuousPaperTradePathStore,
) -> dict[str, object]:
    try:
        payload = excursion_timing_summary(
            journal,
            fact_store,
            trade_path_store,
        )
    except Exception as exc:
        return {
            "enabled": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = dict(payload)
    payload["enabled"] = True
    payload["error"] = None
    return payload


def _live_status_payload(
    execution: PaperExecutionAdapter,
    pump: _RecordPump,
    selected_markets: tuple[MarketId, ...],
    feature_store: LearningFeatureSnapshotStore,
    fact_store: EvaluationFactStore,
    opening_lineage_store: ContinuousPaperOpeningLineageStore,
    trade_path_store: ContinuousPaperTradePathStore,
    opening_rank_store: ContinuousPaperOpeningRankStore,
    opening_fill_liquidity_store: OpeningFillLiquidityStore,
    opening_opportunity_store: ContinuousPaperOpeningOpportunityStore,
    opening_opportunity_path_store: (
        ContinuousPaperOpeningOpportunityPathStore
    ),
    opening_opportunity_exit_book_store: (
        ContinuousPaperOpeningOpportunityExitBookStore
    ),
    replacement_funding_store: ContinuousPaperReplacementFundingStore,
    original_stop_book_store: OriginalStopBookEvidenceStore,
    original_stop_book_capture: OriginalStopBookCapture,
    profit_lock_execution_shadow: _ContinuousProfitLockExecutionShadowSink,
    delayed_entry_execution_shadow: _ContinuousDelayedEntryExecutionShadowSink,
    delayed_entry_120s_execution_shadow: _ContinuousDelayedEntryExecutionShadowSink,
    entry_mid_markout_shadow: _ContinuousEntryMidMarkoutSink,
    drawdown_tracker: ContinuousPaperDrawdownTracker,
    prospective_entry_filter_state: ProspectiveEntryFilterState,
    prospective_delayed_price_confirmation_state: (
        ProspectiveDelayedPriceConfirmationState
    ),
    prospective_top10_rank_filter_state: ProspectiveTop10RankFilterState,
    prospective_trade_quality_state: ProspectiveTradeQualityState,
    prospective_combined_entry_filter_state: ProspectiveCombinedEntryFilterState,
    prospective_replacement_exit_policy_state: (
        ProspectiveReplacementExitPolicyState
    ),
    adaptive_delay_selector_state: AdaptiveDelaySelectorState,
    fill_aware_delay_selector_state: FillAwareDelaySelectorState,
    delay_selector_comparison_state: DelaySelectorComparisonState,
    *,
    trade_path_capture_error: str | None,
    opening_rank_capture_error: str | None,
    opening_fill_liquidity_capture_error: str | None,
    opening_opportunity_capture_error: str | None,
    opening_opportunity_path_capture_error: str | None,
    opening_opportunity_exit_book_capture_error: str | None,
    replacement_funding_capture_error: str | None,
    prospective_entry_filter_restore_error: str | None,
    prospective_delayed_price_confirmation_restore_error: str | None,
    prospective_top10_rank_filter_restore_error: str | None,
    prospective_trade_quality_restore_error: str | None,
    prospective_combined_entry_filter_restore_error: str | None,
    prospective_replacement_exit_policy_restore_error: str | None,
    adaptive_delay_selector_restore_error: str | None,
    fill_aware_delay_selector_restore_error: str | None,
    delay_selector_comparison_restore_error: str | None,
    risk_limits: RiskLimits,
    paper_max_gross_leverage: Decimal,
    native_perp_min_notional: Decimal,
    paper_execution_config: PaperExecutionConfig,
    checkpoint_seconds: int,
    timestamp_ms: int,
) -> dict[str, object]:
    positions: list[dict[str, object]] = []
    for position in execution.account.positions:
        latest_mark = position.latest_mark
        protection = _position_protection_metrics(
            side=position.side.value,
            quantity=position.quantity,
            entry_price=position.average_entry_price,
            stop_price=position.stop_price,
            latest_mark=latest_mark,
            planned_risk=position.planned_risk,
        )
        positions.append(
            {
                "market": position.market.canonical,
                "side": position.side.value,
                "quantity": str(position.quantity),
                "average_entry_price": str(position.average_entry_price),
                "stop_price": str(position.stop_price),
                "latest_mark": (
                    None if latest_mark is None else str(latest_mark)
                ),
                **protection,
                "planned_risk": str(position.planned_risk),
                "opened_at_ms": position.opened_at_ms,
                "opening_plan_id": position.opening_plan_id,
            }
        )
    open_planned_risk = sum(
        (position.planned_risk for position in execution.account.positions),
        Decimal("0"),
    )
    open_planned_risk_fraction = (
        Decimal("0")
        if execution.account.equity == 0
        else open_planned_risk / execution.account.equity
    )
    open_stop_trigger_gross_pnl = sum(
        (
            Decimal(str(position["stop_trigger_gross_pnl"]))
            for position in positions
        ),
        Decimal("0"),
    )
    open_stop_trigger_gross_r = (
        None
        if open_planned_risk == 0
        else open_stop_trigger_gross_pnl / open_planned_risk
    )
    protected_stop_count = sum(
        1
        for position in positions
        if position["stop_protects_profit"] is True
    )
    total_account_pnl = execution.account.equity - execution.account.starting_cash
    total_return_fraction = (
        Decimal("0")
        if execution.account.starting_cash == 0
        else total_account_pnl / execution.account.starting_cash
    )
    gross_open_notional_fraction = (
        Decimal("0")
        if execution.account.equity == 0
        else execution.account.gross_open_notional / execution.account.equity
    )
    closed_trade_performance = _closed_trade_performance(
        tuple(pump.journal.iter_trades()),
        feature_store,
        fact_store,
    )
    account_lifecycle_economics = _account_lifecycle_bridge_payload(
        execution,
        pump.journal,
    )
    closed_trade_concentration = (
        _closed_trade_concentration_payload(
            pump.journal,
            fact_store,
        )
    )
    closed_trade_utc_hour = _closed_trade_utc_hour_payload(
        pump.journal,
        fact_store,
    )
    closed_trade_friction = _closed_trade_friction_payload(
        pump.journal,
        fact_store,
    )
    closed_trade_robustness_payload = (
        _closed_trade_robustness_payload(
            pump.journal,
        )
    )
    closed_trade_stability_payload = (
        _closed_trade_stability_payload(
            pump.journal,
        )
    )
    entry_decision_age = _entry_decision_age_payload(
        pump.journal,
        fact_store,
    )
    drawdown = _drawdown_payload(
        execution,
        pump.journal,
        drawdown_tracker,
        checkpoint_seconds=checkpoint_seconds,
    )
    activity = pump.pipeline.session_decision_activity
    decision_reason_counts = dict(activity.decision_reason_counts)
    risk_reason_counts = dict(activity.risk_reason_counts)
    profit_lock_counterfactual = _profit_lock_counterfactual_payload(
        pump.journal,
        trade_path_store,
    )
    prospective_entry_filter = _prospective_entry_filter_payload(
        pump.journal,
        fact_store,
        prospective_entry_filter_state,
        restore_error=prospective_entry_filter_restore_error,
    )
    prospective_delayed_price_confirmation = (
        _prospective_delayed_price_confirmation_payload(
            pump.journal,
            delayed_entry_execution_shadow,
            execution.store.load_plan,
            prospective_delayed_price_confirmation_state,
            restore_error=(
                prospective_delayed_price_confirmation_restore_error
            ),
        )
    )
    prospective_top10_rank_filter = (
        _prospective_top10_rank_filter_payload(
            pump.journal,
            opening_rank_store,
            prospective_top10_rank_filter_state,
            restore_error=(
                prospective_top10_rank_filter_restore_error
            ),
        )
    )
    prospective_trade_quality = _prospective_trade_quality_payload(
        pump.journal,
        opening_rank_store,
        delayed_entry_execution_shadow,
        execution.store.load_plan,
        prospective_trade_quality_state,
        restore_error=prospective_trade_quality_restore_error,
    )
    prospective_combined_entry_filter = (
        _prospective_combined_entry_filter_payload(
            pump.journal,
            fact_store,
            opening_rank_store,
            prospective_entry_filter_state,
            prospective_top10_rank_filter_state,
            prospective_combined_entry_filter_state,
            restore_error=(
                prospective_combined_entry_filter_restore_error
            ),
        )
    )
    prospective_capacity_reflow_opportunities = (
        _prospective_capacity_reflow_opportunity_payload(
            opening_opportunity_store,
            prospective_combined_entry_filter_state,
        )
    )
    prospective_capacity_reflow_release_lineage = (
        _prospective_capacity_reflow_release_lineage_payload(
            opening_opportunity_store,
            opening_lineage_store,
            pump.journal,
            plan_loader=execution.store.load_plan,
            fact_store=fact_store,
            rank_store=opening_rank_store,
            state=prospective_combined_entry_filter_state,
        )
    )
    prospective_capacity_reflow_fill_feasibility = (
        _prospective_capacity_reflow_fill_feasibility_payload(
            opening_opportunity_store,
            opening_lineage_store,
            pump.journal,
            plan_loader=execution.store.load_plan,
            fact_store=fact_store,
            rank_store=opening_rank_store,
            state=prospective_combined_entry_filter_state,
            config=paper_execution_config,
            position_history_loader=lambda plan_id, through_ms: (
                execution.store.load_position_history(
                    plan_id,
                    through_ms=through_ms,
                )
            ),
        )
    )
    prospective_capacity_reflow_exit_fill = (
        _prospective_capacity_reflow_exit_fill_payload(
            prospective_capacity_reflow_fill_feasibility,
            opening_opportunity_exit_book_store,
            prospective_combined_entry_filter_state,
            paper_execution_config,
        )
    )
    prospective_capacity_reflow_realized_pnl = (
        _prospective_capacity_reflow_realized_pnl_payload(
            prospective_capacity_reflow_exit_fill,
            replacement_funding_store,
            prospective_combined_entry_filter_state,
        )
    )
    prospective_replacement_exit_policy = (
        _prospective_replacement_exit_policy_payload(
            prospective_capacity_reflow_realized_pnl,
            prospective_replacement_exit_policy_state,
            restore_error=(
                prospective_replacement_exit_policy_restore_error
            ),
        )
    )
    prospective_replacement_exit_robustness = (
        _prospective_replacement_exit_robustness_payload(
            prospective_replacement_exit_policy
        )
    )
    prospective_replacement_exit_readiness = (
        _prospective_replacement_exit_readiness_payload(
            prospective_replacement_exit_robustness
        )
    )
    prospective_capacity_reflow_forward_markout = (
        _prospective_capacity_reflow_forward_markout_payload(
            prospective_capacity_reflow_fill_feasibility,
            opening_opportunity_path_store,
            prospective_combined_entry_filter_state,
        )
    )
    prospective_capacity_reflow_forward_excursion = (
        _prospective_capacity_reflow_forward_excursion_payload(
            prospective_capacity_reflow_forward_markout,
            opening_opportunity_path_store,
            prospective_combined_entry_filter_state,
        )
    )
    prospective_daily_loss_lockout_reflow = (
        _prospective_daily_loss_lockout_reflow_payload(
            opening_opportunity_store,
            pump.journal,
            fact_store,
            opening_rank_store,
            prospective_combined_entry_filter_state,
            exit_fill_loader=lambda plan_id: (
                execution.store.load_execution_history(plan_id)[1]
            ),
            funding_loader=lambda market, start_ms: (
                execution.store.load_funding_for_market(
                    market,
                    start_ms=start_ms,
                )
            ),
        )
    )
    delayed_entry_fill_capacity = (
        _delayed_entry_fill_capacity_payload(
            pump.journal,
            delayed_entry_execution_shadow,
        )
    )
    delayed_entry_fill_weighted = (
        _delayed_entry_fill_weighted_payload(
            pump.journal,
            delayed_entry_execution_shadow,
        )
    )
    delayed_entry_fill_weighted_funding = (
        _delayed_entry_fill_weighted_funding_payload(
            pump.journal,
            delayed_entry_execution_shadow,
            lambda market, start_ms: (
                execution.store.load_funding_for_market(
                    market,
                    start_ms=start_ms,
                )
            ),
        )
    )
    delayed_entry_fixed_schedule_portfolio_payload = (
        _delayed_entry_fixed_schedule_portfolio_payload(
            pump.journal,
            delayed_entry_execution_shadow,
            execution.store.load_plan,
        )
    )
    delayed_entry_mtm_portfolio_payload = (
        _delayed_entry_mtm_portfolio_payload(
            pump.journal,
            delayed_entry_execution_shadow,
            trade_path_store,
            lambda market, start_ms: (
                execution.store.load_funding_for_market(
                    market,
                    start_ms=start_ms,
                )
            ),
        )
    )
    delayed_entry_stop_survivability_payload = (
        _delayed_entry_stop_survivability_payload(
            pump.journal,
            delayed_entry_execution_shadow,
            trade_path_store,
        )
    )
    delayed_entry_same_exit_stop_validity_payload = (
        _delayed_entry_same_exit_stop_validity_payload(
            pump.journal,
            delayed_entry_execution_shadow,
            trade_path_store,
            lambda market, start_ms: (
                execution.store.load_funding_for_market(
                    market,
                    start_ms=start_ms,
                )
            ),
        )
    )
    delayed_entry_stop_exit_proxy_payload = (
        _delayed_entry_stop_exit_proxy_payload(
            pump.journal,
            delayed_entry_execution_shadow,
            trade_path_store,
            lambda market, start_ms: (
                execution.store.load_funding_for_market(
                    market,
                    start_ms=start_ms,
                )
            ),
            paper_execution_config,
        )
    )
    delayed_entry_stop_l2_replay_payload = (
        _delayed_entry_stop_l2_replay_payload(
            pump.journal,
            delayed_entry_execution_shadow,
            trade_path_store,
            original_stop_book_store,
            lambda market, start_ms: (
                execution.store.load_funding_for_market(
                    market,
                    start_ms=start_ms,
                )
            ),
            paper_execution_config,
            capture_error=original_stop_book_capture.error,
        )
    )
    delayed_entry_portfolio_capacity = (
        _delayed_entry_portfolio_capacity_payload(
            pump.journal,
            delayed_entry_execution_shadow,
            trade_path_store,
            opening_fill_liquidity_store,
            execution.store.load_plan,
            lambda market, start_ms: (
                execution.store.load_funding_for_market(
                    market,
                    start_ms=start_ms,
                )
            ),
            risk_limits,
            paper_max_gross_leverage,
            native_perp_min_notional,
        )
    )
    delayed_entry_contribution_decomposition = (
        _delayed_entry_contribution_decomposition_payload(
            pump.journal,
            delayed_entry_execution_shadow,
        )
    )
    delayed_entry_contribution_decomposition_funding = (
        _delayed_entry_contribution_decomposition_funding_payload(
            pump.journal,
            delayed_entry_execution_shadow,
            lambda market, start_ms: (
                execution.store.load_funding_for_market(
                    market,
                    start_ms=start_ms,
                )
            ),
        )
    )
    delayed_entry_risk_geometry = (
        _delayed_entry_risk_geometry_payload(
            pump.journal,
            delayed_entry_execution_shadow,
            execution.store.load_plan,
        )
    )
    delayed_entry_same_exit = _delayed_entry_same_exit_payload(
        pump.journal,
        delayed_entry_execution_shadow,
    )
    delayed_entry_pair = _delayed_entry_pair_payload(
        pump.journal,
        delayed_entry_execution_shadow,
        delayed_entry_120s_execution_shadow,
    )
    delayed_entry_pair_fill_weighted = (
        _delayed_entry_pair_fill_weighted_payload(
            pump.journal,
            delayed_entry_execution_shadow,
            delayed_entry_120s_execution_shadow,
        )
    )
    adaptive_delay_selector = _adaptive_delay_selector_payload(
        pump.journal,
        entry_mid_markout_shadow,
        delayed_entry_execution_shadow,
        delayed_entry_120s_execution_shadow,
        adaptive_delay_selector_state,
        restore_error=adaptive_delay_selector_restore_error,
    )
    fill_aware_delay_selector = _fill_aware_delay_selector_payload(
        pump.journal,
        delayed_entry_execution_shadow,
        delayed_entry_120s_execution_shadow,
        fill_aware_delay_selector_state,
        restore_error=fill_aware_delay_selector_restore_error,
    )
    delay_selector_comparison = _delay_selector_comparison_payload(
        pump.journal,
        entry_mid_markout_shadow,
        delayed_entry_execution_shadow,
        delayed_entry_120s_execution_shadow,
        delay_selector_comparison_state,
        restore_error=delay_selector_comparison_restore_error,
    )
    opening_rank = _opening_rank_attribution_payload(
        pump.journal,
        opening_rank_store,
        capture_error=opening_rank_capture_error,
    )
    opening_fill_liquidity = _opening_fill_liquidity_payload(
        pump.journal,
        opening_fill_liquidity_store,
        capture_error=opening_fill_liquidity_capture_error,
    )
    entry_markout = _entry_markout_payload(
        pump.journal,
        fact_store,
        trade_path_store,
        opening_rank_store,
    )
    entry_markout_predictive = (
        _entry_markout_predictiveness_payload(
            pump.journal,
            trade_path_store,
        )
    )
    excursion_timing = _excursion_timing_payload(
        pump.journal,
        fact_store,
        trade_path_store,
    )
    entry_mid_markout = (
        entry_mid_markout_shadow.summary_payload(
            fact_store
        )
    )

    observation = pump.last_observation
    last_observation: dict[str, object] | None = None
    if observation is not None:
        last_observation = {
            "kind": observation.kind.value,
            "timestamp_ms": observation.timestamp_ms,
            "market": (
                None
                if observation.market is None
                else observation.market.canonical
            ),
            "reason_codes": list(observation.reason_codes),
            "plan_id": observation.plan_id,
        }
    return {
        "kind": "continuous-paper-heartbeat",
        "timestamp_ms": timestamp_ms,
        "paper_only": True,
        "live_orders": False,
        "selected_market_count": len(selected_markets),
        "selected_markets": [
            market.canonical for market in selected_markets
        ],
        "processed_records": pump.processed_records,
        "journal_observations": pump.journal_observations,
        "closed_trades": pump.closed_trades,
        "session_closed_trades": pump.session_closed_trades,
        "recent_closed_trades": [
            _closed_trade_status_payload(trade)
            for trade in reversed(pump.recent_closed_trades)
        ],
        "closed_trade_performance": closed_trade_performance,
        "account_lifecycle_economics": account_lifecycle_economics,
        "drawdown": drawdown,
        "closed_trade_concentration": closed_trade_concentration,
        "closed_trade_utc_hour": closed_trade_utc_hour,
        "closed_trade_friction": closed_trade_friction,
        "closed_trade_robustness": (
            closed_trade_robustness_payload
        ),
        "closed_trade_stability": (
            closed_trade_stability_payload
        ),
        "entry_decision_age": entry_decision_age,
        "open_planned_risk": str(open_planned_risk),
        "open_planned_risk_fraction_of_equity": str(
            open_planned_risk_fraction
        ),
        "open_stop_trigger_gross_pnl": str(open_stop_trigger_gross_pnl),
        "open_stop_trigger_gross_r": (
            None
            if open_stop_trigger_gross_r is None
            else str(open_stop_trigger_gross_r)
        ),
        "open_positions_with_profit_protected_stop": protected_stop_count,
        "gross_open_notional": str(execution.account.gross_open_notional),
        "gross_open_notional_fraction_of_equity": str(
            gross_open_notional_fraction
        ),
        "available_margin": str(execution.account.available_margin),
        "session_decision_epochs": activity.decision_epochs,
        "last_decision_boundary_ms": activity.last_decision_boundary_ms,
        "last_decision_evaluated_at_ms": activity.last_decision_evaluated_at_ms,
        "session_decisions": {
            "long": activity.long_decisions,
            "short": activity.short_decisions,
            "no_trade": activity.no_trade_decisions,
        },
        "session_decision_reason_counts": decision_reason_counts,
        "session_risk": {
            "evaluations": activity.risk_evaluations,
            "approvals": activity.risk_approvals,
            "rejections": activity.risk_rejections,
            "reason_counts": risk_reason_counts,
        },
        "session_opening_execution_attempts": activity.opening_execution_attempts,
        "session_opening_fills": activity.opening_fills,
        "cadence_shadow": pump.cadence_shadow_payload(),
        "cadence_opportunity_learning": (
            pump.cadence_opportunity_learning_payload()
        ),
        "trade_path_evidence": {
            "research_only": True,
            "durable_across_workers": True,
            "closed_path_count": trade_path_store.record_count,
            "staged_open_path_count": trade_path_store.open_path_count,
            "capture_error": trade_path_capture_error,
        },
        "original_stop_book_evidence": {
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "durable_across_workers": True,
            "capture_started_at_ms": (
                original_stop_book_store.capture_started_at_ms
            ),
            "captured_books": original_stop_book_store.record_count,
            "pending_crossings": original_stop_book_store.pending_count,
            "state_digest": original_stop_book_store.state_digest,
            "capture_error": original_stop_book_capture.error,
        },
        "profit_lock_counterfactual": profit_lock_counterfactual,
        "profit_lock_execution_shadow": (
            profit_lock_execution_shadow.summary_payload()
        ),
        "delayed_entry_execution_shadow": (
            delayed_entry_execution_shadow.summary_payload()
        ),
        "delayed_entry_120s_execution_shadow": (
            delayed_entry_120s_execution_shadow.summary_payload()
        ),
        "delayed_entry_pair": delayed_entry_pair,
        "delayed_entry_pair_fill_weighted": (
            delayed_entry_pair_fill_weighted
        ),
        "adaptive_delay_selector": adaptive_delay_selector,
        "fill_aware_delay_selector": fill_aware_delay_selector,
        "delay_selector_comparison": delay_selector_comparison,
        "delayed_entry_same_exit": delayed_entry_same_exit,
        "delayed_entry_fill_capacity": delayed_entry_fill_capacity,
        "delayed_entry_fill_weighted": delayed_entry_fill_weighted,
        "delayed_entry_fill_weighted_funding": (
            delayed_entry_fill_weighted_funding
        ),
        "delayed_entry_fixed_schedule_portfolio": (
            delayed_entry_fixed_schedule_portfolio_payload
        ),
        "delayed_entry_mtm_portfolio": (
            delayed_entry_mtm_portfolio_payload
        ),
        "delayed_entry_stop_survivability": (
            delayed_entry_stop_survivability_payload
        ),
        "delayed_entry_same_exit_stop_validity": (
            delayed_entry_same_exit_stop_validity_payload
        ),
        "delayed_entry_stop_exit_proxy": (
            delayed_entry_stop_exit_proxy_payload
        ),
        "delayed_entry_stop_l2_replay": (
            delayed_entry_stop_l2_replay_payload
        ),
        "delayed_entry_portfolio_capacity": (
            delayed_entry_portfolio_capacity
        ),
        "delayed_entry_contribution_decomposition": (
            delayed_entry_contribution_decomposition
        ),
        "delayed_entry_contribution_decomposition_funding": (
            delayed_entry_contribution_decomposition_funding
        ),
        "delayed_entry_risk_geometry": delayed_entry_risk_geometry,
        "prospective_entry_filter": prospective_entry_filter,
        "prospective_delayed_price_confirmation": (
            prospective_delayed_price_confirmation
        ),
        "prospective_top10_rank_filter": (
            prospective_top10_rank_filter
        ),
        "prospective_trade_quality": prospective_trade_quality,
        "prospective_combined_entry_filter": (
            prospective_combined_entry_filter
        ),
        "prospective_capacity_reflow_opportunities": (
            prospective_capacity_reflow_opportunities
        ),
        "prospective_capacity_reflow_release_lineage": (
            prospective_capacity_reflow_release_lineage
        ),
        "prospective_capacity_reflow_fill_feasibility": (
            prospective_capacity_reflow_fill_feasibility
        ),
        "prospective_capacity_reflow_exit_fill": (
            prospective_capacity_reflow_exit_fill
        ),
        "prospective_capacity_reflow_realized_pnl": (
            prospective_capacity_reflow_realized_pnl
        ),
        "prospective_replacement_exit_policy": (
            prospective_replacement_exit_policy
        ),
        "prospective_replacement_exit_robustness": (
            prospective_replacement_exit_robustness
        ),
        "prospective_replacement_exit_readiness": (
            prospective_replacement_exit_readiness
        ),
        "prospective_capacity_reflow_forward_markout": (
            prospective_capacity_reflow_forward_markout
        ),
        "prospective_capacity_reflow_forward_excursion": (
            prospective_capacity_reflow_forward_excursion
        ),
        "prospective_daily_loss_lockout_reflow": (
            prospective_daily_loss_lockout_reflow
        ),
        "opening_scanner_rank": opening_rank,
        "opening_fill_liquidity": opening_fill_liquidity,
        "entry_markout": entry_markout,
        "entry_markout_predictiveness": (
            entry_markout_predictive
        ),
        "excursion_timing": excursion_timing,
        "entry_mid_markout_shadow": entry_mid_markout,
        "open_position_count": len(positions),
        "positions": positions,
        "starting_cash": str(execution.account.starting_cash),
        "cash": str(execution.account.cash),
        "equity": str(execution.account.equity),
        "day_start_ms": execution.account.day_start_ms,
        "day_start_equity": str(execution.account.day_start_equity),
        "daily_realized_pnl": str(
            execution.account.daily_realized_pnl
        ),
        "total_account_pnl": str(total_account_pnl),
        "total_return_fraction": str(total_return_fraction),
        "unrealized_pnl": str(execution.account.unrealized_pnl),
        "realized_gross_pnl": str(execution.account.realized_gross_pnl),
        "cumulative_fees": str(execution.account.cumulative_fees),
        "cumulative_funding": str(execution.account.cumulative_funding),
        "execution_healthy": execution.health.healthy_for_new_exposure,
        "execution_reason_codes": list(execution.health.reason_codes),
        "last_observation": last_observation,
        "opening_opportunity_evidence": {
            "enabled": (
                opening_opportunity_capture_error is None
                and opening_opportunity_path_capture_error is None
            ),
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "claim_scope": (
                "prospective_decision_time_opening_opportunity_"
                "and_forward_mark_capture"
            ),
            "records": opening_opportunity_store.record_count,
            "baseline_approvals": opening_opportunity_store.approved_count,
            "baseline_rejections": opening_opportunity_store.rejected_count,
            "rank_complete": opening_opportunity_store.complete_rank_count,
            "rank_missing": max(
                0,
                opening_opportunity_store.record_count
                - opening_opportunity_store.complete_rank_count,
            ),
            "state_digest": opening_opportunity_store.state_digest,
            "capture_error": opening_opportunity_capture_error,
            "forward_mark_paths": (
                opening_opportunity_path_store.record_count
            ),
            "forward_mark_paths_complete": (
                opening_opportunity_path_store.complete_count
            ),
            "forward_mark_max_age_ms": (
                opening_opportunity_path_store.max_path_age_ms
            ),
            "forward_mark_max_completion_lag_ms": (
                opening_opportunity_path_store.max_completion_lag_ms
            ),
            "forward_mark_state_digest": (
                opening_opportunity_path_store.state_digest
            ),
            "forward_mark_capture_error": (
                opening_opportunity_path_capture_error
            ),
            "exit_book_capture_started_at_ms": (
                opening_opportunity_exit_book_store.capture_started_at_ms
            ),
            "exit_book_registered_opportunities": (
                opening_opportunity_exit_book_store.registration_count
            ),
            "exit_book_captures": (
                opening_opportunity_exit_book_store.capture_count
            ),
            "exit_book_pending": (
                opening_opportunity_exit_book_store.pending_count(
                    now_ms=timestamp_ms
                )
            ),
            "exit_book_missed": (
                opening_opportunity_exit_book_store.missed_count(
                    now_ms=timestamp_ms
                )
            ),
            "exit_book_horizons_ms": list(
                opening_opportunity_exit_book_store.horizons_ms
            ),
            "exit_book_max_capture_lag_ms": (
                opening_opportunity_exit_book_store.max_capture_lag_ms
            ),
            "exit_book_state_digest": (
                opening_opportunity_exit_book_store.state_digest
            ),
            "exit_book_enabled": (
                opening_opportunity_exit_book_capture_error is None
            ),
            "exit_book_capture_error": (
                opening_opportunity_exit_book_capture_error
            ),
            "full_l2_book_captured": True,
            "exact_risk_request_captured": True,
            "replacement_trades_modeled": False,
        },
        "replacement_funding_evidence": {
            "enabled": replacement_funding_capture_error is None,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "claim_scope": (
                "prospective_replacement_hourly_funding_boundary_capture"
            ),
            "capture_started_at_ms": (
                replacement_funding_store.capture_started_at_ms
            ),
            "registered_opportunities": (
                replacement_funding_store.registration_count
            ),
            "required_boundaries": (
                replacement_funding_store.required_boundary_count
            ),
            "oracle_candidates": (
                replacement_funding_store.oracle_candidate_count
            ),
            "captured_boundaries": replacement_funding_store.record_count,
            "pending_boundaries": replacement_funding_store.pending_count(
                now_ms=timestamp_ms
            ),
            "missed_boundaries": replacement_funding_store.missed_count(
                now_ms=timestamp_ms
            ),
            "max_window_ms": replacement_funding_store.max_window_ms,
            "max_oracle_age_ms": (
                replacement_funding_store.max_oracle_age_ms
            ),
            "max_funding_capture_lag_ms": (
                replacement_funding_store.max_funding_capture_lag_ms
            ),
            "state_digest": replacement_funding_store.state_digest,
            "capture_error": replacement_funding_capture_error,
            "funding_pnl_modeled": False,
        },
    }


def _operational_live_status_payload(
    execution: PaperExecutionAdapter,
    pump: _RecordPump,
    selected_markets: tuple[MarketId, ...],
    *,
    timestamp_ms: int,
) -> dict[str, object]:
    positions: list[dict[str, object]] = []
    for position in execution.account.positions:
        latest_mark = position.latest_mark
        protection = _position_protection_metrics(
            side=position.side.value,
            quantity=position.quantity,
            entry_price=position.average_entry_price,
            stop_price=position.stop_price,
            latest_mark=latest_mark,
            planned_risk=position.planned_risk,
        )
        positions.append(
            {
                "market": position.market.canonical,
                "side": position.side.value,
                "quantity": str(position.quantity),
                "average_entry_price": str(position.average_entry_price),
                "stop_price": str(position.stop_price),
                "latest_mark": (
                    None if latest_mark is None else str(latest_mark)
                ),
                **protection,
                "planned_risk": str(position.planned_risk),
                "opened_at_ms": position.opened_at_ms,
                "opening_plan_id": position.opening_plan_id,
            }
        )

    open_planned_risk = sum(
        (position.planned_risk for position in execution.account.positions),
        Decimal("0"),
    )
    open_planned_risk_fraction = (
        Decimal("0")
        if execution.account.equity == 0
        else open_planned_risk / execution.account.equity
    )
    open_stop_trigger_gross_pnl = sum(
        (
            Decimal(str(position["stop_trigger_gross_pnl"]))
            for position in positions
        ),
        Decimal("0"),
    )
    open_stop_trigger_gross_r = (
        None
        if open_planned_risk == 0
        else open_stop_trigger_gross_pnl / open_planned_risk
    )
    protected_stop_count = sum(
        1
        for position in positions
        if position["stop_protects_profit"] is True
    )
    total_account_pnl = (
        execution.account.equity - execution.account.starting_cash
    )
    total_return_fraction = (
        Decimal("0")
        if execution.account.starting_cash == 0
        else total_account_pnl / execution.account.starting_cash
    )
    gross_open_notional_fraction = (
        Decimal("0")
        if execution.account.equity == 0
        else (
            execution.account.gross_open_notional
            / execution.account.equity
        )
    )

    activity = pump.pipeline.session_decision_activity
    observation = pump.last_observation
    last_observation: dict[str, object] | None = None
    if observation is not None:
        last_observation = {
            "kind": observation.kind.value,
            "timestamp_ms": observation.timestamp_ms,
            "market": (
                None
                if observation.market is None
                else observation.market.canonical
            ),
            "reason_codes": list(observation.reason_codes),
            "plan_id": observation.plan_id,
        }

    return {
        "kind": "continuous-paper-heartbeat",
        "heartbeat_scope": "operational",
        "timestamp_ms": timestamp_ms,
        "paper_only": True,
        "live_orders": False,
        "research_telemetry_deferred": True,
        "selected_market_count": len(selected_markets),
        "selected_markets": [
            market.canonical for market in selected_markets
        ],
        "processed_records": pump.processed_records,
        "journal_observations": pump.journal_observations,
        "closed_trades": pump.closed_trades,
        "session_closed_trades": pump.session_closed_trades,
        "recent_closed_trades": [
            _closed_trade_status_payload(trade)
            for trade in reversed(pump.recent_closed_trades)
        ],
        "open_planned_risk": str(open_planned_risk),
        "open_planned_risk_fraction_of_equity": str(
            open_planned_risk_fraction
        ),
        "open_stop_trigger_gross_pnl": str(
            open_stop_trigger_gross_pnl
        ),
        "open_stop_trigger_gross_r": (
            None
            if open_stop_trigger_gross_r is None
            else str(open_stop_trigger_gross_r)
        ),
        "open_positions_with_profit_protected_stop": (
            protected_stop_count
        ),
        "gross_open_notional": str(
            execution.account.gross_open_notional
        ),
        "gross_open_notional_fraction_of_equity": str(
            gross_open_notional_fraction
        ),
        "available_margin": str(execution.account.available_margin),
        "session_decision_epochs": activity.decision_epochs,
        "last_decision_boundary_ms": activity.last_decision_boundary_ms,
        "last_decision_evaluated_at_ms": (
            activity.last_decision_evaluated_at_ms
        ),
        "session_decisions": {
            "long": activity.long_decisions,
            "short": activity.short_decisions,
            "no_trade": activity.no_trade_decisions,
        },
        "session_decision_reason_counts": dict(
            activity.decision_reason_counts
        ),
        "session_risk": {
            "evaluations": activity.risk_evaluations,
            "approvals": activity.risk_approvals,
            "rejections": activity.risk_rejections,
            "reason_counts": dict(activity.risk_reason_counts),
        },
        "session_opening_execution_attempts": (
            activity.opening_execution_attempts
        ),
        "session_opening_fills": activity.opening_fills,
        "open_position_count": len(positions),
        "positions": positions,
        "starting_cash": str(execution.account.starting_cash),
        "cash": str(execution.account.cash),
        "equity": str(execution.account.equity),
        "day_start_ms": execution.account.day_start_ms,
        "day_start_equity": str(execution.account.day_start_equity),
        "daily_realized_pnl": str(
            execution.account.daily_realized_pnl
        ),
        "total_account_pnl": str(total_account_pnl),
        "total_return_fraction": str(total_return_fraction),
        "unrealized_pnl": str(execution.account.unrealized_pnl),
        "realized_gross_pnl": str(
            execution.account.realized_gross_pnl
        ),
        "cumulative_fees": str(execution.account.cumulative_fees),
        "cumulative_funding": str(
            execution.account.cumulative_funding
        ),
        "execution_healthy": (
            execution.health.healthy_for_new_exposure
        ),
        "execution_reason_codes": list(
            execution.health.reason_codes
        ),
        "last_observation": last_observation,
    }


def _emit_operational_live_status(
    execution: PaperExecutionAdapter,
    pump: _RecordPump,
    selected_markets: tuple[MarketId, ...],
    *,
    timestamp_ms: int,
) -> None:
    payload = _operational_live_status_payload(
        execution,
        pump,
        selected_markets,
        timestamp_ms=timestamp_ms,
    )
    print(
        "COCOMELON_PAPER_HEARTBEAT "
        + json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ),
        flush=True,
    )


def _emit_live_status(
    execution: PaperExecutionAdapter,
    pump: _RecordPump,
    selected_markets: tuple[MarketId, ...],
    feature_store: LearningFeatureSnapshotStore,
    fact_store: EvaluationFactStore,
    opening_lineage_store: ContinuousPaperOpeningLineageStore,
    trade_path_store: ContinuousPaperTradePathStore,
    opening_rank_store: ContinuousPaperOpeningRankStore,
    opening_fill_liquidity_store: OpeningFillLiquidityStore,
    opening_opportunity_store: ContinuousPaperOpeningOpportunityStore,
    opening_opportunity_path_store: (
        ContinuousPaperOpeningOpportunityPathStore
    ),
    opening_opportunity_exit_book_store: (
        ContinuousPaperOpeningOpportunityExitBookStore
    ),
    replacement_funding_store: ContinuousPaperReplacementFundingStore,
    original_stop_book_store: OriginalStopBookEvidenceStore,
    original_stop_book_capture: OriginalStopBookCapture,
    profit_lock_execution_shadow: _ContinuousProfitLockExecutionShadowSink,
    delayed_entry_execution_shadow: _ContinuousDelayedEntryExecutionShadowSink,
    delayed_entry_120s_execution_shadow: _ContinuousDelayedEntryExecutionShadowSink,
    entry_mid_markout_shadow: _ContinuousEntryMidMarkoutSink,
    drawdown_tracker: ContinuousPaperDrawdownTracker,
    prospective_entry_filter_state: ProspectiveEntryFilterState,
    prospective_delayed_price_confirmation_state: (
        ProspectiveDelayedPriceConfirmationState
    ),
    prospective_top10_rank_filter_state: ProspectiveTop10RankFilterState,
    prospective_trade_quality_state: ProspectiveTradeQualityState,
    prospective_combined_entry_filter_state: ProspectiveCombinedEntryFilterState,
    prospective_replacement_exit_policy_state: (
        ProspectiveReplacementExitPolicyState
    ),
    adaptive_delay_selector_state: AdaptiveDelaySelectorState,
    fill_aware_delay_selector_state: FillAwareDelaySelectorState,
    delay_selector_comparison_state: DelaySelectorComparisonState,
    *,
    trade_path_capture_error: str | None,
    opening_rank_capture_error: str | None,
    opening_fill_liquidity_capture_error: str | None,
    opening_opportunity_capture_error: str | None,
    opening_opportunity_path_capture_error: str | None,
    opening_opportunity_exit_book_capture_error: str | None,
    replacement_funding_capture_error: str | None,
    prospective_entry_filter_restore_error: str | None,
    prospective_delayed_price_confirmation_restore_error: str | None,
    prospective_top10_rank_filter_restore_error: str | None,
    prospective_trade_quality_restore_error: str | None,
    prospective_combined_entry_filter_restore_error: str | None,
    prospective_replacement_exit_policy_restore_error: str | None,
    adaptive_delay_selector_restore_error: str | None,
    fill_aware_delay_selector_restore_error: str | None,
    delay_selector_comparison_restore_error: str | None,
    risk_limits: RiskLimits,
    paper_max_gross_leverage: Decimal,
    native_perp_min_notional: Decimal,
    paper_execution_config: PaperExecutionConfig,
    checkpoint_seconds: int,
    timestamp_ms: int,
) -> None:
    payload = _live_status_payload(
        execution,
        pump,
        selected_markets,
        feature_store,
        fact_store,
        opening_lineage_store,
        trade_path_store,
        opening_rank_store,
        opening_fill_liquidity_store,
        opening_opportunity_store,
        opening_opportunity_path_store,
        opening_opportunity_exit_book_store,
        replacement_funding_store,
        original_stop_book_store,
        original_stop_book_capture,
        profit_lock_execution_shadow,
        delayed_entry_execution_shadow,
        delayed_entry_120s_execution_shadow,
        entry_mid_markout_shadow,
        drawdown_tracker,
        prospective_entry_filter_state,
        prospective_delayed_price_confirmation_state,
        prospective_top10_rank_filter_state,
        prospective_trade_quality_state,
        prospective_combined_entry_filter_state,
        prospective_replacement_exit_policy_state,
        adaptive_delay_selector_state,
        fill_aware_delay_selector_state,
        delay_selector_comparison_state,
        trade_path_capture_error=trade_path_capture_error,
        opening_rank_capture_error=opening_rank_capture_error,
        opening_fill_liquidity_capture_error=(
            opening_fill_liquidity_capture_error
        ),
        opening_opportunity_capture_error=(
            opening_opportunity_capture_error
        ),
        opening_opportunity_path_capture_error=(
            opening_opportunity_path_capture_error
        ),
        opening_opportunity_exit_book_capture_error=(
            opening_opportunity_exit_book_capture_error
        ),
        replacement_funding_capture_error=(
            replacement_funding_capture_error
        ),
        prospective_entry_filter_restore_error=(
            prospective_entry_filter_restore_error
        ),
        prospective_delayed_price_confirmation_restore_error=(
            prospective_delayed_price_confirmation_restore_error
        ),
        prospective_top10_rank_filter_restore_error=(
            prospective_top10_rank_filter_restore_error
        ),
        prospective_trade_quality_restore_error=(
            prospective_trade_quality_restore_error
        ),
        prospective_combined_entry_filter_restore_error=(
            prospective_combined_entry_filter_restore_error
        ),
        prospective_replacement_exit_policy_restore_error=(
            prospective_replacement_exit_policy_restore_error
        ),
        adaptive_delay_selector_restore_error=(
            adaptive_delay_selector_restore_error
        ),
        fill_aware_delay_selector_restore_error=(
            fill_aware_delay_selector_restore_error
        ),
        delay_selector_comparison_restore_error=(
            delay_selector_comparison_restore_error
        ),
        risk_limits=risk_limits,
        paper_max_gross_leverage=paper_max_gross_leverage,
        native_perp_min_notional=native_perp_min_notional,
        paper_execution_config=paper_execution_config,
        checkpoint_seconds=checkpoint_seconds,
        timestamp_ms=timestamp_ms,
    )
    print(
        "COCOMELON_PAPER_HEARTBEAT "
        + json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ),
        flush=True,
    )


def _restore_open_lifecycles(
    pipeline: BaselineReplayPipeline,
    execution: PaperExecutionAdapter,
    checkpoints: tuple[OpenLifecycleCheckpoint, ...],
) -> None:
    account_markets = {position.market.canonical for position in execution.account.positions}
    checkpoint_markets = {item.market.canonical for item in checkpoints}
    if account_markets != checkpoint_markets:
        raise RuntimeError(
            "paper account/open-lifecycle checkpoint mismatch; refusing unsafe restart"
        )

    for checkpoint in checkpoints:
        opening_plan = execution.store.load_plan(checkpoint.opening_plan_id)
        if opening_plan is None:
            raise RuntimeError("opening plan missing during paper runtime restore")
        opening_attempts, opening_fills = execution.store.load_execution_history(
            opening_plan.plan_id
        )
        filled_opening_attempts = tuple(
            attempt for attempt in opening_attempts if attempt.filled_quantity > 0
        )
        if len(filled_opening_attempts) != 1:
            raise RuntimeError("paper runtime restore requires one filled opening attempt")
        opening_attempt = filled_opening_attempts[0]
        opening_attempt_fills = tuple(
            fill for fill in opening_fills if fill.attempt_id == opening_attempt.attempt_id
        )

        exit_plans: list[PaperOrderPlan] = []
        exit_attempts: list[ExecutionAttempt] = []
        exit_fills: list[PaperFill] = []
        for plan_id in checkpoint.exit_plan_ids:
            plan = execution.store.load_plan(plan_id)
            if plan is None:
                raise RuntimeError("exit plan missing during paper runtime restore")
            exit_plans.append(plan)
            attempts, fills = execution.store.load_execution_history(plan_id)
            exit_attempts.extend(attempts)
            exit_fills.extend(fills)

        position = next(
            position
            for position in execution.account.positions
            if position.market == checkpoint.market
        )
        funding = execution.store.load_funding_for_market(
            checkpoint.market,
            start_ms=position.opened_at_ms,
        )
        pipeline.restore_open_lifecycle(
            checkpoint,
            opening_plan=opening_plan,
            opening_attempt=opening_attempt,
            opening_fills=opening_attempt_fills,
            exit_plans=tuple(exit_plans),
            exit_attempts=tuple(exit_attempts),
            exit_fills=tuple(exit_fills),
            funding_accruals=funding,
        )


async def run_continuous_paper_session(
    state_root: str | Path,
    config: ContinuousPaperConfig,
    *,
    settings: Settings | None = None,
    stop_file: str | Path | None = None,
    runtime_identity: ContinuousPaperRuntimeIdentity | None = None,
) -> ContinuousPaperSummary:
    settings = settings or Settings.from_env()
    if settings.execution_mode is not ExecutionMode.PAPER:
        raise RuntimeError("continuous paper runtime refuses non-paper execution mode")

    root = Path(state_root)
    root.mkdir(parents=True, exist_ok=True)
    stop_path = None if stop_file is None else Path(stop_file)
    if stop_path is not None and stop_path.exists():
        stop_path.unlink()
    started_at_ms = utc_now_ms()
    checkpoint_path = root / CHECKPOINT_FILENAME
    checkpoints, gap_intervals, restored_available_at_ms = _load_checkpoint(checkpoint_path)

    reader = InfoClient(settings)
    replay_config = BaselineReplayConfig()
    execution = PaperExecutionAdapter(
        root / "paper.sqlite3",
        replay_config.execution,
        starting_cash=Decimal("10000"),
        startup_timestamp_ms=started_at_ms,
    )
    journal = JournalStore(root / "journal.sqlite3")
    facts = EvaluationFactStore(root / "facts.sqlite3")
    feature_store = LearningFeatureSnapshotStore(root / "learning-features")
    opening_lineage_store = ContinuousPaperOpeningLineageStore(
        root / "opening-lineage"
    )
    opening_rank_store = ContinuousPaperOpeningRankStore(
        root / "opening-ranks"
    )
    opening_fill_liquidity_store = OpeningFillLiquidityStore(
        root / "opening-fill-liquidity"
    )
    opening_fill_liquidity_sink = (
        _ContinuousOpeningFillLiquiditySink(
            opening_fill_liquidity_store
        )
    )
    opening_opportunity_store = ContinuousPaperOpeningOpportunityStore(
        root / "opening-opportunities"
    )
    opening_opportunity_path_store = (
        ContinuousPaperOpeningOpportunityPathStore(
            root / "opening-opportunity-paths",
            max_path_age_ms=DEFAULT_MAX_PATH_AGE_MS,
            max_completion_lag_ms=DEFAULT_MAX_COMPLETION_LAG_MS,
        )
    )
    opening_opportunity_exit_book_store = (
        ContinuousPaperOpeningOpportunityExitBookStore(
            root / "opening-opportunity-exit-books",
            capture_started_at_ms=started_at_ms,
            horizons_ms=DEFAULT_FORWARD_MARKOUT_HORIZONS_MS,
            max_capture_lag_ms=MAX_FORWARD_MARKOUT_LAG_MS,
        )
    )
    replacement_funding_store = ContinuousPaperReplacementFundingStore(
        root / "replacement-funding-boundaries",
        capture_started_at_ms=started_at_ms,
        max_window_ms=(
            max(DEFAULT_FORWARD_MARKOUT_HORIZONS_MS)
            + MAX_FORWARD_MARKOUT_LAG_MS
            + replay_config.execution.latency_ms
        ),
        max_oracle_age_ms=(
            replay_config.execution.max_asset_ctx_age_ms
        ),
        max_funding_capture_lag_ms=(
            replay_config.execution.funding_reconciliation_grace_ms
        ),
    )
    original_stop_book_store = OriginalStopBookEvidenceStore(
        root / "original-stop-books",
        started_at_ms=started_at_ms,
    )
    rank_tracker = LatestCoarseRankTracker()
    opening_opportunity_sink = _ContinuousOpeningOpportunitySink(
        opening_opportunity_store,
        opening_opportunity_path_store,
        opening_opportunity_exit_book_store,
        replacement_funding_store,
        rank_tracker,
    )
    trade_path_store = ContinuousPaperTradePathStore(root / "trade-paths")
    trade_path_sink = _ContinuousTradePathSink(trade_path_store)

    async def capture_due_exit_books(
        snapshots: dict[str, PerpMarketSnapshot],
        *,
        now_ms: int,
    ) -> None:
        requests = (
            opening_opportunity_exit_book_store.due_requests(
                now_ms=now_ms
            )
        )
        if not requests:
            return
        cycle_error: str | None = None
        for request in _iter_until_stop(requests, stop_path):
            snapshot = snapshots.get(request.market)
            if snapshot is None:
                if cycle_error is None:
                    cycle_error = (
                        "RuntimeError: due exit-book market missing "
                        f"from native snapshot: {request.market}"
                    )
                continue
            try:
                raw_book = await asyncio.to_thread(
                    reader.l2_book,
                    snapshot.meta.market,
                )
                received_at_ms = utc_now_ms()
                book = normalize_l2_book_snapshot(
                    snapshot.meta.market,
                    raw_book,
                    received_at_ms=received_at_ms,
                )
                instrument = InstrumentExecutionSpec(
                    market=snapshot.meta.market,
                    sz_decimals=snapshot.meta.sz_decimals,
                    venue_max_leverage=Decimal(
                        snapshot.meta.max_leverage
                    ),
                    minimum_order_notional=(
                        replay_config.execution.native_perp_min_notional
                    ),
                    metadata_received_at_ms=snapshot.received_at_ms,
                    metadata_source=snapshot.source,
                )
                opening_opportunity_exit_book_store.capture(
                    request,
                    book,
                    instrument,
                )
            except Exception as exc:
                if cycle_error is None:
                    cycle_error = f"{type(exc).__name__}: {exc}"
        opening_opportunity_sink.exit_book_error = cycle_error

    async def capture_due_replacement_funding(
        *,
        now_ms: int,
    ) -> None:
        requests = replacement_funding_store.due_requests(
            now_ms=now_ms
        )
        if not requests:
            return
        by_market: dict[
            str,
            list[ReplacementFundingBoundaryRequest],
        ] = {}
        for request in requests:
            by_market.setdefault(request.market, []).append(request)
        cycle_error: str | None = None
        for market_key, market_requests in _iter_until_stop(
            sorted(by_market.items()),
            stop_path,
        ):
            try:
                market = _market_from_canonical(market_key)
                first_boundary = min(
                    int(request.boundary_ms)
                    for request in market_requests
                )
                raw = await asyncio.to_thread(
                    reader.funding_history,
                    market,
                    start_ms=max(0, first_boundary - 1_000),
                    end_ms=now_ms,
                )
                received_at_ms = utc_now_ms()
                rates = normalize_funding_history(
                    market,
                    raw,
                    received_at_ms=received_at_ms,
                )
                by_boundary: dict[int, FundingRate] = {}
                for rate in rates:
                    boundary_ms = funding_boundary_for_record_time(
                        rate.time_ms
                    )
                    if boundary_ms is None:
                        continue
                    existing = by_boundary.get(boundary_ms)
                    if existing is not None and existing != rate:
                        raise RuntimeError(
                            "conflicting funding rates for boundary "
                            f"{market_key}:{boundary_ms}"
                        )
                    by_boundary[boundary_ms] = rate
                for request in market_requests:
                    matched_rate = by_boundary.get(
                        request.boundary_ms
                    )
                    if matched_rate is None:
                        continue
                    replacement_funding_store.capture(
                        request,
                        matched_rate,
                    )
            except Exception as exc:
                if cycle_error is None:
                    cycle_error = f"{type(exc).__name__}: {exc}"
        if (
            cycle_error is not None
            and opening_opportunity_sink.funding_error is None
        ):
            opening_opportunity_sink.funding_error = cycle_error

    async def capture_replacement_funding_oracles() -> None:
        while True:
            if _stop_requested(stop_path):
                return
            now_ms = utc_now_ms()
            future_boundaries = tuple(
                request.boundary_ms
                for request in replacement_funding_store.required_boundaries()
                if request.boundary_ms >= now_ms
                and replacement_funding_store.markets_for_boundary(
                    request.boundary_ms
                )
            )
            if not future_boundaries:
                await asyncio.sleep(5.0)
                continue
            boundary_ms = min(future_boundaries)
            capture_window_ms = (
                boundary_ms
                - replacement_funding_store.max_oracle_age_ms
            )
            if now_ms < capture_window_ms:
                await asyncio.sleep(
                    min(
                        5.0,
                        max(
                            0.05,
                            (capture_window_ms - now_ms) / 1_000,
                        ),
                    )
                )
                continue
            while utc_now_ms() <= boundary_ms:
                if _stop_requested(stop_path):
                    return
                markets = replacement_funding_store.markets_for_boundary(
                    boundary_ms
                )
                if not markets:
                    break
                try:
                    raw = await asyncio.to_thread(
                        reader.meta_and_asset_ctxs,
                        "",
                    )
                    received_at_ms = utc_now_ms()
                    snapshots = normalize_meta_and_asset_ctxs(
                        "",
                        raw,
                        received_at_ms=received_at_ms,
                    )
                    by_market = {
                        snapshot.meta.market.canonical: snapshot
                        for snapshot in snapshots
                    }
                    for market_key in _iter_until_stop(
                        markets,
                        stop_path,
                    ):
                        snapshot = by_market.get(market_key)
                        if snapshot is not None:
                            replacement_funding_store.observe_snapshot(
                                snapshot
                            )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    if opening_opportunity_sink.funding_error is None:
                        opening_opportunity_sink.funding_error = (
                            f"{type(exc).__name__}: {exc}"
                        )
                remaining_ms = boundary_ms - utc_now_ms()
                if remaining_ms <= 0:
                    break
                await asyncio.sleep(
                    min(1.0, max(0.05, remaining_ms / 1_000))
                )

    original_stop_book_capture = OriginalStopBookCapture(
        original_stop_book_store,
        opening_plan_loader=execution.store.load_plan,
        config=replay_config.execution,
    )
    profit_lock_execution_shadow = (
        _ContinuousProfitLockExecutionShadowSink(
            _restore_profit_lock_execution_shadow(
                root / PROFIT_LOCK_EXECUTION_SHADOW_STATE_FILENAME,
                replay_config.execution,
                started_at_ms=started_at_ms,
            ),
            opening_plan_loader=execution.store.load_plan,
        )
    )
    delayed_entry_execution_shadow = (
        _ContinuousDelayedEntryExecutionShadowSink(
            _restore_delayed_entry_execution_shadow(
                root / DELAYED_ENTRY_EXECUTION_SHADOW_STATE_FILENAME,
                replay_config.execution,
                started_at_ms=started_at_ms,
            ),
            opening_plan_loader=execution.store.load_plan,
        )
    )
    delayed_entry_120s_execution_shadow = (
        _ContinuousDelayedEntryExecutionShadowSink(
            _restore_delayed_entry_execution_shadow(
                root / DELAYED_ENTRY_120S_EXECUTION_SHADOW_STATE_FILENAME,
                replay_config.execution,
                started_at_ms=started_at_ms,
                delay_ms=CHALLENGER_DELAY_MS,
                max_observation_lag_ms=MAX_DELAY_OBSERVATION_LAG_MS,
            ),
            opening_plan_loader=execution.store.load_plan,
        )
    )
    entry_mid_markout_shadow = _ContinuousEntryMidMarkoutSink(
        _restore_entry_mid_markout_shadow(
            root / ENTRY_MID_MARKOUT_SHADOW_STATE_FILENAME,
            started_at_ms=started_at_ms,
        ),
        opening_plan_loader=execution.store.load_plan,
    )
    drawdown_tracker = _restore_drawdown_tracker(
        root / DRAWDOWN_STATE_FILENAME,
        started_at_ms=started_at_ms,
    )
    profit_lock_execution_shadow.reconcile_open_positions(
        execution.account.positions
    )
    delayed_entry_execution_shadow.reconcile_open_positions(
        execution.account.positions
    )
    delayed_entry_120s_execution_shadow.reconcile_open_positions(
        execution.account.positions
    )
    entry_mid_markout_shadow.reconcile_open_positions(
        execution.account.positions
    )
    (
        prospective_entry_filter_state,
        prospective_entry_filter_restore_error,
    ) = _restore_prospective_entry_filter(
        root / PROSPECTIVE_ENTRY_FILTER_STATE_FILENAME,
        started_at_ms=started_at_ms,
    )
    (
        prospective_delayed_price_confirmation_state,
        prospective_delayed_price_confirmation_restore_error,
    ) = _restore_prospective_delayed_price_confirmation(
        root / PROSPECTIVE_DELAYED_PRICE_CONFIRM_STATE_FILENAME,
        started_at_ms=started_at_ms,
    )
    (
        prospective_top10_rank_filter_state,
        prospective_top10_rank_filter_restore_error,
    ) = _restore_prospective_top10_rank_filter(
        root / PROSPECTIVE_TOP10_RANK_FILTER_STATE_FILENAME,
        started_at_ms=started_at_ms,
    )
    (
        prospective_trade_quality_state,
        prospective_trade_quality_restore_error,
    ) = _restore_prospective_trade_quality(
        root / PROSPECTIVE_TRADE_QUALITY_STATE_FILENAME,
        started_at_ms=started_at_ms,
    )
    (
        prospective_combined_entry_filter_state,
        prospective_combined_entry_filter_restore_error,
    ) = _restore_prospective_combined_entry_filter(
        root / PROSPECTIVE_COMBINED_ENTRY_FILTER_STATE_FILENAME,
        started_at_ms=started_at_ms,
    )
    (
        prospective_replacement_exit_policy_state,
        prospective_replacement_exit_policy_restore_error,
    ) = _restore_prospective_replacement_exit_policy(
        root / PROSPECTIVE_REPLACEMENT_EXIT_POLICY_STATE_FILENAME,
        started_at_ms=started_at_ms,
    )
    (
        prospective_side_conditioned_delay_state,
        _prospective_side_conditioned_delay_restore_error,
    ) = _restore_prospective_side_conditioned_delay(
        root / PROSPECTIVE_SIDE_CONDITIONED_DELAY_STATE_FILENAME,
        started_at_ms=started_at_ms,
    )
    (
        adaptive_delay_selector_state,
        adaptive_delay_selector_restore_error,
    ) = _restore_adaptive_delay_selector(
        root / ADAPTIVE_DELAY_SELECTOR_STATE_FILENAME,
        started_at_ms=started_at_ms,
    )
    (
        fill_aware_delay_selector_state,
        fill_aware_delay_selector_restore_error,
    ) = _restore_fill_aware_delay_selector(
        root / FILL_AWARE_DELAY_SELECTOR_STATE_FILENAME,
        started_at_ms=started_at_ms,
    )
    (
        delay_selector_comparison_state,
        delay_selector_comparison_restore_error,
    ) = _restore_delay_selector_comparison(
        root / DELAY_SELECTOR_COMPARISON_STATE_FILENAME,
        started_at_ms=started_at_ms,
    )

    try:
        if not execution.health.healthy_for_new_exposure:
            raise RuntimeError(
                "paper execution state is unhealthy: "
                + ",".join(execution.health.reason_codes)
            )

        initial_received_at_ms = utc_now_ms()
        snapshots = await asyncio.to_thread(
            _native_market_snapshots,
            reader,
            received_at_ms=initial_received_at_ms,
        )
        opening_opportunity_sink.observe_snapshots(snapshots)
        await capture_due_exit_books(
            snapshots,
            now_ms=initial_received_at_ms,
        )
        pinned = tuple(position.market for position in execution.account.positions)
        initial_rank_observed_at_ms = utc_now_ms()
        _initial_features, initial_ranks = _startup_ranks(
            snapshots,
            as_of_ms=initial_rank_observed_at_ms,
        )
        rank_tracker.update(
            initial_ranks,
            observed_at_ms=initial_rank_observed_at_ms,
        )
        selected = _ranked_selection(
            snapshots,
            as_of_ms=initial_received_at_ms,
            deep_limit=config.deep_limit,
            pinned=pinned,
        )
        if not selected:
            raise RuntimeError("continuous paper scan produced no rankable native markets")

        opening_lineage_sink = (
            None
            if runtime_identity is None
            else _ContinuousOpeningLineageSink(
                opening_lineage_store,
                runtime_identity,
                rank_store=opening_rank_store,
                rank_tracker=rank_tracker,
            )
        )
        pipeline = BaselineReplayPipeline(
            replay_config,
            execution,
            facts,
            selected_markets=selected,
            replay_run_id=RUN_ID,
            evidence_class=EvidenceClass.MICROSTRUCTURE,
            feature_snapshot_sink=feature_store,
            opening_lifecycle_sink=opening_lineage_sink,
            closed_lifecycle_sink=trade_path_sink,
            opening_research_observer=(
                _CompositeOpeningResearchObserver(
                    opening_fill_liquidity_sink,
                    opening_opportunity_sink,
                    trade_path_sink,
                )
            ),
            position_research_observer=(
                _CompositePositionResearchObserver(
                    profit_lock_execution_shadow,
                    delayed_entry_execution_shadow,
                    delayed_entry_120s_execution_shadow,
                    original_stop_book_capture,
                )
            ),
        )
        pipeline.restore_gap_intervals(gap_intervals)
        _restore_open_lifecycles(pipeline, execution, checkpoints)
        cadence_shadow = _restore_cadence_shadow(
            root / CADENCE_SHADOW_STATE_FILENAME,
            selected,
            replay_config=replay_config,
        )
        pump = _RecordPump(
            pipeline,
            journal,
            last_available_at_ms=restored_available_at_ms,
            cadence_shadow=cadence_shadow,
            entry_mid_markout_shadow=entry_mid_markout_shadow,
            position_provider=lambda: execution.account.positions,
        )

        selected_keys = {market.canonical for market in selected}
        for market in selected:
            snapshot = snapshots.get(market.canonical)
            if snapshot is None:
                raise RuntimeError(
                    "selected market missing from native registry: "
                    f"{market.canonical}"
                )
            await pump.process(_record_from_public(market_snapshot_record_event(snapshot)))
        for market in _iter_until_stop(selected, stop_path):
            for candle in await _warmup_market(
                reader,
                market,
                end_ms=started_at_ms,
                config=config,
            ):
                if _stop_requested(stop_path):
                    break
                await pump.process(
                    _record_from_public(candle_record_event(candle))
                )

        async def refresh_funding() -> None:
            now_ms = utc_now_ms()
            for position in _iter_until_stop(
                tuple(execution.account.positions),
                stop_path,
            ):
                start_ms = max(
                    position.opened_at_ms,
                    now_ms - 8 * 60 * 60 * 1000,
                )
                raw = await asyncio.to_thread(
                    reader.funding_history,
                    position.market,
                    start_ms=start_ms,
                    end_ms=now_ms,
                )
                received_at_ms = utc_now_ms()
                for rate in normalize_funding_history(
                    position.market,
                    raw,
                    received_at_ms=received_at_ms,
                ):
                    await pump.process(
                        _record_from_public(funding_rate_record_event(rate))
                    )

        await refresh_funding()
        await capture_due_replacement_funding(
            now_ms=utc_now_ms()
        )

        def persist_checkpoint() -> None:
            checkpoint_timestamp_ms = utc_now_ms()
            drawdown_tracker.observe(
                execution.account.equity,
                timestamp_ms=checkpoint_timestamp_ms,
            )
            trade_path_sink.checkpoint(pipeline.open_lifecycle_mark_paths)
            _write_json_atomic(
                checkpoint_path,
                _checkpoint_payload(
                    pipeline,
                    last_available_at_ms=pump.last_available_at_ms,
                    selected_markets=selected,
                ),
            )
            _write_json_atomic(
                root / CADENCE_SHADOW_FILENAME,
                pump.cadence_shadow_payload(),
            )
            if pump.cadence_shadow is not None:
                _write_json_atomic(
                    root / CADENCE_SHADOW_STATE_FILENAME,
                    pump.cadence_shadow.state_payload(),
                )
            if profit_lock_execution_shadow.shadow is not None:
                _write_json_atomic(
                    root / PROFIT_LOCK_EXECUTION_SHADOW_STATE_FILENAME,
                    profit_lock_execution_shadow.shadow.state_payload(),
                )
            if delayed_entry_execution_shadow.shadow is not None:
                _write_json_atomic(
                    root / DELAYED_ENTRY_EXECUTION_SHADOW_STATE_FILENAME,
                    delayed_entry_execution_shadow.shadow.state_payload(),
                )
            if delayed_entry_120s_execution_shadow.shadow is not None:
                _write_json_atomic(
                    root / DELAYED_ENTRY_120S_EXECUTION_SHADOW_STATE_FILENAME,
                    delayed_entry_120s_execution_shadow.shadow.state_payload(),
                )
            _write_json_atomic(
                root / PROSPECTIVE_ENTRY_FILTER_STATE_FILENAME,
                prospective_entry_filter_state.payload(),
            )
            _write_json_atomic(
                root / PROSPECTIVE_DELAYED_PRICE_CONFIRM_STATE_FILENAME,
                prospective_delayed_price_confirmation_state.payload(),
            )
            _write_json_atomic(
                root / PROSPECTIVE_TOP10_RANK_FILTER_STATE_FILENAME,
                prospective_top10_rank_filter_state.payload(),
            )
            _write_json_atomic(
                root / PROSPECTIVE_TRADE_QUALITY_STATE_FILENAME,
                prospective_trade_quality_state.payload(),
            )
            _write_json_atomic(
                root / PROSPECTIVE_COMBINED_ENTRY_FILTER_STATE_FILENAME,
                prospective_combined_entry_filter_state.payload(),
            )
            _write_json_atomic(
                root / PROSPECTIVE_REPLACEMENT_EXIT_POLICY_STATE_FILENAME,
                prospective_replacement_exit_policy_state.payload(),
            )
            _write_json_atomic(
                root / PROSPECTIVE_SIDE_CONDITIONED_DELAY_STATE_FILENAME,
                prospective_side_conditioned_delay_state.payload(),
            )
            _write_json_atomic(
                root / ADAPTIVE_DELAY_SELECTOR_STATE_FILENAME,
                adaptive_delay_selector_state.payload(),
            )
            _write_json_atomic(
                root / FILL_AWARE_DELAY_SELECTOR_STATE_FILENAME,
                fill_aware_delay_selector_state.payload(),
            )
            _write_json_atomic(
                root / DELAY_SELECTOR_COMPARISON_STATE_FILENAME,
                delay_selector_comparison_state.payload(),
            )
            if entry_mid_markout_shadow.shadow is not None:
                _write_json_atomic(
                    root / ENTRY_MID_MARKOUT_SHADOW_STATE_FILENAME,
                    entry_mid_markout_shadow.shadow.state_payload(),
                )
            _write_json_atomic(
                root / DRAWDOWN_STATE_FILENAME,
                drawdown_tracker.state_payload(),
            )

        persist_checkpoint()
        if not _stop_requested(stop_path):
            _emit_operational_live_status(
                execution,
                pump,
                selected,
                timestamp_ms=utc_now_ms(),
            )

        async def connection_factory() -> Any:
            return await connect_mainnet_ws(settings)

        async def start_supervisors(
            markets: tuple[MarketId, ...],
        ) -> tuple[tuple[WebSocketSupervisor, ...], tuple[asyncio.Task[None], ...]]:
            plan = DeepWatchlistManager().reconcile(markets)
            async def event_sink(event: StreamEvent) -> None:
                await pump.process(_record_from_stream(event))

            async def gap_sink(gap: DataGap) -> None:
                await pump.process(_record_from_gap(gap))

            mux = RedundantStreamMux(event_sink=event_sink, gap_sink=gap_sink)
            supervisors: list[WebSocketSupervisor] = []
            tasks: list[asyncio.Task[None]] = []
            for lane in range(2):
                async def lane_event_sink(event: StreamEvent, lane: int = lane) -> None:
                    await mux.on_event(lane, event)

                async def lane_gap_sink(gap: DataGap, lane: int = lane) -> None:
                    await mux.on_gap(lane, gap)

                supervisor = WebSocketSupervisor(
                    connection_factory,
                    plan.subscribe,
                    event_sink=lane_event_sink,
                    gap_sink=lane_gap_sink,
                    clock_ms=utc_now_ms,
                    utcnow=lambda: datetime.now(UTC),
                )
                supervisors.append(supervisor)
                tasks.append(asyncio.create_task(supervisor.run()))
            return tuple(supervisors), tuple(tasks)

        _supervisors, supervisor_tasks = await start_supervisors(selected)
        replacement_funding_oracle_task = asyncio.create_task(
            capture_replacement_funding_oracles()
        )
        deadline_ms = started_at_ms + config.duration_seconds * 1000
        next_selection_refresh_ms = started_at_ms + config.selection_refresh_seconds * 1000
        next_checkpoint_ms = started_at_ms + config.checkpoint_seconds * 1000

        exit_reason = "duration_elapsed"
        try:
            while utc_now_ms() < deadline_ms:
                if _stop_requested(stop_path):
                    exit_reason = "upgrade_requested"
                    break
                now_ms = utc_now_ms()
                sleep_seconds = min(
                    float(config.context_poll_seconds),
                    max(0.1, (deadline_ms - now_ms) / 1000),
                )
                await asyncio.sleep(sleep_seconds)
                now_ms = utc_now_ms()
                if _stop_requested(stop_path):
                    exit_reason = "upgrade_requested"
                    break

                refreshed = await asyncio.to_thread(
                    _native_market_snapshots,
                    reader,
                    received_at_ms=now_ms,
                )
                if _stop_requested(stop_path):
                    exit_reason = "upgrade_requested"
                    break
                opening_opportunity_sink.observe_snapshots(refreshed)
                await capture_due_exit_books(
                    refreshed,
                    now_ms=now_ms,
                )
                if _stop_requested(stop_path):
                    exit_reason = "upgrade_requested"
                    break
                for market in selected:
                    snapshot = refreshed.get(market.canonical)
                    if snapshot is not None:
                        await pump.process(
                            _record_from_public(market_snapshot_record_event(snapshot))
                        )
                rank_observed_at_ms = utc_now_ms()
                _refreshed_features, refreshed_ranks = _startup_ranks(
                    refreshed,
                    as_of_ms=rank_observed_at_ms,
                )
                rank_tracker.update(
                    refreshed_ranks,
                    observed_at_ms=rank_observed_at_ms,
                )
                await refresh_funding()
                await capture_due_replacement_funding(
                    now_ms=utc_now_ms()
                )
                if _stop_requested(stop_path):
                    exit_reason = "upgrade_requested"
                    break

                if now_ms >= next_selection_refresh_ms:
                    pinned = tuple(
                        position.market for position in execution.account.positions
                    )
                    desired = _ranked_selection(
                        refreshed,
                        as_of_ms=now_ms,
                        deep_limit=config.deep_limit,
                        pinned=pinned,
                    )
                    desired_keys = {market.canonical for market in desired}
                    added = tuple(
                        market
                        for market in desired
                        if market.canonical not in selected_keys
                    )
                    for market in added:
                        snapshot = refreshed.get(market.canonical)
                        if snapshot is None:
                            raise RuntimeError(
                                f"newly selected market missing from registry: {market.canonical}"
                            )
                        await pump.process(
                            _record_from_public(market_snapshot_record_event(snapshot))
                        )
                        for candle in await _warmup_market(
                            reader,
                            market,
                            end_ms=now_ms,
                            config=config,
                        ):
                            await pump.process(
                                _record_from_public(candle_record_event(candle))
                            )
                    if desired_keys != selected_keys:
                        for task in supervisor_tasks:
                            task.cancel()
                        await asyncio.gather(*supervisor_tasks, return_exceptions=True)
                        selected = desired
                        selected_keys = desired_keys
                        pipeline.reconcile_markets(selected)
                        pump.reconcile_cadence_shadow(selected)
                        _supervisors, supervisor_tasks = await start_supervisors(selected)
                    next_selection_refresh_ms = (
                        now_ms + config.selection_refresh_seconds * 1000
                    )

                if _stop_requested(stop_path):
                    exit_reason = "upgrade_requested"
                    break

                _emit_operational_live_status(
                    execution,
                    pump,
                    selected,
                    timestamp_ms=now_ms,
                )

                if now_ms >= next_checkpoint_ms:
                    persist_checkpoint()
                    next_checkpoint_ms = now_ms + config.checkpoint_seconds * 1000

                failed = tuple(
                    task for task in supervisor_tasks if task.done() and not task.cancelled()
                )
                for task in failed:
                    exc = task.exception()
                    if exc is not None:
                        raise exc
        finally:
            replacement_funding_oracle_task.cancel()
            for task in supervisor_tasks:
                task.cancel()
            await asyncio.gather(
                *supervisor_tasks,
                replacement_funding_oracle_task,
                return_exceptions=True,
            )

        persist_checkpoint()
        ended_at_ms = utc_now_ms()
        closed_trades = tuple(journal.iter_trades())
        summary = ContinuousPaperSummary(
            started_at_ms=started_at_ms,
            ended_at_ms=ended_at_ms,
            exit_reason=exit_reason,
            selected_markets=tuple(market.canonical for market in selected),
            processed_records=pump.processed_records,
            journal_observations=pump.journal_observations,
            closed_trades=len(closed_trades),
            session_closed_trades=pump.session_closed_trades,
            feature_snapshot_count=len(feature_store.iter_verified()),
            feature_snapshot_state_digest=feature_store.state_digest,
            opening_lineage_count=opening_lineage_store.record_count,
            opening_lineage_state_digest=opening_lineage_store.state_digest,
            opening_rank_count=opening_rank_store.record_count,
            opening_rank_state_digest=opening_rank_store.state_digest,
            opening_rank_capture_error=(
                None
                if opening_lineage_sink is None
                else opening_lineage_sink.rank_error
            ),
            opening_fill_liquidity_count=(
                opening_fill_liquidity_store.record_count
            ),
            opening_fill_liquidity_state_digest=(
                opening_fill_liquidity_store.state_digest
            ),
            opening_fill_liquidity_capture_error=(
                opening_fill_liquidity_sink.error
            ),
            opening_opportunity_count=(
                opening_opportunity_store.record_count
            ),
            opening_opportunity_approved_count=(
                opening_opportunity_store.approved_count
            ),
            opening_opportunity_rejected_count=(
                opening_opportunity_store.rejected_count
            ),
            opening_opportunity_rank_complete_count=(
                opening_opportunity_store.complete_rank_count
            ),
            opening_opportunity_state_digest=(
                opening_opportunity_store.state_digest
            ),
            opening_opportunity_capture_error=(
                opening_opportunity_sink.error
            ),
            opening_opportunity_path_count=(
                opening_opportunity_path_store.record_count
            ),
            opening_opportunity_path_complete_count=(
                opening_opportunity_path_store.complete_count
            ),
            opening_opportunity_path_state_digest=(
                opening_opportunity_path_store.state_digest
            ),
            opening_opportunity_path_capture_error=(
                opening_opportunity_sink.path_error
            ),
            opening_opportunity_exit_book_registration_count=(
                opening_opportunity_exit_book_store.registration_count
            ),
            opening_opportunity_exit_book_capture_count=(
                opening_opportunity_exit_book_store.capture_count
            ),
            opening_opportunity_exit_book_pending_count=(
                opening_opportunity_exit_book_store.pending_count(
                    now_ms=ended_at_ms
                )
            ),
            opening_opportunity_exit_book_missed_count=(
                opening_opportunity_exit_book_store.missed_count(
                    now_ms=ended_at_ms
                )
            ),
            opening_opportunity_exit_book_state_digest=(
                opening_opportunity_exit_book_store.state_digest
            ),
            opening_opportunity_exit_book_capture_error=(
                opening_opportunity_sink.exit_book_error
            ),
            replacement_funding_registration_count=(
                replacement_funding_store.registration_count
            ),
            replacement_funding_required_boundary_count=(
                replacement_funding_store.required_boundary_count
            ),
            replacement_funding_oracle_candidate_count=(
                replacement_funding_store.oracle_candidate_count
            ),
            replacement_funding_capture_count=(
                replacement_funding_store.record_count
            ),
            replacement_funding_pending_count=(
                replacement_funding_store.pending_count(
                    now_ms=ended_at_ms
                )
            ),
            replacement_funding_missed_count=(
                replacement_funding_store.missed_count(
                    now_ms=ended_at_ms
                )
            ),
            replacement_funding_state_digest=(
                replacement_funding_store.state_digest
            ),
            replacement_funding_capture_error=(
                opening_opportunity_sink.funding_error
            ),
            trade_path_count=trade_path_store.record_count,
            trade_path_open_count=trade_path_store.open_path_count,
            trade_path_state_digest=trade_path_store.state_digest,
            trade_path_capture_error=trade_path_sink.error,
            open_positions=len(execution.account.positions),
            equity=execution.account.equity,
            execution_healthy=execution.health.healthy_for_new_exposure,
            execution_reason_codes=execution.health.reason_codes,
        )
        _write_json_atomic(root / SUMMARY_FILENAME, summary.payload())
        return summary
    finally:
        facts.close()
        journal.close()
        execution.close()
