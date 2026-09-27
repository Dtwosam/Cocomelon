from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.journal.store import JournalStore
from cocomelon.research.delayed_entry_execution_shadow import (
    MIN_CLOSED_ELIGIBLE_TRADES,
    MIN_FULL_DELAYED_FILLS,
    DelayedEntryOutcome,
)

ZERO: Final = Decimal("0")


class DelayedEntrySameExitError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DelayedEntrySameExitOutcome:
    trade_id: str
    opening_plan_id: str
    market: str
    direction: str
    actual_net_pnl: Decimal
    actual_net_r: Decimal
    delayed_entry_price: Decimal
    delayed_entry_fee: Decimal
    gross_entry_improvement: Decimal
    entry_fee_improvement: Decimal
    candidate_net_pnl_estimate: Decimal
    candidate_net_r_estimate: Decimal
    delta_net_pnl_estimate: Decimal
    delta_net_r_estimate: Decimal

    def __post_init__(self) -> None:
        for value in (
            self.trade_id,
            self.opening_plan_id,
            self.market,
            self.direction,
        ):
            if not value.strip():
                raise ValueError("same-exit outcome identity must not be empty")
        if self.direction not in {"long", "short"}:
            raise ValueError("direction must be long or short")
        if (
            not self.delayed_entry_price.is_finite()
            or self.delayed_entry_price <= ZERO
        ):
            raise ValueError("delayed_entry_price must be positive")
        for value in (
            self.actual_net_pnl,
            self.actual_net_r,
            self.delayed_entry_fee,
            self.gross_entry_improvement,
            self.entry_fee_improvement,
            self.candidate_net_pnl_estimate,
            self.candidate_net_r_estimate,
            self.delta_net_pnl_estimate,
            self.delta_net_r_estimate,
        ):
            if not value.is_finite():
                raise ValueError("same-exit economics must be finite")
        if self.delayed_entry_fee < ZERO:
            raise ValueError("delayed_entry_fee must be non-negative")


def _trade_map(
    journal: JournalStore,
) -> dict[str, TradeJournalEntry]:
    trades = tuple(journal.iter_trades())
    by_id = {trade.trade_id: trade for trade in trades}
    if len(by_id) != len(trades):
        raise DelayedEntrySameExitError("journal contains duplicate trade ids")
    return by_id


def _evaluate_one(
    trade: TradeJournalEntry,
    outcome: DelayedEntryOutcome,
) -> DelayedEntrySameExitOutcome:
    if outcome.source != "full_visible_book_ioc":
        raise DelayedEntrySameExitError(
            "same-exit evaluation requires a full delayed fill"
        )
    if outcome.delayed_average_fill_price is None:
        raise DelayedEntrySameExitError(
            "full delayed fill is missing average fill price"
        )
    if (
        outcome.opening_plan_id != trade.opening_plan_id
        or outcome.market != trade.market.canonical
        or outcome.direction != trade.direction.value
        or outcome.delayed_filled_quantity != trade.filled_quantity
    ):
        raise DelayedEntrySameExitError(
            "delayed-entry outcome lineage does not match journal"
        )

    signed_price_improvement = (
        trade.entry_price - outcome.delayed_average_fill_price
        if trade.direction.value == "long"
        else outcome.delayed_average_fill_price - trade.entry_price
    )
    gross_entry_improvement = (
        signed_price_improvement * trade.filled_quantity
    )
    entry_fee_improvement = trade.entry_fees - outcome.delayed_fee

    candidate_net_pnl = (
        trade.net_pnl
        + gross_entry_improvement
        + entry_fee_improvement
    )
    candidate_net_r = (
        candidate_net_pnl / trade.initial_risk_amount
    )
    delta_net_pnl = candidate_net_pnl - trade.net_pnl
    delta_net_r = candidate_net_r - trade.net_r

    return DelayedEntrySameExitOutcome(
        trade_id=trade.trade_id,
        opening_plan_id=trade.opening_plan_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        actual_net_pnl=trade.net_pnl,
        actual_net_r=trade.net_r,
        delayed_entry_price=outcome.delayed_average_fill_price,
        delayed_entry_fee=outcome.delayed_fee,
        gross_entry_improvement=gross_entry_improvement,
        entry_fee_improvement=entry_fee_improvement,
        candidate_net_pnl_estimate=candidate_net_pnl,
        candidate_net_r_estimate=candidate_net_r,
        delta_net_pnl_estimate=delta_net_pnl,
        delta_net_r_estimate=delta_net_r,
    )


def _summary(
    items: tuple[DelayedEntrySameExitOutcome, ...],
) -> dict[str, object]:
    count = len(items)
    actual_pnl = sum(
        (item.actual_net_pnl for item in items),
        ZERO,
    )
    candidate_pnl = sum(
        (item.candidate_net_pnl_estimate for item in items),
        ZERO,
    )
    delta_pnl = candidate_pnl - actual_pnl
    actual_r = sum(
        (item.actual_net_r for item in items),
        ZERO,
    )
    candidate_r = sum(
        (item.candidate_net_r_estimate for item in items),
        ZERO,
    )
    delta_r = candidate_r - actual_r
    return {
        "trades": count,
        "actual_wins": sum(
            1 for item in items if item.actual_net_pnl > ZERO
        ),
        "actual_losses": sum(
            1 for item in items if item.actual_net_pnl < ZERO
        ),
        "candidate_wins_estimate": sum(
            1
            for item in items
            if item.candidate_net_pnl_estimate > ZERO
        ),
        "candidate_losses_estimate": sum(
            1
            for item in items
            if item.candidate_net_pnl_estimate < ZERO
        ),
        "loss_to_win_flips_estimate": sum(
            1
            for item in items
            if item.actual_net_pnl < ZERO
            and item.candidate_net_pnl_estimate > ZERO
        ),
        "win_to_loss_flips_estimate": sum(
            1
            for item in items
            if item.actual_net_pnl > ZERO
            and item.candidate_net_pnl_estimate < ZERO
        ),
        "actual_net_pnl": str(actual_pnl),
        "candidate_net_pnl_estimate": str(candidate_pnl),
        "delta_net_pnl_estimate": str(delta_pnl),
        "actual_mean_net_r": (
            None
            if count == 0
            else str(actual_r / Decimal(count))
        ),
        "candidate_mean_net_r_estimate": (
            None
            if count == 0
            else str(candidate_r / Decimal(count))
        ),
        "mean_delta_net_r_estimate": (
            None
            if count == 0
            else str(delta_r / Decimal(count))
        ),
        "mean_gross_entry_improvement": (
            None
            if count == 0
            else str(
                sum(
                    (
                        item.gross_entry_improvement
                        for item in items
                    ),
                    ZERO,
                )
                / Decimal(count)
            )
        ),
        "mean_entry_fee_improvement": (
            None
            if count == 0
            else str(
                sum(
                    (
                        item.entry_fee_improvement
                        for item in items
                    ),
                    ZERO,
                )
                / Decimal(count)
            )
        ),
    }


def delayed_entry_same_exit_contribution(
    journal: JournalStore,
    outcomes: tuple[DelayedEntryOutcome, ...],
) -> dict[str, object]:
    trades = _trade_map(journal)
    full_outcomes = tuple(
        outcome
        for outcome in outcomes
        if outcome.source == "full_visible_book_ioc"
    )
    evaluated: list[DelayedEntrySameExitOutcome] = []
    missing_journal = 0
    lineage_mismatches = 0

    for outcome in full_outcomes:
        trade = trades.get(outcome.trade_id)
        if trade is None:
            missing_journal += 1
            continue
        try:
            evaluated.append(_evaluate_one(trade, outcome))
        except DelayedEntrySameExitError:
            lineage_mismatches += 1

    items = tuple(evaluated)
    by_side = {
        side: _summary(
            tuple(item for item in items if item.direction == side)
        )
        for side in ("long", "short")
    }
    ready = (
        len(outcomes) >= MIN_CLOSED_ELIGIBLE_TRADES
        and len(items) >= MIN_FULL_DELAYED_FILLS
        and missing_journal == 0
        and lineage_mismatches == 0
    )

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "claim_scope": "same_exit_trade_contribution_only",
        "funding_assumption": "actual_trade_funding_held_constant",
        "exit_assumption": "actual_trade_exit_price_and_exit_fee_held_constant",
        "closed_shadow_outcomes": len(outcomes),
        "full_delayed_fill_outcomes": len(full_outcomes),
        "evaluated_full_delayed_fills": len(items),
        "missing_journal_trades": missing_journal,
        "lineage_mismatches": lineage_mismatches,
        "overall": _summary(items),
        "by_side": by_side,
        "readiness": {
            "ready_for_review": ready,
            "min_closed_shadow_outcomes": MIN_CLOSED_ELIGIBLE_TRADES,
            "min_full_delayed_fills": MIN_FULL_DELAYED_FILLS,
            "missing_closed_shadow_outcomes": max(
                0,
                MIN_CLOSED_ELIGIBLE_TRADES - len(outcomes),
            ),
            "missing_full_delayed_fills": max(
                0,
                MIN_FULL_DELAYED_FILLS - len(items),
            ),
        },
    }
