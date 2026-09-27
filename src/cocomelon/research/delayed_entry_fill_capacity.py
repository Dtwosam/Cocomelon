from __future__ import annotations

from decimal import Decimal
from typing import Final

from cocomelon.journal.store import JournalStore
from cocomelon.research.delayed_entry_execution_shadow import (
    DelayedEntryOutcome,
)

ZERO: Final = Decimal("0")
MIN_EVALUATED_ATTEMPTS: Final = 30
MIN_CAUSE_KNOWN_PARTIALS: Final = 10


class DelayedEntryFillCapacityError(RuntimeError):
    pass


def _cause(outcome: DelayedEntryOutcome) -> str:
    if outcome.source == "full_visible_book_ioc":
        return "full_fill"
    if outcome.source == "no_fill":
        return "no_fill"
    if outcome.source != "partial_visible_book_ioc":
        return outcome.source
    reason = outcome.attempt_reason
    if reason is None:
        return "legacy_unknown_partial"
    codes = set(reason.split(","))
    risk = "RISK_CEILING_REACHED" in codes
    notional = "NOTIONAL_CEILING_REACHED" in codes
    if risk and notional:
        return "risk_and_notional_clip"
    if risk:
        return "risk_ceiling_clip"
    if notional:
        return "notional_ceiling_clip"
    return "visible_depth_or_slippage_boundary"


def delayed_entry_fill_capacity_summary(
    journal: JournalStore,
    outcomes: tuple[DelayedEntryOutcome, ...],
) -> dict[str, object]:
    trades = {trade.trade_id: trade for trade in journal.iter_trades()}
    rows: list[tuple[str, str, Decimal, str]] = []
    missing_journal = 0
    lineage_mismatches = 0

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
        ):
            lineage_mismatches += 1
            continue
        fraction = outcome.delayed_filled_quantity / trade.filled_quantity
        if fraction < ZERO or fraction > Decimal("1"):
            raise DelayedEntryFillCapacityError(
                "delayed fill fraction is outside [0, 1]"
            )
        rows.append(
            (
                outcome.direction,
                outcome.source,
                fraction,
                _cause(outcome),
            )
        )

    def summarize(items: list[tuple[str, str, Decimal, str]]) -> dict[str, object]:
        if not items:
            return {
                "attempts": 0,
                "mean_fill_fraction": None,
                "full": 0,
                "partial": 0,
                "no_fill": 0,
            }
        return {
            "attempts": len(items),
            "mean_fill_fraction": str(
                sum((item[2] for item in items), ZERO)
                / Decimal(len(items))
            ),
            "full": sum(1 for item in items if item[1] == "full_visible_book_ioc"),
            "partial": sum(1 for item in items if item[1] == "partial_visible_book_ioc"),
            "no_fill": sum(1 for item in items if item[1] == "no_fill"),
        }

    causes: dict[str, dict[str, object]] = {}
    for name in sorted({item[3] for item in rows}):
        subset = [item for item in rows if item[3] == name]
        causes[name] = summarize(subset)

    partials = [item for item in rows if item[1] == "partial_visible_book_ioc"]
    known_partials = [
        item for item in partials if item[3] != "legacy_unknown_partial"
    ]
    ready = (
        len(rows) >= MIN_EVALUATED_ATTEMPTS
        and len(known_partials) >= MIN_CAUSE_KNOWN_PARTIALS
        and missing_journal == 0
        and lineage_mismatches == 0
    )

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "evaluated_attempts": len(rows),
        "missing_journal_trades": missing_journal,
        "lineage_mismatches": lineage_mismatches,
        "overall": summarize(rows),
        "by_side": {
            side: summarize([item for item in rows if item[0] == side])
            for side in ("long", "short")
        },
        "by_cause": causes,
        "cause_known_partial_fills": len(known_partials),
        "legacy_unknown_partial_fills": len(partials) - len(known_partials),
        "readiness": {
            "ready_for_review": ready,
            "min_evaluated_attempts": MIN_EVALUATED_ATTEMPTS,
            "min_cause_known_partial_fills": MIN_CAUSE_KNOWN_PARTIALS,
            "missing_evaluated_attempts": max(
                0, MIN_EVALUATED_ATTEMPTS - len(rows)
            ),
            "missing_cause_known_partial_fills": max(
                0, MIN_CAUSE_KNOWN_PARTIALS - len(known_partials)
            ),
        },
    }
