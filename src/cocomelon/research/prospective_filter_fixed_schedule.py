from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.research.exact_decimal_aggregation import (
    exact_decimal_sum,
)

ZERO: Final = Decimal("0")
HOUR_MS: Final = Decimal("3600000")


class ProspectiveFilterFixedScheduleError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProspectiveFilterPortfolioItem:
    trade: TradeJournalEntry
    admitted: bool


@dataclass(frozen=True, slots=True)
class _Event:
    timestamp_ms: int
    order: int
    count_delta: int
    notional_delta: Decimal
    risk_delta: Decimal
    realized_pnl_delta: Decimal

    def __post_init__(self) -> None:
        if self.timestamp_ms < 0:
            raise ValueError("event timestamp must be non-negative")
        for value in (
            self.notional_delta,
            self.risk_delta,
            self.realized_pnl_delta,
        ):
            if not value.is_finite():
                raise ValueError(
                    "fixed-schedule event economics must be finite"
                )


def _event_pair(
    trade: TradeJournalEntry,
) -> tuple[_Event, _Event]:
    notional = trade.entry_price * trade.filled_quantity
    risk = trade.initial_risk_amount
    return (
        _Event(
            timestamp_ms=trade.opened_at_ms,
            order=1,
            count_delta=1,
            notional_delta=notional,
            risk_delta=risk,
            realized_pnl_delta=ZERO,
        ),
        _Event(
            timestamp_ms=trade.closed_at_ms,
            order=0,
            count_delta=-1,
            notional_delta=-notional,
            risk_delta=-risk,
            realized_pnl_delta=trade.net_pnl,
        ),
    )


def _timeline(
    items: tuple[ProspectiveFilterPortfolioItem, ...],
    *,
    candidate: bool,
) -> dict[str, object]:
    events: list[_Event] = []
    for item in items:
        if candidate and not item.admitted:
            continue
        events.extend(_event_pair(item.trade))

    if not events:
        return {
            "final_realized_contribution": "0",
            "max_realized_drawdown": "0",
            "max_concurrent_positions": 0,
            "overlap_openings": 0,
            "max_gross_notional": "0",
            "max_planned_risk": "0",
            "position_exposure_hours": "0",
            "notional_exposure_hours": "0",
            "risk_exposure_hours": "0",
        }

    count = 0
    notional = ZERO
    risk = ZERO
    realized = ZERO
    peak = ZERO
    max_drawdown = ZERO
    max_count = 0
    max_notional = ZERO
    max_risk = ZERO
    overlap_openings = 0
    position_ms = ZERO
    notional_ms = ZERO
    risk_ms = ZERO
    previous_ms = min(event.timestamp_ms for event in events)

    for event in sorted(
        events,
        key=lambda item: (item.timestamp_ms, item.order),
    ):
        elapsed = event.timestamp_ms - previous_ms
        if elapsed < 0:
            raise ProspectiveFilterFixedScheduleError(
                "fixed-schedule timeline moved backward"
            )
        elapsed_decimal = Decimal(elapsed)
        position_ms = exact_decimal_sum(
            (
                position_ms,
                Decimal(count) * elapsed_decimal,
            )
        )
        notional_ms = exact_decimal_sum(
            (
                notional_ms,
                notional * elapsed_decimal,
            )
        )
        risk_ms = exact_decimal_sum(
            (
                risk_ms,
                risk * elapsed_decimal,
            )
        )
        previous_ms = event.timestamp_ms

        if event.count_delta > 0 and count > 0:
            overlap_openings += 1
        count += event.count_delta
        notional = exact_decimal_sum(
            (notional, event.notional_delta)
        )
        risk = exact_decimal_sum(
            (risk, event.risk_delta)
        )
        realized = exact_decimal_sum(
            (realized, event.realized_pnl_delta)
        )

        if count < 0 or notional < ZERO or risk < ZERO:
            raise ProspectiveFilterFixedScheduleError(
                "fixed-schedule exposure became negative"
            )
        max_count = max(max_count, count)
        max_notional = max(max_notional, notional)
        max_risk = max(max_risk, risk)
        peak = max(peak, realized)
        max_drawdown = max(max_drawdown, peak - realized)

    if count != 0 or notional != ZERO or risk != ZERO:
        raise ProspectiveFilterFixedScheduleError(
            "fixed-schedule portfolio did not finish flat"
        )

    return {
        "final_realized_contribution": str(realized),
        "max_realized_drawdown": str(max_drawdown),
        "max_concurrent_positions": max_count,
        "overlap_openings": overlap_openings,
        "max_gross_notional": str(max_notional),
        "max_planned_risk": str(max_risk),
        "position_exposure_hours": str(
            position_ms / HOUR_MS
        ),
        "notional_exposure_hours": str(
            notional_ms / HOUR_MS
        ),
        "risk_exposure_hours": str(
            risk_ms / HOUR_MS
        ),
    }


def prospective_filter_fixed_schedule_portfolio(
    items: tuple[ProspectiveFilterPortfolioItem, ...],
) -> dict[str, object]:
    trade_ids = tuple(item.trade.trade_id for item in items)
    if len(set(trade_ids)) != len(trade_ids):
        raise ProspectiveFilterFixedScheduleError(
            "fixed-schedule filter portfolio contains duplicate trade ids"
        )

    ordered = tuple(
        sorted(
            items,
            key=lambda item: (
                item.trade.opened_at_ms,
                item.trade.closed_at_ms,
                item.trade.trade_id,
            ),
        )
    )
    actual = _timeline(ordered, candidate=False)
    candidate = _timeline(ordered, candidate=True)

    actual_final = Decimal(
        str(actual["final_realized_contribution"])
    )
    candidate_final = Decimal(
        str(candidate["final_realized_contribution"])
    )
    actual_drawdown = Decimal(
        str(actual["max_realized_drawdown"])
    )
    candidate_drawdown = Decimal(
        str(candidate["max_realized_drawdown"])
    )
    actual_notional = Decimal(
        str(actual["max_gross_notional"])
    )
    candidate_notional = Decimal(
        str(candidate["max_gross_notional"])
    )
    actual_risk = Decimal(
        str(actual["max_planned_risk"])
    )
    candidate_risk = Decimal(
        str(candidate["max_planned_risk"])
    )

    reference_equity = (
        None
        if not ordered
        else ordered[0].trade.equity_before
    )
    blocked = tuple(
        item.trade for item in ordered if not item.admitted
    )

    return {
        "descriptive_only": True,
        "changes_readiness_gate": False,
        "claim_scope": (
            "fixed_observed_schedule_filter_portfolio_timeline"
        ),
        "actual_sizes_reused": True,
        "actual_close_timing_reused": True,
        "replacement_trades_modeled": False,
        "candidate_equity_resizing_modeled": False,
        "unrealized_equity_modeled": False,
        "attributed_trades": len(ordered),
        "admitted_trades": sum(
            1 for item in ordered if item.admitted
        ),
        "blocked_trades": len(blocked),
        "blocked_actual_net_pnl": str(
            exact_decimal_sum(
                trade.net_pnl for trade in blocked
            )
        ),
        "cohort_reference_equity": (
            None
            if reference_equity is None
            else str(reference_equity)
        ),
        "actual": actual,
        "candidate": candidate,
        "delta_final_realized_contribution": str(
            exact_decimal_sum(
                (candidate_final, -actual_final)
            )
        ),
        "delta_max_realized_drawdown": str(
            exact_decimal_sum(
                (candidate_drawdown, -actual_drawdown)
            )
        ),
        "delta_max_gross_notional": str(
            exact_decimal_sum(
                (candidate_notional, -actual_notional)
            )
        ),
        "delta_max_planned_risk": str(
            exact_decimal_sum(
                (candidate_risk, -actual_risk)
            )
        ),
    }
