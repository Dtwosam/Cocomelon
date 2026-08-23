from __future__ import annotations

from decimal import Decimal

from cocomelon.domain.risk import RiskDecision, RiskRequest
from cocomelon.risk.capacity import calculate_risk_capacity
from cocomelon.risk.market_caps import calculate_market_caps
from cocomelon.risk.sizing import BaseRiskSizing, calculate_base_sizing
from cocomelon.risk.validation import validate_request
from cocomelon.risk.vetoes import hard_veto_reason

ZERO = Decimal("0")


def _reject(
    request: RiskRequest,
    reason: str,
    *,
    sizing: BaseRiskSizing | None = None,
) -> RiskDecision:
    return RiskDecision(
        strategy_decision_id=request.strategy_decision_id,
        market=request.market,
        direction=request.direction,
        approved=False,
        reason_codes=(reason,),
        target_risk_amount=(ZERO if sizing is None else sizing.target_risk_amount),
        approved_risk_amount=ZERO,
        approved_notional=ZERO,
        entry_reference_price=request.entry_reference_price,
        stop_price=request.strategy_decision.invalidation_price,
        stop_distance_fraction=(None if sizing is None else sizing.stop_distance_fraction),
        effective_loss_fraction=(None if sizing is None else sizing.effective_loss_fraction),
        correlation_bucket=request.correlation_bucket,
        binding_caps=(),
        timestamp_ms=request.timestamp_ms,
    )


def evaluate_risk(request: RiskRequest) -> RiskDecision:
    validation_reasons = validate_request(request)
    if validation_reasons:
        return _reject(request, validation_reasons[0])

    veto = hard_veto_reason(request)
    if veto is not None:
        return _reject(request, veto)

    stop = request.strategy_decision.invalidation_price
    if stop is None:
        return _reject(request, "missing_stop")

    sizing = calculate_base_sizing(
        entry_price=request.entry_reference_price,
        stop_price=stop,
        equity=request.account_state.equity,
        costs=request.cost_estimate,
        limits=request.limits,
    )

    capacity = calculate_risk_capacity(
        request,
        target_risk_amount=sizing.target_risk_amount,
    )
    if capacity.rejection_reason is not None:
        return _reject(request, capacity.rejection_reason, sizing=sizing)

    market_caps = calculate_market_caps(
        request,
        approved_risk_amount=capacity.approved_risk_amount,
        effective_loss_fraction=sizing.effective_loss_fraction,
        raw_notional=sizing.raw_notional,
    )
    if market_caps.rejection_reason is not None:
        return _reject(request, market_caps.rejection_reason, sizing=sizing)

    binding_caps = tuple(sorted(set((*capacity.binding_caps, *market_caps.binding_caps))))
    return RiskDecision(
        strategy_decision_id=request.strategy_decision_id,
        market=request.market,
        direction=request.direction,
        approved=True,
        reason_codes=("risk_approved",),
        target_risk_amount=sizing.target_risk_amount,
        approved_risk_amount=market_caps.planned_risk,
        approved_notional=market_caps.final_notional,
        entry_reference_price=request.entry_reference_price,
        stop_price=stop,
        stop_distance_fraction=sizing.stop_distance_fraction,
        effective_loss_fraction=sizing.effective_loss_fraction,
        correlation_bucket=request.correlation_bucket,
        binding_caps=binding_caps,
        timestamp_ms=request.timestamp_ms,
    )
