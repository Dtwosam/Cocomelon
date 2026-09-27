from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.journal.store import JournalStore
from cocomelon.research.delayed_entry_execution_shadow import (
    MIN_CLOSED_ELIGIBLE_TRADES,
    DelayedEntryOutcome,
)

ZERO: Final = Decimal("0")
ONE: Final = Decimal("1")
MIN_EVALUATED_DELAYED_ATTEMPTS: Final = 20
EVALUABLE_SOURCES: Final = frozenset(
    {
        "full_visible_book_ioc",
        "partial_visible_book_ioc",
        "no_fill",
    }
)


class DelayedEntryFillWeightedError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DelayedEntryFillWeightedOutcome:
    trade_id: str
    opening_plan_id: str
    market: str
    direction: str
    source: str
    fill_fraction: Decimal
    delayed_filled_quantity: Decimal
    delayed_average_fill_price: Decimal | None
    delayed_entry_fee: Decimal
    scaled_exit_fee: Decimal
    scaled_funding_pnl: Decimal
    actual_net_pnl: Decimal
    actual_net_r: Decimal
    candidate_net_pnl_estimate: Decimal
    candidate_net_r_contribution: Decimal
    delta_net_pnl_estimate: Decimal
    delta_net_r_contribution: Decimal

    def __post_init__(self) -> None:
        for identity in (
            self.trade_id,
            self.opening_plan_id,
            self.market,
            self.direction,
            self.source,
        ):
            if not identity.strip():
                raise ValueError(
                    "fill-weighted outcome identity must not be empty"
                )
        if self.direction not in {"long", "short"}:
            raise ValueError("direction must be long or short")
        if not ZERO <= self.fill_fraction <= ONE:
            raise ValueError("fill_fraction must be between zero and one")
        if self.delayed_filled_quantity < ZERO:
            raise ValueError(
                "delayed_filled_quantity must be non-negative"
            )
        if self.delayed_average_fill_price is not None:
            if (
                not self.delayed_average_fill_price.is_finite()
                or self.delayed_average_fill_price <= ZERO
            ):
                raise ValueError(
                    "delayed_average_fill_price must be positive"
                )
        for metric in (
            self.delayed_entry_fee,
            self.scaled_exit_fee,
        ):
            if not metric.is_finite() or metric < ZERO:
                raise ValueError(
                    "fill-weighted fee metrics must be non-negative"
                )
        for metric in (
            self.scaled_funding_pnl,
            self.actual_net_pnl,
            self.actual_net_r,
            self.candidate_net_pnl_estimate,
            self.candidate_net_r_contribution,
            self.delta_net_pnl_estimate,
            self.delta_net_r_contribution,
        ):
            if not metric.is_finite():
                raise ValueError(
                    "fill-weighted economics must be finite"
                )


def _trade_map(
    journal: JournalStore,
) -> dict[str, TradeJournalEntry]:
    trades = tuple(journal.iter_trades())
    by_id = {trade.trade_id: trade for trade in trades}
    if len(by_id) != len(trades):
        raise DelayedEntryFillWeightedError(
            "journal contains duplicate trade ids"
        )
    return by_id


def _validate_lineage(
    trade: TradeJournalEntry,
    outcome: DelayedEntryOutcome,
) -> None:
    if (
        outcome.opening_plan_id != trade.opening_plan_id
        or outcome.market != trade.market.canonical
        or outcome.direction != trade.direction.value
    ):
        raise DelayedEntryFillWeightedError(
            "delayed-entry outcome lineage does not match journal"
        )
    if trade.filled_quantity <= ZERO:
        raise DelayedEntryFillWeightedError(
            "journal trade quantity must be positive"
        )
    if trade.initial_risk_amount <= ZERO:
        raise DelayedEntryFillWeightedError(
            "journal initial risk must be positive"
        )
    if (
        outcome.delayed_filled_quantity < ZERO
        or outcome.delayed_filled_quantity > trade.filled_quantity
    ):
        raise DelayedEntryFillWeightedError(
            "delayed filled quantity is outside journal quantity"
        )


def _evaluate_one(
    trade: TradeJournalEntry,
    outcome: DelayedEntryOutcome,
) -> DelayedEntryFillWeightedOutcome:
    if outcome.source not in EVALUABLE_SOURCES:
        raise DelayedEntryFillWeightedError(
            "delayed outcome is not fill-weight evaluable"
        )
    _validate_lineage(trade, outcome)

    quantity = outcome.delayed_filled_quantity
    fill_fraction = quantity / trade.filled_quantity

    if outcome.source == "full_visible_book_ioc":
        if (
            quantity != trade.filled_quantity
            or outcome.delayed_average_fill_price is None
        ):
            raise DelayedEntryFillWeightedError(
                "full delayed fill economics are inconsistent"
            )
    elif outcome.source == "partial_visible_book_ioc":
        if (
            quantity <= ZERO
            or quantity >= trade.filled_quantity
            or outcome.delayed_average_fill_price is None
        ):
            raise DelayedEntryFillWeightedError(
                "partial delayed fill economics are inconsistent"
            )
    elif outcome.source == "no_fill":
        if (
            quantity != ZERO
            or outcome.delayed_average_fill_price is not None
            or outcome.delayed_fee != ZERO
        ):
            raise DelayedEntryFillWeightedError(
                "no-fill delayed economics are inconsistent"
            )

    scaled_exit_fee = trade.exit_fees * fill_fraction
    scaled_funding = trade.funding_cash_pnl * fill_fraction

    if quantity == ZERO:
        candidate_net = ZERO
    else:
        delayed_price = outcome.delayed_average_fill_price
        if delayed_price is None:
            raise DelayedEntryFillWeightedError(
                "filled delayed attempt is missing average fill price"
            )
        gross = (
            (trade.exit_price - delayed_price) * quantity
            if trade.direction.value == "long"
            else (delayed_price - trade.exit_price) * quantity
        )
        candidate_net = (
            gross
            - outcome.delayed_fee
            - scaled_exit_fee
            + scaled_funding
        )

    candidate_r = candidate_net / trade.initial_risk_amount
    return DelayedEntryFillWeightedOutcome(
        trade_id=trade.trade_id,
        opening_plan_id=trade.opening_plan_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        source=outcome.source,
        fill_fraction=fill_fraction,
        delayed_filled_quantity=quantity,
        delayed_average_fill_price=(
            outcome.delayed_average_fill_price
        ),
        delayed_entry_fee=outcome.delayed_fee,
        scaled_exit_fee=scaled_exit_fee,
        scaled_funding_pnl=scaled_funding,
        actual_net_pnl=trade.net_pnl,
        actual_net_r=trade.net_r,
        candidate_net_pnl_estimate=candidate_net,
        candidate_net_r_contribution=candidate_r,
        delta_net_pnl_estimate=candidate_net - trade.net_pnl,
        delta_net_r_contribution=candidate_r - trade.net_r,
    )


def _summary(
    items: tuple[DelayedEntryFillWeightedOutcome, ...],
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
    actual_r = sum(
        (item.actual_net_r for item in items),
        ZERO,
    )
    candidate_r = sum(
        (item.candidate_net_r_contribution for item in items),
        ZERO,
    )
    return {
        "trades": count,
        "actual_wins": sum(
            1 for item in items if item.actual_net_pnl > ZERO
        ),
        "actual_losses": sum(
            1 for item in items if item.actual_net_pnl < ZERO
        ),
        "candidate_positive_contributions": sum(
            1
            for item in items
            if item.candidate_net_pnl_estimate > ZERO
        ),
        "candidate_negative_contributions": sum(
            1
            for item in items
            if item.candidate_net_pnl_estimate < ZERO
        ),
        "candidate_zero_contributions": sum(
            1
            for item in items
            if item.candidate_net_pnl_estimate == ZERO
        ),
        "candidate_better_than_actual": sum(
            1
            for item in items
            if item.candidate_net_pnl_estimate
            > item.actual_net_pnl
        ),
        "candidate_worse_than_actual": sum(
            1
            for item in items
            if item.candidate_net_pnl_estimate
            < item.actual_net_pnl
        ),
        "candidate_equal_to_actual": sum(
            1
            for item in items
            if item.candidate_net_pnl_estimate
            == item.actual_net_pnl
        ),
        "actual_win_to_nonpositive_contribution": sum(
            1
            for item in items
            if item.actual_net_pnl > ZERO
            and item.candidate_net_pnl_estimate <= ZERO
        ),
        "actual_loss_to_nonnegative_contribution": sum(
            1
            for item in items
            if item.actual_net_pnl < ZERO
            and item.candidate_net_pnl_estimate >= ZERO
        ),
        "actual_net_pnl": str(actual_pnl),
        "candidate_fill_weighted_net_pnl": str(candidate_pnl),
        "delta_net_pnl_estimate": str(
            candidate_pnl - actual_pnl
        ),
        "actual_mean_net_r": (
            None
            if count == 0
            else str(actual_r / Decimal(count))
        ),
        "candidate_mean_r_contribution": (
            None
            if count == 0
            else str(candidate_r / Decimal(count))
        ),
        "mean_delta_r_contribution": (
            None
            if count == 0
            else str(
                (candidate_r - actual_r) / Decimal(count)
            )
        ),
        "mean_fill_fraction": (
            None
            if count == 0
            else str(
                sum(
                    (item.fill_fraction for item in items),
                    ZERO,
                )
                / Decimal(count)
            )
        ),
    }


def delayed_entry_fill_weighted_contribution(
    journal: JournalStore,
    outcomes: tuple[DelayedEntryOutcome, ...],
) -> dict[str, object]:
    trades = _trade_map(journal)
    evaluated: list[DelayedEntryFillWeightedOutcome] = []
    missing_journal = 0
    lineage_mismatches = 0

    source_counts = {
        "full_visible_book_ioc": 0,
        "partial_visible_book_ioc": 0,
        "no_fill": 0,
        "censored_before_delay": 0,
        "missing_delayed_book": 0,
        "rejected": 0,
        "expired": 0,
    }

    for outcome in outcomes:
        source_counts[outcome.source] = (
            source_counts.get(outcome.source, 0) + 1
        )
        if outcome.source not in EVALUABLE_SOURCES:
            continue
        trade = trades.get(outcome.trade_id)
        if trade is None:
            missing_journal += 1
            continue
        try:
            evaluated.append(_evaluate_one(trade, outcome))
        except DelayedEntryFillWeightedError:
            lineage_mismatches += 1

    items = tuple(evaluated)
    by_side = {
        side: _summary(
            tuple(
                item
                for item in items
                if item.direction == side
            )
        )
        for side in ("long", "short")
    }
    by_source = {
        source: _summary(
            tuple(
                item
                for item in items
                if item.source == source
            )
        )
        for source in (
            "full_visible_book_ioc",
            "partial_visible_book_ioc",
            "no_fill",
        )
    }

    ready = (
        len(outcomes) >= MIN_CLOSED_ELIGIBLE_TRADES
        and len(items) >= MIN_EVALUATED_DELAYED_ATTEMPTS
        and missing_journal == 0
        and lineage_mismatches == 0
    )

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "claim_scope": (
            "fill_weighted_same_exit_trade_contribution_only"
        ),
        "exit_assumption": (
            "actual_exit_price_with_exit_fee_scaled_by_fill_fraction"
        ),
        "funding_assumption": (
            "actual_trade_funding_scaled_by_fill_fraction"
        ),
        "unfilled_assumption": (
            "unfilled_quantity_contributes_zero_and_is_not_replaced"
        ),
        "closed_shadow_outcomes": len(outcomes),
        "evaluated_delayed_attempts": len(items),
        "missing_journal_trades": missing_journal,
        "lineage_mismatches": lineage_mismatches,
        "source_counts": source_counts,
        "overall": _summary(items),
        "by_side": by_side,
        "by_source": by_source,
        "readiness": {
            "ready_for_review": ready,
            "min_closed_shadow_outcomes": (
                MIN_CLOSED_ELIGIBLE_TRADES
            ),
            "min_evaluated_delayed_attempts": (
                MIN_EVALUATED_DELAYED_ATTEMPTS
            ),
            "missing_closed_shadow_outcomes": max(
                0,
                MIN_CLOSED_ELIGIBLE_TRADES - len(outcomes),
            ),
            "missing_evaluated_delayed_attempts": max(
                0,
                MIN_EVALUATED_DELAYED_ATTEMPTS - len(items),
            ),
        },
    }
