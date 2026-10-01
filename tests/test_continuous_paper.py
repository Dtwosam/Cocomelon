from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from cocomelon.continuous_paper import (
    RUN_ID,
    ContinuousPaperConfig,
    _account_lifecycle_bridge_payload,
    _closed_trade_concentration_payload,
    _closed_trade_friction_payload,
    _closed_trade_robustness_payload,
    _closed_trade_stability_payload,
    _closed_trade_stop_reentry_payload,
    _closed_trade_utc_hour_payload,
    _ContinuousDelayedEntryExecutionShadowSink,
    _ContinuousEntryMidMarkoutSink,
    _ContinuousOpeningFillLiquiditySink,
    _ContinuousProfitLockExecutionShadowSink,
    _ContinuousTradePathSink,
    _delayed_entry_contribution_decomposition_funding_payload,
    _delayed_entry_contribution_decomposition_payload,
    _delayed_entry_fill_weighted_funding_payload,
    _delayed_entry_fill_weighted_payload,
    _delayed_entry_fixed_schedule_portfolio_payload,
    _delayed_entry_mtm_portfolio_payload,
    _delayed_entry_pair_fill_weighted_payload,
    _delayed_entry_portfolio_capacity_payload,
    _delayed_entry_risk_geometry_payload,
    _delayed_entry_same_exit_payload,
    _delayed_entry_same_exit_stop_validity_payload,
    _delayed_entry_stop_exit_proxy_payload,
    _delayed_entry_stop_l2_replay_payload,
    _delayed_entry_stop_survivability_payload,
    _drawdown_payload,
    _entry_decision_age_payload,
    _entry_markout_payload,
    _entry_markout_predictiveness_payload,
    _excursion_timing_payload,
    _iter_until_stop,
    _load_checkpoint,
    _opening_fill_liquidity_payload,
    _opening_rank_attribution_payload,
    _position_action_from_payload,
    _position_action_payload,
    _position_protection_metrics,
    _profit_lock_counterfactual_payload,
    _prospective_candidate_stack_overlap_payload,
    _prospective_combined_entry_filter_payload,
    _prospective_consecutive_loss_cooldown_shadow_payload,
    _prospective_full_stack_capacity_reflow_payload,
    _prospective_full_stack_entry_exit_payload,
    _prospective_momentum_band_entry_payload,
    _prospective_two_strike_stop_filter_payload,
    _record_from_gap,
    _record_from_payload,
    _record_from_stream,
    _record_payload,
    _RecordPump,
    _restore_adaptive_delay_selector,
    _restore_cadence_shadow,
    _restore_delay_selector_comparison,
    _restore_delayed_entry_execution_shadow,
    _restore_drawdown_tracker,
    _restore_entry_mid_markout_shadow,
    _restore_fill_aware_delay_selector,
    _restore_profit_lock_execution_shadow,
    _restore_prospective_delayed_price_confirmation,
    _restore_prospective_entry_filter,
    _restore_prospective_momentum_band_entry,
    _restore_prospective_top10_rank_filter,
    _restore_prospective_two_strike_stop_filter,
    _stop_requested,
)
from cocomelon.domain.execution import (
    PaperExecutionConfig,
    PositionAction,
    PositionActionType,
)
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import ReplayRecord, SourceRecordKind
from cocomelon.domain.stream import DataGap, StreamEvent, StreamKind
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.execution.accounting import PaperPosition, PositionSide
from cocomelon.research.delayed_entry_execution_shadow import (
    DelayedEntryExecutionShadow,
)
from cocomelon.research.profit_lock_execution_shadow import (
    ProfitLockExecutionShadow,
)
from cocomelon.research.prospective_momentum_band_entry import (
    EMBARGO_MS as MOMENTUM_BAND_EMBARGO_MS,
)
from cocomelon.research.prospective_momentum_band_entry import (
    ProspectiveMomentumBandEntryState,
)
from cocomelon.research.prospective_two_strike_stop_filter import (
    EMBARGO_MS as TWO_STRIKE_EMBARGO_MS,
)
from cocomelon.research.prospective_two_strike_stop_filter import (
    ProspectiveTwoStrikeStopFilterState,
)


def test_candidate_stack_overlap_telemetry_fails_open() -> None:
    payload = _prospective_candidate_stack_overlap_payload(
        SimpleNamespace(iter_trades=lambda: ()),  # type: ignore[arg-type]
        {},
        {},
        {},
    )

    assert payload["enabled"] is False
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False
    assert payload["changes_readiness_gate"] is False
    assert "started_at_ms" in str(payload["error"])
def test_full_stack_capacity_reflow_telemetry_fails_open() -> None:
    payload = _prospective_full_stack_capacity_reflow_payload(
        SimpleNamespace(iter_records=lambda: ()),  # type: ignore[arg-type]
        SimpleNamespace(iter_records=lambda: ()),  # type: ignore[arg-type]
        SimpleNamespace(iter_trades=lambda: ()),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(started_at_ms=0),  # type: ignore[arg-type]
        SimpleNamespace(started_at_ms=0),  # type: ignore[arg-type]
        SimpleNamespace(started_at_ms=0),  # type: ignore[arg-type]
        {},
        {},
        {},
        PaperExecutionConfig(),
        position_history_loader=lambda _plan_id, _through_ms: (),
    )

    assert payload["enabled"] is False
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False
    assert payload["changes_readiness_gate"] is False
    assert "decision map" in str(payload["error"])


def test_full_stack_capacity_reflow_preserves_lineage_when_fill_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def evaluation(*_args: object, **_kwargs: object) -> object:
        return SimpleNamespace(
            releases=(),
            summary={
                "research_only": True,
                "execution_authority": False,
                "promotion_authority": False,
                "descriptive_only": True,
                "changes_readiness_gate": False,
                "integrity_clean": True,
            },
        )

    def fail_fill(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("fill boom")

    monkeypatch.setattr(
        "cocomelon.continuous_paper."
        "prospective_full_stack_capacity_reflow",
        evaluation,
    )
    monkeypatch.setattr(
        "cocomelon.continuous_paper."
        "prospective_capacity_reflow_fill_feasibility_summary",
        fail_fill,
    )

    payload = _prospective_full_stack_capacity_reflow_payload(
        SimpleNamespace(iter_records=lambda: ()),  # type: ignore[arg-type]
        SimpleNamespace(iter_records=lambda: ()),  # type: ignore[arg-type]
        SimpleNamespace(iter_trades=lambda: ()),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(started_at_ms=0),  # type: ignore[arg-type]
        SimpleNamespace(started_at_ms=0),  # type: ignore[arg-type]
        SimpleNamespace(started_at_ms=0),  # type: ignore[arg-type]
        {},
        {},
        {},
        PaperExecutionConfig(),
        position_history_loader=lambda _plan_id, _through_ms: (),
    )

    assert payload["enabled"] is True
    assert payload["integrity_clean"] is True
    assert payload["replacement_entries_modeled"] is False
    fill = payload["fill_feasibility"]
    assert isinstance(fill, dict)
    assert fill["enabled"] is False
    assert fill["error"] == "RuntimeError: fill boom"


def test_full_stack_entry_exit_telemetry_fails_open() -> None:
    payload = _prospective_full_stack_entry_exit_payload(
        SimpleNamespace(iter_trades=lambda: ()),  # type: ignore[arg-type]
        {},
        {},
        {},
        {},
        SimpleNamespace(started_at_ms=0),  # type: ignore[arg-type]
    )

    assert payload["enabled"] is False
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False
    assert payload["changes_readiness_gate"] is False
    assert "ProspectiveFullStackEntryExitError" in str(
        payload["error"]
    )


def test_continuous_config_requires_aligned_refresh_interval() -> None:
    with pytest.raises(ValueError, match="divisible"):
        ContinuousPaperConfig(
            duration_seconds=60,
            context_poll_seconds=60,
            selection_refresh_seconds=61,
        )


def test_gap_record_preserves_recovered_interval() -> None:
    gap = DataGap(
        stream_id="l2Book:BTC",
        started_ms=1_000,
        ended_ms=1_500,
        reason="recovered",
    )
    record = _record_from_gap(gap)
    assert record.record_kind is SourceRecordKind.DATA_GAP
    assert record.available_at_ms == 1_000
    assert record.payload == {
        "ended_ms": 1_500,
        "reason": "recovered",
        "started_ms": 1_000,
        "stream_id": "l2Book:BTC",
    }


def test_stream_record_round_trip_is_canonical() -> None:
    event = StreamEvent(
        kind=StreamKind.ACTIVE_ASSET_CTX,
        market=MarketId("", "BTC"),
        exchange_time_ms=2_000,
        receive_time=datetime.fromtimestamp(2, tz=UTC),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key="ctx-1",
        payload={
            "mark_px": Decimal("100"),
            "mid_px": Decimal("100.1"),
            "oracle_px": Decimal("99.9"),
            "funding": Decimal("0.0001"),
            "open_interest": Decimal("50"),
        },
    )
    record = _record_from_stream(event)
    restored = _record_from_payload(_record_payload(record))
    assert restored == record
    assert RUN_ID == "continuous-paper-mainnet-v1"


def test_runtime_source_exposes_structured_live_heartbeat() -> None:
    source = Path("src/cocomelon/continuous_paper.py").read_text(encoding="utf-8")
    assert "COCOMELON_PAPER_HEARTBEAT " in source
    assert '"paper_only": True' in source
    assert '"live_orders": False' in source
    assert '"positions": positions' in source
    assert '"stop_price": str(position.stop_price)' in source
    assert '"session_decision_epochs"' in source
    assert '"session_decisions"' in source
    assert '"session_risk"' in source
    assert '"open_planned_risk"' in source
    assert '"open_planned_risk_fraction_of_equity"' in source
    assert '"recent_closed_trades"' in source
    assert '"session_closed_trades"' in source
    assert '"net_pnl": str(trade.net_pnl)' in source
    assert '"net_r": str(trade.net_r)' in source
    assert '"exit_reason": trade.exit_reason' in source
    assert 'CADENCE_SHADOW_STATE_FILENAME = "cadence-shadow-state.json"' in source
    assert "pump.cadence_shadow.state_payload()" in source
    assert 'ContinuousPaperTradePathStore(root / "trade-paths")' in source
    assert 'OriginalStopBookEvidenceStore(' in source
    assert 'root / "original-stop-books"' in source
    assert "original_stop_book_capture" in source
    assert "closed_lifecycle_sink=trade_path_sink" in source
    assert '"trade_path_count": self.trade_path_count' in source
    assert '"trade_path_open_count": self.trade_path_open_count' in source
    assert '"trade_path_state_digest": self.trade_path_state_digest' in source
    assert "trade_path_sink.checkpoint(pipeline.open_lifecycle_mark_paths)" in source
    assert '"trade_path_capture_error": self.trade_path_capture_error' in source
    assert '"trade_path_evidence": {' in source
    assert '"original_stop_book_evidence": {' in source
    assert '"captured_books": original_stop_book_store.record_count' in source
    assert '"pending_crossings": original_stop_book_store.pending_count' in source
    assert '"capture_error": original_stop_book_capture.error' in source
    assert '"closed_path_count": trade_path_store.record_count' in source
    assert '"staged_open_path_count": trade_path_store.open_path_count' in source
    assert '"capture_error": trade_path_capture_error' in source
    assert '"profit_lock_counterfactual": profit_lock_counterfactual' in source
    assert "evaluate_profit_lock_state(journal, trade_path_store)" in source
    assert "profit_lock_readiness(study)" in source
    assert '"min_complete_paths": MIN_COMPLETE_PATHS' in source
    assert '"min_activated_trades_per_rule"' in source
    assert '"min_triggered_trades_per_rule"' in source
    assert '"readiness_status"' in source
    assert (
        'PROFIT_LOCK_EXECUTION_SHADOW_STATE_FILENAME = (' in source
    )
    assert (
        'DELAYED_ENTRY_EXECUTION_SHADOW_STATE_FILENAME = (' in source
    )
    assert (
        'DELAYED_ENTRY_120S_EXECUTION_SHADOW_STATE_FILENAME = (' in source
    )
    assert "position_research_observer=(" in source
    assert "_CompositePositionResearchObserver(" in source
    assert source.count(
        "opening_plan_loader=execution.store.load_plan"
    ) >= 3
    assert "opening_lineage_source" in source
    assert "_position_with_original_stop(" in source
    assert '"profit_lock_execution_shadow": (' in source
    assert '"delayed_entry_execution_shadow": (' in source
    assert '"delayed_entry_120s_execution_shadow": (' in source
    assert '"delayed_entry_pair": delayed_entry_pair' in source
    assert (
        '"delayed_entry_pair_fill_weighted": (' in source
    )
    assert '"delayed_entry_same_exit": delayed_entry_same_exit' in source
    assert '"delayed_entry_fill_weighted": delayed_entry_fill_weighted' in source
    assert (
        '"delayed_entry_fill_weighted_funding": (' in source
    )
    assert "delayed_entry_funding_corrected_fill_weighted(" in source
    assert (
        '"delayed_entry_fixed_schedule_portfolio": (' in source
    )
    assert "delayed_entry_fixed_schedule_portfolio(" in source
    assert '"delayed_entry_mtm_portfolio": (' in source
    assert "delayed_entry_mtm_portfolio(" in source
    assert '"delayed_entry_stop_survivability": (' in source
    assert "delayed_entry_stop_survivability(" in source
    assert (
        '"delayed_entry_same_exit_stop_validity": (' in source
    )
    assert "delayed_entry_same_exit_stop_validity(" in source
    assert '"delayed_entry_stop_exit_proxy": (' in source
    assert "delayed_entry_stop_exit_proxy_range(" in source
    assert '"delayed_entry_stop_l2_replay": (' in source
    assert "delayed_entry_stop_l2_replay(" in source
    assert "capture_error=original_stop_book_capture.error" in source
    assert "def _operational_live_status_payload(" in source
    assert '"heartbeat_scope": "operational"' in source
    assert '"delayed_entry_portfolio_capacity": (' in source
    assert "delayed_entry_portfolio_capacity_overlay(" in source
    assert (
        '"delayed_entry_contribution_decomposition": (' in source
    )
    assert "delayed_entry_contribution_decomposition(" in source
    assert (
        '"delayed_entry_contribution_decomposition_funding": (' in source
    )
    assert "delayed_entry_funding_decomposition(" in source
    assert '"delayed_entry_risk_geometry": delayed_entry_risk_geometry' in source
    assert "delayed_entry_risk_geometry_summary(" in source
    assert "execution.store.load_plan" in source
    assert "delayed_entry_same_exit_contribution(" in source
    assert "delayed_entry_fill_weighted_contribution(" in source
    assert "delayed_entry_pair_fill_weighted_summary(" in source
    assert "profit_lock_execution_shadow.shadow.state_payload()" in source
    assert "delayed_entry_execution_shadow.shadow.state_payload()" in source
    assert (
        "delayed_entry_120s_execution_shadow.shadow.state_payload()"
        in source
    )
    assert "profit_lock_execution_readiness(payload)" in source
    assert "reconcile_open_positions(" in source
    assert '"lineage_mismatch_closed_trades"' in source
    assert '"orphaned_restored_positions"' in source
    assert '"min_economically_evaluated_trades_per_rule"' in source
    assert '"min_simulated_full_closes_per_rule"' in source
    assert (
        'PROSPECTIVE_ENTRY_FILTER_STATE_FILENAME = (' in source
    )
    assert '"prospective_entry_filter": prospective_entry_filter' in source
    assert "prospective_entry_filter_state.payload()" in source
    assert (
        'PROSPECTIVE_DELAYED_PRICE_CONFIRM_STATE_FILENAME = (' in source
    )
    assert (
        '"prospective_delayed_price_confirmation": (' in source
    )
    assert (
        "prospective_delayed_price_confirmation_state.payload()"
        in source
    )
    assert (
        'PROSPECTIVE_TOP10_RANK_FILTER_STATE_FILENAME = (' in source
    )
    assert (
        'PROSPECTIVE_COMBINED_ENTRY_FILTER_STATE_FILENAME = (' in source
    )
    assert (
        'PROSPECTIVE_SIDE_CONDITIONED_DELAY_STATE_FILENAME = (' in source
    )
    assert "_restore_prospective_side_conditioned_delay(" in source
    assert "prospective_side_conditioned_delay_state.payload()" in source
    assert (
        'ADAPTIVE_DELAY_SELECTOR_STATE_FILENAME = (' in source
    )
    assert '"adaptive_delay_selector": adaptive_delay_selector' in source
    assert "adaptive_delay_selector_state.payload()" in source
    assert "adaptive_delay_selector_summary(" in source
    assert (
        'FILL_AWARE_DELAY_SELECTOR_STATE_FILENAME = (' in source
    )
    assert (
        '"fill_aware_delay_selector": fill_aware_delay_selector'
        in source
    )
    assert "fill_aware_delay_selector_state.payload()" in source
    assert "fill_aware_delay_selector_summary(" in source
    assert (
        'DELAY_SELECTOR_COMPARISON_STATE_FILENAME = (' in source
    )
    assert (
        '"delay_selector_comparison": delay_selector_comparison'
        in source
    )
    assert "delay_selector_comparison_state.payload()" in source
    assert "delay_selector_comparison_summary(" in source
    assert (
        '"prospective_top10_rank_filter": (' in source
    )
    assert "prospective_top10_rank_filter_state.payload()" in source
    assert (
        'PROSPECTIVE_TRADE_QUALITY_STATE_FILENAME = (' in source
    )
    assert '"prospective_trade_quality": prospective_trade_quality' in source
    assert "prospective_trade_quality_state.payload()" in source
    assert "prospective_trade_quality_summary(" in source
    assert "prospective_combined_entry_filter_state.payload()" in source
    assert (
        '"prospective_combined_entry_filter": (' in source
    )
    assert (
        'PROSPECTIVE_MOMENTUM_BAND_ENTRY_STATE_FILENAME = ('
        in source
    )
    assert "prospective-momentum-band-entry-state.json" in source
    assert "_restore_prospective_momentum_band_entry(" in source
    assert "prospective_momentum_band_entry_state.payload()" in source
    assert '"prospective_momentum_band_entry": (' in source
    assert "evaluate_prospective_momentum_band_entry(" in source
    assert (
        'PROSPECTIVE_TWO_STRIKE_STOP_FILTER_STATE_FILENAME = ('
        in source
    )
    assert "prospective-two-strike-stop-filter-state.json" in source
    assert "_restore_prospective_two_strike_stop_filter(" in source
    assert (
        'PROSPECTIVE_BREAKEVEN_PROFIT_LOCK_STATE_FILENAME = ('
        in source
    )
    assert "prospective-breakeven-profit-lock-state.json" in source
    assert "_restore_prospective_breakeven_profit_lock(" in source
    assert "prospective_breakeven_profit_lock_state.payload()" in source
    assert "prospective_two_strike_stop_filter_state.payload()" in source
    assert (
        '"prospective_two_strike_stop_filter": (' in source
    )
    assert "evaluate_prospective_two_strike_stop_filter(" in source
    assert "evaluate_prospective_combined_entry_filter(" in source
    assert "evaluate_prospective_combined_matched_overlap(" in source
    assert '"matched_standalone_overlap"' in source
    assert '"day_start_ms": execution.account.day_start_ms' in source
    assert '"day_start_equity": str(execution.account.day_start_equity)' in source
    assert '"daily_realized_pnl": str(' in source
    assert "evaluate_prospective_capacity_reflow_opportunities(" in source
    assert '"prospective_capacity_reflow_opportunities": (' in source
    assert "evaluate_prospective_capacity_reflow_release_lineage(" in source
    assert '"prospective_capacity_reflow_release_lineage": (' in source
    assert (
        "evaluate_prospective_capacity_reflow_fill_feasibility("
        in source
    )
    assert (
        '"prospective_capacity_reflow_fill_feasibility": ('
        in source
    )
    assert (
        "evaluate_prospective_capacity_reflow_exit_fill("
        in source
    )
    assert (
        '"prospective_capacity_reflow_exit_fill": ('
        in source
    )
    assert (
        "evaluate_prospective_capacity_reflow_realized_pnl("
        in source
    )
    assert (
        '"prospective_capacity_reflow_realized_pnl": ('
        in source
    )
    assert "ProspectiveReplacementExitPolicyState(" in source
    assert (
        'PROSPECTIVE_REPLACEMENT_EXIT_POLICY_STATE_FILENAME = ('
        in source
    )
    assert 'prospective-replacement-5m-exit-state.json' in source
    assert "prospective_replacement_exit_policy_summary(" in source
    assert '"prospective_replacement_exit_policy": (' in source
    assert "prospective_replacement_exit_robustness(" in source
    assert '"prospective_replacement_exit_robustness": (' in source
    assert "prospective_replacement_exit_readiness(" in source
    assert '"prospective_replacement_exit_readiness": (' in source
    assert "_restore_prospective_replacement_exit_policy(" in source
    assert "prospective_replacement_exit_policy_state.payload()" in source
    realized_pnl_call = source.index(
        "evaluate_prospective_capacity_reflow_realized_pnl("
    )
    assert source.index(
        "replacement_funding_store,",
        realized_pnl_call,
    ) > realized_pnl_call
    assert (
        "evaluate_prospective_capacity_reflow_forward_markout("
        in source
    )
    assert (
        '"prospective_capacity_reflow_forward_markout": ('
        in source
    )
    assert (
        "evaluate_prospective_capacity_reflow_forward_excursion("
        in source
    )
    assert (
        '"prospective_capacity_reflow_forward_excursion": ('
        in source
    )
    assert "opening_opportunity_path_store," in source
    assert "execution.store.load_position_history(" in source
    assert "evaluate_prospective_daily_loss_lockout_reflow(" in source
    assert '"prospective_daily_loss_lockout_reflow": (' in source
    assert "execution.store.load_execution_history(plan_id)[1]" in source
    assert "execution.store.load_funding_for_market(" in source
    assert "opening_lineage_store," in source
    assert 'ContinuousPaperOpeningRankStore(' in source
    assert 'root / "opening-ranks"' in source
    assert '"opening_scanner_rank": opening_rank' in source
    assert '"opening_rank_count": self.opening_rank_count' in source
    assert '"opening_rank_state_digest": self.opening_rank_state_digest' in source
    assert "OpeningFillLiquidityStore(" in source
    assert 'root / "opening-fill-liquidity"' in source
    assert "opening_research_observer=(" in source
    assert '"opening_fill_liquidity": opening_fill_liquidity' in source
    assert '"opening_fill_liquidity_count": self.opening_fill_liquidity_count' in source
    assert (
        '"opening_fill_liquidity_state_digest": (' in source
    )
    assert "ContinuousPaperOpeningOpportunityStore(" in source
    assert 'root / "opening-opportunities"' in source
    assert "ContinuousPaperOpeningOpportunityPathStore(" in source
    assert 'root / "opening-opportunity-paths"' in source
    assert "ContinuousPaperOpeningOpportunityExitBookStore(" in source
    assert 'root / "opening-opportunity-exit-books"' in source
    assert "ContinuousPaperReplacementFundingStore(" in source
    assert 'root / "replacement-funding-boundaries"' in source
    assert "capture_replacement_funding_oracles()" in source
    assert "reader.meta_and_asset_ctxs" in source
    assert source.count("replacement_funding_store.observe_snapshot(") == 1
    precise_raw_at = source.index(
        "raw = await asyncio.to_thread(\n"
        "                        reader.meta_and_asset_ctxs"
    )
    precise_received_at = source.index(
        "received_at_ms = utc_now_ms()",
        precise_raw_at,
    )
    precise_normalize_at = source.index(
        "snapshots = normalize_meta_and_asset_ctxs(",
        precise_received_at,
    )
    assert precise_raw_at < precise_received_at < precise_normalize_at
    assert "capture_due_replacement_funding(" in source
    assert "reader.funding_history" in source
    assert "funding_boundary_for_record_time(" in source
    assert '"replacement_funding_evidence": {' in source
    assert '"required_boundaries": (' in source
    assert '"captured_boundaries": replacement_funding_store.record_count' in source
    assert "opening_opportunity_sink.observe_snapshots(" in source
    assert "capture_due_exit_books(" in source
    assert "reader.l2_book" in source
    assert "normalize_l2_book_snapshot(" in source
    assert '"opening_opportunity_evidence": {' in source
    assert '"exit_book_captures": (' in source
    assert '"exit_book_state_digest": (' in source
    assert '"forward_mark_paths": (' in source
    assert '"forward_mark_paths_complete": (' in source
    assert '"forward_mark_state_digest": (' in source
    assert '"opening_opportunity_count": self.opening_opportunity_count' in source
    assert '"opening_opportunity_state_digest": (' in source
    assert "opportunity_evidence_from_trace(" in source
    assert "trace.risk_request.timestamp_ms" in source
    assert (
        '"account_lifecycle_economics": account_lifecycle_economics'
        in source
    )
    assert "account_lifecycle_bridge(" in source
    assert (
        '"closed_trade_concentration": closed_trade_concentration'
        in source
    )
    assert "closed_trade_concentration_summary(" in source
    assert '"closed_trade_friction": closed_trade_friction' in source
    assert "closed_trade_friction_summary(" in source
    assert '"closed_trade_robustness": (' in source
    assert "closed_trade_robustness(" in source
    assert '"closed_trade_stability": (' in source
    assert "closed_trade_stability(" in source
    assert '"closed_trade_utc_hour": closed_trade_utc_hour' in source
    assert "closed_trade_utc_hour_summary(" in source
    assert '"entry_decision_age": entry_decision_age' in source
    assert "entry_decision_age_summary(" in source
    assert 'DRAWDOWN_STATE_FILENAME = "drawdown-state.json"' in source
    assert '"drawdown": drawdown' in source
    assert "drawdown_tracker.state_payload()" in source
    assert "drawdown_tracker.observe(" in source
    assert '"entry_markout": entry_markout' in source
    assert '"entry_markout_predictiveness": (' in source
    assert "entry_markout_predictiveness(" in source
    assert '"excursion_timing": excursion_timing' in source
    assert "excursion_timing_summary(" in source
    assert "entry_mid_markout_readiness(payload)" in source
    assert '"min_fresh_observations_per_horizon"' in source
    assert '"max_non_fresh_fraction"' in source
    assert "entry_markout_summary(" in source
    assert "opening_rank_store," in source
    assert "entry_markout_readiness(payload)" in source
    assert '"min_observations_per_horizon"' in source
    assert '"readiness_status"' in source
    assert '"missing_observations"' in source
    assert (
        'ENTRY_MID_MARKOUT_SHADOW_STATE_FILENAME = (' in source
    )
    assert 'entry_mid_markout_shadow=' in source
    assert '"entry_mid_markout_shadow": entry_mid_markout' in source
    assert "entry_mid_markout_shadow.shadow.state_payload()" in source


def test_account_lifecycle_bridge_telemetry_fails_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("bridge boom")

    monkeypatch.setattr(
        "cocomelon.continuous_paper.account_lifecycle_bridge",
        fail,
    )
    payload = _account_lifecycle_bridge_payload(
        SimpleNamespace(account=SimpleNamespace()),  # type: ignore[arg-type]
        SimpleNamespace(iter_trades=lambda: ()),  # type: ignore[arg-type]
    )

    assert payload["enabled"] is False
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False
    assert payload["error"] == "RuntimeError: bridge boom"


def test_drawdown_telemetry_fails_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("drawdown boom")

    monkeypatch.setattr(
        "cocomelon.continuous_paper.drawdown_summary",
        fail,
    )
    payload = _drawdown_payload(
        SimpleNamespace(
            account=SimpleNamespace(
                starting_cash=Decimal("10000")
            )
        ),  # type: ignore[arg-type]
        SimpleNamespace(iter_trades=lambda: ()),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        checkpoint_seconds=30,
    )

    assert payload["enabled"] is False
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False
    assert payload["error"] == "RuntimeError: drawdown boom"


def test_drawdown_restore_failure_is_fail_open(
    tmp_path: Path,
) -> None:
    path = tmp_path / "drawdown-state.json"
    path.write_text("{not-json", encoding="utf-8")

    tracker = _restore_drawdown_tracker(
        path,
        started_at_ms=123,
    )

    assert tracker.started_at_ms == 123
    assert tracker.observation_count == 0
    assert tracker.state_restore_error is not None
    assert "JSONDecodeError" in tracker.state_restore_error


def test_entry_decision_age_telemetry_fails_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("entry age boom")

    monkeypatch.setattr(
        "cocomelon.continuous_paper.entry_decision_age_summary",
        fail,
    )
    payload = _entry_decision_age_payload(
        SimpleNamespace(iter_trades=lambda: ()),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
    )

    assert payload["enabled"] is False
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False
    assert payload["error"] == "RuntimeError: entry age boom"


def test_closed_trade_concentration_telemetry_fails_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("concentration boom")

    monkeypatch.setattr(
        "cocomelon.continuous_paper.closed_trade_concentration_summary",
        fail,
    )
    payload = _closed_trade_concentration_payload(
        SimpleNamespace(iter_trades=lambda: ()),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
    )

    assert payload["enabled"] is False
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False
    assert payload["error"] == "RuntimeError: concentration boom"


def test_closed_trade_stop_reentry_telemetry_fails_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("reentry boom")

    monkeypatch.setattr(
        "cocomelon.continuous_paper.closed_trade_stop_reentry_summary",
        fail,
    )
    payload = _closed_trade_stop_reentry_payload(
        SimpleNamespace(iter_trades=lambda: ()),  # type: ignore[arg-type]
    )

    assert payload["enabled"] is False
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False
    assert payload["error"] == "RuntimeError: reentry boom"


def test_closed_trade_utc_hour_telemetry_fails_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("utc hour boom")

    monkeypatch.setattr(
        "cocomelon.continuous_paper.closed_trade_utc_hour_summary",
        fail,
    )
    payload = _closed_trade_utc_hour_payload(
        SimpleNamespace(iter_trades=lambda: ()),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
    )

    assert payload["enabled"] is False
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False
    assert payload["error"] == "RuntimeError: utc hour boom"


def test_closed_trade_friction_telemetry_fails_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("friction boom")

    monkeypatch.setattr(
        "cocomelon.continuous_paper.closed_trade_friction_summary",
        fail,
    )
    payload = _closed_trade_friction_payload(
        SimpleNamespace(iter_trades=lambda: ()),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
    )

    assert payload["enabled"] is False
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False
    assert payload["error"] == "RuntimeError: friction boom"


def test_closed_trade_stability_telemetry_fails_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("stability boom")

    monkeypatch.setattr(
        "cocomelon.continuous_paper.closed_trade_stability",
        fail,
    )
    payload = _closed_trade_stability_payload(
        SimpleNamespace(iter_trades=lambda: ()),  # type: ignore[arg-type]
    )

    assert payload["enabled"] is False
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False
    assert payload["error"] == "RuntimeError: stability boom"


def test_closed_trade_robustness_telemetry_fails_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("robustness boom")

    monkeypatch.setattr(
        "cocomelon.continuous_paper.closed_trade_robustness",
        fail,
    )
    payload = _closed_trade_robustness_payload(
        SimpleNamespace(iter_trades=lambda: ()),  # type: ignore[arg-type]
    )

    assert payload["enabled"] is False
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False
    assert payload["error"] == "RuntimeError: robustness boom"


def test_opening_rank_telemetry_fails_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("rank boom")

    monkeypatch.setattr(
        "cocomelon.continuous_paper.opening_rank_attribution",
        fail,
    )
    payload = _opening_rank_attribution_payload(
        SimpleNamespace(iter_trades=lambda: ()),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        capture_error=None,
    )

    assert payload["enabled"] is False
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False
    assert payload["error"] == "RuntimeError: rank boom"


def test_excursion_timing_telemetry_fails_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("timing boom")

    monkeypatch.setattr(
        "cocomelon.continuous_paper.excursion_timing_summary",
        fail,
    )
    payload = _excursion_timing_payload(
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
    )

    assert payload["enabled"] is False
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False
    assert payload["error"] == "RuntimeError: timing boom"


def test_entry_markout_predictiveness_telemetry_fails_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("predictiveness boom")

    monkeypatch.setattr(
        "cocomelon.continuous_paper.entry_markout_predictiveness",
        fail,
    )
    payload = _entry_markout_predictiveness_payload(
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
    )

    assert payload["enabled"] is False
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False
    assert payload["error"] == "RuntimeError: predictiveness boom"


def test_opening_fill_liquidity_capture_is_fail_open() -> None:
    class Store:
        def record(self, _evidence: object) -> bool:
            raise RuntimeError("liquidity store boom")

    sink = _ContinuousOpeningFillLiquiditySink(  # type: ignore[arg-type]
        Store()
    )

    sink.record_opening_trace(SimpleNamespace())  # type: ignore[arg-type]

    assert sink.error is not None
    assert sink.error.startswith("AttributeError:")


def test_opening_fill_liquidity_telemetry_fails_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("liquidity boom")

    monkeypatch.setattr(
        "cocomelon.continuous_paper.opening_fill_liquidity_attribution",
        fail,
    )
    payload = _opening_fill_liquidity_payload(
        SimpleNamespace(iter_trades=lambda: ()),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        capture_error="capture-warning",
    )

    assert payload["enabled"] is False
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False
    assert payload["capture_error"] == "capture-warning"
    assert payload["error"] == "RuntimeError: liquidity boom"


def test_entry_markout_telemetry_fails_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("markout boom")

    monkeypatch.setattr(
        "cocomelon.continuous_paper.entry_markout_summary",
        fail,
    )
    payload = _entry_markout_payload(
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
    )

    assert payload["enabled"] is False
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False
    assert payload["error"] == "RuntimeError: markout boom"


def test_profit_lock_counterfactual_telemetry_fails_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object) -> object:
        raise RuntimeError("counterfactual boom")

    monkeypatch.setattr(
        "cocomelon.continuous_paper.evaluate_profit_lock_state",
        fail,
    )

    payload = _profit_lock_counterfactual_payload(
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
    )

    assert payload["enabled"] is False
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False
    assert payload["error"] == "RuntimeError: counterfactual boom"


def test_combined_filter_profit_lock_overlap_fails_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def combined(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {
            "residual_profit_lock": {
                "research_only": True,
                "changes_readiness_gate": False,
            }
        }

    def overlap(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {
            "descriptive_only": True,
            "changes_readiness_gate": False,
        }

    monkeypatch.setattr(
        "cocomelon.continuous_paper."
        "evaluate_prospective_combined_entry_filter",
        combined,
    )
    monkeypatch.setattr(
        "cocomelon.continuous_paper."
        "evaluate_prospective_combined_matched_overlap",
        overlap,
    )

    payload = _prospective_combined_entry_filter_payload(
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        profit_lock_error="RuntimeError: path boom",
        restore_error=None,
    )

    residual = payload["residual_profit_lock"]
    assert isinstance(residual, dict)
    assert residual["enabled"] is False
    assert residual["source_error"] == "RuntimeError: path boom"
    assert payload["enabled"] is True
    assert payload["error"] is None


def test_entry_mid_markout_shadow_sink_fails_open() -> None:
    class FailingShadow:
        def observe(
            self,
            *_args: object,
            **_kwargs: object,
        ) -> None:
            raise RuntimeError("mid shadow boom")

        def summary_payload(
            self,
            *_args: object,
        ) -> dict[str, object]:
            return {}

    sink = _ContinuousEntryMidMarkoutSink(
        FailingShadow(),  # type: ignore[arg-type]
        opening_plan_loader=lambda _: None,
    )
    sink.observe(
        ReplayRecord(
            record_kind=SourceRecordKind.DATA_GAP,
            available_at_ms=1,
            source="fixture",
            schema_version=1,
            market=None,
            exchange_time_ms=None,
            event_key="gap-mid-shadow",
            payload_json=(
                '{"started_ms":1,"ended_ms":1,'
                '"reason":"fixture","stream_id":"x"}'
            ),
            event_kind=None,
        ),
        (),
        now_ms=1,
    )

    assert sink.shadow is None
    payload = sink.summary_payload(
        SimpleNamespace(),  # type: ignore[arg-type]
    )
    assert payload["enabled"] is False
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False
    assert payload["error"] == "RuntimeError: mid shadow boom"


def test_entry_mid_markout_readiness_failure_is_fail_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Shadow:
        def summary_payload(
            self,
            *_args: object,
        ) -> dict[str, object]:
            return {"fixture": True}

    def fail(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("mid readiness boom")

    monkeypatch.setattr(
        "cocomelon.continuous_paper.entry_mid_markout_readiness",
        fail,
    )
    sink = _ContinuousEntryMidMarkoutSink(
        Shadow(),  # type: ignore[arg-type]
        opening_plan_loader=lambda _: None,
    )

    payload = sink.summary_payload(
        SimpleNamespace(),  # type: ignore[arg-type]
    )

    assert sink.shadow is None
    assert payload["enabled"] is False
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False
    assert payload["error"] == "RuntimeError: mid readiness boom"


def test_entry_mid_markout_sink_uses_opening_risk_ceiling_without_mutating_position() -> None:
    captured_observe: list[PaperPosition] = []
    captured_reconcile: list[PaperPosition] = []

    class Shadow:
        def observe(
            self,
            _record: ReplayRecord,
            positions: tuple[PaperPosition, ...],
            *,
            now_ms: int,
        ) -> None:
            assert now_ms == 1
            captured_observe.extend(positions)

        def reconcile_open_positions(
            self,
            positions: tuple[PaperPosition, ...],
        ) -> None:
            captured_reconcile.extend(positions)

    market = MarketId("", "SOL")
    position = PaperPosition(
        market=market,
        side=PositionSide.LONG,
        quantity=Decimal("2"),
        average_entry_price=Decimal("100"),
        stop_price=Decimal("95"),
        opening_plan_id="open-plan-1",
        opened_at_ms=1,
        updated_at_ms=1,
        planned_risk=Decimal("7"),
    )
    plan = SimpleNamespace(
        reduce_only=False,
        market=market,
        approved_risk_amount_ceiling=Decimal("10"),
    )
    sink = _ContinuousEntryMidMarkoutSink(
        Shadow(),  # type: ignore[arg-type]
        opening_plan_loader=lambda plan_id: (
            plan if plan_id == "open-plan-1" else None
        ),
    )
    record = ReplayRecord(
        record_kind=SourceRecordKind.DATA_GAP,
        available_at_ms=1,
        source="fixture",
        schema_version=1,
        market=None,
        exchange_time_ms=None,
        event_key="gap-opening-risk-lineage",
        payload_json=(
            '{"started_ms":1,"ended_ms":1,'
            '"reason":"fixture","stream_id":"x"}'
        ),
        event_kind=None,
    )

    sink.observe(record, (position,), now_ms=1)
    sink.reconcile_open_positions((position,))

    assert position.planned_risk == Decimal("7")
    assert captured_observe[0].planned_risk == Decimal("10")
    assert captured_reconcile[0].planned_risk == Decimal("10")


def test_entry_mid_markout_restore_failure_is_fail_open(
    tmp_path: Path,
) -> None:
    path = tmp_path / "entry-mid-markout-shadow-state.json"
    path.write_text("{not-json", encoding="utf-8")

    shadow = _restore_entry_mid_markout_shadow(
        path,
        started_at_ms=789,
    )

    facts = SimpleNamespace()
    payload = shadow.summary_payload(  # type: ignore[arg-type]
        facts,
    )
    assert payload["state_restored"] is False
    assert payload["started_at_ms"] == 789
    assert "JSONDecodeError" in str(
        payload["state_restore_error"]
    )


def test_record_pump_mid_markout_failure_does_not_block_paper() -> None:
    class Pipeline:
        def on_record(
            self,
            _record: ReplayRecord,
            _now_ms: int,
        ) -> tuple[object, ...]:
            return ()

        def finalize(
            self,
            _end_ms: int,
        ) -> tuple[object, ...]:
            return ()

    class Journal:
        def iter_trades(self) -> tuple[object, ...]:
            return ()

        def record_observation(
            self,
            _observation: object,
        ) -> None:
            raise AssertionError("no observations expected")

    class FailingShadow:
        def observe(
            self,
            *_args: object,
            **_kwargs: object,
        ) -> None:
            raise RuntimeError("mid observer boom")

    sink = _ContinuousEntryMidMarkoutSink(
        FailingShadow(),  # type: ignore[arg-type]
        opening_plan_loader=lambda _: None,
    )
    pump = _RecordPump(
        Pipeline(),  # type: ignore[arg-type]
        Journal(),  # type: ignore[arg-type]
        last_available_at_ms=0,
        entry_mid_markout_shadow=sink,
        position_provider=lambda: (),
    )
    record = ReplayRecord(
        record_kind=SourceRecordKind.DATA_GAP,
        available_at_ms=1,
        source="fixture",
        schema_version=1,
        market=None,
        exchange_time_ms=None,
        event_key="gap-mid-pump",
        payload_json=(
            '{"started_ms":1,"ended_ms":1,'
            '"reason":"fixture","stream_id":"x"}'
        ),
        event_kind=None,
    )

    asyncio.run(pump.process(record))

    assert pump.processed_records == 1
    assert sink.shadow is None
    assert sink.error == "RuntimeError: mid observer boom"


def test_profit_lock_execution_shadow_sink_fails_open() -> None:
    class FailingShadow:
        def observe_mark(self, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError("shadow boom")

        def summary_payload(self) -> dict[str, object]:
            return {}

    sink = _ContinuousProfitLockExecutionShadowSink(
        FailingShadow(),  # type: ignore[arg-type]
        opening_plan_loader=lambda _plan_id: None,
    )
    sink.observe_mark(
        (),
        SimpleNamespace(),  # type: ignore[arg-type]
        now_ms=1,
    )

    assert sink.shadow is None
    payload = sink.summary_payload()
    assert payload["enabled"] is False
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False
    assert payload["error"] == "RuntimeError: shadow boom"


def test_delayed_entry_pair_fill_weighted_telemetry_fails_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("paired fill weighted boom")

    monkeypatch.setattr(
        "cocomelon.continuous_paper.delayed_entry_pair_fill_weighted_summary",
        fail,
    )
    shadow = SimpleNamespace(
        outcomes=(),
        summary_payload=lambda: {"started_at_ms": 123},
    )
    payload = _delayed_entry_pair_fill_weighted_payload(
        SimpleNamespace(iter_trades=lambda: ()),  # type: ignore[arg-type]
        SimpleNamespace(shadow=shadow, error=None),  # type: ignore[arg-type]
        SimpleNamespace(shadow=shadow, error=None),  # type: ignore[arg-type]
    )

    assert payload["enabled"] is False
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False
    assert payload["error"] == "RuntimeError: paired fill weighted boom"


def test_delayed_entry_contribution_decomposition_fails_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("decomposition boom")

    monkeypatch.setattr(
        "cocomelon.continuous_paper."
        "delayed_entry_contribution_decomposition",
        fail,
    )
    payload = _delayed_entry_contribution_decomposition_payload(
        SimpleNamespace(iter_trades=lambda: ()),  # type: ignore[arg-type]
        SimpleNamespace(
            shadow=SimpleNamespace(outcomes=()),
            error=None,
        ),  # type: ignore[arg-type]
    )

    assert payload["enabled"] is False
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False
    assert payload["error"] == "RuntimeError: decomposition boom"


def test_delayed_entry_contribution_decomposition_funding_fails_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("funding decomposition boom")

    monkeypatch.setattr(
        "cocomelon.continuous_paper."
        "delayed_entry_funding_decomposition",
        fail,
    )
    payload = _delayed_entry_contribution_decomposition_funding_payload(
        SimpleNamespace(iter_trades=lambda: ()),  # type: ignore[arg-type]
        SimpleNamespace(
            shadow=SimpleNamespace(outcomes=()),
            error=None,
        ),  # type: ignore[arg-type]
        lambda _market, _start_ms: (),
    )

    assert payload["enabled"] is False
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False
    assert payload["error"] == "RuntimeError: funding decomposition boom"


def test_delayed_entry_risk_geometry_fails_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("risk geometry boom")

    monkeypatch.setattr(
        "cocomelon.continuous_paper."
        "delayed_entry_risk_geometry_summary",
        fail,
    )
    payload = _delayed_entry_risk_geometry_payload(
        SimpleNamespace(iter_trades=lambda: ()),  # type: ignore[arg-type]
        SimpleNamespace(
            shadow=SimpleNamespace(outcomes=()),
            error=None,
        ),  # type: ignore[arg-type]
        lambda _plan_id: None,
    )

    assert payload["enabled"] is False
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False
    assert payload["error"] == "RuntimeError: risk geometry boom"


def test_delayed_entry_fixed_schedule_portfolio_fails_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("portfolio boom")

    monkeypatch.setattr(
        "cocomelon.continuous_paper.delayed_entry_fixed_schedule_portfolio",
        fail,
    )
    payload = _delayed_entry_fixed_schedule_portfolio_payload(
        SimpleNamespace(iter_trades=lambda: ()),  # type: ignore[arg-type]
        SimpleNamespace(
            shadow=SimpleNamespace(outcomes=()),
            error=None,
        ),  # type: ignore[arg-type]
        lambda _plan_id: None,
    )

    assert payload["enabled"] is False
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False
    assert payload["error"] == "RuntimeError: portfolio boom"


def test_delayed_entry_mtm_portfolio_fails_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("mtm portfolio boom")

    monkeypatch.setattr(
        "cocomelon.continuous_paper.delayed_entry_mtm_portfolio",
        fail,
    )
    payload = _delayed_entry_mtm_portfolio_payload(
        SimpleNamespace(iter_trades=lambda: ()),  # type: ignore[arg-type]
        SimpleNamespace(
            shadow=SimpleNamespace(outcomes=()),
            error=None,
        ),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        lambda _market, _start_ms: (),
    )

    assert payload["enabled"] is False
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False
    assert payload["error"] == "RuntimeError: mtm portfolio boom"


def test_delayed_entry_stop_survivability_fails_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("stop survivability boom")

    monkeypatch.setattr(
        "cocomelon.continuous_paper.delayed_entry_stop_survivability",
        fail,
    )
    payload = _delayed_entry_stop_survivability_payload(
        SimpleNamespace(iter_trades=lambda: ()),  # type: ignore[arg-type]
        SimpleNamespace(
            shadow=SimpleNamespace(outcomes=()),
            error=None,
        ),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
    )

    assert payload["enabled"] is False
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False
    assert payload["error"] == "RuntimeError: stop survivability boom"


def test_delayed_entry_same_exit_stop_validity_fails_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("stop validity boom")

    monkeypatch.setattr(
        "cocomelon.continuous_paper."
        "delayed_entry_same_exit_stop_validity",
        fail,
    )
    payload = _delayed_entry_same_exit_stop_validity_payload(
        SimpleNamespace(iter_trades=lambda: ()),  # type: ignore[arg-type]
        SimpleNamespace(
            shadow=SimpleNamespace(outcomes=()),
            error=None,
        ),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        lambda _market, _start_ms: (),
    )

    assert payload["enabled"] is False
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False
    assert payload["error"] == "RuntimeError: stop validity boom"


def test_delayed_entry_stop_exit_proxy_fails_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("stop exit proxy boom")

    monkeypatch.setattr(
        "cocomelon.continuous_paper."
        "delayed_entry_stop_exit_proxy_range",
        fail,
    )
    payload = _delayed_entry_stop_exit_proxy_payload(
        SimpleNamespace(iter_trades=lambda: ()),  # type: ignore[arg-type]
        SimpleNamespace(
            shadow=SimpleNamespace(outcomes=()),
            error=None,
        ),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        lambda _market, _start_ms: (),
        PaperExecutionConfig(),
    )

    assert payload["enabled"] is False
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False
    assert payload["error"] == "RuntimeError: stop exit proxy boom"


def test_delayed_entry_portfolio_capacity_fails_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("capacity overlay boom")

    monkeypatch.setattr(
        "cocomelon.continuous_paper.delayed_entry_portfolio_capacity_overlay",
        fail,
    )
    payload = _delayed_entry_portfolio_capacity_payload(
        SimpleNamespace(iter_trades=lambda: ()),  # type: ignore[arg-type]
        SimpleNamespace(
            shadow=SimpleNamespace(outcomes=()),
            error=None,
        ),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(load=lambda _plan_id: None),  # type: ignore[arg-type]
        lambda _plan_id: None,
        lambda _market, _start_ms: (),
        BaselineReplayConfig().risk_limits,
        BaselineReplayConfig().execution.paper_max_gross_leverage,
        BaselineReplayConfig().execution.native_perp_min_notional,
    )

    assert payload["enabled"] is False
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False
    assert payload["error"] == "RuntimeError: capacity overlay boom"


def test_delayed_entry_fill_weighted_telemetry_fails_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("fill weighted boom")

    monkeypatch.setattr(
        "cocomelon.continuous_paper.delayed_entry_fill_weighted_contribution",
        fail,
    )
    payload = _delayed_entry_fill_weighted_payload(
        SimpleNamespace(iter_trades=lambda: ()),  # type: ignore[arg-type]
        SimpleNamespace(
            shadow=SimpleNamespace(outcomes=()),
            error=None,
        ),  # type: ignore[arg-type]
    )

    assert payload["enabled"] is False
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False
    assert payload["error"] == "RuntimeError: fill weighted boom"


def test_delayed_entry_fill_weighted_funding_fails_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("funding corrected fill boom")

    monkeypatch.setattr(
        "cocomelon.continuous_paper."
        "delayed_entry_funding_corrected_fill_weighted",
        fail,
    )
    payload = _delayed_entry_fill_weighted_funding_payload(
        SimpleNamespace(iter_trades=lambda: ()),  # type: ignore[arg-type]
        SimpleNamespace(
            shadow=SimpleNamespace(outcomes=()),
            error=None,
        ),  # type: ignore[arg-type]
        lambda _market, _start_ms: (),
    )

    assert payload["enabled"] is False
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False
    assert payload["error"] == "RuntimeError: funding corrected fill boom"


def test_delayed_entry_same_exit_telemetry_fails_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("same exit boom")

    monkeypatch.setattr(
        "cocomelon.continuous_paper.delayed_entry_same_exit_contribution",
        fail,
    )
    payload = _delayed_entry_same_exit_payload(
        SimpleNamespace(iter_trades=lambda: ()),  # type: ignore[arg-type]
        SimpleNamespace(
            shadow=SimpleNamespace(outcomes=()),
            error=None,
        ),  # type: ignore[arg-type]
    )

    assert payload["enabled"] is False
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False
    assert payload["error"] == "RuntimeError: same exit boom"


def test_delayed_entry_execution_shadow_sink_fails_open() -> None:
    class FailingShadow:
        def observe_mark(self, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError("delay shadow boom")

        def summary_payload(self) -> dict[str, object]:
            return {}

    sink = _ContinuousDelayedEntryExecutionShadowSink(
        FailingShadow(),  # type: ignore[arg-type]
        opening_plan_loader=lambda _plan_id: None,
    )
    sink.observe_mark(
        (),
        SimpleNamespace(),  # type: ignore[arg-type]
        now_ms=1,
    )

    assert sink.shadow is None
    payload = sink.summary_payload()
    assert payload["enabled"] is False
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False
    assert payload["error"] == "RuntimeError: delay shadow boom"


def test_profit_lock_shadow_uses_persisted_opening_risk_envelope() -> None:
    market = MarketId("", "BTC")
    position = PaperPosition(
        market=market,
        side=PositionSide.LONG,
        quantity=Decimal("1"),
        average_entry_price=Decimal("100"),
        stop_price=Decimal("98"),
        opening_plan_id="opening-plan-profit-lock",
        opened_at_ms=1_000,
        updated_at_ms=2_000,
        initial_risk_decision_id="risk-1",
        correlation_bucket="crypto_beta",
        cost_buffer_fraction=Decimal("0.001"),
        planned_risk=Decimal("2.2"),
        venue_max_leverage=Decimal("20"),
        latest_mark=Decimal("101"),
    )
    opening_plan = SimpleNamespace(
        reduce_only=False,
        market=market,
        stop_price=Decimal("90"),
        approved_risk_amount_ceiling=Decimal("10"),
        cost_buffer_fraction=Decimal("0.002"),
    )

    class RecordingShadow:
        positions: tuple[PaperPosition, ...] = ()

        def observe_mark(
            self,
            positions: tuple[PaperPosition, ...],
            _mark_event: object,
            *,
            now_ms: int,
        ) -> None:
            assert now_ms == 2_000
            self.positions = positions

        def summary_payload(self) -> dict[str, object]:
            return {}

    shadow = RecordingShadow()
    sink = _ContinuousProfitLockExecutionShadowSink(
        shadow,  # type: ignore[arg-type]
        opening_plan_loader=lambda _plan_id: opening_plan,  # type: ignore[arg-type]
    )
    sink.observe_mark(
        (position,),
        SimpleNamespace(),  # type: ignore[arg-type]
        now_ms=2_000,
    )

    assert sink.error is None
    assert len(shadow.positions) == 1
    canonical = shadow.positions[0]
    assert canonical.quantity == position.quantity
    assert canonical.average_entry_price == position.average_entry_price
    assert canonical.stop_price == Decimal("90")
    assert canonical.planned_risk == Decimal("10")
    assert canonical.cost_buffer_fraction == Decimal("0.002")


def test_delayed_entry_shadow_uses_persisted_opening_stop() -> None:
    market = MarketId("", "BTC")
    position = PaperPosition(
        market=market,
        side=PositionSide.LONG,
        quantity=Decimal("1"),
        average_entry_price=Decimal("100"),
        stop_price=Decimal("98"),
        opening_plan_id="opening-plan-1",
        opened_at_ms=1_000,
        updated_at_ms=2_000,
        initial_risk_decision_id="risk-1",
        correlation_bucket="crypto_beta",
        cost_buffer_fraction=Decimal("0"),
        planned_risk=Decimal("10"),
        venue_max_leverage=Decimal("20"),
        latest_mark=Decimal("101"),
    )
    opening_plan = SimpleNamespace(
        reduce_only=False,
        market=market,
        stop_price=Decimal("90"),
    )
    shadow = DelayedEntryExecutionShadow(
        PaperExecutionConfig(),
        started_at_ms=0,
    )
    sink = _ContinuousDelayedEntryExecutionShadowSink(
        shadow,
        opening_plan_loader=lambda _plan_id: opening_plan,  # type: ignore[arg-type]
    )

    sink.reconcile_open_positions((position,))

    assert sink.error is None
    state = shadow.state_payload()
    open_state = state["open"]
    assert isinstance(open_state, list)
    assert len(open_state) == 1
    assert open_state[0]["initial_stop_price"] == "90"
    assert open_state[0]["initial_stop_price"] != str(
        position.stop_price
    )


def test_delayed_entry_execution_shadow_restore_failure_is_fail_open(
    tmp_path: Path,
) -> None:
    path = tmp_path / "delayed-entry-execution-shadow-state.json"
    path.write_text("{not-json", encoding="utf-8")

    shadow = _restore_delayed_entry_execution_shadow(
        path,
        PaperExecutionConfig(),
        started_at_ms=456,
    )

    payload = shadow.summary_payload()
    assert payload["state_restored"] is False
    assert payload["state_restore_error"] is not None
    assert "JSONDecodeError" in str(payload["state_restore_error"])


def test_120s_delayed_entry_restore_failure_is_fail_open(
    tmp_path: Path,
) -> None:
    path = tmp_path / "delayed-entry-120s-execution-shadow-state.json"
    path.write_text("{not-json", encoding="utf-8")

    shadow = _restore_delayed_entry_execution_shadow(
        path,
        PaperExecutionConfig(),
        started_at_ms=789,
        delay_ms=120_000,
        max_observation_lag_ms=60_000,
    )

    payload = shadow.summary_payload()
    assert payload["delay_ms"] == 120_000
    assert payload["state_restored"] is False
    assert payload["state_restore_error"] is not None
    assert "JSONDecodeError" in str(payload["state_restore_error"])


def test_profit_lock_v1_state_restarts_cleanly_on_v2_protocol(
    tmp_path: Path,
) -> None:
    path = tmp_path / "profit-lock-execution-shadow-state.json"
    old = ProfitLockExecutionShadow(
        BaselineReplayConfig().execution,
        started_at_ms=123,
    ).state_payload()
    old["schema_version"] = 1
    path.write_text(json.dumps(old), encoding="utf-8")

    restored = _restore_profit_lock_execution_shadow(
        path,
        BaselineReplayConfig().execution,
        started_at_ms=456,
    )

    payload = restored.summary_payload()
    assert payload["state_restored"] is False
    assert payload["started_at_ms"] == 456
    assert payload["closed_outcome_count"] == 0
    assert payload["lineage_mismatch_closed_trades"] == 0
    assert "unsupported execution-shadow state schema" in str(
        payload["state_restore_error"]
    )


def test_profit_lock_execution_shadow_restore_failure_is_fail_open(
    tmp_path: Path,
) -> None:
    path = tmp_path / "profit-lock-execution-shadow-state.json"
    path.write_text("{not-json", encoding="utf-8")

    shadow = _restore_profit_lock_execution_shadow(
        path,
        BaselineReplayConfig().execution,
        started_at_ms=123,
    )

    payload = shadow.summary_payload()
    assert payload["enabled"] is True
    assert payload["execution_authority"] is False
    assert payload["state_restored"] is False
    assert "JSONDecodeError" in str(payload["state_restore_error"])


def test_adaptive_delay_selector_restore_failure_is_fail_open(
    tmp_path: Path,
) -> None:
    path = tmp_path / "adaptive-delay-selector-state.json"
    path.write_text("{not-json", encoding="utf-8")

    state, error = _restore_adaptive_delay_selector(
        path,
        started_at_ms=456,
    )

    assert state.started_at_ms == 456
    assert error is not None
    assert "JSONDecodeError" in error


def test_fill_aware_delay_selector_restore_failure_is_fail_open(
    tmp_path: Path,
) -> None:
    path = tmp_path / "fill-aware-delay-selector-state.json"
    path.write_text("{not-json", encoding="utf-8")

    state, error = _restore_fill_aware_delay_selector(
        path,
        started_at_ms=987,
    )

    assert state.started_at_ms == 987
    assert error is not None
    assert "JSONDecodeError" in error


def test_delay_selector_comparison_restore_failure_is_fail_open(
    tmp_path: Path,
) -> None:
    path = tmp_path / "delay-selector-comparison-state.json"
    path.write_text("{not-json", encoding="utf-8")

    state, error = _restore_delay_selector_comparison(
        path,
        started_at_ms=789,
    )

    assert state.started_at_ms == 789
    assert error is not None
    assert "JSONDecodeError" in error


def test_prospective_entry_filter_restore_failure_is_fail_open(
    tmp_path: Path,
) -> None:
    path = tmp_path / "prospective-entry-filter-state.json"
    path.write_text("{not-json", encoding="utf-8")

    state, error = _restore_prospective_entry_filter(
        path,
        started_at_ms=456,
    )

    assert state.started_at_ms == 456
    assert error is not None
    assert "JSONDecodeError" in error


def test_prospective_delayed_price_confirmation_restore_failure_is_fail_open(
    tmp_path: Path,
) -> None:
    path = tmp_path / "prospective-delayed-price-confirm-state.json"
    path.write_text("{not-json", encoding="utf-8")

    state, error = _restore_prospective_delayed_price_confirmation(
        path,
        started_at_ms=789,
    )

    assert state.started_at_ms == 789
    assert error is not None
    assert "JSONDecodeError" in error


def test_prospective_top10_rank_filter_restore_failure_is_fail_open(
    tmp_path: Path,
) -> None:
    path = tmp_path / "prospective-top10-rank-filter-state.json"
    path.write_text("{not-json", encoding="utf-8")

    state, error = _restore_prospective_top10_rank_filter(
        path,
        started_at_ms=654,
    )

    assert state.started_at_ms == 654
    assert error is not None
    assert "JSONDecodeError" in error


def test_position_protection_metrics_handle_long_and_short_stops() -> None:
    long = _position_protection_metrics(
        side="long",
        quantity=Decimal("2"),
        entry_price=Decimal("100"),
        stop_price=Decimal("102"),
        latest_mark=Decimal("104"),
        planned_risk=Decimal("10"),
    )
    short = _position_protection_metrics(
        side="short",
        quantity=Decimal("2"),
        entry_price=Decimal("100"),
        stop_price=Decimal("98"),
        latest_mark=Decimal("96"),
        planned_risk=Decimal("10"),
    )

    assert long["unrealized_gross_pnl"] == "8"
    assert long["current_gross_r"] == "0.8"
    assert long["stop_trigger_gross_pnl"] == "4"
    assert long["stop_trigger_gross_r"] == "0.4"
    assert long["stop_protects_profit"] is True

    assert short["unrealized_gross_pnl"] == "8"
    assert short["current_gross_r"] == "0.8"
    assert short["stop_trigger_gross_pnl"] == "4"
    assert short["stop_trigger_gross_r"] == "0.4"
    assert short["stop_protects_profit"] is True


def test_position_protection_metrics_allow_legacy_zero_planned_risk() -> None:
    metrics = _position_protection_metrics(
        side="long",
        quantity=Decimal("1"),
        entry_price=Decimal("100"),
        stop_price=Decimal("99"),
        latest_mark=Decimal("101"),
        planned_risk=Decimal("0"),
    )

    assert metrics["unrealized_gross_pnl"] == "1"
    assert metrics["current_gross_r"] is None
    assert metrics["stop_trigger_gross_pnl"] == "-1"
    assert metrics["stop_trigger_gross_r"] is None
    assert metrics["stop_protects_profit"] is False


def test_position_protection_metrics_keep_unprotected_stop_negative() -> None:
    metrics = _position_protection_metrics(
        side="short",
        quantity=Decimal("5"),
        entry_price=Decimal("100"),
        stop_price=Decimal("102"),
        latest_mark=None,
        planned_risk=Decimal("10"),
    )

    assert metrics["unrealized_gross_pnl"] is None
    assert metrics["current_gross_r"] is None
    assert metrics["stop_trigger_gross_pnl"] == "-10"
    assert metrics["stop_trigger_gross_r"] == "-1"
    assert metrics["stop_protects_profit"] is False


def test_trade_path_sink_stages_opening_venue_leverage() -> None:
    calls: list[dict[str, object]] = []

    class Store:
        def checkpoint_open_path(self, **kwargs: object) -> int:
            calls.append(kwargs)
            return 0

        def finalize_trade(self, *_args: object) -> bool:
            return True

    sink = _ContinuousTradePathSink(Store())  # type: ignore[arg-type]
    sink.record_opening_trace(
        SimpleNamespace(
            submission=SimpleNamespace(
                plan=SimpleNamespace(
                    plan_id="plan-1",
                    market=MarketId("", "BTC"),
                ),
                simulation=SimpleNamespace(
                    fills=(
                        SimpleNamespace(timestamp_ms=101),
                        SimpleNamespace(timestamp_ms=103),
                    )
                ),
                account=SimpleNamespace(
                    positions=(
                        SimpleNamespace(
                            opening_plan_id="plan-1",
                            market=MarketId("", "BTC"),
                            opened_at_ms=105,
                            venue_max_leverage=Decimal("20"),
                        ),
                    )
                ),
            ),
            instrument=SimpleNamespace(
                venue_max_leverage=Decimal("20")
            ),
        )
    )

    assert calls == [
        {
            "opening_plan_id": "plan-1",
            "market": MarketId("", "BTC"),
            "opened_at_ms": 105,
            "mark_observations": (),
            "venue_max_leverage": Decimal("20"),
        }
    ]
    assert sink.error is None


def test_trade_path_capture_failure_is_fail_open() -> None:
    class Store:
        def finalize_trade(self, *_args: object) -> bool:
            raise RuntimeError("path boom")

        def checkpoint_open_path(self, **_kwargs: object) -> int:
            raise RuntimeError("checkpoint boom")

    sink = _ContinuousTradePathSink(Store())  # type: ignore[arg-type]

    assert sink.record(SimpleNamespace(), (), ()) is False  # type: ignore[arg-type]
    assert sink.error == "RuntimeError: path boom"

    sink.checkpoint(
        (
            SimpleNamespace(
                opening_plan_id="plan-1",
                market=MarketId("", "BTC"),
                opened_at_ms=1,
                mark_observations=(),
            ),
        )
    )
    assert sink.error == "RuntimeError: path boom"


def test_record_pump_counts_each_closed_trade_once() -> None:
    trade = SimpleNamespace(trade_id="trade-1")

    class Pipeline:
        def on_record(self, _record: ReplayRecord, _now_ms: int) -> tuple[object, ...]:
            return ()

        def finalize(self, _end_ms: int) -> tuple[SimpleNamespace, ...]:
            return (trade,)

    class Journal:
        def __init__(self) -> None:
            self.recorded: list[str] = []

        def iter_trades(self) -> tuple[object, ...]:
            return ()

        def record_observation(self, _observation: object) -> None:
            raise AssertionError("no observations expected")

        def record_trade(self, item: SimpleNamespace) -> None:
            self.recorded.append(item.trade_id)

    journal = Journal()
    pump = _RecordPump(
        Pipeline(),  # type: ignore[arg-type]
        journal,  # type: ignore[arg-type]
        last_available_at_ms=0,
    )
    record = ReplayRecord(
        record_kind=SourceRecordKind.DATA_GAP,
        available_at_ms=1,
        source="fixture",
        schema_version=1,
        market=None,
        exchange_time_ms=None,
        event_key="gap-1",
        payload_json='{"started_ms":1,"ended_ms":1,"reason":"fixture","stream_id":"x"}',
        event_kind=None,
    )
    asyncio.run(pump.process(record))
    asyncio.run(pump.process(record))

    assert journal.recorded == ["trade-1"]
    assert pump.closed_trades == 1
    assert pump.session_closed_trades == 1


def test_record_pump_disables_failing_cadence_shadow() -> None:
    class Pipeline:
        def on_record(
            self,
            _record: ReplayRecord,
            _now_ms: int,
        ) -> tuple[object, ...]:
            return ()

        def finalize(self, _end_ms: int) -> tuple[object, ...]:
            return ()

    class Journal:
        def iter_trades(self) -> tuple[object, ...]:
            return ()

        def record_observation(self, _observation: object) -> None:
            raise AssertionError("no observations expected")

        def record_trade(self, _trade: object) -> None:
            raise AssertionError("no trades expected")

    class FailingShadow:
        def observe(self, _record: ReplayRecord, _now_ms: int) -> None:
            raise RuntimeError("diagnostic boom")

    pump = _RecordPump(
        Pipeline(),  # type: ignore[arg-type]
        Journal(),  # type: ignore[arg-type]
        last_available_at_ms=0,
        cadence_shadow=FailingShadow(),  # type: ignore[arg-type]
    )
    record = ReplayRecord(
        record_kind=SourceRecordKind.DATA_GAP,
        available_at_ms=1,
        source="fixture",
        schema_version=1,
        market=None,
        exchange_time_ms=None,
        event_key="gap-shadow",
        payload_json=(
            '{"started_ms":1,"ended_ms":1,"reason":"fixture","stream_id":"x"}'
        ),
        event_kind=None,
    )

    asyncio.run(pump.process(record))

    assert pump.cadence_shadow is None
    payload = pump.cadence_shadow_payload()
    assert payload["enabled"] is False
    assert payload["execution_authority"] is False
    assert payload["error"] == "RuntimeError: diagnostic boom"


def test_cadence_shadow_restore_failure_is_fail_open(tmp_path: Path) -> None:
    path = tmp_path / "cadence-shadow-state.json"
    path.write_text("{not-json", encoding="utf-8")

    shadow = _restore_cadence_shadow(
        path,
        (MarketId("", "BTC"),),
        replay_config=BaselineReplayConfig(),
    )

    payload = shadow.summary_payload()
    assert payload["state_restored"] is False
    assert payload["durable_state"] is True
    assert "JSONDecodeError" in str(payload["state_restore_error"])


def test_position_action_checkpoint_round_trip() -> None:
    action = PositionAction(
        action_type=PositionActionType.TIGHTEN_STOP,
        market=MarketId("", "BTC"),
        quantity=None,
        new_stop_price=Decimal("99.5"),
        reason_codes=("TRAILING_STOP",),
        timestamp_ms=1_700_000_000_000,
    )

    restored = _position_action_from_payload(_position_action_payload(action))

    assert restored == action


def test_legacy_checkpoint_without_position_actions_remains_loadable(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runtime-state.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": RUN_ID,
                "last_available_at_ms": 123,
                "selected_markets": ["BTC"],
                "open_lifecycles": [
                    {
                        "market": "BTC",
                        "opening_plan_id": "plan-1",
                        "feature_snapshot_id": "feature-1",
                        "equity_before": "10000",
                        "exit_plan_ids": [],
                        "mark_observations": [],
                    }
                ],
                "known_gap_intervals": [],
                "execution_mode": "paper",
                "live_orders": False,
            }
        ),
        encoding="utf-8",
    )

    checkpoints, gaps, last_available_at_ms = _load_checkpoint(path)

    assert last_available_at_ms == 123
    assert gaps == ()
    assert len(checkpoints) == 1
    assert checkpoints[0].position_actions == ()


def test_stop_aware_iterator_stops_before_starting_more_work(
    tmp_path: Path,
) -> None:
    stop_path = tmp_path / "upgrade-requested"
    observed: list[int] = []

    assert _stop_requested(None) is False
    assert _stop_requested(stop_path) is False

    for item in _iter_until_stop((1, 2, 3), stop_path):
        observed.append(item)
        stop_path.touch()

    assert observed == [1]
    assert _stop_requested(stop_path) is True


def test_continuous_runtime_honors_upgrade_stop_file_contract() -> None:
    source = Path("src/cocomelon/continuous_paper.py").read_text(encoding="utf-8")
    cli = Path("src/cocomelon/continuous_paper_cli.py").read_text(encoding="utf-8")
    assert 'stop_file: str | Path | None = None' in source
    assert 'exit_reason = "upgrade_requested"' in source
    assert '"exit_reason": self.exit_reason' in source
    assert 'parser.add_argument("--stop-file", type=Path)' in cli
    assert "stop_file=args.stop_file" in cli
    assert "for request in _iter_until_stop(requests, stop_path):" in source
    assert (
        "for market_key, market_requests in _iter_until_stop("
        in source
    )
    assert (
        "for position in _iter_until_stop("
        in source
    )
    assert "if _stop_requested(stop_path):" in source
    assert "for market in _iter_until_stop(selected, stop_path):" in source
    assert (
        "if not _stop_requested(stop_path):\n"
        "            _emit_operational_live_status("
        in source
    )


def test_runtime_persists_authenticated_learning_features() -> None:
    source = Path("src/cocomelon/continuous_paper.py").read_text(encoding="utf-8")
    assert "LearningFeatureSnapshotStore(root / \"learning-features\")" in source
    assert "feature_snapshot_sink=feature_store" in source
    assert '"feature_snapshot_count": self.feature_snapshot_count' in source
    assert (
        '"feature_snapshot_state_digest": self.feature_snapshot_state_digest'
        in source
    )


def test_runtime_persists_opening_runtime_lineage() -> None:
    source = Path("src/cocomelon/continuous_paper.py").read_text(encoding="utf-8")
    assert "ContinuousPaperOpeningLineageStore(" in source
    assert 'root / "opening-lineage"' in source
    assert "_ContinuousOpeningLineageSink" in source
    assert "opening_lifecycle_sink=" in source
    assert '"opening_lineage_count": self.opening_lineage_count' in source
    assert '"opening_lineage_state_digest": self.opening_lineage_state_digest' in source


def test_delayed_entry_stop_l2_telemetry_fails_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("stop l2 boom")

    monkeypatch.setattr(
        "cocomelon.continuous_paper.delayed_entry_stop_l2_replay",
        fail,
    )
    payload = _delayed_entry_stop_l2_replay_payload(
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(
            shadow=SimpleNamespace(outcomes=()),
            error=None,
        ),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        lambda _market, _start_ms: (),
        PaperExecutionConfig(),
        capture_error="capture degraded",
    )

    assert payload["enabled"] is False
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False
    assert payload["capture_error"] == "capture degraded"
    assert payload["error"] == "RuntimeError: stop l2 boom"


def test_runtime_exposes_cadence_opportunity_learning() -> None:
    source = Path("src/cocomelon/continuous_paper.py").read_text(
        encoding="utf-8"
    )
    assert "evaluate_cadence_opportunity_learning(" in source
    assert "cadence_opportunity_learning_payload(" in source
    assert '"cadence_opportunity_learning": (' in source
    assert "self.cadence_shadow.outcomes" in source


def test_runtime_hot_path_uses_only_operational_heartbeat() -> None:
    source = Path("src/cocomelon/continuous_paper.py").read_text(
        encoding="utf-8"
    )

    assert '"heartbeat_scope": "operational"' in source
    assert source.count("_emit_operational_live_status(") == 3
    assert source.count("_emit_live_status(") == 1


def test_momentum_band_state_restore_preserves_original_freeze(
    tmp_path: Path,
) -> None:
    path = tmp_path / "momentum-band.json"
    original = ProspectiveMomentumBandEntryState(
        frozen_at_ms=123
    )
    path.write_text(
        json.dumps(original.payload()),
        encoding="utf-8",
    )

    restored, error = _restore_prospective_momentum_band_entry(
        path,
        frozen_at_ms=999,
    )

    assert error is None
    assert restored == original
    assert restored.frozen_at_ms == 123
    assert (
        restored.started_at_ms
        == 123 + MOMENTUM_BAND_EMBARGO_MS
    )


def test_momentum_band_restore_failure_restarts_clean_freeze(
    tmp_path: Path,
) -> None:
    path = tmp_path / "momentum-band.json"
    path.write_text("{bad", encoding="utf-8")

    restored, error = _restore_prospective_momentum_band_entry(
        path,
        frozen_at_ms=999,
    )

    assert restored.frozen_at_ms == 999
    assert (
        restored.started_at_ms
        == 999 + MOMENTUM_BAND_EMBARGO_MS
    )
    assert error is not None
    assert "JSONDecodeError" in error


def test_momentum_band_payload_failure_is_research_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("momentum-band boom")

    monkeypatch.setattr(
        "cocomelon.continuous_paper."
        "evaluate_prospective_momentum_band_entry",
        fail,
    )
    state = ProspectiveMomentumBandEntryState(
        frozen_at_ms=100
    )

    payload = _prospective_momentum_band_entry_payload(
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        state,
        restore_error=None,
    )

    assert payload["enabled"] is False
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False
    assert payload["candidate_id"] == state.candidate_id
    assert payload["frozen_at_ms"] == 100
    assert (
        payload["started_at_ms"]
        == 100 + MOMENTUM_BAND_EMBARGO_MS
    )
    assert payload["error"] == "RuntimeError: momentum-band boom"


def test_two_strike_state_restore_preserves_original_freeze(
    tmp_path: Path,
) -> None:
    path = tmp_path / "two-strike.json"
    original = ProspectiveTwoStrikeStopFilterState(
        frozen_at_ms=123
    )
    path.write_text(
        json.dumps(original.payload()),
        encoding="utf-8",
    )

    restored, error = _restore_prospective_two_strike_stop_filter(
        path,
        frozen_at_ms=999,
    )

    assert error is None
    assert restored == original
    assert restored.frozen_at_ms == 123
    assert restored.started_at_ms == 123 + TWO_STRIKE_EMBARGO_MS


def test_two_strike_state_restore_failure_restarts_clean_freeze(
    tmp_path: Path,
) -> None:
    path = tmp_path / "two-strike.json"
    path.write_text("{bad", encoding="utf-8")

    restored, error = _restore_prospective_two_strike_stop_filter(
        path,
        frozen_at_ms=999,
    )

    assert restored.frozen_at_ms == 999
    assert restored.started_at_ms == 999 + TWO_STRIKE_EMBARGO_MS
    assert error is not None
    assert "JSONDecodeError" in error


def test_two_strike_payload_failure_is_research_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("two-strike boom")

    monkeypatch.setattr(
        "cocomelon.continuous_paper."
        "evaluate_prospective_two_strike_stop_filter",
        fail,
    )
    state = ProspectiveTwoStrikeStopFilterState(
        frozen_at_ms=100
    )

    payload = _prospective_two_strike_stop_filter_payload(
        SimpleNamespace(),  # type: ignore[arg-type]
        state,
        restore_error=None,
    )

    assert payload["enabled"] is False
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False
    assert payload["candidate_id"] == state.candidate_id
    assert payload["frozen_at_ms"] == 100
    assert payload["started_at_ms"] == 100 + TWO_STRIKE_EMBARGO_MS
    assert payload["error"] == "RuntimeError: two-strike boom"


def test_cooldown_shadow_telemetry_fails_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("cooldown boom")

    monkeypatch.setattr(
        "cocomelon.continuous_paper."
        "evaluate_prospective_consecutive_loss_cooldown_shadow",
        fail,
    )
    state = SimpleNamespace(
        candidate_id="cooldown-test",
        frozen_at_ms=100,
        started_at_ms=200,
    )
    payload = _prospective_consecutive_loss_cooldown_shadow_payload(
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        state,  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        restore_error=None,
    )

    assert payload["enabled"] is False
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False
    assert payload["changes_risk_limits"] is False
    assert payload["error"] == "RuntimeError: cooldown boom"


def test_full_stack_entry_exit_summary_is_persisted_at_worker_end() -> None:
    source = Path("src/cocomelon/continuous_paper.py").read_text(
        encoding="utf-8"
    )

    assert (
        'PROSPECTIVE_FULL_STACK_ENTRY_EXIT_SUMMARY_FILENAME = ('
        in source
    )
    assert (
        '"prospective-full-stack-entry-exit-summary.json"'
        in source
    )
    assert "_prospective_full_stack_entry_exit_payload(" in source
    assert "profit_lock_execution_shadow.shadow.state_payload()" in source
    assert (
        "root / PROSPECTIVE_FULL_STACK_ENTRY_EXIT_SUMMARY_FILENAME"
        in source
    )
