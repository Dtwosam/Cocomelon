from __future__ import annotations

from cocomelon.domain.risk import RiskRequest


def hard_veto_reason(request: RiskRequest) -> str | None:
    for position in request.open_positions:
        if position.market == request.market:
            return "existing_market_exposure"

    account = request.account_state
    limits = request.limits

    daily_loss_amount = account.day_start_equity * limits.daily_loss_limit
    if account.daily_realized_pnl <= -daily_loss_amount:
        return "daily_loss_lockout"

    weekly_drawdown = (
        account.rolling_7d_peak_equity - account.equity
    ) / account.rolling_7d_peak_equity
    if weekly_drawdown >= limits.weekly_drawdown_limit:
        return "weekly_drawdown_lockout"

    if account.consecutive_losses >= limits.consecutive_loss_cooldown:
        last_closed_ms = account.last_closed_trade_ms
        if last_closed_ms is None or last_closed_ms > request.timestamp_ms:
            return "risk_state_inconsistent"
        elapsed_ms = request.timestamp_ms - last_closed_ms
        if elapsed_ms < limits.cooldown_ms:
            return "consecutive_loss_cooldown"

    return None
