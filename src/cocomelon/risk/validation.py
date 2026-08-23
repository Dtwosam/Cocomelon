from __future__ import annotations

from cocomelon.domain.risk import RiskRequest
from cocomelon.domain.strategy import Direction


def _is_stale(*, as_of_ms: int, request_ms: int, max_age_ms: int) -> bool:
    return request_ms - as_of_ms > max_age_ms


def validate_request(request: RiskRequest) -> tuple[str, ...]:
    strategy = request.strategy_decision
    if strategy.direction is Direction.NO_TRADE:
        return ("strategy_no_trade",)

    stop = strategy.invalidation_price
    if stop is None:
        return ("missing_stop",)
    if strategy.direction is Direction.LONG and stop >= request.entry_reference_price:
        return ("invalid_stop_side",)
    if strategy.direction is Direction.SHORT and stop <= request.entry_reference_price:
        return ("invalid_stop_side",)

    request_ms = request.timestamp_ms
    timestamps = (
        strategy.timestamp_ms,
        request.account_state.as_of_ms,
        request.health_state.as_of_ms,
        request.liquidity_state.as_of_ms,
    )
    if any(timestamp > request_ms for timestamp in timestamps):
        return ("risk_state_inconsistent",)

    health = request.health_state
    if not health.market_data_fresh:
        return ("stale_market_data",)
    if not health.account_state_fresh:
        return ("stale_account_state",)
    if not health.execution_health_ok:
        return ("execution_health_degraded",)
    if not health.state_consistent:
        return ("risk_state_inconsistent",)

    max_age_ms = request.limits.max_state_age_ms
    if _is_stale(
        as_of_ms=request.account_state.as_of_ms,
        request_ms=request_ms,
        max_age_ms=max_age_ms,
    ):
        return ("stale_account_state",)
    if _is_stale(
        as_of_ms=health.as_of_ms,
        request_ms=request_ms,
        max_age_ms=max_age_ms,
    ):
        return ("stale_market_data",)
    if _is_stale(
        as_of_ms=request.liquidity_state.as_of_ms,
        request_ms=request_ms,
        max_age_ms=max_age_ms,
    ):
        return ("stale_market_data",)

    return ()
