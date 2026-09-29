from __future__ import annotations

from decimal import Decimal

from cocomelon.domain.execution import OrderSide, OrderType, PaperFill, PaperOrderPlan
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.execution.funding import FundingAccrual
from cocomelon.research.cross_day_trade_cash import (
    cross_day_trade_cash_contribution,
)

DAY_MS = 86_400_000
MARKET = MarketId.from_wire_name("", "SOL")


def _exit_plan() -> PaperOrderPlan:
    return PaperOrderPlan(
        risk_decision_id="risk-exit",
        strategy_decision_id="strategy-exit",
        market=MARKET,
        side=OrderSide.SELL,
        requested_quantity=Decimal("1"),
        order_type=OrderType.MARKETABLE_IOC,
        reduce_only=True,
        execution_reference_price=Decimal("82"),
        max_slippage_bps=Decimal("25"),
        stop_price=None,
        approved_notional_ceiling=Decimal("1000"),
        created_at_ms=DAY_MS + 40_000,
        earliest_execution_ms=DAY_MS + 40_000,
        execution_config_version="phase7-v1",
        instrument_metadata_received_at_ms=DAY_MS - 10_000,
    )


def _funding(boundary_ms: int, cash: str) -> FundingAccrual:
    return FundingAccrual(
        market=MARKET,
        boundary_ms=boundary_ms,
        position_id="position-cross-day",
        signed_quantity=Decimal("1"),
        oracle_price=Decimal("100"),
        funding_rate=Decimal("0.001"),
        cash_delta=Decimal(cash),
        oracle_event_key=f"oracle-{boundary_ms}",
        funding_source="fixture",
        funding_received_at_ms=boundary_ms,
    )


def test_cross_day_cash_uses_only_current_day_exit_and_funding_cash() -> None:
    plan = _exit_plan()
    exit_fill = PaperFill(
        plan_id=plan.plan_id,
        attempt_id="exit-attempt",
        market=MARKET,
        side=OrderSide.SELL,
        price=Decimal("82"),
        quantity=Decimal("1"),
        notional=Decimal("82"),
        taker_fee=Decimal("1"),
        source_event_key="exit-book",
        timestamp_ms=DAY_MS + 50_000,
    )
    pre_day_funding = _funding(
        DAY_MS - 3_600_000,
        "-0.5",
    )
    same_day_funding = _funding(DAY_MS, "1.5")
    trade = TradeJournalEntry(
        market=MARKET,
        direction=Direction.LONG,
        opened_at_ms=DAY_MS - 7_200_000,
        closed_at_ms=DAY_MS + 50_000,
        feature_snapshot_id="feature-cross-day",
        strategy_decision_id="strategy-cross-day",
        risk_decision_id="risk-cross-day",
        opening_plan_id="opening-cross-day",
        opening_attempt_id="opening-attempt",
        exit_plan_ids=(plan.plan_id,),
        exit_attempt_ids=("exit-attempt",),
        fill_ids=("opening-fill", exit_fill.fill_id),
        position_action_ids=("close-action",),
        funding_event_ids=(
            pre_day_funding.accrual_id,
            same_day_funding.accrual_id,
        ),
        initial_stop=Decimal("90"),
        initial_risk_amount=Decimal("10"),
        entry_price=Decimal("100"),
        exit_price=Decimal("82"),
        filled_quantity=Decimal("1"),
        gross_realized_pnl=Decimal("-18"),
        entry_fees=Decimal("2"),
        exit_fees=Decimal("1"),
        funding_cash_pnl=Decimal("1"),
        net_pnl=Decimal("-20"),
        entry_slippage_amount=Decimal("0"),
        exit_slippage_amount=Decimal("0"),
        entry_slippage_fraction=Decimal("0"),
        exit_slippage_fraction=Decimal("0"),
        holding_duration_ms=7_250_000,
        mfe=None,
        mae=None,
        net_r=Decimal("-2"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("9980"),
        exit_reason="fixture",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id="continuous-mainnet-paper-v1",
    )

    contribution = cross_day_trade_cash_contribution(
        trade,
        day_start_ms=DAY_MS,
        end_ms=DAY_MS + 60_000,
        plan_loader=lambda plan_id: (
            plan if plan_id == plan.plan_id else None
        ),
        execution_history_loader=lambda _plan_id: (
            (),
            (exit_fill,),
        ),
        funding_loader=lambda _market: (
            pre_day_funding,
            same_day_funding,
        ),
    )

    assert contribution.realized_gross_pnl == Decimal("-18")
    assert contribution.exit_fees == Decimal("1")
    assert contribution.funding_cash_pnl == Decimal("1.5")
    assert contribution.net_cash_pnl == Decimal("-17.5")
    assert contribution.entry_fees_excluded is True
    assert contribution.lifecycle_reconciled is True


def test_cross_day_cash_fails_closed_on_missing_funding_lineage() -> None:
    plan = _exit_plan()
    exit_fill = PaperFill(
        plan_id=plan.plan_id,
        attempt_id="exit-attempt",
        market=MARKET,
        side=OrderSide.SELL,
        price=Decimal("80"),
        quantity=Decimal("1"),
        notional=Decimal("80"),
        taker_fee=Decimal("0"),
        source_event_key="exit-book",
        timestamp_ms=DAY_MS + 50_000,
    )
    funding = _funding(DAY_MS, "1")
    trade = TradeJournalEntry(
        market=MARKET,
        direction=Direction.LONG,
        opened_at_ms=DAY_MS - 1_000,
        closed_at_ms=DAY_MS + 50_000,
        feature_snapshot_id="feature-missing-funding",
        strategy_decision_id="strategy-missing-funding",
        risk_decision_id="risk-missing-funding",
        opening_plan_id="opening-missing-funding",
        opening_attempt_id="opening-attempt",
        exit_plan_ids=(plan.plan_id,),
        exit_attempt_ids=("exit-attempt",),
        fill_ids=("opening-fill", exit_fill.fill_id),
        position_action_ids=("close-action",),
        funding_event_ids=(funding.accrual_id,),
        initial_stop=Decimal("90"),
        initial_risk_amount=Decimal("10"),
        entry_price=Decimal("100"),
        exit_price=Decimal("80"),
        filled_quantity=Decimal("1"),
        gross_realized_pnl=Decimal("-20"),
        entry_fees=Decimal("0"),
        exit_fees=Decimal("0"),
        funding_cash_pnl=Decimal("1"),
        net_pnl=Decimal("-19"),
        entry_slippage_amount=Decimal("0"),
        exit_slippage_amount=Decimal("0"),
        entry_slippage_fraction=Decimal("0"),
        exit_slippage_fraction=Decimal("0"),
        holding_duration_ms=51_000,
        mfe=None,
        mae=None,
        net_r=Decimal("-1.9"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("9981"),
        exit_reason="fixture",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id="continuous-mainnet-paper-v1",
    )

    try:
        cross_day_trade_cash_contribution(
            trade,
            day_start_ms=DAY_MS,
            end_ms=DAY_MS + 60_000,
            plan_loader=lambda _plan_id: plan,
            execution_history_loader=lambda _plan_id: (
                (),
                (exit_fill,),
            ),
            funding_loader=lambda _market: (),
        )
    except RuntimeError as exc:
        assert "CROSS_DAY_FUNDING_LINEAGE_INCOMPLETE" in str(exc)
    else:
        raise AssertionError("missing funding lineage must fail closed")
