from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from cocomelon.domain.risk import RiskRequest
from cocomelon.domain.strategy import Direction

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class MarketRiskCaps:
    gross_capacity: Decimal
    margin_capacity: Decimal
    liquidity_capacity: Decimal
    risk_notional: Decimal
    final_notional: Decimal
    planned_risk: Decimal
    binding_caps: tuple[str, ...]
    rejection_reason: str | None


def _rejected(
    *,
    gross_capacity: Decimal,
    margin_capacity: Decimal,
    liquidity_capacity: Decimal,
    risk_notional: Decimal,
    reason: str,
) -> MarketRiskCaps:
    return MarketRiskCaps(
        gross_capacity=max(ZERO, gross_capacity),
        margin_capacity=max(ZERO, margin_capacity),
        liquidity_capacity=max(ZERO, liquidity_capacity),
        risk_notional=risk_notional,
        final_notional=ZERO,
        planned_risk=ZERO,
        binding_caps=(),
        rejection_reason=reason,
    )


def _liquidation_buffer_ok(request: RiskRequest) -> bool:
    liquidation = request.liquidity_state.liquidation_price
    stop = request.strategy_decision.invalidation_price
    entry = request.entry_reference_price
    if liquidation is None or stop is None:
        return False

    minimum = request.limits.min_liquidation_stop_multiple
    if request.direction is Direction.LONG:
        if liquidation >= stop:
            return False
        stop_distance = entry - stop
        liquidation_distance = entry - liquidation
    elif request.direction is Direction.SHORT:
        if liquidation <= stop:
            return False
        stop_distance = stop - entry
        liquidation_distance = liquidation - entry
    else:
        return False

    if stop_distance <= ZERO or liquidation_distance <= ZERO:
        return False
    return liquidation_distance / stop_distance >= minimum


def calculate_market_caps(
    request: RiskRequest,
    *,
    approved_risk_amount: Decimal,
    effective_loss_fraction: Decimal,
    raw_notional: Decimal,
) -> MarketRiskCaps:
    for value, field in (
        (approved_risk_amount, "approved_risk_amount"),
        (effective_loss_fraction, "effective_loss_fraction"),
        (raw_notional, "raw_notional"),
    ):
        if not value.is_finite() or value <= ZERO:
            raise ValueError(f"{field} must be positive and finite")

    account = request.account_state
    liquidity = request.liquidity_state
    limits = request.limits
    effective_leverage = min(limits.max_gross_leverage, liquidity.venue_max_leverage)

    gross_ceiling = account.equity * effective_leverage
    gross_capacity = gross_ceiling - account.gross_open_notional
    margin_capacity = (
        account.available_margin
        * limits.max_available_margin_fraction
        * effective_leverage
    )
    liquidity_capacity = (
        min(
            liquidity.entry_side_visible_notional_25bps,
            liquidity.exit_side_visible_notional_25bps,
        )
        * limits.max_visible_depth_fraction
    )
    risk_notional = approved_risk_amount / effective_loss_fraction

    if gross_capacity <= ZERO:
        return _rejected(
            gross_capacity=gross_capacity,
            margin_capacity=margin_capacity,
            liquidity_capacity=liquidity_capacity,
            risk_notional=risk_notional,
            reason="gross_leverage_exhausted",
        )
    if margin_capacity <= ZERO:
        return _rejected(
            gross_capacity=gross_capacity,
            margin_capacity=margin_capacity,
            liquidity_capacity=liquidity_capacity,
            risk_notional=risk_notional,
            reason="margin_capacity_exhausted",
        )
    if liquidity_capacity <= ZERO:
        return _rejected(
            gross_capacity=gross_capacity,
            margin_capacity=margin_capacity,
            liquidity_capacity=liquidity_capacity,
            risk_notional=risk_notional,
            reason="liquidity_capacity_exhausted",
        )

    final_notional = min(
        raw_notional,
        risk_notional,
        gross_capacity,
        margin_capacity,
        liquidity_capacity,
    )

    if not _liquidation_buffer_ok(request):
        return _rejected(
            gross_capacity=gross_capacity,
            margin_capacity=margin_capacity,
            liquidity_capacity=liquidity_capacity,
            risk_notional=risk_notional,
            reason="liquidation_buffer_insufficient",
        )

    venue_minimum = liquidity.venue_min_notional
    if venue_minimum is not None and final_notional < venue_minimum:
        return _rejected(
            gross_capacity=gross_capacity,
            margin_capacity=margin_capacity,
            liquidity_capacity=liquidity_capacity,
            risk_notional=risk_notional,
            reason="below_venue_min_notional",
        )

    baseline = min(raw_notional, risk_notional)
    bindings: list[str] = []
    if final_notional < baseline:
        if final_notional == gross_capacity:
            bindings.append("gross_leverage")
        if final_notional == margin_capacity:
            bindings.append("margin_capacity")
        if final_notional == liquidity_capacity:
            bindings.append("liquidity")

    return MarketRiskCaps(
        gross_capacity=gross_capacity,
        margin_capacity=margin_capacity,
        liquidity_capacity=liquidity_capacity,
        risk_notional=risk_notional,
        final_notional=final_notional,
        planned_risk=final_notional * effective_loss_fraction,
        binding_caps=tuple(bindings),
        rejection_reason=None,
    )
