from dataclasses import replace
from decimal import Decimal

from cocomelon.domain.execution import (
    ExecutionAttempt,
    ExecutionResult,
    OrderSide,
    OrderType,
    PaperFill,
    PaperOrderPlan,
    PositionAction,
    PositionActionType,
)
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass, ReplayRecord, SourceRecordKind
from cocomelon.execution.funding import FundingAccrual
from cocomelon.journal.assembler import (
    JournalInconsistency,
    TradeLifecycleInput,
    assemble_trade_journal_entry,
)

MARKET = MarketId("", "SOL")


def opening_plan() -> PaperOrderPlan:
    return PaperOrderPlan(
        risk_decision_id="risk-1",
        strategy_decision_id="strategy-1",
        market=MARKET,
        side=OrderSide.BUY,
        requested_quantity=Decimal("10"),
        order_type=OrderType.MARKETABLE_IOC,
        reduce_only=False,
        execution_reference_price=Decimal("99.9"),
        max_slippage_bps=Decimal("25"),
        stop_price=Decimal("95"),
        approved_notional_ceiling=Decimal("1100"),
        created_at_ms=900,
        earliest_execution_ms=1_000,
        execution_config_version="phase7-v1",
        instrument_metadata_received_at_ms=800,
        approved_risk_amount_ceiling=Decimal("25"),
        stop_distance_fraction=Decimal("0.05"),
        effective_loss_fraction=Decimal("0.0525"),
    )


def exit_plan(opening: PaperOrderPlan) -> PaperOrderPlan:
    return PaperOrderPlan(
        risk_decision_id=opening.risk_decision_id,
        strategy_decision_id=opening.strategy_decision_id,
        market=MARKET,
        side=OrderSide.SELL,
        requested_quantity=Decimal("10"),
        order_type=OrderType.MARKETABLE_IOC,
        reduce_only=True,
        execution_reference_price=Decimal("102.2"),
        max_slippage_bps=Decimal("25"),
        stop_price=None,
        approved_notional_ceiling=Decimal("1100"),
        created_at_ms=1_900,
        earliest_execution_ms=2_000,
        execution_config_version="phase7-v1",
        instrument_metadata_received_at_ms=800,
    )


def attempt(plan: PaperOrderPlan, avg: str, ts: int, suffix: str) -> ExecutionAttempt:
    quantity = plan.requested_quantity
    price = Decimal(avg)
    return ExecutionAttempt(
        plan_id=plan.plan_id,
        source_event_key=f"book-{suffix}",
        requested_quantity=quantity,
        filled_quantity=quantity,
        average_fill_price=price,
        gross_fill_notional=price * quantity,
        fee=Decimal("0"),
        unfilled_quantity=Decimal("0"),
        result=ExecutionResult.FULL,
        reason_codes=("FILLED",),
        snapshot_exchange_ms=ts - 10,
        snapshot_received_ms=ts - 5,
        attempt_timestamp_ms=ts,
    )


def fill(
    plan: PaperOrderPlan,
    attempt_: ExecutionAttempt,
    price: str,
    fee: str,
    ts: int,
) -> PaperFill:
    quantity = Decimal("10")
    px = Decimal(price)
    return PaperFill(
        plan_id=plan.plan_id,
        attempt_id=attempt_.attempt_id,
        market=MARKET,
        side=plan.side,
        price=px,
        quantity=quantity,
        notional=px * quantity,
        taker_fee=Decimal(fee),
        source_event_key=f"book:{ts}",
        timestamp_ms=ts,
    )


def mark(ts: int, px: str) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=ts,
        source="hyperliquid-mainnet-ws",
        schema_version=1,
        market="SOL",
        exchange_time_ms=None,
        event_key=f"ctx:{ts}",
        payload_json=f'{{"mark_px":"{px}"}}',
        event_kind="active_asset_ctx",
    )


def lifecycle() -> TradeLifecycleInput:
    open_plan = opening_plan()
    close_plan = exit_plan(open_plan)
    open_attempt = attempt(open_plan, "100", 1_000, "open")
    close_attempt = attempt(close_plan, "102", 2_000, "close")
    open_fill = fill(open_plan, open_attempt, "100", "0.45", 1_000)
    close_fill = fill(close_plan, close_attempt, "102", "0.459", 2_000)
    action = PositionAction(
        action_type=PositionActionType.EXIT_THESIS,
        market=MARKET,
        quantity=Decimal("10"),
        new_stop_price=None,
        reason_codes=("OPPOSING_THESIS",),
        timestamp_ms=1_900,
    )
    funding = FundingAccrual(
        market=MARKET,
        boundary_ms=1_500,
        position_id="position-1",
        signed_quantity=Decimal("10"),
        oracle_price=Decimal("100"),
        funding_rate=Decimal("0.0001"),
        cash_delta=Decimal("-0.1"),
        oracle_event_key="ctx:1500",
        funding_source="hyperliquid-mainnet-rest",
        funding_received_at_ms=1_600,
    )
    return TradeLifecycleInput(
        feature_snapshot_id="feature-1",
        opening_plan=open_plan,
        opening_attempt=open_attempt,
        exit_plans=(close_plan,),
        exit_attempts=(close_attempt,),
        fills=(open_fill, close_fill),
        position_actions=(action,),
        funding_accruals=(funding,),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10018.991"),
        exit_reason="exit_thesis",
        mark_observations=(mark(1_200, "98"), mark(1_800, "103")),
        known_gap_intervals=(),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id="run-1",
    )


def test_full_lifecycle_assembles_reconciled_trade_entry() -> None:
    result = assemble_trade_journal_entry(lifecycle())

    assert not isinstance(result, JournalInconsistency)
    assert result.market == MARKET
    assert result.entry_price == Decimal("100")
    assert result.exit_price == Decimal("102")
    assert result.gross_realized_pnl == Decimal("20")
    assert result.net_pnl == Decimal("18.991")
    assert result.net_r == Decimal("0.75964")
    assert result.funding_event_ids
    assert result.position_action_ids


def test_mismatched_fill_market_returns_structured_inconsistency() -> None:
    item = lifecycle()
    bad_fill = PaperFill(
        plan_id=item.fills[1].plan_id,
        attempt_id=item.fills[1].attempt_id,
        market=MarketId("", "BTC"),
        side=item.fills[1].side,
        price=item.fills[1].price,
        quantity=item.fills[1].quantity,
        notional=item.fills[1].notional,
        taker_fee=item.fills[1].taker_fee,
        source_event_key=item.fills[1].source_event_key,
        timestamp_ms=item.fills[1].timestamp_ms,
    )
    result = assemble_trade_journal_entry(replace(item, fills=(item.fills[0], bad_fill)))

    assert isinstance(result, JournalInconsistency)
    assert result.reason == "FILL_MARKET_MISMATCH"


def test_open_and_exit_quantity_must_reconcile_to_zero() -> None:
    item = lifecycle()
    half = PaperFill(
        plan_id=item.fills[1].plan_id,
        attempt_id=item.fills[1].attempt_id,
        market=MARKET,
        side=OrderSide.SELL,
        price=Decimal("102"),
        quantity=Decimal("5"),
        notional=Decimal("510"),
        taker_fee=Decimal("0.2295"),
        source_event_key="book:partial",
        timestamp_ms=2_000,
    )
    result = assemble_trade_journal_entry(replace(item, fills=(item.fills[0], half)))

    assert isinstance(result, JournalInconsistency)
    assert result.reason == "POSITION_NOT_FULLY_CLOSED"
