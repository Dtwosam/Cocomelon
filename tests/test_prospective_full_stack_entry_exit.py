from __future__ import annotations

from decimal import Decimal

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.research.profit_lock_execution_shadow import (
    ProfitLockExecutionOutcome,
)
from cocomelon.research.prospective_breakeven_profit_lock import (
    ProspectiveBreakevenProfitLockState,
)
from cocomelon.research.prospective_full_stack_entry_exit import (
    prospective_full_stack_entry_exit_summary,
)


def _trade(
    suffix: str,
    *,
    direction: Direction,
    pnl: str,
    opened_at_ms: int,
    market: str,
) -> TradeJournalEntry:
    net = Decimal(pnl)
    risk = Decimal("10")
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
        initial_risk_amount=risk,
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
        net_r=net / risk,
        equity_before=Decimal("10000"),
        equity_after=Decimal("10000") + net,
        exit_reason="MARK_STOP_TRIGGERED",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id="continuous-paper-mainnet-v1",
    )


def _outcome(
    trade: TradeJournalEntry,
    *,
    candidate_pnl: str | None,
) -> dict[str, object]:
    candidate = (
        None
        if candidate_pnl is None
        else Decimal(candidate_pnl)
    )
    outcome = ProfitLockExecutionOutcome(
        trade_id=trade.trade_id,
        opening_plan_id=trade.opening_plan_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        rule_id="breakeven_after_0_5r",
        activated=True,
        triggered=True,
        simulated_close_complete=candidate is not None,
        activation_timestamp_ms=trade.opened_at_ms + 1_000,
        trigger_timestamp_ms=trade.opened_at_ms + 2_000,
        completion_timestamp_ms=(
            trade.opened_at_ms + 3_000
            if candidate is not None
            else None
        ),
        simulated_filled_quantity=(
            Decimal("1")
            if candidate is not None
            else Decimal("0")
        ),
        simulated_average_exit_price=(
            Decimal("100")
            if candidate is not None
            else None
        ),
        simulated_exit_fees=Decimal("0"),
        attempt_count=1,
        planning_rejection_count=0,
        no_fill_count=0,
        actual_net_pnl=trade.net_pnl,
        actual_net_r=trade.net_r,
        candidate_net_pnl_estimate=candidate,
        candidate_net_r_estimate=(
            None
            if candidate is None
            else candidate / trade.initial_risk_amount
        ),
        delta_net_pnl_estimate=(
            None
            if candidate is None
            else candidate - trade.net_pnl
        ),
        delta_net_r_estimate=(
            None
            if candidate is None
            else candidate / trade.initial_risk_amount - trade.net_r
        ),
        candidate_source=(
            "visible_book_ioc"
            if candidate is not None
            else "triggered_incomplete"
        ),
    )
    return outcome.payload()


def test_full_stack_applies_exit_only_to_entry_admitted_trades() -> None:
    start = 30_000_000
    breakeven = ProspectiveBreakevenProfitLockState(
        frozen_at_ms=start - 6 * 60 * 60 * 1_000
    )
    blocked = _trade(
        "blocked",
        direction=Direction.LONG,
        pnl="-8",
        opened_at_ms=start + 1_000,
        market="SOL",
    )
    admitted = _trade(
        "admitted",
        direction=Direction.SHORT,
        pnl="-6",
        opened_at_ms=start + 2_000,
        market="ETH",
    )
    combined = {
        "started_at_ms": start,
        "decision_block_reason_by_trade_id": {
            blocked.trade_id: "long_trend_block",
            admitted.trade_id: None,
        },
    }
    two = {
        "started_at_ms": start,
        "decision_prior_strikes": {
            blocked.trade_id: 0,
            admitted.trade_id: 0,
        },
    }
    momentum = {
        "started_at_ms": start,
        "decision_details": {
            blocked.trade_id: {"decision": "ADMIT"},
            admitted.trade_id: {"decision": "ADMIT"},
        },
    }
    execution_state = {
        "outcomes": [
            _outcome(blocked, candidate_pnl="5"),
            _outcome(admitted, candidate_pnl="1"),
        ]
    }

    result = prospective_full_stack_entry_exit_summary(
        (blocked, admitted),
        combined,
        two,
        momentum,
        execution_state,
        breakeven,
    )

    assert result["closed_trades_since_overlap_start"] == 2
    assert result["economically_evaluated_trades"] == 2
    assert result["entry_blocked_trades"] == 1
    assert result["entry_admitted_trades"] == 1
    assert result["actual_net_pnl"] == "-14"
    assert result["entry_stack_candidate_net_pnl"] == "-6"
    assert result["full_stack_candidate_net_pnl"] == "1"
    assert result["full_stack_delta_net_pnl"] == "15"
    assert result["breakeven_incremental_net_pnl"] == "7"
    assert result["integrity_clean"] is True
    decisions = result["decision_by_trade_id"]
    assert isinstance(decisions, dict)
    assert decisions[blocked.trade_id]["exit_evaluation"] == "NOT_APPLICABLE"
    assert decisions[admitted.trade_id]["exit_evaluation"] == "EVALUATED"


def test_full_stack_reports_missing_exit_only_for_admitted_trade() -> None:
    start = 30_000_000
    breakeven = ProspectiveBreakevenProfitLockState(
        frozen_at_ms=start - 6 * 60 * 60 * 1_000
    )
    blocked = _trade(
        "blocked-missing",
        direction=Direction.LONG,
        pnl="-8",
        opened_at_ms=start + 1_000,
        market="SOL",
    )
    admitted = _trade(
        "admitted-missing",
        direction=Direction.SHORT,
        pnl="-6",
        opened_at_ms=start + 2_000,
        market="ETH",
    )
    combined = {
        "started_at_ms": start,
        "decision_block_reason_by_trade_id": {
            blocked.trade_id: None,
            admitted.trade_id: None,
        },
    }
    two = {
        "started_at_ms": start,
        "decision_prior_strikes": {
            blocked.trade_id: 2,
            admitted.trade_id: 0,
        },
    }
    momentum = {
        "started_at_ms": start,
        "decision_details": {
            blocked.trade_id: {"decision": "ADMIT"},
            admitted.trade_id: {"decision": "ADMIT"},
        },
    }

    result = prospective_full_stack_entry_exit_summary(
        (blocked, admitted),
        combined,
        two,
        momentum,
        {"outcomes": []},
        breakeven,
    )

    assert result["entry_blocked_trades"] == 1
    assert result["entry_admitted_trades"] == 1
    assert result["missing_breakeven_outcomes"] == 1
    assert result["economically_evaluated_trades"] == 1
    assert result["integrity_clean"] is False
    assert result["actual_net_pnl"] == "-8"
    assert result["full_stack_candidate_net_pnl"] == "0"


def test_full_stack_reports_unevaluable_exact_outcome() -> None:
    start = 30_000_000
    breakeven = ProspectiveBreakevenProfitLockState(
        frozen_at_ms=start - 6 * 60 * 60 * 1_000
    )
    trade = _trade(
        "unevaluable",
        direction=Direction.LONG,
        pnl="-5",
        opened_at_ms=start + 1_000,
        market="SOL",
    )
    combined = {
        "started_at_ms": start,
        "decision_block_reason_by_trade_id": {trade.trade_id: None},
    }
    two = {
        "started_at_ms": start,
        "decision_prior_strikes": {trade.trade_id: 0},
    }
    momentum = {
        "started_at_ms": start,
        "decision_details": {
            trade.trade_id: {"decision": "ADMIT"}
        },
    }

    result = prospective_full_stack_entry_exit_summary(
        (trade,),
        combined,
        two,
        momentum,
        {"outcomes": [_outcome(trade, candidate_pnl=None)]},
        breakeven,
    )

    assert result["missing_breakeven_outcomes"] == 0
    assert result["unevaluable_breakeven_outcomes"] == 1
    assert result["economically_evaluated_trades"] == 0
    assert result["integrity_clean"] is False
