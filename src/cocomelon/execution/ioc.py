from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Context, Decimal, localcontext

from cocomelon.domain.execution import (
    ExecutionAttempt,
    ExecutionResult,
    InstrumentExecutionSpec,
    OrderSide,
    PaperExecutionConfig,
    PaperFill,
    PaperOrderPlan,
)
from cocomelon.domain.stream import StreamEvent, StreamKind

ZERO = Decimal("0")
ONE = Decimal("1")
BPS = Decimal("10000")
AUTHORITATIVE_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)


@dataclass(frozen=True, slots=True)
class IocSimulation:
    attempt: ExecutionAttempt
    fills: tuple[PaperFill, ...]


@dataclass(frozen=True, slots=True)
class _Level:
    price: Decimal
    quantity: Decimal
    index: int


def _receive_time_ms(event: StreamEvent) -> int:
    return int(event.receive_time.timestamp() * 1000)


def _rejected(
    plan: PaperOrderPlan,
    event: StreamEvent,
    attempt_timestamp_ms: int,
    reason: str,
) -> IocSimulation:
    received_ms = _receive_time_ms(event)
    attempt = ExecutionAttempt(
        plan_id=plan.plan_id,
        source_event_key=event.event_key,
        requested_quantity=plan.requested_quantity,
        filled_quantity=ZERO,
        average_fill_price=None,
        gross_fill_notional=ZERO,
        fee=ZERO,
        unfilled_quantity=plan.requested_quantity,
        result=ExecutionResult.REJECTED,
        reason_codes=(reason,),
        snapshot_exchange_ms=event.exchange_time_ms,
        snapshot_received_ms=received_ms,
        attempt_timestamp_ms=max(attempt_timestamp_ms, 0),
    )
    return IocSimulation(attempt=attempt, fills=())


def _parse_levels(value: object) -> tuple[_Level, ...] | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return None
    parsed: list[_Level] = []
    for index, raw in enumerate(value):
        if not isinstance(raw, Mapping):
            return None
        price = raw.get("px")
        quantity = raw.get("sz")
        if not isinstance(price, Decimal) or not isinstance(quantity, Decimal):
            return None
        if (
            not price.is_finite()
            or not quantity.is_finite()
            or price <= ZERO
            or quantity <= ZERO
        ):
            return None
        parsed.append(_Level(price=price, quantity=quantity, index=index))
    return tuple(parsed)


def _floor_quantity(value: Decimal, quantum: Decimal) -> Decimal:
    if value <= ZERO:
        return ZERO
    return value.quantize(quantum, rounding=ROUND_DOWN)


def _risk_per_quantity(
    plan: PaperOrderPlan,
    price: Decimal,
    cost_buffer_fraction: Decimal,
) -> Decimal:
    if plan.stop_price is None:
        raise ValueError("opening IOC requires stop_price")
    if plan.side is OrderSide.BUY:
        return price * (ONE + cost_buffer_fraction) - plan.stop_price
    return plan.stop_price - price * (ONE - cost_buffer_fraction)


def simulate_ioc(
    plan: PaperOrderPlan,
    event: StreamEvent,
    instrument: InstrumentExecutionSpec,
    config: PaperExecutionConfig,
    *,
    attempt_timestamp_ms: int,
) -> IocSimulation:
    if attempt_timestamp_ms < 0:
        return _rejected(plan, event, attempt_timestamp_ms, "INVALID_ATTEMPT_TIMESTAMP")
    if event.kind is not StreamKind.L2_BOOK:
        return _rejected(plan, event, attempt_timestamp_ms, "NOT_L2_BOOK")
    if event.market != plan.market:
        return _rejected(plan, event, attempt_timestamp_ms, "MARKET_MISMATCH")
    if instrument.market != plan.market:
        return _rejected(plan, event, attempt_timestamp_ms, "INSTRUMENT_MISMATCH")
    if not instrument.execution_supported:
        return _rejected(
            plan,
            event,
            attempt_timestamp_ms,
            instrument.unsupported_reason or "UNSUPPORTED_INSTRUMENT",
        )
    if instrument.metadata_received_at_ms != plan.instrument_metadata_received_at_ms:
        return _rejected(plan, event, attempt_timestamp_ms, "INSTRUMENT_VERSION_MISMATCH")
    if config.config_version != plan.execution_config_version:
        return _rejected(plan, event, attempt_timestamp_ms, "EXECUTION_CONFIG_MISMATCH")
    if attempt_timestamp_ms < plan.earliest_execution_ms:
        return _rejected(plan, event, attempt_timestamp_ms, "LATENCY_NOT_ELAPSED")

    received_ms = _receive_time_ms(event)
    if received_ms > attempt_timestamp_ms:
        return _rejected(plan, event, attempt_timestamp_ms, "FUTURE_BOOK")
    if attempt_timestamp_ms - received_ms > config.max_book_age_ms:
        return _rejected(plan, event, attempt_timestamp_ms, "STALE_BOOK")
    if event.exchange_time_ms is not None and event.exchange_time_ms > attempt_timestamp_ms:
        return _rejected(plan, event, attempt_timestamp_ms, "FUTURE_BOOK")

    bids = _parse_levels(event.payload.get("bids"))
    asks = _parse_levels(event.payload.get("asks"))
    if bids is None or asks is None or not bids or not asks:
        return _rejected(plan, event, attempt_timestamp_ms, "MALFORMED_BOOK")

    sorted_bids = tuple(sorted(bids, key=lambda level: level.price, reverse=True))
    sorted_asks = tuple(sorted(asks, key=lambda level: level.price))
    if sorted_bids[0].price >= sorted_asks[0].price:
        return _rejected(plan, event, attempt_timestamp_ms, "CROSSED_BOOK")

    with localcontext(AUTHORITATIVE_CONTEXT):
        effective_slippage_bps = min(plan.max_slippage_bps, config.max_ioc_slippage_bps)
        slippage_fraction = effective_slippage_bps / BPS
        if plan.side is OrderSide.BUY:
            boundary = plan.execution_reference_price * (ONE + slippage_fraction)
            levels = sorted_asks
        else:
            boundary = plan.execution_reference_price * (ONE - slippage_fraction)
            levels = sorted_bids

        if not plan.reduce_only:
            if (
                plan.stop_price is None
                or plan.approved_risk_amount_ceiling is None
                or plan.cost_buffer_fraction is None
            ):
                return _rejected(plan, event, attempt_timestamp_ms, "INCOMPLETE_RISK_ENVELOPE")
            if plan.side is OrderSide.BUY and plan.stop_price >= sorted_asks[0].price:
                return _rejected(plan, event, attempt_timestamp_ms, "STOP_ALREADY_BREACHED")
            if plan.side is OrderSide.SELL and plan.stop_price <= sorted_bids[0].price:
                return _rejected(plan, event, attempt_timestamp_ms, "STOP_ALREADY_BREACHED")
            remaining_risk: Decimal | None = plan.approved_risk_amount_ceiling
            cost_buffer_fraction = plan.cost_buffer_fraction
        else:
            remaining_risk = None
            cost_buffer_fraction = ZERO

        remaining_quantity = _floor_quantity(plan.requested_quantity, instrument.size_quantum)
        remaining_notional = plan.approved_notional_ceiling
        quantum = instrument.size_quantum
        raw_fills: list[tuple[_Level, Decimal, Decimal, Decimal]] = []
        gross_notional = ZERO
        total_fee = ZERO
        risk_clipped = False
        notional_clipped = False

        for level in levels:
            if remaining_quantity <= ZERO or remaining_notional <= ZERO:
                break
            if plan.side is OrderSide.BUY and level.price > boundary:
                break
            if plan.side is OrderSide.SELL and level.price < boundary:
                break

            max_by_notional = _floor_quantity(remaining_notional / level.price, quantum)
            visible_quantity = _floor_quantity(level.quantity, quantum)
            fill_quantity = min(remaining_quantity, visible_quantity, max_by_notional)
            if max_by_notional < min(remaining_quantity, visible_quantity):
                notional_clipped = True

            if remaining_risk is not None:
                unit_risk = _risk_per_quantity(plan, level.price, cost_buffer_fraction)
                if not unit_risk.is_finite() or unit_risk <= ZERO:
                    return _rejected(plan, event, attempt_timestamp_ms, "INVALID_RISK_GEOMETRY")
                max_by_risk = _floor_quantity(remaining_risk / unit_risk, quantum)
                if max_by_risk < fill_quantity:
                    fill_quantity = max_by_risk
                    risk_clipped = True

            fill_quantity = _floor_quantity(fill_quantity, quantum)
            if fill_quantity <= ZERO:
                break

            fill_notional = level.price * fill_quantity
            fee = fill_notional * config.taker_fee_rate
            raw_fills.append((level, fill_quantity, fill_notional, fee))
            remaining_quantity -= fill_quantity
            remaining_notional -= fill_notional
            gross_notional += fill_notional
            total_fee += fee

            if remaining_risk is not None:
                unit_risk = _risk_per_quantity(plan, level.price, cost_buffer_fraction)
                remaining_risk -= unit_risk * fill_quantity
                if remaining_risk < ZERO:
                    return _rejected(plan, event, attempt_timestamp_ms, "RISK_ENVELOPE_BREACH")

        filled_quantity = plan.requested_quantity - remaining_quantity
        average_fill_price = (
            gross_notional / filled_quantity if filled_quantity > ZERO else None
        )

    reasons: tuple[str, ...]
    if filled_quantity == plan.requested_quantity:
        result = ExecutionResult.FULL
        reasons = ("FILLED_VISIBLE_DEPTH",)
    elif filled_quantity > ZERO:
        result = ExecutionResult.PARTIAL
        partial_reasons = ["IOC_REMAINDER_CANCELLED"]
        if risk_clipped:
            partial_reasons.append("RISK_CEILING_REACHED")
        if notional_clipped:
            partial_reasons.append("NOTIONAL_CEILING_REACHED")
        reasons = tuple(partial_reasons)
    else:
        result = ExecutionResult.NO_FILL
        if risk_clipped:
            reasons = ("RISK_CEILING_REACHED",)
        elif notional_clipped:
            reasons = ("NOTIONAL_CEILING_REACHED",)
        else:
            reasons = ("NO_ELIGIBLE_VISIBLE_DEPTH",)

    attempt = ExecutionAttempt(
        plan_id=plan.plan_id,
        source_event_key=event.event_key,
        requested_quantity=plan.requested_quantity,
        filled_quantity=filled_quantity,
        average_fill_price=average_fill_price,
        gross_fill_notional=gross_notional,
        fee=total_fee,
        unfilled_quantity=remaining_quantity,
        result=result,
        reason_codes=reasons,
        snapshot_exchange_ms=event.exchange_time_ms,
        snapshot_received_ms=received_ms,
        attempt_timestamp_ms=attempt_timestamp_ms,
    )
    fills = tuple(
        PaperFill(
            plan_id=plan.plan_id,
            attempt_id=attempt.attempt_id,
            market=plan.market,
            side=plan.side,
            price=level.price,
            quantity=quantity,
            notional=notional,
            taker_fee=fee,
            source_event_key=f"{event.event_key}:level:{level.index}",
            timestamp_ms=attempt_timestamp_ms,
        )
        for level, quantity, notional, fee in raw_fills
    )
    return IocSimulation(attempt=attempt, fills=fills)
