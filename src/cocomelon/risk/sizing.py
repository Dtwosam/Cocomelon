from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from cocomelon.domain.risk import ExecutionCostEstimate, RiskLimits

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class BaseRiskSizing:
    target_risk_amount: Decimal
    stop_distance_fraction: Decimal
    effective_loss_fraction: Decimal
    raw_notional: Decimal


def _require_positive(value: Decimal, field: str) -> None:
    if not value.is_finite() or value <= ZERO:
        raise ValueError(f"{field} must be positive and finite")


def calculate_base_sizing(
    *,
    entry_price: Decimal,
    stop_price: Decimal,
    equity: Decimal,
    costs: ExecutionCostEstimate,
    limits: RiskLimits,
) -> BaseRiskSizing:
    _require_positive(entry_price, "entry_price")
    _require_positive(stop_price, "stop_price")
    _require_positive(equity, "equity")

    target_risk_amount = equity * limits.risk_per_trade
    stop_distance_fraction = abs(entry_price - stop_price) / entry_price
    effective_loss_fraction = (
        stop_distance_fraction
        + costs.entry_slippage_fraction
        + costs.stop_slippage_fraction
        + costs.round_trip_fee_fraction
    )
    if not effective_loss_fraction.is_finite() or effective_loss_fraction <= ZERO:
        raise ValueError("effective_loss_fraction must be positive and finite")

    raw_notional = target_risk_amount / effective_loss_fraction
    return BaseRiskSizing(
        target_risk_amount=target_risk_amount,
        stop_distance_fraction=stop_distance_fraction,
        effective_loss_fraction=effective_loss_fraction,
        raw_notional=raw_notional,
    )
