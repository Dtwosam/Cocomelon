from __future__ import annotations

from decimal import Decimal

import pytest

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.research.loss_context_account_readiness import (
    loss_context_account_readiness,
)
from cocomelon.research.loss_context_candidate import build_loss_context_candidate_freeze
from cocomelon.research.loss_streak_context_audit import LOSS_STREAK_CONTEXT_SCHEMA_VERSION


def _freeze():
    candidate = {
        "dimensions": ("lead_strategy", "trend_regime"),
        "values": ("mean_reversion", "down"),
        "recurring_loss_streaks": 3,
        "discovery_rows": 14,
        "discovery_markets": 5,
        "discovery_loss_share": "0.7",
        "discovery_filter_delta_pnl": "30",
        "validation_rows": 12,
        "validation_markets": 4,
        "validation_loss_share": "0.75",
        "validation_filter_delta_pnl": "20",
        "validation_leave_one_trade_min_delta_pnl": "12",
        "validation_leave_one_market_min_delta_pnl": "6",
        "validation_block_rows": (6, 6),
        "validation_block_loss_shares": ("0.7", "0.8"),
        "validation_block_filter_delta_pnl": ("8", "12"),
        "validation_blocks_consistent": 2,
        "stable_on_validation": True,
        "strategy_authority": False,
        "risk_authority": False,
        "execution_authority": False,
    }
    audit = {
        "research_only": True,
        "descriptive_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_strategy": False,
        "changes_risk_limits": False,
        "schema_version": LOSS_STREAK_CONTEXT_SCHEMA_VERSION,
        "trade_count": 40,
        "max_trade_closed_at_ms": 9_000,
        "baseline_normalization_complete": True,
        "context_filter_stability": {
            "schema_version": 1,
            "candidate_count": 1,
            "stable_candidate_count": 1,
            "candidates": [candidate],
            "direction_only_candidates_allowed": False,
            "lead_strategy_context_required": True,
            "entry_time_context_only": True,
            "realized_net_pnl_economics_required": True,
            "chronological_holdout_required": True,
            "leave_one_trade_robustness_required": True,
            "leave_one_market_robustness_required": True,
            "validation_block_consistency_required": True,
            "prospective_freeze_required_before_strategy_use": True,
            "changes_strategy": False,
            "changes_risk_limits": False,
            "promotion_authority": False,
            "execution_authority": False,
        },
    }
    freeze = build_loss_context_candidate_freeze(
        audit,
        frozen_at_ms=10_000,
        source_paper_run_id=1,
        source_paper_run_attempt=1,
        source_paper_head_sha="a" * 40,
    )
    assert freeze is not None
    return freeze


def _trade(index: int, pnl: str) -> TradeJournalEntry:
    value = Decimal(pnl)
    return TradeJournalEntry(
        market=MarketId.from_wire_name("", ("A", "B", "C", "D")[index % 4]),
        direction=Direction.LONG if index % 2 == 0 else Direction.SHORT,
        opened_at_ms=50_000 + index,
        closed_at_ms=60_000 + index,
        feature_snapshot_id=f"feature-{index}",
        strategy_decision_id=f"strategy-{index}",
        risk_decision_id=f"risk-{index}",
        opening_plan_id=f"plan-{index}",
        opening_attempt_id=f"attempt-{index}",
        exit_plan_ids=(f"exit-plan-{index}",),
        exit_attempt_ids=(f"exit-attempt-{index}",),
        fill_ids=(f"open-{index}", f"close-{index}"),
        position_action_ids=(f"action-{index}",),
        funding_event_ids=(),
        initial_stop=Decimal("90"),
        initial_risk_amount=Decimal("10"),
        entry_price=Decimal("100"),
        exit_price=Decimal("100") + value,
        filled_quantity=Decimal("1"),
        gross_realized_pnl=value,
        entry_fees=Decimal("0"),
        exit_fees=Decimal("0"),
        funding_cash_pnl=Decimal("0"),
        net_pnl=value,
        entry_slippage_amount=Decimal("0"),
        exit_slippage_amount=Decimal("0"),
        entry_slippage_fraction=Decimal("0"),
        exit_slippage_fraction=Decimal("0"),
        holding_duration_ms=10_000,
        mfe=None,
        mae=None,
        net_r=value / Decimal("10"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10000") + value,
        exit_reason="MARK_STOP_TRIGGERED",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id="continuous-paper-mainnet-v1",
    )


def _case(allowed_pnl: str):
    freeze = _freeze()
    items = tuple(
        [(_trade(index, "-1"), True) for index in range(30)]
        + [(_trade(30 + index, allowed_pnl), False) for index in range(12)]
    )
    prospective = {
        "candidate_id": freeze.candidate_id,
        "future_resolved_trade_count": len(items),
        "future_unresolved_trade_count": 0,
        "matching_outcomes": 30,
        "total_filter_delta_pnl": "30",
        "source_complete": True,
        "ready_for_review": True,
        "prospective_only": True,
        "paper_only": True,
        "research_only": True,
        "changes_strategy": False,
        "changes_risk_limits": False,
        "promotion_authority": False,
        "execution_authority": False,
    }
    return freeze, items, prospective


def test_less_bad_but_still_losing_portfolio_stays_closed() -> None:
    freeze, items, prospective = _case("-0.5")
    result = loss_context_account_readiness(
        items,
        freeze=freeze,
        prospective_report=prospective,
    )
    economics = result["fixed_schedule_economics"]
    assert isinstance(economics, dict)
    assert Decimal(str(economics["delta_net_pnl"])) > 0
    assert Decimal(str(economics["candidate_net_pnl"])) < 0
    assert economics["improvement_positive"] is True
    assert economics["candidate_profitable"] is False
    assert result["ready_for_capacity_reflow_investigation"] is False


def test_profitable_robust_portfolio_can_advance_to_reflow_investigation() -> None:
    freeze, items, prospective = _case("1")
    result = loss_context_account_readiness(
        items,
        freeze=freeze,
        prospective_report=prospective,
    )
    economics = result["fixed_schedule_economics"]
    assert isinstance(economics, dict)
    assert economics["economics_ready"] is True
    assert result["ready_for_capacity_reflow_investigation"] is True
    assert result["capacity_reflow_modeled"] is False
    assert result["capacity_reflow_required_before_strategy_use"] is True
    assert result["direction_only_filter_allowed"] is False
    assert result["changes_strategy"] is False
    assert result["execution_authority"] is False


def test_d038_review_failure_keeps_account_gate_closed() -> None:
    freeze, items, prospective = _case("1")
    prospective["ready_for_review"] = False
    result = loss_context_account_readiness(
        items,
        freeze=freeze,
        prospective_report=prospective,
    )
    assert result["fixed_schedule_economics_ready"] is True
    assert result["prospective_filter_review_ready"] is False
    assert result["ready_for_capacity_reflow_investigation"] is False



def test_loss_context_account_gate_rejects_delta_source_drift() -> None:
    freeze, items, prospective = _case("1")
    prospective["total_filter_delta_pnl"] = "29"
    with pytest.raises(
        RuntimeError,
        match="LOSS_CONTEXT_FILTER_DELTA_MISMATCH",
    ):
        loss_context_account_readiness(
            items,
            freeze=freeze,
            prospective_report=prospective,
        )
