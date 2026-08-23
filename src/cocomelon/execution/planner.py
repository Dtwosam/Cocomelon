from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Context, Decimal, localcontext

from cocomelon.domain.execution import (
    InstrumentExecutionSpec,
    OrderSide,
    OrderType,
    PaperExecutionConfig,
    PaperOrderPlan,
    PositionAction,
    PositionActionType,
)
from cocomelon.domain.risk import RiskDecision
from cocomelon.domain.strategy import Direction
from cocomelon.execution.accounting import PaperPosition, PositionSide

ZERO = Decimal("0")
ONE = Decimal("1")
BPS = Decimal("10000")
AUTHORITATIVE_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)


@dataclass(frozen=True, slots=True)
class PlanningRejection:
    reason: str


def plan_opening_order(
    risk_decision: RiskDecision,
    instrument: InstrumentExecutionSpec,
    config: PaperExecutionConfig,
    reference_price: Decimal,
    created_at_ms: int,
) -> PaperOrderPlan | PlanningRejection:
    if not risk_decision.approved:
        return PlanningRejection("RISK_NOT_APPROVED")
    if risk_decision.direction is Direction.NO_TRADE:
        return PlanningRejection("NO_TRADE")
    if not instrument.execution_supported:
        return PlanningRejection(instrument.unsupported_reason or "EXECUTION_UNSUPPORTED")
    if risk_decision.market != instrument.market:
        return PlanningRejection("MARKET_MISMATCH")
    if not reference_price.is_finite() or reference_price <= ZERO:
        return PlanningRejection("INVALID_REFERENCE_PRICE")
    if created_at_ms < 0:
        return PlanningRejection("INVALID_CREATED_AT")
    if instrument.metadata_received_at_ms > created_at_ms:
        return PlanningRejection("FUTURE_INSTRUMENT_METADATA")
    if (
        risk_decision.stop_price is None
        or risk_decision.stop_distance_fraction is None
        or risk_decision.effective_loss_fraction is None
        or risk_decision.approved_risk_amount <= ZERO
    ):
        return PlanningRejection("INCOMPLETE_RISK_ENVELOPE")

    with localcontext(AUTHORITATIVE_CONTEXT):
        raw_quantity = risk_decision.approved_notional / reference_price
        quantity = raw_quantity.quantize(instrument.size_quantum, rounding=ROUND_DOWN)
        if quantity <= ZERO:
            return PlanningRejection("QUANTITY_ROUNDED_TO_ZERO")
        planned_notional = quantity * reference_price

    minimum_notional = max(
        instrument.minimum_order_notional,
        config.native_perp_min_notional,
    )
    if planned_notional < minimum_notional:
        return PlanningRejection("BELOW_MINIMUM_NOTIONAL")
    if planned_notional > risk_decision.approved_notional:
        return PlanningRejection("APPROVED_NOTIONAL_EXCEEDED")

    side = OrderSide.BUY if risk_decision.direction is Direction.LONG else OrderSide.SELL
    return PaperOrderPlan(
        risk_decision_id=risk_decision.risk_decision_id,
        strategy_decision_id=risk_decision.strategy_decision_id,
        market=risk_decision.market,
        side=side,
        requested_quantity=quantity,
        order_type=OrderType.MARKETABLE_IOC,
        reduce_only=False,
        execution_reference_price=reference_price,
        max_slippage_bps=config.max_ioc_slippage_bps,
        stop_price=risk_decision.stop_price,
        approved_notional_ceiling=risk_decision.approved_notional,
        created_at_ms=created_at_ms,
        earliest_execution_ms=created_at_ms + config.latency_ms,
        execution_config_version=config.config_version,
        instrument_metadata_received_at_ms=instrument.metadata_received_at_ms,
        approved_risk_amount_ceiling=risk_decision.approved_risk_amount,
        stop_distance_fraction=risk_decision.stop_distance_fraction,
        effective_loss_fraction=risk_decision.effective_loss_fraction,
    )


def plan_reduce_only_order(
    position: PaperPosition,
    action: PositionAction,
    instrument: InstrumentExecutionSpec,
    config: PaperExecutionConfig,
    *,
    reference_price: Decimal,
    created_at_ms: int,
) -> PaperOrderPlan | PlanningRejection:
    executable_actions = {
        PositionActionType.REDUCE,
        PositionActionType.EXIT_THESIS,
        PositionActionType.EXIT_STOP,
        PositionActionType.EXIT_EMERGENCY,
    }
    if action.action_type not in executable_actions:
        return PlanningRejection("ACTION_NOT_EXECUTABLE")
    if action.market != position.market or instrument.market != position.market:
        return PlanningRejection("MARKET_MISMATCH")
    if not instrument.execution_supported:
        return PlanningRejection(instrument.unsupported_reason or "EXECUTION_UNSUPPORTED")
    if not reference_price.is_finite() or reference_price <= ZERO:
        return PlanningRejection("INVALID_REFERENCE_PRICE")
    if created_at_ms < 0:
        return PlanningRejection("INVALID_CREATED_AT")
    if action.timestamp_ms > created_at_ms:
        return PlanningRejection("FUTURE_POSITION_ACTION")
    if instrument.metadata_received_at_ms > created_at_ms:
        return PlanningRejection("FUTURE_INSTRUMENT_METADATA")
    if action.quantity is None or action.quantity <= ZERO:
        return PlanningRejection("INVALID_REDUCTION_QUANTITY")

    with localcontext(AUTHORITATIVE_CONTEXT):
        target_quantity = min(action.quantity, position.quantity)
        quantity = target_quantity.quantize(instrument.size_quantum, rounding=ROUND_DOWN)
        if quantity <= ZERO:
            return PlanningRejection("QUANTITY_ROUNDED_TO_ZERO")
        slippage_fraction = config.max_ioc_slippage_bps / BPS
        notional_ceiling = quantity * reference_price * (ONE + slippage_fraction)

    side = OrderSide.SELL if position.side is PositionSide.LONG else OrderSide.BUY
    return PaperOrderPlan(
        risk_decision_id=f"reduce-only:{position.opening_plan_id}",
        strategy_decision_id=(
            f"position-action:{action.action_type.value}:{action.timestamp_ms}"
        ),
        market=position.market,
        side=side,
        requested_quantity=quantity,
        order_type=OrderType.MARKETABLE_IOC,
        reduce_only=True,
        execution_reference_price=reference_price,
        max_slippage_bps=config.max_ioc_slippage_bps,
        stop_price=position.stop_price,
        approved_notional_ceiling=notional_ceiling,
        created_at_ms=created_at_ms,
        earliest_execution_ms=created_at_ms + config.latency_ms,
        execution_config_version=config.config_version,
        instrument_metadata_received_at_ms=instrument.metadata_received_at_ms,
    )
