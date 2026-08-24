from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.execution import (
    ExecutionAttempt,
    ExecutionResult,
    OrderSide,
    OrderType,
    PaperExecutionConfig,
    PaperFill,
    PaperOrderPlan,
)
from cocomelon.domain.market import MarketId
from cocomelon.execution.accounting import (
    apply_funding_accrual,
    apply_opening_fills,
    empty_account,
    mark_to_market,
)
from cocomelon.execution.funding import FundingAccrual, funding_cash_delta
from cocomelon.execution.paper import PaperExecutionAdapter
from cocomelon.execution.store import PaperExecutionStore

MARKET = MarketId("", "SOL")
STARTING_CASH = Decimal("10000")
OPENED_MS = 1_300
MARKED_MS = 2_000
BOUNDARY_MS = 3_600_000
APPLIED_MS = BOUNDARY_MS + 1_000


def _plan(side: OrderSide) -> PaperOrderPlan:
    stop = Decimal("95") if side is OrderSide.BUY else Decimal("105")
    return PaperOrderPlan(
        risk_decision_id=f"risk-funding-{side.value}",
        strategy_decision_id=f"strategy-funding-{side.value}",
        market=MARKET,
        side=side,
        requested_quantity=Decimal("2"),
        order_type=OrderType.MARKETABLE_IOC,
        reduce_only=False,
        execution_reference_price=Decimal("100"),
        max_slippage_bps=Decimal("25"),
        stop_price=stop,
        approved_notional_ceiling=Decimal("250"),
        created_at_ms=1_000,
        earliest_execution_ms=1_250,
        execution_config_version="phase7-v1",
        instrument_metadata_received_at_ms=900,
        approved_risk_amount_ceiling=Decimal("20"),
        stop_distance_fraction=Decimal("0.05"),
        effective_loss_fraction=Decimal("0.0525"),
    )


def _fill(plan: PaperOrderPlan) -> PaperFill:
    return PaperFill(
        plan_id=plan.plan_id,
        attempt_id=f"attempt-{plan.side.value}",
        market=MARKET,
        side=plan.side,
        price=Decimal("100"),
        quantity=Decimal("2"),
        notional=Decimal("200"),
        taker_fee=Decimal("0.09"),
        source_event_key=f"l2:SOL:{plan.side.value}",
        timestamp_ms=OPENED_MS,
    )


def _attempt(plan: PaperOrderPlan) -> ExecutionAttempt:
    return ExecutionAttempt(
        plan_id=plan.plan_id,
        source_event_key=f"l2:SOL:{plan.side.value}",
        requested_quantity=Decimal("2"),
        filled_quantity=Decimal("2"),
        average_fill_price=Decimal("100"),
        gross_fill_notional=Decimal("200"),
        fee=Decimal("0.09"),
        unfilled_quantity=Decimal("0"),
        result=ExecutionResult.FULL,
        reason_codes=("FILLED_VISIBLE_DEPTH",),
        snapshot_exchange_ms=1_250,
        snapshot_received_ms=1_260,
        attempt_timestamp_ms=OPENED_MS,
    )


def _marked_account(side: OrderSide):
    plan = _plan(side)
    fill = _fill(plan)
    opened = apply_opening_fills(
        empty_account(STARTING_CASH, 1_000),
        plan,
        (fill,),
        correlation_bucket="crypto_beta",
        venue_max_leverage=Decimal("20"),
    )
    mark = Decimal("110") if side is OrderSide.BUY else Decimal("90")
    return mark_to_market(opened, {MARKET: mark}, MARKED_MS)


def _accrual(account, *, rate: Decimal = Decimal("0.001")) -> FundingAccrual:
    position = account.positions[0]
    signed_quantity = (
        position.quantity if position.side.value == "long" else -position.quantity
    )
    oracle = Decimal("100")
    return FundingAccrual(
        market=MARKET,
        boundary_ms=BOUNDARY_MS,
        position_id=position.position_id,
        signed_quantity=signed_quantity,
        oracle_price=oracle,
        funding_rate=rate,
        cash_delta=funding_cash_delta(signed_quantity, oracle, rate),
        oracle_event_key="ctx:SOL:funding",
        funding_source="hyperliquid-mainnet-info",
        funding_received_at_ms=BOUNDARY_MS + 500,
    )


@pytest.mark.parametrize(
    ("side", "expected_delta"),
    (
        (OrderSide.BUY, Decimal("-0.200")),
        (OrderSide.SELL, Decimal("0.200")),
    ),
)
def test_apply_funding_updates_cash_equity_and_position_without_losing_marks(
    side: OrderSide,
    expected_delta: Decimal,
) -> None:
    prior = _marked_account(side)
    accrual = _accrual(prior)

    updated = apply_funding_accrual(prior, accrual, APPLIED_MS)

    assert accrual.cash_delta == expected_delta
    assert updated.cash == prior.cash + expected_delta
    assert updated.cumulative_funding == prior.cumulative_funding + expected_delta
    assert updated.positions[0].cumulative_funding == (
        prior.positions[0].cumulative_funding + expected_delta
    )
    assert updated.daily_realized_pnl == prior.daily_realized_pnl + expected_delta
    assert updated.realized_gross_pnl == prior.realized_gross_pnl
    assert updated.cumulative_fees == prior.cumulative_fees
    assert updated.unrealized_pnl == prior.unrealized_pnl
    assert updated.gross_open_notional == prior.gross_open_notional
    assert updated.reserved_margin == prior.reserved_margin
    assert updated.positions[0].latest_mark == prior.positions[0].latest_mark
    assert updated.equity == updated.cash + updated.unrealized_pnl
    assert updated.updated_at_ms == APPLIED_MS


def test_apply_funding_rejects_wrong_position_lineage_and_backward_time() -> None:
    prior = _marked_account(OrderSide.BUY)
    accrual = _accrual(prior)
    wrong = FundingAccrual(
        market=accrual.market,
        boundary_ms=accrual.boundary_ms,
        position_id="wrong-position",
        signed_quantity=accrual.signed_quantity,
        oracle_price=accrual.oracle_price,
        funding_rate=accrual.funding_rate,
        cash_delta=accrual.cash_delta,
        oracle_event_key=accrual.oracle_event_key,
        funding_source=accrual.funding_source,
        funding_received_at_ms=accrual.funding_received_at_ms,
    )

    with pytest.raises(ValueError, match="position"):
        apply_funding_accrual(prior, wrong, APPLIED_MS)
    with pytest.raises(ValueError, match="timestamp"):
        apply_funding_accrual(prior, accrual, MARKED_MS - 1)


def _seed_adapter(path: Path, side: OrderSide) -> None:
    plan = _plan(side)
    fill = _fill(plan)
    account = _marked_account(side)
    store = PaperExecutionStore(path)
    store.persist_plan(plan)
    store.persist_execution(_attempt(plan), (fill,), account)
    store.close()


def test_adapter_funding_is_idempotent_before_and_after_restart(tmp_path: Path) -> None:
    path = tmp_path / "paper.sqlite3"
    _seed_adapter(path, OrderSide.BUY)
    adapter = PaperExecutionAdapter(
        path,
        PaperExecutionConfig(),
        starting_cash=STARTING_CASH,
        startup_timestamp_ms=1_000,
    )
    accrual = _accrual(adapter.account)

    first = adapter.apply_funding(accrual, timestamp_ms=APPLIED_MS)
    first_state_id = first.state_id
    first_cash = first.cash
    first_funding = first.cumulative_funding
    second = adapter.apply_funding(accrual, timestamp_ms=APPLIED_MS + 1_000)

    assert second.state_id == first_state_id
    assert second.cash == first_cash
    assert second.cumulative_funding == first_funding
    assert adapter.store.has_funding_accrual(accrual.accrual_id) is True
    adapter.close()

    reopened = PaperExecutionAdapter(
        path,
        PaperExecutionConfig(),
        starting_cash=STARTING_CASH,
        startup_timestamp_ms=1_000,
    )
    third = reopened.apply_funding(accrual, timestamp_ms=APPLIED_MS + 2_000)
    assert third.state_id == first_state_id
    assert third.cash == first_cash
    assert third.cumulative_funding == first_funding
    assert reopened.store.table_counts()["paper_funding_events"] == 1
    reopened.close()
