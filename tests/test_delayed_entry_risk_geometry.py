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
from cocomelon.research.delayed_entry_risk_geometry import (
    delayed_entry_risk_geometry_summary,
)

MARKET = MarketId("", "SOL")
RUN_ID = "continuous-paper-mainnet-v1"


def _trade(
    *,
    suffix: str,
    direction: Direction,
    initial_risk: str,
) -> TradeJournalEntry:
    return TradeJournalEntry(
        market=MARKET,
        direction=direction,
        opened_at_ms=1_000,
        closed_at_ms=100_000,
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
        initial_risk_amount=Decimal(initial_risk),
        entry_price=Decimal("100"),
        exit_price=Decimal("100"),
        filled_quantity=Decimal("2"),
        gross_realized_pnl=Decimal("0"),
        entry_fees=Decimal("0"),
        exit_fees=Decimal("0"),
        funding_cash_pnl=Decimal("0"),
        net_pnl=Decimal("0"),
        entry_slippage_amount=Decimal("0"),
        exit_slippage_amount=Decimal("0"),
        entry_slippage_fraction=Decimal("0"),
        exit_slippage_fraction=Decimal("0"),
        holding_duration_ms=99_000,
        mfe=None,
        mae=None,
        net_r=Decimal("0"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10000"),
        exit_reason="fixture",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id=RUN_ID,
    )


def _plan(
    trade: TradeJournalEntry,
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
        execution_reference_price=trade.entry_price,
        max_slippage_bps=Decimal("50"),
        stop_price=trade.initial_stop,
        approved_notional_ceiling=Decimal("1000"),
        created_at_ms=900,
        earliest_execution_ms=950,
        execution_config_version="paper-v1",
        instrument_metadata_received_at_ms=800,
        approved_risk_amount_ceiling=trade.initial_risk_amount,
        stop_distance_fraction=Decimal("0.10"),
        effective_loss_fraction=Decimal("0.101"),
    )


def _outcome(
    trade: TradeJournalEntry,
    *,
    source: str,
    quantity: str,
    price: str | None,
    reason: str | None = None,
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
        observation_lag_ms=1_000,
        signed_price_improvement_bps=None,
        gross_r_improvement=None,
        attempt_reason=reason,
        capacity_cause=None,
    )


def test_risk_geometry_separates_full_and_risk_clipped_attempts(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    try:
        full = _trade(
            suffix="full",
            direction=Direction.LONG,
            initial_risk="20.2",
        )
        clipped = _trade(
            suffix="clip",
            direction=Direction.LONG,
            initial_risk="20.2",
        )
        for trade in (full, clipped):
            journal.record_trade(trade)
        plans = {
            full.opening_plan_id: _plan(full),
            clipped.opening_plan_id: _plan(clipped),
        }

        result = delayed_entry_risk_geometry_summary(
            journal,
            (
                _outcome(
                    full,
                    source="full_visible_book_ioc",
                    quantity="2",
                    price="99",
                ),
                _outcome(
                    clipped,
                    source="partial_visible_book_ioc",
                    quantity="1.5",
                    price="101",
                    reason=(
                        "IOC_REMAINDER_CANCELLED,"
                        "RISK_CEILING_REACHED"
                    ),
                ),
            ),
            plans.get,
        )
    finally:
        journal.close()

    assert result["evaluated_filled_attempts"] == 2
    overall = result["overall"]
    assert isinstance(overall, dict)
    assert overall["attempts"] == 2
    assert overall["risk_clipped"] == 1
    assert overall["full_size_risk_above_ceiling"] == 1

    causes = result["by_cause"]
    assert isinstance(causes, dict)
    risk_clip = causes["risk_ceiling_clip"]
    assert risk_clip["attempts"] == 1
    assert risk_clip["risk_clipped"] == 1
    assert Decimal(
        str(risk_clip["mean_full_size_risk_ratio"])
    ) > Decimal("1")
    assert Decimal(
        str(risk_clip["mean_risk_capacity_fraction"])
    ) < Decimal("1")

    full_fill = causes["full_fill"]
    assert Decimal(
        str(full_fill["mean_full_size_risk_ratio"])
    ) < Decimal("1")
    assert Decimal(
        str(full_fill["mean_unit_risk_change_fraction"])
    ) < Decimal("0")


def test_short_better_entry_reduces_per_unit_risk(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    try:
        trade = _trade(
            suffix="short",
            direction=Direction.SHORT,
            initial_risk="20.2",
        )
        journal.record_trade(trade)
        plan = _plan(trade)

        result = delayed_entry_risk_geometry_summary(
            journal,
            (
                _outcome(
                    trade,
                    source="full_visible_book_ioc",
                    quantity="2",
                    price="101",
                ),
            ),
            lambda _plan_id: plan,
        )
    finally:
        journal.close()

    side = result["by_side"]
    assert isinstance(side, dict)
    short = side["short"]
    assert short["attempts"] == 1
    assert Decimal(
        str(short["mean_unit_risk_change_fraction"])
    ) < Decimal("0")
    assert Decimal(
        str(short["mean_full_size_risk_ratio"])
    ) < Decimal("1")


def test_missing_plan_is_reported_not_guessed(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    try:
        trade = _trade(
            suffix="missing",
            direction=Direction.LONG,
            initial_risk="20.2",
        )
        journal.record_trade(trade)
        result = delayed_entry_risk_geometry_summary(
            journal,
            (
                _outcome(
                    trade,
                    source="full_visible_book_ioc",
                    quantity="2",
                    price="99",
                ),
            ),
            lambda _plan_id: None,
        )
    finally:
        journal.close()

    assert result["evaluated_filled_attempts"] == 0
    assert result["missing_opening_plans"] == 1
    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert readiness["ready_for_review"] is False
