from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.execution import OrderSide, OrderType, PaperOrderPlan
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.journal.store import JournalStore
from cocomelon.research.delayed_entry_execution_shadow import (
    DelayedEntryOutcome,
)
from cocomelon.research.prospective_delayed_price_confirmation import (
    CANDIDATE_ID,
    ProspectiveDelayedPriceConfirmationError,
    ProspectiveDelayedPriceConfirmationState,
    prospective_delayed_price_confirmation_summary,
)

MARKET = MarketId("", "SOL")


def _trade(
    *,
    suffix: str,
    direction: Direction,
    opened_at_ms: int,
    pnl: str,
) -> TradeJournalEntry:
    net = Decimal(pnl)
    entry = Decimal("100")
    quantity = Decimal("1")
    exit_price = (
        entry + net
        if direction is Direction.LONG
        else entry - net
    )
    return TradeJournalEntry(
        market=MARKET,
        direction=direction,
        opened_at_ms=opened_at_ms,
        closed_at_ms=opened_at_ms + 180_000,
        feature_snapshot_id=f"feature-{suffix}",
        strategy_decision_id=f"strategy-{suffix}",
        risk_decision_id=f"risk-{suffix}",
        opening_plan_id=f"plan-{suffix}",
        opening_attempt_id=f"attempt-{suffix}",
        exit_plan_ids=(f"exit-plan-{suffix}",),
        exit_attempt_ids=(f"exit-attempt-{suffix}",),
        fill_ids=(f"open-fill-{suffix}", f"exit-fill-{suffix}"),
        position_action_ids=(f"action-{suffix}",),
        funding_event_ids=(),
        initial_stop=(
            Decimal("90")
            if direction is Direction.LONG
            else Decimal("110")
        ),
        initial_risk_amount=Decimal("10"),
        entry_price=entry,
        exit_price=exit_price,
        filled_quantity=quantity,
        gross_realized_pnl=net,
        entry_fees=Decimal("0"),
        exit_fees=Decimal("0"),
        funding_cash_pnl=Decimal("0"),
        net_pnl=net,
        entry_slippage_amount=Decimal("0"),
        exit_slippage_amount=Decimal("0"),
        entry_slippage_fraction=Decimal("0"),
        exit_slippage_fraction=Decimal("0"),
        holding_duration_ms=180_000,
        mfe=None,
        mae=None,
        net_r=net / Decimal("10"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10000") + net,
        exit_reason="fixture",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id="continuous-paper-mainnet-v1",
    )


def _plan(
    trade: TradeJournalEntry,
    *,
    reference: str = "100",
) -> PaperOrderPlan:
    side = (
        OrderSide.BUY
        if trade.direction is Direction.LONG
        else OrderSide.SELL
    )
    return PaperOrderPlan(
        risk_decision_id=trade.risk_decision_id,
        strategy_decision_id=trade.strategy_decision_id,
        market=trade.market,
        side=side,
        requested_quantity=trade.filled_quantity,
        order_type=OrderType.MARKETABLE_IOC,
        reduce_only=False,
        execution_reference_price=Decimal(reference),
        max_slippage_bps=Decimal("25"),
        stop_price=trade.initial_stop,
        approved_notional_ceiling=Decimal("200"),
        created_at_ms=trade.opened_at_ms - 1_000,
        earliest_execution_ms=trade.opened_at_ms - 900,
        execution_config_version="paper-v1",
        instrument_metadata_received_at_ms=trade.opened_at_ms - 2_000,
        approved_risk_amount_ceiling=trade.initial_risk_amount,
        stop_distance_fraction=Decimal("0.1"),
        effective_loss_fraction=Decimal("0.101"),
    )


def _outcome(
    trade: TradeJournalEntry,
    *,
    source: str,
    price: str | None,
    quantity: str = "1",
) -> DelayedEntryOutcome:
    return DelayedEntryOutcome(
        trade_id=trade.trade_id,
        opening_plan_id=trade.opening_plan_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        source=source,
        delayed_filled_quantity=Decimal(quantity),
        delayed_average_fill_price=(
            None if price is None else Decimal(price)
        ),
        delayed_fee=Decimal("0"),
        observation_lag_ms=500,
        signed_price_improvement_bps=None,
        gross_r_improvement=None,
    )


def test_price_confirmation_uses_future_trades_only_and_is_side_symmetric(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    try:
        old = _trade(
            suffix="old",
            direction=Direction.LONG,
            opened_at_ms=9_000,
            pnl="-20",
        )
        long_better = _trade(
            suffix="long-better",
            direction=Direction.LONG,
            opened_at_ms=11_000,
            pnl="-5",
        )
        short_better = _trade(
            suffix="short-better",
            direction=Direction.SHORT,
            opened_at_ms=12_000,
            pnl="4",
        )
        worse = _trade(
            suffix="worse",
            direction=Direction.LONG,
            opened_at_ms=13_000,
            pnl="-3",
        )
        no_fill = _trade(
            suffix="no-fill",
            direction=Direction.SHORT,
            opened_at_ms=14_000,
            pnl="-2",
        )
        trades = (old, long_better, short_better, worse, no_fill)
        for trade in trades:
            journal.record_trade(trade)
        plans = {
            trade.opening_plan_id: _plan(trade)
            for trade in trades
        }
        outcomes = (
            _outcome(
                old,
                source="full_visible_book_ioc",
                price="99",
            ),
            _outcome(
                long_better,
                source="full_visible_book_ioc",
                price="99",
            ),
            _outcome(
                short_better,
                source="full_visible_book_ioc",
                price="101",
            ),
            _outcome(
                worse,
                source="full_visible_book_ioc",
                price="101",
            ),
            _outcome(
                no_fill,
                source="no_fill",
                price=None,
                quantity="0",
            ),
        )

        result = prospective_delayed_price_confirmation_summary(
            journal,
            outcomes,
            plans.get,
            ProspectiveDelayedPriceConfirmationState(
                started_at_ms=10_000
            ),
        )
    finally:
        journal.close()

    assert result["prospective_closed_trades"] == 4
    assert result["evaluated_trades"] == 4
    assert result["confirmed_trades"] == 2
    assert result["skipped_trades"] == 2
    assert result["worse_price_skips"] == 1
    assert result["no_fill_skips"] == 1
    assert result["actual_net_pnl"] == "-6"
    assert result["candidate_trade_contribution_pnl"] == "1"
    assert result["delta_trade_contribution_pnl"] == "7"
    assert result["mean_confirmed_signed_improvement_bps"] == "100.00"
    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert readiness["ready_for_review"] is False


def test_partial_better_price_uses_fill_weighted_contribution(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    try:
        trade = _trade(
            suffix="partial",
            direction=Direction.LONG,
            opened_at_ms=11_000,
            pnl="10",
        )
        journal.record_trade(trade)
        plan = _plan(trade)
        outcome = _outcome(
            trade,
            source="partial_visible_book_ioc",
            price="99",
            quantity="0.5",
        )

        result = prospective_delayed_price_confirmation_summary(
            journal,
            (outcome,),
            lambda plan_id: (
                plan
                if plan_id == trade.opening_plan_id
                else None
            ),
            ProspectiveDelayedPriceConfirmationState(
                started_at_ms=10_000
            ),
        )
    finally:
        journal.close()

    assert result["confirmed_trades"] == 1
    assert result["skipped_trades"] == 0
    assert result["actual_net_pnl"] == "10"
    candidate = Decimal(
        str(result["candidate_trade_contribution_pnl"])
    )
    assert candidate > Decimal("5")
    assert candidate < Decimal("6")


def test_missing_plan_prevents_readiness(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    try:
        trade = _trade(
            suffix="missing-plan",
            direction=Direction.LONG,
            opened_at_ms=11_000,
            pnl="-5",
        )
        journal.record_trade(trade)
        result = prospective_delayed_price_confirmation_summary(
            journal,
            (
                _outcome(
                    trade,
                    source="full_visible_book_ioc",
                    price="99",
                ),
            ),
            lambda _plan_id: None,
            ProspectiveDelayedPriceConfirmationState(
                started_at_ms=10_000
            ),
        )
    finally:
        journal.close()

    assert result["evaluated_trades"] == 0
    assert result["missing_opening_plans"] == 1
    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert readiness["ready_for_review"] is False


def test_state_round_trip_rejects_rule_drift() -> None:
    state = ProspectiveDelayedPriceConfirmationState(
        started_at_ms=123
    )
    restored = ProspectiveDelayedPriceConfirmationState.from_payload(
        state.payload()
    )
    assert restored == state
    assert restored.candidate_id == CANDIDATE_ID

    payload = state.payload()
    rule = payload["rule"]
    assert isinstance(rule, dict)
    rule["minimum_signed_improvement_bps"] = "5"
    with pytest.raises(
        ProspectiveDelayedPriceConfirmationError,
        match="frozen candidate",
    ):
        ProspectiveDelayedPriceConfirmationState.from_payload(
            payload
        )
