from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from cocomelon.domain.execution import (
    ExecutionAttempt,
    OrderSide,
    PaperFill,
    PaperOrderPlan,
)
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.execution.funding import FundingAccrual
from cocomelon.research.exact_decimal_aggregation import (
    exact_decimal_sum,
)

ZERO: Final = Decimal("0")


class CrossDayTradeCashError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CrossDayTradeCashContribution:
    trade_id: str
    market: str
    day_start_ms: int
    end_ms: int
    realized_gross_pnl: Decimal
    exit_fees: Decimal
    funding_cash_pnl: Decimal
    net_cash_pnl: Decimal
    entry_fees_excluded: bool
    lifecycle_reconciled: bool


PlanLoader = Callable[[str], PaperOrderPlan | None]
ExecutionHistoryLoader = Callable[
    [str],
    tuple[tuple[ExecutionAttempt, ...], tuple[PaperFill, ...]],
]
FundingLoader = Callable[[MarketId], tuple[FundingAccrual, ...]]


def _realized_pnl(
    trade: TradeJournalEntry,
    fill: PaperFill,
) -> Decimal:
    if fill.market != trade.market:
        raise CrossDayTradeCashError(
            "CROSS_DAY_EXIT_FILL_MARKET_MISMATCH"
        )
    expected_side = (
        OrderSide.SELL
        if trade.direction is Direction.LONG
        else OrderSide.BUY
    )
    if fill.side is not expected_side:
        raise CrossDayTradeCashError(
            "CROSS_DAY_EXIT_FILL_SIDE_MISMATCH"
        )
    if trade.direction is Direction.LONG:
        return (
            fill.price - trade.entry_price
        ) * fill.quantity
    return (
        trade.entry_price - fill.price
    ) * fill.quantity


def cross_day_trade_cash_contribution(
    trade: TradeJournalEntry,
    *,
    day_start_ms: int,
    end_ms: int,
    plan_loader: PlanLoader,
    execution_history_loader: ExecutionHistoryLoader,
    funding_loader: FundingLoader,
) -> CrossDayTradeCashContribution:
    if day_start_ms < 0:
        raise ValueError("day_start_ms must be non-negative")
    if end_ms <= day_start_ms:
        raise ValueError("end_ms must be after day_start_ms")
    if not (
        trade.opened_at_ms < day_start_ms
        <= trade.closed_at_ms
        < end_ms
    ):
        raise CrossDayTradeCashError(
            "CROSS_DAY_TRADE_WINDOW_INVALID"
        )

    exit_fills: list[PaperFill] = []
    for plan_id in trade.exit_plan_ids:
        plan = plan_loader(plan_id)
        if plan is None:
            raise CrossDayTradeCashError(
                "CROSS_DAY_EXIT_PLAN_MISSING"
            )
        if (
            not plan.reduce_only
            or plan.market != trade.market
            or plan.plan_id != plan_id
        ):
            raise CrossDayTradeCashError(
                "CROSS_DAY_EXIT_PLAN_LINEAGE_MISMATCH"
            )
        _attempts, fills = execution_history_loader(plan_id)
        for fill in fills:
            if fill.plan_id != plan_id:
                raise CrossDayTradeCashError(
                    "CROSS_DAY_EXIT_FILL_PLAN_MISMATCH"
                )
            if fill.fill_id not in trade.fill_ids:
                raise CrossDayTradeCashError(
                    "CROSS_DAY_EXIT_FILL_NOT_IN_TRADE"
                )
            exit_fills.append(fill)

    if not exit_fills:
        raise CrossDayTradeCashError(
            "CROSS_DAY_EXIT_FILLS_MISSING"
        )

    lifecycle_gross = exact_decimal_sum(
        _realized_pnl(trade, fill)
        for fill in exit_fills
    )
    lifecycle_exit_fees = exact_decimal_sum(
        fill.taker_fee for fill in exit_fills
    )
    if lifecycle_gross != trade.gross_realized_pnl:
        raise CrossDayTradeCashError(
            "CROSS_DAY_GROSS_RECONCILIATION_MISMATCH"
        )
    if lifecycle_exit_fees != trade.exit_fees:
        raise CrossDayTradeCashError(
            "CROSS_DAY_EXIT_FEE_RECONCILIATION_MISMATCH"
        )

    all_funding = funding_loader(trade.market)
    by_id: dict[str, FundingAccrual] = {}
    for accrual in all_funding:
        if accrual.market != trade.market:
            raise CrossDayTradeCashError(
                "CROSS_DAY_FUNDING_MARKET_MISMATCH"
            )
        if accrual.accrual_id in by_id:
            raise CrossDayTradeCashError(
                "CROSS_DAY_FUNDING_DUPLICATE"
            )
        by_id[accrual.accrual_id] = accrual

    funding_rows: list[FundingAccrual] = []
    for accrual_id in trade.funding_event_ids:
        accrual = by_id.get(accrual_id)
        if accrual is None:
            raise CrossDayTradeCashError(
                "CROSS_DAY_FUNDING_LINEAGE_INCOMPLETE"
            )
        funding_rows.append(accrual)

    lifecycle_funding = exact_decimal_sum(
        accrual.cash_delta for accrual in funding_rows
    )
    if lifecycle_funding != trade.funding_cash_pnl:
        raise CrossDayTradeCashError(
            "CROSS_DAY_FUNDING_RECONCILIATION_MISMATCH"
        )

    day_exit_fills = tuple(
        fill
        for fill in exit_fills
        if day_start_ms <= fill.timestamp_ms < end_ms
    )
    day_funding = tuple(
        accrual
        for accrual in funding_rows
        if day_start_ms <= accrual.boundary_ms < end_ms
    )
    realized = exact_decimal_sum(
        _realized_pnl(trade, fill)
        for fill in day_exit_fills
    )
    exit_fees = exact_decimal_sum(
        fill.taker_fee for fill in day_exit_fills
    )
    funding = exact_decimal_sum(
        accrual.cash_delta for accrual in day_funding
    )
    net_cash = exact_decimal_sum(
        (realized, -exit_fees, funding)
    )

    return CrossDayTradeCashContribution(
        trade_id=trade.trade_id,
        market=trade.market.canonical,
        day_start_ms=day_start_ms,
        end_ms=end_ms,
        realized_gross_pnl=realized,
        exit_fees=exit_fees,
        funding_cash_pnl=funding,
        net_cash_pnl=net_cash,
        entry_fees_excluded=True,
        lifecycle_reconciled=True,
    )
