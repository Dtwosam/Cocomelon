from decimal import Decimal
from pathlib import Path

from cocomelon.domain.execution import (
    InstrumentExecutionSpec,
    OrderSide,
    OrderType,
    PaperExecutionConfig,
    PaperOrderPlan,
    PositionAction,
    PositionActionType,
)
from cocomelon.domain.market import MarketId
from cocomelon.execution.accounting import PaperPosition, PositionSide
from cocomelon.execution.planner import PlanningRejection, plan_reduce_only_order
from cocomelon.execution.store import PaperExecutionStore

MARKET = MarketId(dex="", coin="SOL")


def opening_plan() -> PaperOrderPlan:
    return PaperOrderPlan(
        risk_decision_id="risk-origin",
        strategy_decision_id="strategy-origin",
        market=MARKET,
        side=OrderSide.BUY,
        requested_quantity=Decimal("5"),
        order_type=OrderType.MARKETABLE_IOC,
        reduce_only=False,
        execution_reference_price=Decimal("100"),
        max_slippage_bps=Decimal("25"),
        stop_price=Decimal("95"),
        approved_notional_ceiling=Decimal("500"),
        created_at_ms=1_000,
        earliest_execution_ms=1_250,
        execution_config_version="phase7-v1",
        instrument_metadata_received_at_ms=900,
        approved_risk_amount_ceiling=Decimal("25"),
        stop_distance_fraction=Decimal("0.05"),
        effective_loss_fraction=Decimal("0.0525"),
    )


def position(plan: PaperOrderPlan) -> PaperPosition:
    return PaperPosition(
        market=MARKET,
        side=PositionSide.LONG,
        quantity=Decimal("5"),
        average_entry_price=Decimal("100"),
        stop_price=Decimal("95"),
        opening_plan_id=plan.plan_id,
        opened_at_ms=1_300,
        updated_at_ms=1_300,
        initial_risk_decision_id=plan.risk_decision_id,
        correlation_bucket="sol-beta",
        cost_buffer_fraction=Decimal("0.0025"),
        planned_risk=Decimal("25"),
    )


def instrument() -> InstrumentExecutionSpec:
    return InstrumentExecutionSpec(
        market=MARKET,
        sz_decimals=2,
        venue_max_leverage=Decimal("20"),
        minimum_order_notional=Decimal("10"),
        metadata_received_at_ms=1_500,
        metadata_source="hyperliquid-mainnet-meta",
    )


def exit_action() -> PositionAction:
    return PositionAction(
        action_type=PositionActionType.EXIT_STOP,
        market=MARKET,
        quantity=Decimal("5"),
        new_stop_price=None,
        reason_codes=("MARK_STOP_TRIGGERED",),
        timestamp_ms=2_000,
    )


def test_store_recovers_originating_plan_lineage_after_restart(tmp_path: Path) -> None:
    path = tmp_path / "paper.sqlite3"
    plan = opening_plan()
    store = PaperExecutionStore(path)
    store.persist_plan(plan)
    store.close()

    reopened = PaperExecutionStore(path)
    try:
        assert reopened.load_plan_lineage(plan.plan_id) == (
            plan.risk_decision_id,
            plan.strategy_decision_id,
        )
        assert reopened.load_plan_lineage("missing-plan") is None
    finally:
        reopened.close()


def test_reduce_only_plan_preserves_originating_trade_lineage() -> None:
    origin = opening_plan()
    planned = plan_reduce_only_order(
        position(origin),
        exit_action(),
        instrument(),
        PaperExecutionConfig(),
        originating_risk_decision_id=origin.risk_decision_id,
        originating_strategy_decision_id=origin.strategy_decision_id,
        reference_price=Decimal("95"),
        created_at_ms=2_000,
    )

    assert not isinstance(planned, PlanningRejection)
    assert planned.risk_decision_id == origin.risk_decision_id
    assert planned.strategy_decision_id == origin.strategy_decision_id


def test_reduce_only_plan_rejects_risk_lineage_that_disagrees_with_position() -> None:
    origin = opening_plan()
    rejected = plan_reduce_only_order(
        position(origin),
        exit_action(),
        instrument(),
        PaperExecutionConfig(),
        originating_risk_decision_id="wrong-risk",
        originating_strategy_decision_id=origin.strategy_decision_id,
        reference_price=Decimal("95"),
        created_at_ms=2_000,
    )

    assert isinstance(rejected, PlanningRejection)
    assert rejected.reason == "ORIGINATING_RISK_DECISION_MISMATCH"
