from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Final

from cocomelon.domain.execution import OrderSide, PaperOrderPlan
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.strategy import Direction
from cocomelon.journal.store import JournalStore
from cocomelon.research.delayed_entry_execution_shadow import (
    DelayedEntryOutcome,
)

ZERO: Final = Decimal("0")
ONE: Final = Decimal("1")
MIN_EVALUATED_FILLED_ATTEMPTS: Final = 20
MIN_RISK_CLIPPED_ATTEMPTS: Final = 5


class DelayedEntryRiskGeometryError(RuntimeError):
    pass


def _risk_per_quantity(
    plan: PaperOrderPlan,
    price: Decimal,
) -> Decimal:
    if plan.stop_price is None:
        raise DelayedEntryRiskGeometryError(
            "opening plan is missing stop price"
        )
    cost_buffer = plan.cost_buffer_fraction
    if cost_buffer is None:
        raise DelayedEntryRiskGeometryError(
            "opening plan is missing cost buffer"
        )
    if plan.side is OrderSide.BUY:
        value = price * (ONE + cost_buffer) - plan.stop_price
    else:
        value = plan.stop_price - price * (ONE - cost_buffer)
    if not value.is_finite() or value <= ZERO:
        raise DelayedEntryRiskGeometryError(
            "opening plan has invalid per-unit risk"
        )
    return value


def _is_risk_clipped(outcome: DelayedEntryOutcome) -> bool:
    reason = outcome.attempt_reason
    if reason is None:
        return False
    return "RISK_CEILING_REACHED" in set(reason.split(","))


def _cause(outcome: DelayedEntryOutcome) -> str:
    if outcome.source == "full_visible_book_ioc":
        return "full_fill"
    if outcome.source == "no_fill":
        return "no_fill"
    if outcome.source != "partial_visible_book_ioc":
        return outcome.source
    if _is_risk_clipped(outcome):
        return "risk_ceiling_clip"
    if outcome.capacity_cause is not None:
        return outcome.capacity_cause
    return "partial_other"


def _decimal(value: Decimal) -> str:
    if not value.is_finite():
        raise DelayedEntryRiskGeometryError(
            "risk geometry metric must be finite"
        )
    return str(value)


def _summarize(
    rows: list[dict[str, object]],
) -> dict[str, object]:
    if not rows:
        return {
            "attempts": 0,
            "mean_fill_fraction": None,
            "mean_risk_utilization": None,
            "mean_full_size_risk_ratio": None,
            "mean_risk_capacity_fraction": None,
            "mean_unit_risk_change_fraction": None,
            "risk_clipped": 0,
            "full_size_risk_above_ceiling": 0,
        }

    def mean(field: str) -> str:
        values: list[Decimal] = []
        for row in rows:
            value = row.get(field)
            if not isinstance(value, Decimal):
                raise DelayedEntryRiskGeometryError(
                    f"missing risk geometry field: {field}"
                )
            values.append(value)
        return _decimal(
            sum(values, ZERO) / Decimal(len(values))
        )

    return {
        "attempts": len(rows),
        "mean_fill_fraction": mean("fill_fraction"),
        "mean_risk_utilization": mean("risk_utilization"),
        "mean_full_size_risk_ratio": mean(
            "full_size_risk_ratio"
        ),
        "mean_risk_capacity_fraction": mean(
            "risk_capacity_fraction"
        ),
        "mean_unit_risk_change_fraction": mean(
            "unit_risk_change_fraction"
        ),
        "risk_clipped": sum(
            1 for row in rows if row["risk_clipped"] is True
        ),
        "full_size_risk_above_ceiling": sum(
            1
            for row in rows
            if (
                isinstance(
                    row["full_size_risk_ratio"],
                    Decimal,
                )
                and row["full_size_risk_ratio"] > ONE
            )
        ),
    }


def _trade_by_id(
    journal: JournalStore,
) -> dict[str, TradeJournalEntry]:
    trades = tuple(journal.iter_trades())
    by_id = {trade.trade_id: trade for trade in trades}
    if len(by_id) != len(trades):
        raise DelayedEntryRiskGeometryError(
            "duplicate journal trade ids"
        )
    return by_id


def delayed_entry_risk_geometry_summary(
    journal: JournalStore,
    outcomes: tuple[DelayedEntryOutcome, ...],
    plan_loader: Callable[[str], PaperOrderPlan | None],
) -> dict[str, object]:
    trades = _trade_by_id(journal)
    rows: list[dict[str, object]] = []
    missing_journal = 0
    missing_plan = 0
    lineage_mismatches = 0
    missing_fill_price = 0
    no_fill_outcomes = 0

    for outcome in outcomes:
        if outcome.source not in {
            "full_visible_book_ioc",
            "partial_visible_book_ioc",
            "no_fill",
        }:
            continue
        trade = trades.get(outcome.trade_id)
        if trade is None:
            missing_journal += 1
            continue
        if (
            trade.opening_plan_id != outcome.opening_plan_id
            or trade.market.canonical != outcome.market
            or trade.direction.value != outcome.direction
            or trade.filled_quantity <= ZERO
            or trade.initial_risk_amount <= ZERO
        ):
            lineage_mismatches += 1
            continue
        plan = plan_loader(outcome.opening_plan_id)
        if plan is None:
            missing_plan += 1
            continue
        expected_side = (
            OrderSide.BUY
            if trade.direction is Direction.LONG
            else OrderSide.SELL
        )
        if (
            plan.reduce_only
            or plan.market != trade.market
            or plan.side is not expected_side
            or plan.stop_price is None
            or plan.cost_buffer_fraction is None
        ):
            lineage_mismatches += 1
            continue

        if outcome.source == "no_fill":
            no_fill_outcomes += 1
            continue
        if (
            outcome.delayed_average_fill_price is None
            or outcome.delayed_filled_quantity <= ZERO
        ):
            missing_fill_price += 1
            continue

        actual_unit_risk = _risk_per_quantity(
            plan,
            trade.entry_price,
        )
        delayed_unit_risk = _risk_per_quantity(
            plan,
            outcome.delayed_average_fill_price,
        )
        risk_ceiling = trade.initial_risk_amount
        risk_used = (
            delayed_unit_risk
            * outcome.delayed_filled_quantity
        )
        requested_full_risk = (
            delayed_unit_risk * trade.filled_quantity
        )
        actual_full_risk = (
            actual_unit_risk * trade.filled_quantity
        )
        fill_fraction = (
            outcome.delayed_filled_quantity
            / trade.filled_quantity
        )
        risk_utilization = risk_used / risk_ceiling
        full_size_risk_ratio = (
            requested_full_risk / risk_ceiling
        )
        risk_capacity_fraction = min(
            ONE,
            risk_ceiling / requested_full_risk,
        )
        unit_risk_change_fraction = (
            delayed_unit_risk / actual_unit_risk - ONE
        )
        actual_full_size_risk_ratio = (
            actual_full_risk / risk_ceiling
        )

        for value, field in (
            (fill_fraction, "fill_fraction"),
            (risk_utilization, "risk_utilization"),
            (full_size_risk_ratio, "full_size_risk_ratio"),
            (risk_capacity_fraction, "risk_capacity_fraction"),
            (
                unit_risk_change_fraction,
                "unit_risk_change_fraction",
            ),
            (
                actual_full_size_risk_ratio,
                "actual_full_size_risk_ratio",
            ),
        ):
            if not value.is_finite():
                raise DelayedEntryRiskGeometryError(
                    f"{field} must be finite"
                )
        if fill_fraction < ZERO or fill_fraction > ONE:
            raise DelayedEntryRiskGeometryError(
                "delayed fill fraction is outside [0, 1]"
            )

        rows.append(
            {
                "direction": outcome.direction,
                "source": outcome.source,
                "cause": _cause(outcome),
                "risk_clipped": _is_risk_clipped(outcome),
                "fill_fraction": fill_fraction,
                "risk_utilization": risk_utilization,
                "full_size_risk_ratio": full_size_risk_ratio,
                "risk_capacity_fraction": risk_capacity_fraction,
                "unit_risk_change_fraction": (
                    unit_risk_change_fraction
                ),
                "actual_full_size_risk_ratio": (
                    actual_full_size_risk_ratio
                ),
            }
        )

    risk_clipped_rows = [
        row for row in rows if row["risk_clipped"] is True
    ]
    ready = (
        len(rows) >= MIN_EVALUATED_FILLED_ATTEMPTS
        and len(risk_clipped_rows)
        >= MIN_RISK_CLIPPED_ATTEMPTS
        and missing_journal == 0
        and missing_plan == 0
        and lineage_mismatches == 0
        and missing_fill_price == 0
    )

    causes = {
        cause: _summarize(
            [row for row in rows if row["cause"] == cause]
        )
        for cause in sorted(
            {str(row["cause"]) for row in rows}
        )
    }

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "definition": (
            "delayed_average_fill_risk_vs_actual_position_risk"
        ),
        "evaluated_filled_attempts": len(rows),
        "no_fill_outcomes": no_fill_outcomes,
        "missing_journal_trades": missing_journal,
        "missing_opening_plans": missing_plan,
        "lineage_mismatches": lineage_mismatches,
        "missing_delayed_fill_price": missing_fill_price,
        "overall": _summarize(rows),
        "risk_clipped": _summarize(risk_clipped_rows),
        "by_side": {
            side: _summarize(
                [
                    row
                    for row in rows
                    if row["direction"] == side
                ]
            )
            for side in ("long", "short")
        },
        "by_cause": causes,
        "readiness": {
            "ready_for_review": ready,
            "min_evaluated_filled_attempts": (
                MIN_EVALUATED_FILLED_ATTEMPTS
            ),
            "min_risk_clipped_attempts": (
                MIN_RISK_CLIPPED_ATTEMPTS
            ),
            "missing_evaluated_filled_attempts": max(
                0,
                MIN_EVALUATED_FILLED_ATTEMPTS - len(rows),
            ),
            "missing_risk_clipped_attempts": max(
                0,
                MIN_RISK_CLIPPED_ATTEMPTS
                - len(risk_clipped_rows),
            ),
        },
    }
