from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from cocomelon.domain.risk import RiskRequest

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class RiskCapacity:
    remaining_aggregate_risk: Decimal
    remaining_bucket_risk: Decimal
    approved_risk_amount: Decimal
    binding_caps: tuple[str, ...]
    rejection_reason: str | None


def calculate_risk_capacity(
    request: RiskRequest,
    *,
    target_risk_amount: Decimal,
) -> RiskCapacity:
    if not target_risk_amount.is_finite() or target_risk_amount <= ZERO:
        raise ValueError("target_risk_amount must be positive and finite")

    equity = request.account_state.equity
    max_total_risk = equity * request.limits.max_open_risk
    bucket_limit = equity * request.limits.correlation_bucket_risk_limit

    existing_open_risk = sum(
        (position.planned_risk for position in request.open_positions),
        start=ZERO,
    )
    existing_bucket_risk = sum(
        (
            position.planned_risk
            for position in request.open_positions
            if position.correlation_bucket == request.correlation_bucket
        ),
        start=ZERO,
    )

    remaining_aggregate = max_total_risk - existing_open_risk
    remaining_bucket = bucket_limit - existing_bucket_risk

    if remaining_aggregate <= ZERO:
        return RiskCapacity(
            remaining_aggregate_risk=max(ZERO, remaining_aggregate),
            remaining_bucket_risk=max(ZERO, remaining_bucket),
            approved_risk_amount=ZERO,
            binding_caps=(),
            rejection_reason="aggregate_risk_exhausted",
        )
    if remaining_bucket <= ZERO:
        return RiskCapacity(
            remaining_aggregate_risk=remaining_aggregate,
            remaining_bucket_risk=ZERO,
            approved_risk_amount=ZERO,
            binding_caps=(),
            rejection_reason="correlation_bucket_exhausted",
        )

    approved = min(target_risk_amount, remaining_aggregate, remaining_bucket)
    bindings: list[str] = []
    if approved < target_risk_amount:
        if approved == remaining_aggregate:
            bindings.append("aggregate_risk")
        if approved == remaining_bucket:
            bindings.append("correlation_bucket")

    return RiskCapacity(
        remaining_aggregate_risk=remaining_aggregate,
        remaining_bucket_risk=remaining_bucket,
        approved_risk_amount=approved,
        binding_caps=tuple(bindings),
        rejection_reason=None,
    )
