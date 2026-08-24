import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.execution import (
    ExecutionAttempt,
    ExecutionResult,
    OrderSide,
    OrderType,
    PaperFill,
    PaperOrderPlan,
)
from cocomelon.domain.market import MarketId
from cocomelon.execution.accounting import apply_opening_fills, empty_account
from cocomelon.execution.funding import FundingAccrual, funding_cash_delta
from cocomelon.execution.store import PaperExecutionStore

MARKET = MarketId("", "SOL")


def plan() -> PaperOrderPlan:
    return PaperOrderPlan(
        risk_decision_id="risk-store-1",
        strategy_decision_id="strategy-store-1",
        market=MARKET,
        side=OrderSide.BUY,
        requested_quantity=Decimal("2"),
        order_type=OrderType.MARKETABLE_IOC,
        reduce_only=False,
        execution_reference_price=Decimal("100"),
        max_slippage_bps=Decimal("25"),
        stop_price=Decimal("95"),
        approved_notional_ceiling=Decimal("250"),
        created_at_ms=1_000,
        earliest_execution_ms=1_250,
        execution_config_version="phase7-v1",
        instrument_metadata_received_at_ms=900,
        approved_risk_amount_ceiling=Decimal("20"),
        stop_distance_fraction=Decimal("0.05"),
        effective_loss_fraction=Decimal("0.0525"),
    )


def fill(order: PaperOrderPlan) -> PaperFill:
    return PaperFill(
        plan_id=order.plan_id,
        attempt_id="attempt-store-1",
        market=MARKET,
        side=OrderSide.BUY,
        price=Decimal("100"),
        quantity=Decimal("2"),
        notional=Decimal("200"),
        taker_fee=Decimal("0.09"),
        source_event_key="l2:SOL:store",
        timestamp_ms=1_300,
    )


def attempt(order: PaperOrderPlan) -> ExecutionAttempt:
    return ExecutionAttempt(
        plan_id=order.plan_id,
        source_event_key="l2:SOL:store",
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
        attempt_timestamp_ms=1_300,
    )


def opened_state(order: PaperOrderPlan, paper_fill: PaperFill):
    return apply_opening_fills(
        empty_account(Decimal("10000"), 1_000),
        order,
        (paper_fill,),
        correlation_bucket="crypto_beta",
        venue_max_leverage=Decimal("20"),
    )


def funding_accrual(account) -> FundingAccrual:
    position = account.positions[0]
    rate = Decimal("0.001")
    oracle = Decimal("100")
    return FundingAccrual(
        market=MARKET,
        boundary_ms=3_600_000,
        position_id=position.position_id,
        signed_quantity=position.quantity,
        oracle_price=oracle,
        funding_rate=rate,
        cash_delta=funding_cash_delta(position.quantity, oracle, rate),
        oracle_event_key="ctx:SOL:store-funding",
        funding_source="hyperliquid-mainnet-info",
        funding_received_at_ms=3_601_000,
    )


def test_store_creates_only_required_phase7_operational_tables(tmp_path: Path) -> None:
    path = tmp_path / "paper.sqlite3"
    store = PaperExecutionStore(path)
    store.close()

    with sqlite3.connect(path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }

    assert tables == {
        "paper_meta",
        "paper_order_plans",
        "paper_execution_attempts",
        "paper_fills",
        "paper_positions",
        "paper_position_events",
        "paper_funding_events",
        "paper_account_state",
        "paper_rolling_peak_candidates",
    }


def test_plan_and_execution_round_trip_restart_exactly(tmp_path: Path) -> None:
    path = tmp_path / "paper.sqlite3"
    order = plan()
    paper_fill = fill(order)
    execution = attempt(order)
    account = opened_state(order, paper_fill)

    store = PaperExecutionStore(path)
    store.persist_plan(order)
    store.persist_execution(execution, (paper_fill,), account)
    store.close()

    reopened = PaperExecutionStore(path)
    result = reopened.load_and_reconcile()
    reopened.close()

    assert result.healthy is True
    assert result.reason_codes == ()
    assert result.account is not None
    assert result.account.state_id == account.state_id


def test_duplicate_plan_and_execution_are_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "paper.sqlite3"
    order = plan()
    paper_fill = fill(order)
    execution = attempt(order)
    account = opened_state(order, paper_fill)
    store = PaperExecutionStore(path)

    store.persist_plan(order)
    store.persist_plan(order)
    store.persist_execution(execution, (paper_fill,), account)
    store.persist_execution(execution, (paper_fill,), account)

    counts = store.table_counts()
    store.close()
    assert counts["paper_order_plans"] == 1
    assert counts["paper_execution_attempts"] == 1
    assert counts["paper_fills"] == 1
    assert counts["paper_positions"] == 1


def test_same_immutable_id_with_different_payload_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "paper.sqlite3"
    order = plan()
    store = PaperExecutionStore(path)
    store.persist_plan(order)

    with store.raw_connection() as conn:
        conn.execute(
            "UPDATE paper_order_plans SET payload_json = '{}' WHERE plan_id = ?",
            (order.plan_id,),
        )

    with pytest.raises(ValueError, match="immutable payload mismatch"):
        store.persist_plan(order)
    store.close()


def test_funding_lookup_and_immutable_payload_guard(tmp_path: Path) -> None:
    path = tmp_path / "paper.sqlite3"
    order = plan()
    paper_fill = fill(order)
    account = opened_state(order, paper_fill)
    accrual = funding_accrual(account)
    store = PaperExecutionStore(path)

    assert store.has_funding_accrual(accrual.accrual_id) is False
    store.persist_funding(accrual, account)
    assert store.has_funding_accrual(accrual.accrual_id) is True

    with store.raw_connection() as conn:
        conn.execute(
            "UPDATE paper_funding_events SET payload_json = '{}' WHERE accrual_id = ?",
            (accrual.accrual_id,),
        )

    with pytest.raises(ValueError, match="immutable payload mismatch"):
        store.persist_funding(accrual, account)
    store.close()


def test_execution_transaction_rolls_back_on_position_constraint_failure(tmp_path: Path) -> None:
    path = tmp_path / "paper.sqlite3"
    order = plan()
    paper_fill = fill(order)
    execution = attempt(order)
    account = opened_state(order, paper_fill)
    store = PaperExecutionStore(path)
    store.persist_plan(order)

    with store.raw_connection() as conn:
        conn.execute(
            "CREATE TRIGGER reject_position BEFORE INSERT ON paper_positions "
            "BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
        )

    with pytest.raises(sqlite3.IntegrityError, match="injected failure"):
        store.persist_execution(execution, (paper_fill,), account)

    counts = store.table_counts()
    store.close()
    assert counts["paper_execution_attempts"] == 0
    assert counts["paper_fills"] == 0
    assert counts["paper_account_state"] == 0


def test_materialized_position_tamper_makes_restart_unhealthy(tmp_path: Path) -> None:
    path = tmp_path / "paper.sqlite3"
    order = plan()
    paper_fill = fill(order)
    execution = attempt(order)
    account = opened_state(order, paper_fill)
    store = PaperExecutionStore(path)
    store.persist_plan(order)
    store.persist_execution(execution, (paper_fill,), account)

    with store.raw_connection() as conn:
        conn.execute(
            "UPDATE paper_positions SET payload_json = ? WHERE market = ?",
            ("{}", MARKET.canonical),
        )

    result = store.load_and_reconcile()
    store.close()
    assert result.healthy is False
    assert "MATERIALIZED_POSITION_MISMATCH" in result.reason_codes


def test_database_enforces_one_active_position_per_market(tmp_path: Path) -> None:
    path = tmp_path / "paper.sqlite3"
    store = PaperExecutionStore(path)
    with store.raw_connection() as conn:
        conn.execute(
            "INSERT INTO paper_positions(market, position_id, payload_json) VALUES (?, ?, ?)",
            (MARKET.canonical, "one", "{}"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO paper_positions(market, position_id, payload_json) VALUES (?, ?, ?)",
                (MARKET.canonical, "two", "{}"),
            )
    store.close()
