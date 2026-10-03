from __future__ import annotations

import asyncio
import json
import time
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from cocomelon.continuous_paper import (
    RUN_ID,
    ContinuousPaperConfig,
    _account_lifecycle_bridge_payload,
    _clean_evidence_runway_payload,
    _closed_trade_concentration_payload,
    _closed_trade_friction_payload,
    _closed_trade_robustness_payload,
    _closed_trade_stability_payload,
    _closed_trade_stop_reentry_payload,
    _closed_trade_utc_hour_payload,
    _consecutive_loss_cooldown_status,
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
    _is_systemic_l2_failure,
    _iter_until_stop,
    _l2_event_fresh_for_promotion,
    _latest_epoch_stale_l2_market_keys,
    _load_checkpoint,
    _monitor_event_loop_lag,
    _opening_fill_liquidity_payload,
    _opening_rank_attribution_payload,
    _pipeline_l2_recovery_plan,
    _position_action_from_payload,
    _position_action_payload,
    _position_protection_metrics,
    _post_freshness_paper_cohort_payload,
    _profit_lock_counterfactual_payload,
    _prospective_candidate_stack_overlap_payload,
    _prospective_combined_entry_filter_payload,
    _prospective_consecutive_loss_cooldown_shadow_payload,
    _prospective_full_stack_capacity_reflow_payload,
    _prospective_full_stack_entry_exit_payload,
    _prospective_full_stack_exit_capacity_reflow_payload,
    _prospective_momentum_band_entry_payload,
    _prospective_two_strike_stop_filter_payload,
    _ranked_selection,
    _record_from_gap,
    _record_from_payload,
    _record_from_stream,
    _record_payload,
    _RecordPump,
    _refresh_native_market_snapshots,
    _reseed_l2_books_via_rest,
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
    _revoke_stale_l2_readiness,
    _stop_requested,
    _supervisor_group_health_payload,
    _SupervisorGroup,
    _wait_supervisor_group_ready,
)
from cocomelon.domain.execution import (
    PaperExecutionConfig,
    PositionAction,
    PositionActionType,
)
from cocomelon.domain.market import (
    MarketId,
    PerpMarketContext,
    PerpMarketMeta,
    PerpMarketSnapshot,
)
from cocomelon.domain.replay import ReplayRecord, SourceRecordKind
from cocomelon.domain.risk import RiskLimits
from cocomelon.domain.stream import DataGap, StreamEvent, StreamKind
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.evidence.lifecycle import SessionDecisionActivity
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


def _watchlist_snapshot(
    coin: str,
    *,
    volume: str,
    open_interest: str = "10",
    received_at_ms: int = 1_000,
    valid_prices: bool = True,
) -> PerpMarketSnapshot:
    market = MarketId("", coin)
    price = Decimal("100") if valid_prices else None
    return PerpMarketSnapshot(
        meta=PerpMarketMeta(
            market=market,
            wire_name=coin,
            sz_decimals=2,
            max_leverage=10,
            margin_table_id=None,
            only_isolated=False,
            is_delisted=False,
            margin_mode=None,
        ),
        context=PerpMarketContext(
            market=market,
            mark_px=price,
            mid_px=price,
            oracle_px=price,
            funding=Decimal("0"),
            open_interest=Decimal(open_interest),
            day_ntl_vlm=Decimal(volume),
            premium=Decimal("0"),
            prev_day_px=Decimal("100"),
        ),
        source="test",
        received_at_ms=received_at_ms,
        schema_version=1,
    )


def test_ranked_selection_pads_l2_watchlist_when_ranker_collapses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshots = {
        item.meta.market.canonical: item
        for item in (
            _watchlist_snapshot("RANKED", volume="1"),
            _watchlist_snapshot("LIQUID", volume="900"),
            _watchlist_snapshot("SECOND", volume="800"),
            _watchlist_snapshot("THIRD", volume="700"),
            _watchlist_snapshot("INVALID", volume="1000", valid_prices=False),
        )
    }
    ranked_market = MarketId("", "RANKED")
    monkeypatch.setattr(
        "cocomelon.continuous_paper._startup_ranks",
        lambda *_args, **_kwargs: (
            {},
            (SimpleNamespace(market=ranked_market),),
        ),
    )

    selected = _ranked_selection(
        snapshots,
        as_of_ms=1_000,
        deep_limit=4,
        pinned=(),
    )

    assert [market.canonical for market in selected] == [
        "RANKED",
        "LIQUID",
        "SECOND",
        "THIRD",
    ]


def test_ranked_selection_keeps_pinned_market_beyond_watchlist_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshots = {
        item.meta.market.canonical: item
        for item in (
            _watchlist_snapshot("RANKED", volume="1"),
            _watchlist_snapshot("LIQUID", volume="900"),
            _watchlist_snapshot("SECOND", volume="800"),
        )
    }
    monkeypatch.setattr(
        "cocomelon.continuous_paper._startup_ranks",
        lambda *_args, **_kwargs: (
            {},
            (SimpleNamespace(market=MarketId("", "RANKED")),),
        ),
    )

    selected = _ranked_selection(
        snapshots,
        as_of_ms=1_000,
        deep_limit=2,
        pinned=(MarketId("", "PINNED"),),
    )

    assert [market.canonical for market in selected] == [
        "RANKED",
        "LIQUID",
        "PINNED",
    ]

def test_consecutive_loss_cooldown_status_locks_exact_boundary() -> None:
    execution = SimpleNamespace(
        account=SimpleNamespace(
            consecutive_losses=3,
            last_closed_trade_ms=1_000,
        )
    )
    limits = RiskLimits(
        consecutive_loss_cooldown=3,
        cooldown_ms=3_600_000,
    )

    active = _consecutive_loss_cooldown_status(
        execution,  # type: ignore[arg-type]
        limits,
        timestamp_ms=3_600_999,
    )
    assert active["active"] is True
    assert active["elapsed_since_last_close_ms"] == 3_599_999
    assert active["remaining_ms"] == 1
    assert active["state_consistent"] is True

    expired = _consecutive_loss_cooldown_status(
        execution,  # type: ignore[arg-type]
        limits,
        timestamp_ms=3_601_000,
    )
    assert expired["active"] is False
    assert expired["remaining_ms"] == 0

    inconsistent = _consecutive_loss_cooldown_status(
        SimpleNamespace(
            account=SimpleNamespace(
                consecutive_losses=3,
                last_closed_trade_ms=None,
            )
        ),  # type: ignore[arg-type]
        limits,
        timestamp_ms=3_601_000,
    )
    assert inconsistent["active"] is False
    assert inconsistent["remaining_ms"] is None
    assert inconsistent["state_consistent"] is False

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
def test_full_stack_exit_capacity_reflow_telemetry_fails_open() -> None:
    payload = _prospective_full_stack_exit_capacity_reflow_payload(
        SimpleNamespace(iter_records=lambda: ()),  # type: ignore[arg-type]
        SimpleNamespace(iter_trades=lambda: ()),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(started_at_ms=0),  # type: ignore[arg-type]
        SimpleNamespace(started_at_ms=0),  # type: ignore[arg-type]
        SimpleNamespace(started_at_ms=0),  # type: ignore[arg-type]
        {},
        {},
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        PaperExecutionConfig(),
        position_history_loader=lambda _plan_id, _through_ms: (),
    )

    assert payload["enabled"] is False
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False
    assert payload["changes_readiness_gate"] is False
    assert "overlap_started_at_ms" in str(payload["error"])


def test_full_stack_exit_capacity_reflow_composes_exact_one_hop_economics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "cocomelon.continuous_paper."
        "prospective_full_stack_exit_capacity_reflow",
        lambda *_args, **_kwargs: SimpleNamespace(
            releases=(),
            release_terminal_contributions=(),
            summary={
                "research_only": True,
                "execution_authority": False,
                "promotion_authority": False,
                "descriptive_only": True,
                "changes_readiness_gate": False,
                "integrity_clean": True,
                "portfolio_counterfactual": False,
            },
        ),
    )
    monkeypatch.setattr(
        "cocomelon.continuous_paper."
        "prospective_capacity_reflow_fill_feasibility_summary",
        lambda *_args, **_kwargs: {
            "replacement_entry_fills_modeled": True,
            "fillable_options": 1,
        },
    )
    monkeypatch.setattr(
        "cocomelon.continuous_paper."
        "evaluate_prospective_capacity_reflow_exit_fill",
        lambda *_args, **_kwargs: {
            "replacement_exit_fills_modeled": True,
        },
    )
    monkeypatch.setattr(
        "cocomelon.continuous_paper."
        "evaluate_prospective_capacity_reflow_realized_pnl",
        lambda *_args, **_kwargs: {
            "exact_realized_pnl_available": True,
            "exact_realized_pnl_option_horizons": 1,
            "strategy_level_realized_pnl_claimed": False,
        },
    )

    payload = _prospective_full_stack_exit_capacity_reflow_payload(
        SimpleNamespace(iter_records=lambda: ()),  # type: ignore[arg-type]
        SimpleNamespace(iter_trades=lambda: ()),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(started_at_ms=0),  # type: ignore[arg-type]
        SimpleNamespace(started_at_ms=0),  # type: ignore[arg-type]
        SimpleNamespace(started_at_ms=0),  # type: ignore[arg-type]
        {"overlap_started_at_ms": 0, "breakeven_started_at_ms": 0},
        {},
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        PaperExecutionConfig(),
        position_history_loader=lambda _plan_id, _through_ms: (),
    )

    assert payload["enabled"] is True
    assert payload["replacement_entries_modeled"] is True
    assert payload["replacement_exits_modeled"] is True
    assert payload["pnl_modeled"] is True
    assert payload["exact_realized_pnl_available"] is True
    assert payload["cross_horizon_economics_aggregated"] is False
    assert payload["strategy_level_realized_pnl_claimed"] is False
    assert payload["portfolio_counterfactual"] is False


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
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        PaperExecutionConfig(),
        position_history_loader=lambda _plan_id, _through_ms: (),
    )

    assert payload["enabled"] is False
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False
    assert payload["changes_readiness_gate"] is False
    assert "decision map" in str(payload["error"])


def test_full_stack_capacity_reflow_composes_exact_one_hop_economics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "cocomelon.continuous_paper."
        "prospective_full_stack_capacity_reflow",
        lambda *_args, **_kwargs: SimpleNamespace(
            releases=(),
            summary={
                "research_only": True,
                "execution_authority": False,
                "promotion_authority": False,
                "descriptive_only": True,
                "changes_readiness_gate": False,
                "integrity_clean": True,
                "portfolio_counterfactual": False,
            },
        ),
    )
    monkeypatch.setattr(
        "cocomelon.continuous_paper."
        "prospective_capacity_reflow_fill_feasibility_summary",
        lambda *_args, **_kwargs: {
            "replacement_entry_fills_modeled": True,
            "fillable_options": 1,
        },
    )
    monkeypatch.setattr(
        "cocomelon.continuous_paper."
        "evaluate_prospective_capacity_reflow_exit_fill",
        lambda *_args, **_kwargs: {
            "replacement_entry_fills_modeled": True,
            "replacement_exit_fills_modeled": True,
            "cross_horizon_economics_aggregated": False,
        },
    )
    monkeypatch.setattr(
        "cocomelon.continuous_paper."
        "evaluate_prospective_capacity_reflow_realized_pnl",
        lambda *_args, **_kwargs: {
            "exact_realized_pnl_available": True,
            "exact_realized_pnl_option_horizons": 1,
            "cross_horizon_economics_aggregated": False,
            "portfolio_counterfactual_complete": False,
            "strategy_level_realized_pnl_claimed": False,
        },
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
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        PaperExecutionConfig(),
        position_history_loader=lambda _plan_id, _through_ms: (),
    )

    assert payload["enabled"] is True
    assert payload["replacement_entries_modeled"] is True
    assert payload["replacement_exits_modeled"] is True
    assert payload["pnl_modeled"] is True
    assert payload["exact_realized_pnl_available"] is True
    assert payload["cross_horizon_economics_aggregated"] is False
    assert payload["strategy_level_realized_pnl_claimed"] is False
    assert payload["portfolio_counterfactual"] is False


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
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
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


def test_full_stack_capacity_reflow_preserves_fill_when_exit_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "cocomelon.continuous_paper."
        "prospective_full_stack_capacity_reflow",
        lambda *_args, **_kwargs: SimpleNamespace(
            releases=(),
            summary={
                "research_only": True,
                "execution_authority": False,
                "promotion_authority": False,
                "descriptive_only": True,
                "changes_readiness_gate": False,
                "integrity_clean": True,
            },
        ),
    )
    monkeypatch.setattr(
        "cocomelon.continuous_paper."
        "prospective_capacity_reflow_fill_feasibility_summary",
        lambda *_args, **_kwargs: {
            "replacement_entry_fills_modeled": True,
        },
    )

    def fail_exit(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("exit boom")

    monkeypatch.setattr(
        "cocomelon.continuous_paper."
        "evaluate_prospective_capacity_reflow_exit_fill",
        fail_exit,
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
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        PaperExecutionConfig(),
        position_history_loader=lambda _plan_id, _through_ms: (),
    )

    assert payload["enabled"] is True
    assert payload["replacement_entries_modeled"] is True
    assert payload["replacement_exits_modeled"] is False
    assert payload["pnl_modeled"] is False
    exit_fill = payload["exit_fill"]
    assert isinstance(exit_fill, dict)
    assert exit_fill["error"] == "RuntimeError: exit boom"


def test_full_stack_capacity_reflow_preserves_exit_when_funding_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "cocomelon.continuous_paper."
        "prospective_full_stack_capacity_reflow",
        lambda *_args, **_kwargs: SimpleNamespace(
            releases=(),
            summary={
                "research_only": True,
                "execution_authority": False,
                "promotion_authority": False,
                "descriptive_only": True,
                "changes_readiness_gate": False,
                "integrity_clean": True,
            },
        ),
    )
    monkeypatch.setattr(
        "cocomelon.continuous_paper."
        "prospective_capacity_reflow_fill_feasibility_summary",
        lambda *_args, **_kwargs: {
            "replacement_entry_fills_modeled": True,
        },
    )
    monkeypatch.setattr(
        "cocomelon.continuous_paper."
        "evaluate_prospective_capacity_reflow_exit_fill",
        lambda *_args, **_kwargs: {
            "replacement_entry_fills_modeled": True,
            "replacement_exit_fills_modeled": True,
        },
    )

    def fail_funding(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("funding boom")

    monkeypatch.setattr(
        "cocomelon.continuous_paper."
        "evaluate_prospective_capacity_reflow_realized_pnl",
        fail_funding,
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
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        PaperExecutionConfig(),
        position_history_loader=lambda _plan_id, _through_ms: (),
    )

    assert payload["enabled"] is True
    assert payload["replacement_entries_modeled"] is True
    assert payload["replacement_exits_modeled"] is True
    assert payload["pnl_modeled"] is False
    realized = payload["realized_pnl"]
    assert isinstance(realized, dict)
    assert realized["error"] == "RuntimeError: funding boom"


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


def test_record_pump_drops_duplicate_event_keys() -> None:
    class Pipeline:
        def __init__(self) -> None:
            self.calls = 0

        def on_record(
            self,
            _record: ReplayRecord,
            _now_ms: int,
        ) -> tuple[object, ...]:
            self.calls += 1
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

    pipeline = Pipeline()
    pump = _RecordPump(
        pipeline,  # type: ignore[arg-type]
        Journal(),  # type: ignore[arg-type]
        last_available_at_ms=0,
    )
    record = ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=1,
        source="hyperliquid-mainnet-ws",
        schema_version=1,
        market="BTC",
        exchange_time_ms=1,
        event_key="duplicate-key",
        payload_json='{"mark_px":"100"}',
        event_kind="active_asset_ctx",
    )

    asyncio.run(pump.process(record))
    asyncio.run(pump.process(record))

    assert pipeline.calls == 1
    assert pump.processed_records == 1
    assert pump.duplicate_records_dropped == 1


def test_record_pump_wakes_on_new_decision_epoch() -> None:
    async def scenario() -> None:
        class Pipeline:
            def __init__(self) -> None:
                self.session_decision_activity = SimpleNamespace(
                    last_decision_boundary_ms=None
                )

            def on_record(
                self,
                _record: ReplayRecord,
                _now_ms: int,
            ) -> tuple[object, ...]:
                self.session_decision_activity = SimpleNamespace(
                    last_decision_boundary_ms=30_000
                )
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

        wakeup = asyncio.Event()
        pump = _RecordPump(
            Pipeline(),  # type: ignore[arg-type]
            Journal(),  # type: ignore[arg-type]
            last_available_at_ms=0,
            decision_epoch_wakeup=wakeup,
        )
        record = ReplayRecord(
            record_kind=SourceRecordKind.NORMALIZED_EVENT,
            available_at_ms=1,
            source="hyperliquid-mainnet-ws",
            schema_version=1,
            market="BTC",
            exchange_time_ms=1,
            event_key="decision-epoch-wakeup",
            payload_json='{"mark_px":"100"}',
            event_kind="active_asset_ctx",
        )

        await pump.process(record)

        assert wakeup.is_set() is True

    asyncio.run(scenario())


def test_event_loop_lag_monitor_records_blocking_phase() -> None:
    async def scenario() -> None:
        pump = SimpleNamespace(
            event_loop_phase="unit_test_block",
            event_loop_lag_samples=0,
            event_loop_max_lag_ms=0,
            event_loop_max_lag_wakeup=None,
            event_loop_slow_wakeup_count=0,
            event_loop_last_slow_wakeup=None,
            event_loop_slow_wakeup_count_by_phase={},
            event_loop_max_lag_ms_by_phase={},
        )
        task = asyncio.create_task(
            _monitor_event_loop_lag(
                pump,
                interval_seconds=0.005,
                slow_lag_ms=5,
            )
        )
        await asyncio.sleep(0.01)
        time.sleep(0.03)
        pump.event_loop_phase = "after_block"
        await asyncio.sleep(0.01)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

        assert pump.event_loop_lag_samples > 0
        assert pump.event_loop_max_lag_ms >= 10
        assert pump.event_loop_max_lag_wakeup["lag_ms"] == (
            pump.event_loop_max_lag_ms
        )
        assert pump.event_loop_max_lag_wakeup["phase"] == (
            "unit_test_block"
        )
        assert pump.event_loop_max_lag_wakeup["observed_phase"] == (
            "after_block"
        )
        assert (
            pump.event_loop_max_lag_ms_by_phase["unit_test_block"]
            >= 10
        )
        assert pump.event_loop_slow_wakeup_count >= 1
        assert (
            pump.event_loop_slow_wakeup_count_by_phase[
                "unit_test_block"
            ]
            >= 1
        )
        assert pump.event_loop_last_slow_wakeup["phase"] == (
            "unit_test_block"
        )
        assert pump.event_loop_last_slow_wakeup["observed_phase"] == (
            "after_block"
        )
        assert pump.event_loop_last_slow_wakeup["lag_ms"] >= 10

    asyncio.run(scenario())


def test_rest_l2_reseed_accepts_only_fresh_real_books() -> None:
    class Reader:
        def l2_book(self, market: MarketId) -> object:
            if market.coin == "BTC":
                return {
                    "coin": "BTC",
                    "time": 9_999,
                    "levels": [
                        [{"px": "100", "sz": "2", "n": 1}],
                        [{"px": "101", "sz": "3", "n": 1}],
                    ],
                }
            if market.coin == "ETH":
                return {
                    "coin": "ETH",
                    "time": 4_000,
                    "levels": [
                        [{"px": "200", "sz": "2", "n": 1}],
                        [{"px": "201", "sz": "3", "n": 1}],
                    ],
                }
            raise RuntimeError("book unavailable")

    class Pump:
        def __init__(self) -> None:
            self.records: list[ReplayRecord] = []

        async def process(self, record: ReplayRecord) -> None:
            self.records.append(record)

    pump = Pump()
    refreshed, failed = asyncio.run(
        _reseed_l2_books_via_rest(
            Reader(),  # type: ignore[arg-type]
            (
                MarketId("", "BTC"),
                MarketId("", "BTC"),
                MarketId("", "ETH"),
                MarketId("", "SOL"),
            ),
            pump,  # type: ignore[arg-type]
            max_book_age_ms=5_000,
            clock_ms=lambda: 10_000,
        )
    )

    assert refreshed == 1
    assert failed == 2
    assert len(pump.records) == 1
    record = pump.records[0]
    assert record.market == "BTC"
    assert record.event_kind == "l2_book"
    assert record.exchange_time_ms == 9_999
    assert record.available_at_ms == 10_000
    assert record.source == "hyperliquid-mainnet-info"


def test_pipeline_stale_l2_trigger_uses_latest_decision_epoch() -> None:
    activity = SessionDecisionActivity(
        decision_epochs=1,
        last_decision_boundary_ms=10_000,
        last_decision_evaluated_at_ms=10_100,
        long_decisions=0,
        short_decisions=0,
        no_trade_decisions=4,
        decision_reason_counts=(("not_deep_ready", 4),),
        eligibility_evaluations=4,
        eligibility_rankable=4,
        eligibility_deep_ready=0,
        eligibility_reason_counts=(("stale_book", 2),),
        latest_epoch_market_count=4,
        latest_epoch_rankable_count=4,
        latest_epoch_deep_ready_count=0,
        latest_epoch_eligibility_reason_counts=(
            ("stale_book", 2),
        ),
        latest_epoch_stale_book_age_ms=(
            ("BTC", 6_000),
            ("ETH", 7_000),
            ("SOL", 1_000),
            ("OLD", 9_000),
        ),
        risk_evaluations=0,
        risk_approvals=0,
        risk_rejections=0,
        risk_reason_counts=(),
        opening_execution_attempts=0,
        opening_fills=0,
    )
    selected = frozenset({"BTC", "ETH", "SOL", "ENA"})

    stale = _latest_epoch_stale_l2_market_keys(
        activity,
        selected_market_keys=selected,
        max_book_age_ms=5_000,
    )

    assert stale == frozenset({"BTC", "ETH"})
    assert _is_systemic_l2_failure(selected, stale) is True
    assert (
        _is_systemic_l2_failure(
            selected,
            frozenset({"BTC"}),
        )
        is False
    )


def test_pipeline_l2_recovery_plan_uses_exact_stale_keys() -> None:
    activity = SessionDecisionActivity(
        decision_epochs=1,
        last_decision_boundary_ms=10_000,
        last_decision_evaluated_at_ms=10_100,
        long_decisions=0,
        short_decisions=0,
        no_trade_decisions=4,
        decision_reason_counts=(("not_deep_ready", 4),),
        eligibility_evaluations=4,
        eligibility_rankable=4,
        eligibility_deep_ready=0,
        eligibility_reason_counts=(("stale_book", 2),),
        latest_epoch_market_count=4,
        latest_epoch_rankable_count=4,
        latest_epoch_deep_ready_count=0,
        latest_epoch_eligibility_reason_counts=(
            ("stale_book", 2),
        ),
        latest_epoch_stale_book_age_ms=(
            ("BTC", 6_000),
            ("ETH", 7_000),
        ),
        risk_evaluations=0,
        risk_approvals=0,
        risk_rejections=0,
        risk_reason_counts=(),
        opening_execution_attempts=0,
        opening_fills=0,
    )

    boundary, markets, fallback = _pipeline_l2_recovery_plan(
        activity,
        selected_market_keys=frozenset(
            {"BTC", "ETH", "SOL", "ENA"}
        ),
        last_recovery_boundary_ms=None,
        max_book_age_ms=5_000,
    )

    assert boundary == 10_000
    assert markets == frozenset({"BTC", "ETH"})
    assert fallback is False


def test_pipeline_l2_recovery_plan_falls_back_to_epoch_stale_count() -> None:
    stale_ages = tuple(
        (f"stale-{index}", 57_233)
        for index in range(16)
    )
    activity = SessionDecisionActivity(
        decision_epochs=1,
        last_decision_boundary_ms=20_000,
        last_decision_evaluated_at_ms=20_100,
        long_decisions=0,
        short_decisions=0,
        no_trade_decisions=20,
        decision_reason_counts=(("not_deep_ready", 20),),
        eligibility_evaluations=20,
        eligibility_rankable=16,
        eligibility_deep_ready=0,
        eligibility_reason_counts=(("stale_book", 16),),
        latest_epoch_market_count=20,
        latest_epoch_rankable_count=16,
        latest_epoch_deep_ready_count=0,
        latest_epoch_eligibility_reason_counts=(
            ("stale_book", 16),
        ),
        latest_epoch_stale_book_age_ms=stale_ages,
        risk_evaluations=0,
        risk_approvals=0,
        risk_rejections=0,
        risk_reason_counts=(),
        opening_execution_attempts=0,
        opening_fills=0,
    )
    selected = frozenset(
        f"selected-{index}" for index in range(20)
    )

    boundary, markets, fallback = _pipeline_l2_recovery_plan(
        activity,
        selected_market_keys=selected,
        last_recovery_boundary_ms=None,
        max_book_age_ms=5_000,
    )

    assert boundary == 20_000
    assert markets == selected
    assert fallback is True


def test_pipeline_l2_recovery_plan_recovers_systemic_missing_deep() -> None:
    activity = SessionDecisionActivity(
        decision_epochs=1,
        last_decision_boundary_ms=25_000,
        last_decision_evaluated_at_ms=25_100,
        long_decisions=0,
        short_decisions=0,
        no_trade_decisions=20,
        decision_reason_counts=(("not_deep_ready", 16),),
        eligibility_evaluations=20,
        eligibility_rankable=16,
        eligibility_deep_ready=0,
        eligibility_reason_counts=(("missing_deep_data", 16),),
        latest_epoch_market_count=20,
        latest_epoch_rankable_count=16,
        latest_epoch_deep_ready_count=0,
        latest_epoch_eligibility_reason_counts=(
            ("missing_deep_data", 16),
        ),
        latest_epoch_stale_book_age_ms=(),
        risk_evaluations=0,
        risk_approvals=0,
        risk_rejections=0,
        risk_reason_counts=(),
        opening_execution_attempts=0,
        opening_fills=0,
    )
    selected = frozenset(
        f"selected-{index}" for index in range(20)
    )

    boundary, markets, fallback = _pipeline_l2_recovery_plan(
        activity,
        selected_market_keys=selected,
        last_recovery_boundary_ms=None,
        max_book_age_ms=5_000,
    )

    assert boundary == 25_000
    assert markets == selected
    assert fallback is True


def test_pipeline_l2_recovery_plan_ignores_minor_missing_deep() -> None:
    activity = SessionDecisionActivity(
        decision_epochs=1,
        last_decision_boundary_ms=26_000,
        last_decision_evaluated_at_ms=26_100,
        long_decisions=0,
        short_decisions=0,
        no_trade_decisions=20,
        decision_reason_counts=(("not_deep_ready", 4),),
        eligibility_evaluations=20,
        eligibility_rankable=20,
        eligibility_deep_ready=16,
        eligibility_reason_counts=(("missing_deep_data", 4),),
        latest_epoch_market_count=20,
        latest_epoch_rankable_count=20,
        latest_epoch_deep_ready_count=16,
        latest_epoch_eligibility_reason_counts=(
            ("missing_deep_data", 4),
        ),
        latest_epoch_stale_book_age_ms=(),
        risk_evaluations=0,
        risk_approvals=0,
        risk_rejections=0,
        risk_reason_counts=(),
        opening_execution_attempts=0,
        opening_fills=0,
    )
    selected = frozenset(
        f"selected-{index}" for index in range(20)
    )

    assert _pipeline_l2_recovery_plan(
        activity,
        selected_market_keys=selected,
        last_recovery_boundary_ms=None,
        max_book_age_ms=5_000,
    ) == (None, frozenset(), False)


def test_pipeline_l2_recovery_plan_survives_watchlist_count_drift() -> None:
    stale_ages = tuple(
        (f"old-{index}", 42_598)
        for index in range(17)
    )
    activity = SessionDecisionActivity(
        decision_epochs=1,
        last_decision_boundary_ms=40_000,
        last_decision_evaluated_at_ms=40_100,
        long_decisions=0,
        short_decisions=0,
        no_trade_decisions=21,
        decision_reason_counts=(("not_deep_ready", 21),),
        eligibility_evaluations=21,
        eligibility_rankable=17,
        eligibility_deep_ready=0,
        eligibility_reason_counts=(("stale_book", 17),),
        latest_epoch_market_count=21,
        latest_epoch_rankable_count=17,
        latest_epoch_deep_ready_count=0,
        latest_epoch_eligibility_reason_counts=(
            ("stale_book", 17),
        ),
        latest_epoch_stale_book_age_ms=stale_ages,
        risk_evaluations=0,
        risk_approvals=0,
        risk_rejections=0,
        risk_reason_counts=(),
        opening_execution_attempts=0,
        opening_fills=0,
    )
    current_selected = frozenset(
        f"current-{index}" for index in range(20)
    )

    boundary, markets, fallback = _pipeline_l2_recovery_plan(
        activity,
        selected_market_keys=current_selected,
        last_recovery_boundary_ms=None,
        max_book_age_ms=5_000,
    )

    assert boundary == 40_000
    assert markets == current_selected
    assert fallback is True


def test_pipeline_l2_recovery_plan_does_not_repeat_or_overreact() -> None:
    activity = SessionDecisionActivity(
        decision_epochs=1,
        last_decision_boundary_ms=30_000,
        last_decision_evaluated_at_ms=30_100,
        long_decisions=0,
        short_decisions=0,
        no_trade_decisions=20,
        decision_reason_counts=(("not_deep_ready", 20),),
        eligibility_evaluations=20,
        eligibility_rankable=20,
        eligibility_deep_ready=12,
        eligibility_reason_counts=(("stale_book", 8),),
        latest_epoch_market_count=20,
        latest_epoch_rankable_count=20,
        latest_epoch_deep_ready_count=12,
        latest_epoch_eligibility_reason_counts=(
            ("stale_book", 8),
        ),
        latest_epoch_stale_book_age_ms=tuple(
            (f"stale-{index}", 57_233)
            for index in range(8)
        ),
        risk_evaluations=0,
        risk_approvals=0,
        risk_rejections=0,
        risk_reason_counts=(),
        opening_execution_attempts=0,
        opening_fills=0,
    )
    selected = frozenset(
        f"selected-{index}" for index in range(20)
    )

    assert _pipeline_l2_recovery_plan(
        activity,
        selected_market_keys=selected,
        last_recovery_boundary_ms=None,
        max_book_age_ms=5_000,
    ) == (None, frozenset(), False)

    systemic_activity = replace(
        activity,
        latest_epoch_eligibility_reason_counts=(
            ("stale_book", 16),
        ),
    )
    assert _pipeline_l2_recovery_plan(
        systemic_activity,
        selected_market_keys=selected,
        last_recovery_boundary_ms=30_000,
        max_book_age_ms=5_000,
    ) == (None, frozenset(), False)


def test_supervisor_group_readiness_requires_full_market_coverage() -> None:
    async def scenario() -> tuple[bool, bool]:
        sleeper = asyncio.create_task(asyncio.sleep(60))
        group = _SupervisorGroup(
            supervisors=(),
            tasks=(sleeper,),
            forward_gaps=asyncio.Event(),
            required_market_keys=frozenset({"BTC", "ETH"}),
            ready_market_keys=({"BTC"}, {"BTC", "ETH"}),
        )
        try:
            incomplete = await _wait_supervisor_group_ready(
                group,
                timeout_seconds=0.02,
                poll_seconds=0.005,
            )
            group.ready_market_keys[0].add("ETH")
            complete = await _wait_supervisor_group_ready(
                group,
                timeout_seconds=0.02,
                poll_seconds=0.005,
            )
            return incomplete, complete
        finally:
            sleeper.cancel()
            await asyncio.gather(sleeper, return_exceptions=True)

    incomplete, complete = asyncio.run(scenario())
    assert incomplete is False
    assert complete is True


def test_rotation_promotes_replacement_before_retiring_previous() -> None:
    source = Path("src/cocomelon/continuous_paper.py").read_text(
        encoding="utf-8"
    )
    rotation_guard_index = source.index(
        "if (\n"
        "                    not systemically_unhealthy_l2\n"
        "                    and now_ms >= next_selection_refresh_ms"
    )
    start_index = source.index(
        "replacement_group = await start_supervisors(",
        rotation_guard_index,
    )
    readiness_index = source.index(
        "await _wait_supervisor_group_ready(",
        start_index,
    )
    promote_index = source.index(
        "supervisor_group = replacement_group",
        readiness_index,
    )
    retire_index = source.index(
        "await _cancel_supervisor_group(",
        promote_index,
    )

    assert start_index < readiness_index < promote_index < retire_index
    window = source[start_index:retire_index]
    assert "forward_gaps=False" in window
    assert "replacement_group.forward_gaps.set()" in window
    assert "pipeline.reconcile_markets(selected)" in window
    assert "_l2_event_fresh_for_promotion(" in source
    assert "required_market_keys <= ready" in source

def test_runtime_checkpoints_write_off_event_loop_single_flight() -> None:
    source = Path("src/cocomelon/continuous_paper.py").read_text(
        encoding="utf-8"
    )
    snapshot_index = source.index(
        "def checkpoint_payloads()"
    )
    background_index = source.index(
        "async def maybe_start_background_checkpoint()",
        snapshot_index,
    )
    skip_index = source.index(
        "pump.checkpoint_background_skips += 1",
        background_index,
    )
    thread_index = source.index(
        "await asyncio.to_thread(",
        background_index,
    )
    runtime_index = source.index(
        "await maybe_start_background_checkpoint()",
        thread_index,
    )
    deadline_index = source.index(
        "utc_now_ms()\n"
        "                        + config.checkpoint_seconds * 1000",
        runtime_index,
    )
    flush_index = source.index(
        "await flush_background_checkpoint()",
        deadline_index,
    )

    assert (
        snapshot_index
        < background_index
        < skip_index
        < thread_index
        < runtime_index
        < deadline_index
        < flush_index
    )
    assert "persist_checkpoint_sync()" in source
    assert source.count(
        "await maybe_start_background_checkpoint()"
    ) == 1


def test_runtime_wakes_l2_recovery_on_completed_decision_epoch() -> None:
    source = Path("src/cocomelon/continuous_paper.py").read_text(
        encoding="utf-8"
    )
    helper_index = source.index(
        "async def recover_systemic_l2_if_needed()"
    )
    wake_wait_index = source.index(
        "await asyncio.wait_for(\n"
        "                        decision_epoch_wakeup.wait()",
        helper_index,
    )
    wake_recovery_index = source.index(
        "await recover_systemic_l2_if_needed()",
        wake_wait_index,
    )
    context_refresh_index = source.index(
        "await _refresh_native_market_snapshots(reader)",
        wake_recovery_index,
    )
    first_poll_recovery_index = source.index(
        "await recover_systemic_l2_if_needed()",
        context_refresh_index,
    )
    rotation_index = source.index(
        "not systemically_unhealthy_l2\n"
        "                    and now_ms >= next_selection_refresh_ms",
        first_poll_recovery_index,
    )
    late_check_index = source.index(
        "await recover_systemic_l2_if_needed()",
        rotation_index,
    )
    heartbeat_index = source.index(
        "_emit_operational_live_status(",
        late_check_index,
    )

    assert (
        helper_index
        < wake_wait_index
        < wake_recovery_index
        < context_refresh_index
        < first_poll_recovery_index
        < rotation_index
        < late_check_index
        < heartbeat_index
    )
    assert "decision_epoch_wakeup=decision_epoch_wakeup" in source
    assert "self._decision_epoch_wakeup.set()" in source
    assert source.count(
        "await recover_systemic_l2_if_needed()"
    ) == 3


def test_runtime_refreshes_clock_after_l2_recovery_before_context_due_check() -> None:
    source = Path("src/cocomelon/continuous_paper.py").read_text(
        encoding="utf-8"
    )
    wake_wait_index = source.index(
        "await asyncio.wait_for(\n"
        "                        decision_epoch_wakeup.wait()"
    )
    wake_recovery_index = source.index(
        "await recover_systemic_l2_if_needed()",
        wake_wait_index,
    )
    refreshed_clock_index = source.index(
        "now_ms = utc_now_ms()",
        wake_recovery_index,
    )
    context_due_index = source.index(
        "if now_ms < next_context_poll_ms:",
        refreshed_clock_index,
    )
    context_refresh_index = source.index(
        "await _refresh_native_market_snapshots(reader)",
        context_due_index,
    )

    assert (
        wake_recovery_index
        < refreshed_clock_index
        < context_due_index
        < context_refresh_index
    )
    window = source[wake_recovery_index:context_due_index]
    assert "recovery cannot starve" in window


def test_runtime_context_refresh_failure_retries_fail_closed() -> None:
    source = Path("src/cocomelon/continuous_paper.py").read_text(
        encoding="utf-8"
    )
    refresh_index = source.index(
        'pump.event_loop_phase = "context_refresh"'
    )
    attempt_index = source.index(
        "pump.context_refresh_attempts += 1",
        refresh_index,
    )
    call_index = source.index(
        "await _refresh_native_market_snapshots(reader)",
        attempt_index,
    )
    except_index = source.index(
        "except (InfoHttpError, TransportError) as refresh_exc:",
        call_index,
    )
    failure_index = source.index(
        "pump.context_refresh_failures += 1",
        except_index,
    )
    heartbeat_index = source.index(
        "_emit_operational_live_status(",
        failure_index,
    )
    continue_index = source.index(
        "continue",
        heartbeat_index,
    )
    success_index = source.index(
        "pump.context_refresh_successes += 1",
        continue_index,
    )

    assert (
        refresh_index
        < attempt_index
        < call_index
        < except_index
        < failure_index
        < heartbeat_index
        < continue_index
        < success_index
    )
    failure_window = source[except_index:continue_index]
    assert "context_refresh_consecutive_failures += 1" in failure_window
    assert "context_refresh_last_error" in failure_window
    assert "Keep the previous context timestamps untouched." in failure_window
    assert "refreshed_received_at_ms" not in failure_window.split(
        "_emit_operational_live_status(",
        1,
    )[1]


def test_stale_l2_gap_revokes_rotation_readiness() -> None:
    ready = {"BTC", "ETH"}
    required = frozenset({"BTC", "ETH"})

    _revoke_stale_l2_readiness(
        ready,
        DataGap(
            stream_id="l2Book:BTC",
            started_ms=10_000,
            ended_ms=None,
            reason="stale",
        ),
        required_market_keys=required,
    )
    assert ready == {"ETH"}

    _revoke_stale_l2_readiness(
        ready,
        DataGap(
            stream_id="l2Book:ETH",
            started_ms=10_000,
            ended_ms=10_001,
            reason="recovered",
        ),
        required_market_keys=required,
    )
    assert ready == {"ETH"}

    _revoke_stale_l2_readiness(
        ready,
        DataGap(
            stream_id="l2Book:ETH",
            started_ms=10_002,
            ended_ms=None,
            reason="disconnect",
        ),
        required_market_keys=required,
    )
    assert ready == set()


def test_l2_rotation_promotion_requires_fresh_exchange_timestamp() -> None:
    receive = datetime.fromtimestamp(10, tz=UTC)
    fresh = StreamEvent(
        kind=StreamKind.L2_BOOK,
        market=MarketId("", "BTC"),
        exchange_time_ms=9_999,
        receive_time=receive,
        schema_version=1,
        source="test",
        event_key="fresh-book",
        payload={"bids": (), "asks": ()},
    )
    stale = StreamEvent(
        kind=StreamKind.L2_BOOK,
        market=MarketId("", "BTC"),
        exchange_time_ms=4_000,
        receive_time=receive,
        schema_version=1,
        source="test",
        event_key="stale-book",
        payload={"bids": (), "asks": ()},
    )

    assert _l2_event_fresh_for_promotion(
        fresh,
        max_book_age_ms=5_000,
    )
    assert not _l2_event_fresh_for_promotion(
        stale,
        max_book_age_ms=5_000,
    )


def test_supervisor_group_health_payload_exposes_lane_failure_shape() -> None:
    required = frozenset({"BTC", "ETH", "SOL"})

    class Lane:
        def __init__(
            self,
            stale: tuple[str, ...],
            *,
            connected: bool,
            last_server_message_ms: int | None,
            reconnect_count: int,
        ) -> None:
            self._stale = stale
            self.health = SimpleNamespace(
                connected=connected,
                last_server_message_ms=last_server_message_ms,
                reconnect_count=reconnect_count,
                systemic_l2_stale_reconnect_count=0,
                duplicate_count=2,
                anomaly_count=1,
            )

        def stale_l2_streams(
            self,
            *,
            now_ms: int,
        ) -> tuple[str, ...]:
            del now_ms
            return self._stale

    group = _SupervisorGroup(
        supervisors=(
            Lane(
                ("l2Book:ETH", "l2Book:SOL"),
                connected=True,
                last_server_message_ms=9_900,
                reconnect_count=3,
            ),  # type: ignore[arg-type]
            Lane(
                ("l2Book:ETH",),
                connected=False,
                last_server_message_ms=9_000,
                reconnect_count=5,
            ),  # type: ignore[arg-type]
        ),
        tasks=(),
        forward_gaps=asyncio.Event(),
        required_market_keys=required,
        ready_market_keys=(
            {"BTC", "ETH", "SOL"},
            {"BTC", "ETH"},
        ),
        l2_exchange_age_ms_by_market=(
            {"BTC": -250, "ETH": 80, "SOL": 120},
            {"BTC": -300, "ETH": 90, "SOL": 140},
        ),
    )

    payload = _supervisor_group_health_payload(
        group,
        now_ms=10_000,
    )

    assert payload["required_market_count"] == 3
    assert payload["unhealthy_l2_market_count"] == 2
    assert payload["unhealthy_l2_markets"] == ["ETH", "SOL"]
    lanes = payload["lanes"]
    assert isinstance(lanes, list)
    assert lanes[0]["connected"] is True
    assert lanes[0]["ready_l2_market_count"] == 3
    assert lanes[0]["stale_l2_market_count"] == 2
    assert lanes[0]["last_server_message_age_ms"] == 100
    assert lanes[0]["l2_exchange_age_observed_market_count"] == 3
    assert lanes[0]["l2_exchange_age_negative_market_count"] == 1
    assert lanes[0]["l2_exchange_age_min_ms"] == -250
    assert lanes[0]["l2_exchange_age_max_ms"] == 120
    assert lanes[0]["l2_negative_exchange_age_markets"] == ["BTC"]
    assert lanes[0]["l2_exchange_age_ms_by_market"] == {
        "BTC": -250,
        "ETH": 80,
        "SOL": 120,
    }
    assert lanes[1]["connected"] is False
    assert lanes[1]["missing_ready_l2_markets"] == ["SOL"]
    assert lanes[1]["last_server_message_age_ms"] == 1_000
    assert lanes[1]["reconnect_count"] == 5
    assert lanes[1]["systemic_l2_stale_reconnect_count"] == 0


def test_supervisor_group_recovers_on_majority_stale_l2() -> None:
    required = frozenset({"BTC", "ETH", "SOL", "ENA"})

    class Lane:
        def __init__(self, stale: tuple[str, ...]) -> None:
            self._stale = stale

        def stale_l2_streams(
            self,
            *,
            now_ms: int,
        ) -> tuple[str, ...]:
            del now_ms
            return self._stale

    one_market = _SupervisorGroup(
        supervisors=(
            Lane(("l2Book:BTC",)),  # type: ignore[arg-type]
            Lane(("l2Book:BTC",)),  # type: ignore[arg-type]
        ),
        tasks=(),
        forward_gaps=asyncio.Event(),
        required_market_keys=required,
        ready_market_keys=(
            {"ETH", "SOL", "ENA"},
            {"ETH", "SOL", "ENA"},
        ),
    )
    majority = _SupervisorGroup(
        supervisors=(
            Lane(("l2Book:BTC", "l2Book:ETH")),  # type: ignore[arg-type]
            Lane(("l2Book:BTC", "l2Book:ETH")),  # type: ignore[arg-type]
        ),
        tasks=(),
        forward_gaps=asyncio.Event(),
        required_market_keys=required,
        ready_market_keys=(
            {"SOL", "ENA"},
            {"SOL", "ENA"},
        ),
    )
    split_lanes = _SupervisorGroup(
        supervisors=(
            Lane(("l2Book:BTC", "l2Book:ETH")),  # type: ignore[arg-type]
            Lane(("l2Book:SOL", "l2Book:ENA")),  # type: ignore[arg-type]
        ),
        tasks=(),
        forward_gaps=asyncio.Event(),
        required_market_keys=required,
        ready_market_keys=(
            {"SOL", "ENA"},
            {"BTC", "ETH"},
        ),
    )
    reconnect_grace_without_books = _SupervisorGroup(
        supervisors=(
            Lane(()),  # type: ignore[arg-type]
            Lane(()),  # type: ignore[arg-type]
        ),
        tasks=(),
        forward_gaps=asyncio.Event(),
        required_market_keys=required,
        ready_market_keys=(
            {"SOL"},
            {"ENA"},
        ),
    )

    assert one_market.systemically_stale_l2(now_ms=10_000) is False
    assert majority.systemically_stale_l2(now_ms=10_000) is True
    assert split_lanes.systemically_stale_l2(now_ms=10_000) is False
    assert (
        reconnect_grace_without_books.systemically_stale_l2(
            now_ms=10_000
        )
        is True
    )


def test_runtime_recovers_only_systemically_stale_l2_group() -> None:
    source = Path("src/cocomelon/continuous_paper.py").read_text(
        encoding="utf-8"
    )

    assert "supervisor.stale_l2_streams(now_ms=now_ms)" in source
    assert "systemically_stale_l2(" in source
    assert "pipeline_systemically_unhealthy_l2" in source
    assert "last_pipeline_stale_recovery_boundary_ms" in source
    assert "pump.stale_l2_pipeline_recovery_triggers += 1" in source
    assert "pump.stale_l2_rest_reseed_attempts += 1" in source
    assert "_reseed_l2_books_via_rest(" in source
    assert "pump.stale_l2_rest_reseed_books += reseeded_books" in source
    assert "pump.stale_l2_rest_reseed_failures += (" in source
    assert "pump.stale_l2_recovery_attempts += 1" in source
    assert "pump.stale_l2_recovery_promotions += 1" in source
    assert "stale_l2_recovery_readiness_failures += 1" in source
    assert (
        "stale_after_ms=(\n"
        "                        replay_config.eligibility.max_book_age_ms"
        in source
    )
    assert "_l2_event_fresh_for_promotion(" in source
    recovery_index = source.index(
        "systemically_unhealthy_l2 = ("
    )
    reseed_index = source.index(
        "_reseed_l2_books_via_rest(",
        recovery_index,
    )
    replacement_index = source.index(
        "replacement_group = await start_supervisors(",
        reseed_index,
    )
    assert recovery_index < reseed_index < replacement_index
    rotation_index = source.index(
        "if (\n"
        "                    not systemically_unhealthy_l2\n"
        "                    and now_ms >= next_selection_refresh_ms"
    )
    assert recovery_index < rotation_index


def test_context_refresh_timestamps_response_receipt() -> None:
    order: list[str] = []

    class Reader:
        def meta_and_asset_ctxs(self, dex: str = "") -> object:
            assert dex == ""
            order.append("response")
            return [
                {
                    "universe": [
                        {
                            "name": "BTC",
                            "szDecimals": 5,
                            "maxLeverage": 40,
                        }
                    ]
                },
                [
                    {
                        "dayNtlVlm": "1000000",
                        "funding": "0.00001",
                        "markPx": "65000",
                        "midPx": "65000",
                        "openInterest": "100",
                        "oraclePx": "65000",
                        "premium": "0",
                        "prevDayPx": "64000",
                    }
                ],
            ]

    def clock_ms() -> int:
        order.append("clock")
        return 10_500

    snapshots, received_at_ms = asyncio.run(
        _refresh_native_market_snapshots(
            Reader(),  # type: ignore[arg-type]
            clock_ms=clock_ms,
        )
    )

    assert order == ["response", "clock"]
    assert received_at_ms == 10_500
    assert snapshots["BTC"].received_at_ms == 10_500


def test_continuous_context_poll_has_freshness_headroom() -> None:
    config = ContinuousPaperConfig()
    workflow = Path(
        ".github/workflows/continuous-paper.yml"
    ).read_text(encoding="utf-8")

    assert config.context_poll_seconds == 30
    assert config.context_poll_seconds * 1000 < 60_000
    assert config.websocket_server_silence_timeout_ms == 15_000
    assert "--context-poll-seconds 30" in workflow
    assert "--websocket-server-silence-timeout-ms 15000" in workflow
    assert "--context-poll-seconds 60" not in workflow


def test_startup_warmup_seeds_before_fresh_context_starts_decisions() -> None:
    source = Path("src/cocomelon/continuous_paper.py").read_text(
        encoding="utf-8"
    )
    startup_index = source.index(
        "selected_keys = {market.canonical for market in selected}"
    )
    warmup_index = source.index(
        "for market in _iter_until_stop(selected, stop_path):",
        startup_index,
    )
    fresh_context_index = source.index(
        "startup_context_received_at_ms",
        warmup_index,
    )
    funding_index = source.index(
        "async def refresh_funding() -> None:",
        fresh_context_index,
    )

    bootstrap_window = source[startup_index:fresh_context_index]
    assert bootstrap_window.count("evaluate_decisions=False") >= 2
    assert "startup_context_refreshed_at_ms" not in source
    assert (
        startup_index
        < warmup_index
        < fresh_context_index
        < funding_index
    )


def test_continuous_config_requires_positive_websocket_silence_timeout() -> None:
    with pytest.raises(ValueError, match="websocket_server_silence_timeout_ms"):
        ContinuousPaperConfig(
            websocket_server_silence_timeout_ms=0,
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
    assert '"session_eligibility"' in source
    assert '"latest_epoch_eligibility"' in source
    assert '"stale_book_age_ms_by_market"' in source
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


def test_post_freshness_cohort_telemetry_fails_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("post-freshness boom")

    monkeypatch.setattr(
        "cocomelon.continuous_paper.post_freshness_paper_cohort_summary",
        fail,
    )
    payload = _post_freshness_paper_cohort_payload(
        SimpleNamespace(iter_trades=lambda: ()),  # type: ignore[arg-type]
    )

    assert payload["enabled"] is False
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False
    assert payload["error"] == "RuntimeError: post-freshness boom"


def test_clean_evidence_runway_telemetry_fails_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("runway boom")

    monkeypatch.setattr(
        "cocomelon.continuous_paper.clean_evidence_runway_summary",
        fail,
    )
    payload = _clean_evidence_runway_payload(
        SimpleNamespace(iter_records=lambda: ()),  # type: ignore[arg-type]
        SimpleNamespace(iter_records=lambda: ()),  # type: ignore[arg-type]
        SimpleNamespace(iter_trades=lambda: ()),  # type: ignore[arg-type]
        SimpleNamespace(  # type: ignore[arg-type]
            candidate_id="combined",
            started_at_ms=1_000,
        ),
        SimpleNamespace(  # type: ignore[arg-type]
            candidate_id="momentum",
            started_at_ms=2_000,
        ),
        SimpleNamespace(  # type: ignore[arg-type]
            candidate_id="two-strike",
            started_at_ms=1_500,
        ),
        timestamp_ms=3_000,
    )

    assert payload["enabled"] is False
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False
    assert payload["error"] == "RuntimeError: runway boom"


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

    operational_at = source.index(
        "def _operational_live_status_payload("
    )
    operational_end = source.index(
        "def _emit_operational_live_status(",
        operational_at,
    )
    operational = source[operational_at:operational_end]

    assert '"heartbeat_scope": "operational"' in operational
    for field in (
        "stale_l2_recovery_attempts",
        "stale_l2_recovery_promotions",
        "stale_l2_recovery_readiness_failures",
        "stale_l2_rest_reseed_attempts",
        "stale_l2_rest_reseed_books",
        "stale_l2_rest_reseed_failures",
        "stale_l2_pipeline_recovery_triggers",
        "stale_l2_pipeline_reason_fallback_triggers",
    ):
        assert f'"{field}"' in operational
    assert source.count("_emit_operational_live_status(") == 5
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
