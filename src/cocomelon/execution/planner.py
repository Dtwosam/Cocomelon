from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Context, Decimal, localcontext

from cocomelon.domain.execution import (
    InstrumentExecutionSpec,
    OrderSide,
    OrderType,
    PaperExecutionConfig,
    PaperOrderPlan,
)
from cocomelon.domain.risk import RiskDecision
from cocomelon.domain.strategy import Direction

ZERO = Decimal("0")
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
    if risk_decision.market != instrument.market:
        return PlanningRejection("MARKET_MISMATCH")
    if not instrument.execution_supported:
        return PlanningRejection(instrument.unsupported_reason or "EXECUTION_UNSUPPORTED")
    if not reference_price.is_finite() or reference_price <= ZERO:
        return PlanningRejection("INVALID_REFERENCE_PRICE")
    if created_at_ms < 0:
        return PlanningRejection("INVALID_CREATED_AT")
    if instrument.metadata_received_at_ms > created_at_ms:
        return PlanningRejection("FUTURE_INSTRUMENT_METADATA")

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
    )
