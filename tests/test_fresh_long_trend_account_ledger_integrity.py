"""Read-only v3 economic audit proves individual real execution cash lineage."""
from __future__ import annotations

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
from cocomelon.research.fresh_long_trend_account_audit import (
    V3AccountAuditError,
    _verified_original_execution_cash,
)

M = MarketId("", "SOL")


def _real_execution_store(path: Path) -> None:
    plan = PaperOrderPlan(
        risk_decision_id="risk",
        strategy_decision_id="strategy",
        market=M,
        side=OrderSide.BUY,
        requested_quantity=Decimal("2"),
        order_type=OrderType.MARKETABLE_IOC,
        reduce_only=False,
        execution_reference_price=Decimal("100"),
        max_slippage_bps=Decimal("25"),
        stop_price=Decimal("95"),
        approved_notional_ceiling=Decimal("250"),
        created_at_ms=1000,
        earliest_execution_ms=1250,
        execution_config_version="phase7-v1",
        instrument_metadata_received_at_ms=900,
        approved_risk_amount_ceiling=Decimal("20"),
        stop_distance_fraction=Decimal("0.05"),
        effective_loss_fraction=Decimal("0.0525"),
    )
    attempt = ExecutionAttempt(
        plan_id=plan.plan_id,
        source_event_key="book:SOL",
        requested_quantity=Decimal("2"),
        filled_quantity=Decimal("2"),
        average_fill_price=Decimal("100"),
        gross_fill_notional=Decimal("200"),
        fee=Decimal("0.09"),
        unfilled_quantity=Decimal("0"),
        result=ExecutionResult.FULL,
        reason_codes=("FILLED_VISIBLE_DEPTH",),
        snapshot_exchange_ms=1250,
        snapshot_received_ms=1260,
        attempt_timestamp_ms=1300,
    )
    fill = PaperFill(
        plan_id=plan.plan_id,
        attempt_id=attempt.attempt_id,
        market=M,
        side=OrderSide.BUY,
        price=Decimal("100"),
        quantity=Decimal("2"),
        notional=Decimal("200"),
        taker_fee=Decimal("0.09"),
        source_event_key="book:SOL",
        timestamp_ms=1300,
    )
    account = apply_opening_fills(
        empty_account(Decimal("10000"), 1000),
        plan, (fill,),
        correlation_bucket="crypto_beta",
        venue_max_leverage=Decimal("20"),
    )
    accrual = FundingAccrual(
        market=M, boundary_ms=3_600_000,
        position_id=account.positions[0].position_id,
        signed_quantity=Decimal("2"),
        oracle_price=Decimal("100"),
        funding_rate=Decimal("0.001"),
        cash_delta=funding_cash_delta(
            Decimal("2"), Decimal("100"), Decimal("0.001")
        ),
        oracle_event_key="ctx:SOL", funding_source="hyperliquid-mainnet-info",
        funding_received_at_ms=3_601_000,
    )
    store = PaperExecutionStore(path)
    store.persist_plan(plan)
    store.persist_execution(attempt, (fill,), account)
    store.persist_funding(accrual, account)
    store.close()


def _verify(path: Path) -> tuple[Decimal, Decimal, int, int, int]:
    with sqlite3.connect(path.resolve(strict=True).as_uri() + "?mode=ro&immutable=1",
                         uri=True) as conn:
        conn.execute("PRAGMA query_only = ON")
        return _verified_original_execution_cash(conn)


def test_v3_original_execution_history_accepts_real_fills_and_funding(
    tmp_path: Path,
) -> None:
    path = tmp_path / "real.sqlite3"
    _real_execution_store(path)
    original = path.read_bytes()
    assert _verify(path) == (
        Decimal("0.09"), Decimal("-0.200"), 1, 1, 1
    )
    assert path.read_bytes() == original


@pytest.mark.parametrize("corruption", [
    "fill_id", "fill_attempt", "fill_fee", "funding_id", "funding_amount",
    "attempt_id", "plan_id",
])
def test_v3_original_row_integrity_denies_balanced_or_rewritten_journals(
    tmp_path: Path, corruption: str,
) -> None:
    path = tmp_path / "tampered.sqlite3"
    _real_execution_store(path)
    with sqlite3.connect(path) as conn:
        if corruption == "fill_id":
            conn.execute("UPDATE paper_fills SET fill_id = 'fake'")
        elif corruption == "fill_attempt":
            conn.execute("UPDATE paper_fills SET attempt_id = 'fake'")
        elif corruption == "fill_fee":
            conn.execute(
                "UPDATE paper_fills SET payload_json = "
                "REPLACE(payload_json, '0.09', '0.10')"
            )
        elif corruption == "funding_id":
            conn.execute("UPDATE paper_funding_events SET accrual_id = 'fake'")
        elif corruption == "funding_amount":
            conn.execute(
                "UPDATE paper_funding_events SET payload_json = "
                "REPLACE(payload_json, '-0.200', '0.200')"
            )
        elif corruption == "attempt_id":
            conn.execute(
                "UPDATE paper_execution_attempts SET attempt_id = 'fake'"
            )
        else:
            conn.execute("UPDATE paper_order_plans SET plan_id = 'fake'")
    tampered = path.read_bytes()
    with pytest.raises(V3AccountAuditError):
        _verify(path)
    assert path.read_bytes() == tampered
