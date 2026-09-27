from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from cocomelon.domain.execution import (
    OrderSide,
    OrderType,
    PaperOrderPlan,
)
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.journal.store import JournalStore
from cocomelon.research.delayed_entry_execution_shadow import (
    DelayedEntryOutcome,
)
from cocomelon.research.delayed_entry_fixed_schedule_portfolio import (
    delayed_entry_fixed_schedule_portfolio,
)

MARKET = MarketId("", "SOL")


def _trade(
    *,
    suffix: str,
    direction: Direction,
    opened_at_ms: int,
    closed_at_ms: int,
    exit_price: str,
) -> TradeJournalEntry:
    entry = Decimal("100")
    exit_px = Decimal(exit_price)
    quantity = Decimal("2")
    gross = (
        (exit_px - entry) * quantity
        if direction is Direction.LONG
        else (entry - exit_px) * quantity
    )
    entry_fee = Decimal("0.5")
    exit_fee = Decimal("0.5")
    net = gross - entry_fee - exit_fee
    return TradeJournalEntry(
        market=MARKET,
        direction=direction,
        opened_at_ms=opened_at_ms,
        closed_at_ms=closed_at_ms,
        feature_snapshot_id=f"feature-{suffix}",
        strategy_decision_id=f"strategy-{suffix}",
        risk_decision_id=f"risk-{suffix}",
        opening_plan_id=f"plan-{suffix}",
        opening_attempt_id=f"attempt-{suffix}",
        exit_plan_ids=(f"exit-plan-{suffix}",),
        exit_attempt_ids=(f"exit-attempt-{suffix}",),
        fill_ids=(f"fill-open-{suffix}", f"fill-exit-{suffix}"),
        position_action_ids=(f"action-{suffix}",),
        funding_event_ids=(),
        initial_stop=(
            Decimal("90")
            if direction is Direction.LONG
            else Decimal("110")
        ),
        initial_risk_amount=Decimal("21"),
        entry_price=entry,
        exit_price=exit_px,
        filled_quantity=quantity,
        gross_realized_pnl=gross,
        entry_fees=entry_fee,
        exit_fees=exit_fee,
        funding_cash_pnl=Decimal("0"),
        net_pnl=net,
        entry_slippage_amount=Decimal("0"),
        exit_slippage_amount=Decimal("0"),
        entry_slippage_fraction=Decimal("0"),
        exit_slippage_fraction=Decimal("0"),
        holding_duration_ms=closed_at_ms - opened_at_ms,
        mfe=None,
        mae=None,
        net_r=net / Decimal("21"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10000") + net,
        exit_reason="fixture",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id="continuous-paper-mainnet-v1",
    )


def _plan(trade: TradeJournalEntry) -> PaperOrderPlan:
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
        execution_reference_price=trade.entry_price,
        max_slippage_bps=Decimal("25"),
        stop_price=trade.initial_stop,
        approved_notional_ceiling=Decimal("250"),
        created_at_ms=trade.opened_at_ms - 1_000,
        earliest_execution_ms=trade.opened_at_ms,
        execution_config_version="paper-v1",
        instrument_metadata_received_at_ms=trade.opened_at_ms - 2_000,
        approved_risk_amount_ceiling=trade.initial_risk_amount,
        stop_distance_fraction=Decimal("0.10"),
        effective_loss_fraction=Decimal("0.105"),
    )


def _outcome(
    trade: TradeJournalEntry,
    *,
    source: str,
    quantity: str,
    price: str | None,
    fee: str,
) -> DelayedEntryOutcome:
    delayed_quantity = Decimal(quantity)
    delayed_price = None if price is None else Decimal(price)
    return DelayedEntryOutcome(
        trade_id=trade.trade_id,
        opening_plan_id=trade.opening_plan_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        source=source,
        delayed_filled_quantity=delayed_quantity,
        delayed_average_fill_price=delayed_price,
        delayed_fee=Decimal(fee),
        observation_lag_ms=1_000,
        signed_price_improvement_bps=None,
        gross_r_improvement=None,
        attempt_reason=None,
        capacity_cause=None,
    )


def test_fixed_schedule_portfolio_tracks_overlap_exposure_and_drawdown(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    try:
        first = _trade(
            suffix="first",
            direction=Direction.LONG,
            opened_at_ms=100_000,
            closed_at_ms=400_000,
            exit_price="102",
        )
        second = _trade(
            suffix="second",
            direction=Direction.SHORT,
            opened_at_ms=130_000,
            closed_at_ms=430_000,
            exit_price="98",
        )
        third = _trade(
            suffix="third",
            direction=Direction.LONG,
            opened_at_ms=160_000,
            closed_at_ms=460_000,
            exit_price="98",
        )
        for trade in (first, second, third):
            journal.record_trade(trade)

        plans = {
            trade.opening_plan_id: _plan(trade)
            for trade in (first, second, third)
        }
        result = delayed_entry_fixed_schedule_portfolio(
            journal,
            (
                _outcome(
                    first,
                    source="full_visible_book_ioc",
                    quantity="2",
                    price="99",
                    fee="0.4",
                ),
                _outcome(
                    second,
                    source="partial_visible_book_ioc",
                    quantity="1",
                    price="101",
                    fee="0.2",
                ),
                _outcome(
                    third,
                    source="no_fill",
                    quantity="0",
                    price=None,
                    fee="0",
                ),
            ),
            plans.get,
        )
    finally:
        journal.close()

    assert result["evaluated_delayed_attempts"] == 3
    assert result["candidate_no_fill_trades"] == 1
    assert result["candidate_risk_ceiling_exceeded"] == 0
    assert result["replacement_trades_modeled"] is False
    assert result["changed_exit_timing_modeled"] is False
    assert result["unrealized_equity_modeled"] is False

    actual = result["actual"]
    candidate = result["candidate"]
    assert isinstance(actual, dict)
    assert isinstance(candidate, dict)
    assert actual["max_concurrent_positions"] == 3
    assert candidate["max_concurrent_positions"] == 2
    assert actual["overlap_openings"] == 2
    assert candidate["overlap_openings"] == 1
    assert Decimal(str(candidate["max_gross_notional"])) < Decimal(
        str(actual["max_gross_notional"])
    )
    assert Decimal(str(candidate["max_planned_risk"])) < Decimal(
        str(actual["max_planned_risk"])
    )
    assert Decimal(str(candidate["notional_exposure_hours"])) < Decimal(
        str(actual["notional_exposure_hours"])
    )
    assert result["delta_final_realized_contribution"] != "0"

    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert readiness["ready_for_review"] is False
    assert readiness["missing_actual_overlap_openings"] == 3


def test_fixed_schedule_portfolio_reports_unresolved_and_missing_plan(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    try:
        trade = _trade(
            suffix="missing-plan",
            direction=Direction.LONG,
            opened_at_ms=100_000,
            closed_at_ms=400_000,
            exit_price="102",
        )
        journal.record_trade(trade)
        result = delayed_entry_fixed_schedule_portfolio(
            journal,
            (
                _outcome(
                    trade,
                    source="expired",
                    quantity="0",
                    price=None,
                    fee="0",
                ),
                DelayedEntryOutcome(
                    trade_id=trade.trade_id + "-other",
                    opening_plan_id="missing-plan",
                    market=trade.market.canonical,
                    direction=trade.direction.value,
                    source="no_fill",
                    delayed_filled_quantity=Decimal("0"),
                    delayed_average_fill_price=None,
                    delayed_fee=Decimal("0"),
                    observation_lag_ms=1_000,
                    signed_price_improvement_bps=None,
                    gross_r_improvement=None,
                    attempt_reason=None,
                    capacity_cause=None,
                ),
            ),
            lambda _plan_id: None,
        )
    finally:
        journal.close()

    assert result["unresolved_outcomes"] == 1
    assert result["missing_journal_trades"] == 1
    assert result["evaluated_delayed_attempts"] == 0
    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert readiness["ready_for_review"] is False
