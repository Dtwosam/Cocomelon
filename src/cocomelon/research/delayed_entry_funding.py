from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.execution.funding import (
    FundingAccrual,
    funding_cash_delta,
)

ZERO: Final = Decimal("0")
ONE: Final = Decimal("1")

FundingLoader = Callable[
    [MarketId, int],
    tuple[FundingAccrual, ...],
]


class DelayedEntryFundingError(RuntimeError):
    pass


class DelayedEntryFundingMissingError(
    DelayedEntryFundingError
):
    pass


def trade_funding_accruals(
    trade: TradeJournalEntry,
    funding_loader: FundingLoader,
) -> tuple[FundingAccrual, ...]:
    accruals = funding_loader(
        trade.market,
        trade.opened_at_ms,
    )
    relevant = tuple(
        accrual
        for accrual in accruals
        if accrual.boundary_ms <= trade.closed_at_ms
    )
    by_id = {
        accrual.accrual_id: accrual
        for accrual in relevant
    }
    if len(by_id) != len(relevant):
        raise DelayedEntryFundingError(
            "duplicate funding accrual ids"
        )

    selected: list[FundingAccrual] = []
    for accrual_id in trade.funding_event_ids:
        accrual = by_id.get(accrual_id)
        if accrual is None:
            raise DelayedEntryFundingMissingError(
                "journal funding event is missing from execution store"
            )
        if (
            accrual.market != trade.market
            or not (
                trade.opened_at_ms
                < accrual.boundary_ms
                <= trade.closed_at_ms
            )
        ):
            raise DelayedEntryFundingError(
                "funding accrual is outside journal lifecycle"
            )
        expected_sign = (
            ONE
            if trade.direction.value == "long"
            else -ONE
        )
        if accrual.signed_quantity * expected_sign <= ZERO:
            raise DelayedEntryFundingError(
                "funding accrual direction mismatches journal"
            )
        if funding_cash_delta(
            accrual.signed_quantity,
            accrual.oracle_price,
            accrual.funding_rate,
        ) != accrual.cash_delta:
            raise DelayedEntryFundingError(
                "funding accrual cash delta is inconsistent"
            )
        selected.append(accrual)

    selected.sort(
        key=lambda item: (
            item.boundary_ms,
            item.accrual_id,
        )
    )
    if sum(
        (item.cash_delta for item in selected),
        ZERO,
    ) != trade.funding_cash_pnl:
        raise DelayedEntryFundingError(
            "journal funding pnl does not match execution accruals"
        )
    return tuple(selected)


def scaled_funding_events(
    accruals: tuple[FundingAccrual, ...],
    *,
    fill_fraction: Decimal,
    open_ms: int,
) -> tuple[tuple[int, Decimal], ...]:
    if (
        not fill_fraction.is_finite()
        or not ZERO <= fill_fraction <= ONE
    ):
        raise ValueError(
            "fill_fraction must be finite and between zero and one"
        )
    if open_ms < 0:
        raise ValueError("open_ms must be non-negative")
    if fill_fraction == ZERO:
        return ()

    return tuple(
        (
            accrual.boundary_ms,
            funding_cash_delta(
                accrual.signed_quantity * fill_fraction,
                accrual.oracle_price,
                accrual.funding_rate,
            ),
        )
        for accrual in accruals
        if accrual.boundary_ms > open_ms
    )
