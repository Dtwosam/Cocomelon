from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal, localcontext

from cocomelon.domain.journal import AUTHORITATIVE_CONTEXT, TradeSummary
from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class ExcursionPoint:
    timestamp_ms: int
    mark_price: Decimal

    def __post_init__(self) -> None:
        if self.timestamp_ms < 0:
            raise ValueError("timestamp_ms must be non-negative")
        if not self.mark_price.is_finite() or self.mark_price <= ZERO:
            raise ValueError("mark_price must be positive and finite")


def _signed_price_move(
    direction: Direction,
    *,
    entry_price: Decimal,
    current_price: Decimal,
) -> Decimal:
    if direction is Direction.LONG:
        return current_price - entry_price
    if direction is Direction.SHORT:
        return entry_price - current_price
    raise ValueError("direction must be LONG or SHORT")


def build_trade_summary(
    *,
    trade_id: str,
    decision_id: str,
    risk_decision_id: str,
    opening_plan_id: str,
    replay_run_id: str,
    market: MarketId,
    direction: Direction,
    entry_timestamp_ms: int,
    exit_timestamp_ms: int,
    entry_price: Decimal,
    exit_price: Decimal,
    quantity: Decimal,
    initial_stop_price: Decimal,
    approved_risk_amount: Decimal,
    maximum_actual_notional: Decimal,
    fees: Decimal,
    funding: Decimal,
    entry_slippage: Decimal,
    exit_slippage: Decimal,
    exit_reason: str,
    reason_trace: tuple[str, ...],
    equity_before: Decimal,
    excursion_points: Iterable[ExcursionPoint],
) -> TradeSummary:
    if direction not in {Direction.LONG, Direction.SHORT}:
        raise ValueError("direction must be LONG or SHORT")
    if entry_timestamp_ms < 0:
        raise ValueError("entry_timestamp_ms must be non-negative")
    if exit_timestamp_ms < entry_timestamp_ms:
        raise ValueError("exit_timestamp_ms must be >= entry_timestamp_ms")
    for field, value in (
        ("entry_price", entry_price),
        ("exit_price", exit_price),
        ("quantity", quantity),
        ("initial_stop_price", initial_stop_price),
        ("approved_risk_amount", approved_risk_amount),
        ("maximum_actual_notional", maximum_actual_notional),
    ):
        if not value.is_finite() or value <= ZERO:
            raise ValueError(f"{field} must be positive and finite")
    for field, value in (
        ("fees", fees),
        ("funding", funding),
        ("entry_slippage", entry_slippage),
        ("exit_slippage", exit_slippage),
        ("equity_before", equity_before),
    ):
        if not value.is_finite():
            raise ValueError(f"{field} must be finite")
    if fees < ZERO:
        raise ValueError("fees must be non-negative")
    if entry_slippage < ZERO or exit_slippage < ZERO:
        raise ValueError("slippage must be non-negative")

    with localcontext(AUTHORITATIVE_CONTEXT):
        gross_pnl = _signed_price_move(
            direction,
            entry_price=entry_price,
            current_price=exit_price,
        ) * quantity
        net_pnl = gross_pnl - fees + funding - entry_slippage - exit_slippage
        equity_after = equity_before + net_pnl

        mfe_pnl = ZERO
        mae_pnl = ZERO
        for point in excursion_points:
            if point.timestamp_ms < entry_timestamp_ms or point.timestamp_ms > exit_timestamp_ms:
                continue
            excursion = _signed_price_move(
                direction,
                entry_price=entry_price,
                current_price=point.mark_price,
            ) * quantity
            if excursion > mfe_pnl:
                mfe_pnl = excursion
            if excursion < mae_pnl:
                mae_pnl = excursion

    return TradeSummary(
        trade_id=trade_id,
        decision_id=decision_id,
        risk_decision_id=risk_decision_id,
        opening_plan_id=opening_plan_id,
        replay_run_id=replay_run_id,
        market=market,
        direction=direction,
        entry_timestamp_ms=entry_timestamp_ms,
        exit_timestamp_ms=exit_timestamp_ms,
        entry_price=entry_price,
        exit_price=exit_price,
        quantity=quantity,
        initial_stop_price=initial_stop_price,
        approved_risk_amount=approved_risk_amount,
        maximum_actual_notional=maximum_actual_notional,
        gross_pnl=gross_pnl,
        fees=fees,
        funding=funding,
        entry_slippage=entry_slippage,
        exit_slippage=exit_slippage,
        net_pnl=net_pnl,
        mfe_pnl=mfe_pnl,
        mae_pnl=mae_pnl,
        exit_reason=exit_reason,
        reason_trace=reason_trace,
        equity_before=equity_before,
        equity_after=equity_after,
    )
