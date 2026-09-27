from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.journal.store import JournalStore
from cocomelon.research.delayed_entry_execution_shadow import (
    DelayedEntryOutcome,
)

ZERO: Final = Decimal("0")
BPS: Final = Decimal("10000")
BASE_DELAY_MS: Final = 60_000
CHALLENGER_DELAY_MS: Final = 120_000
MIN_PROSPECTIVE_CLOSED_TRADES: Final = 30
MIN_PAIRED_FULL_FILLS: Final = 20
MIN_LONG_PAIRED_FULL_FILLS: Final = 5
MIN_SHORT_PAIRED_FULL_FILLS: Final = 5


class DelayedEntryPairError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DelayedEntryPairOutcome:
    trade_id: str
    opening_plan_id: str
    market: str
    direction: str
    actual_net_pnl: Decimal
    actual_net_r: Decimal
    base_entry_price: Decimal
    challenger_entry_price: Decimal
    base_entry_fee: Decimal
    challenger_entry_fee: Decimal
    base_same_exit_net_pnl: Decimal
    challenger_same_exit_net_pnl: Decimal
    base_same_exit_net_r: Decimal
    challenger_same_exit_net_r: Decimal
    challenger_minus_base_pnl: Decimal
    challenger_minus_base_r: Decimal
    challenger_minus_base_bps: Decimal

    def __post_init__(self) -> None:
        for value in (
            self.trade_id,
            self.opening_plan_id,
            self.market,
            self.direction,
        ):
            if not value.strip():
                raise ValueError("paired delayed-entry identity must not be empty")
        if self.direction not in {"long", "short"}:
            raise ValueError("paired delayed-entry direction must be long or short")
        for price in (
            self.base_entry_price,
            self.challenger_entry_price,
        ):
            if not price.is_finite() or price <= ZERO:
                raise ValueError("paired delayed-entry price must be positive")
        for fee in (self.base_entry_fee, self.challenger_entry_fee):
            if not fee.is_finite() or fee < ZERO:
                raise ValueError("paired delayed-entry fee must be non-negative")
        for metric in (
            self.actual_net_pnl,
            self.actual_net_r,
            self.base_same_exit_net_pnl,
            self.challenger_same_exit_net_pnl,
            self.base_same_exit_net_r,
            self.challenger_same_exit_net_r,
            self.challenger_minus_base_pnl,
            self.challenger_minus_base_r,
            self.challenger_minus_base_bps,
        ):
            if not metric.is_finite():
                raise ValueError("paired delayed-entry economics must be finite")


def _trade_map(journal: JournalStore) -> dict[str, TradeJournalEntry]:
    trades = tuple(journal.iter_trades())
    by_id = {trade.trade_id: trade for trade in trades}
    if len(by_id) != len(trades):
        raise DelayedEntryPairError("journal contains duplicate trade ids")
    return by_id


def _outcome_map(
    outcomes: tuple[DelayedEntryOutcome, ...],
    *,
    label: str,
) -> dict[str, DelayedEntryOutcome]:
    by_id = {outcome.trade_id: outcome for outcome in outcomes}
    if len(by_id) != len(outcomes):
        raise DelayedEntryPairError(
            f"{label} delayed-entry outcomes contain duplicate trade ids"
        )
    return by_id


def _candidate_same_exit(
    trade: TradeJournalEntry,
    outcome: DelayedEntryOutcome,
) -> tuple[Decimal, Decimal]:
    if outcome.source != "full_visible_book_ioc":
        raise DelayedEntryPairError(
            "paired comparison requires full visible-book fills"
        )
    if outcome.delayed_average_fill_price is None:
        raise DelayedEntryPairError(
            "full delayed fill is missing average fill price"
        )
    if (
        outcome.opening_plan_id != trade.opening_plan_id
        or outcome.market != trade.market.canonical
        or outcome.direction != trade.direction.value
        or outcome.delayed_filled_quantity != trade.filled_quantity
    ):
        raise DelayedEntryPairError(
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
    fee_improvement = trade.entry_fees - outcome.delayed_fee
    candidate_pnl = (
        trade.net_pnl + gross_entry_improvement + fee_improvement
    )
    candidate_r = candidate_pnl / trade.initial_risk_amount
    return candidate_pnl, candidate_r


def _evaluate_pair(
    trade: TradeJournalEntry,
    base: DelayedEntryOutcome,
    challenger: DelayedEntryOutcome,
) -> DelayedEntryPairOutcome:
    base_pnl, base_r = _candidate_same_exit(trade, base)
    challenger_pnl, challenger_r = _candidate_same_exit(
        trade,
        challenger,
    )
    assert base.delayed_average_fill_price is not None
    assert challenger.delayed_average_fill_price is not None
    signed_increment = (
        base.delayed_average_fill_price
        - challenger.delayed_average_fill_price
        if trade.direction.value == "long"
        else challenger.delayed_average_fill_price
        - base.delayed_average_fill_price
    )
    return DelayedEntryPairOutcome(
        trade_id=trade.trade_id,
        opening_plan_id=trade.opening_plan_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        actual_net_pnl=trade.net_pnl,
        actual_net_r=trade.net_r,
        base_entry_price=base.delayed_average_fill_price,
        challenger_entry_price=challenger.delayed_average_fill_price,
        base_entry_fee=base.delayed_fee,
        challenger_entry_fee=challenger.delayed_fee,
        base_same_exit_net_pnl=base_pnl,
        challenger_same_exit_net_pnl=challenger_pnl,
        base_same_exit_net_r=base_r,
        challenger_same_exit_net_r=challenger_r,
        challenger_minus_base_pnl=challenger_pnl - base_pnl,
        challenger_minus_base_r=challenger_r - base_r,
        challenger_minus_base_bps=(
            signed_increment / base.delayed_average_fill_price * BPS
        ),
    )


def _summary(
    items: tuple[DelayedEntryPairOutcome, ...],
) -> dict[str, object]:
    count = len(items)
    base_pnl = sum(
        (item.base_same_exit_net_pnl for item in items),
        ZERO,
    )
    challenger_pnl = sum(
        (item.challenger_same_exit_net_pnl for item in items),
        ZERO,
    )
    incremental_pnl = challenger_pnl - base_pnl
    return {
        "trades": count,
        "challenger_better": sum(
            1 for item in items if item.challenger_minus_base_pnl > ZERO
        ),
        "base_better": sum(
            1 for item in items if item.challenger_minus_base_pnl < ZERO
        ),
        "equal": sum(
            1 for item in items if item.challenger_minus_base_pnl == ZERO
        ),
        "base_same_exit_net_pnl": str(base_pnl),
        "challenger_same_exit_net_pnl": str(challenger_pnl),
        "challenger_minus_base_pnl": str(incremental_pnl),
        "mean_challenger_minus_base_r": (
            None
            if count == 0
            else str(
                sum(
                    (
                        item.challenger_minus_base_r
                        for item in items
                    ),
                    ZERO,
                )
                / Decimal(count)
            )
        ),
        "mean_challenger_minus_base_bps": (
            None
            if count == 0
            else str(
                sum(
                    (
                        item.challenger_minus_base_bps
                        for item in items
                    ),
                    ZERO,
                )
                / Decimal(count)
            )
        ),
    }


def delayed_entry_pair_summary(
    journal: JournalStore,
    base_outcomes: tuple[DelayedEntryOutcome, ...],
    challenger_outcomes: tuple[DelayedEntryOutcome, ...],
    *,
    started_at_ms: int,
) -> dict[str, object]:
    if started_at_ms < 0:
        raise ValueError("started_at_ms must be non-negative")
    trades = _trade_map(journal)
    base_map = _outcome_map(base_outcomes, label="base")
    challenger_map = _outcome_map(
        challenger_outcomes,
        label="challenger",
    )

    prospective_trades = tuple(
        trade
        for trade in trades.values()
        if trade.opened_at_ms >= started_at_ms
    )
    paired: list[DelayedEntryPairOutcome] = []
    missing_base_outcome = 0
    missing_challenger_outcome = 0
    non_full_base = 0
    non_full_challenger = 0
    lineage_mismatches = 0

    for trade in prospective_trades:
        base = base_map.get(trade.trade_id)
        challenger = challenger_map.get(trade.trade_id)
        if base is None:
            missing_base_outcome += 1
            continue
        if challenger is None:
            missing_challenger_outcome += 1
            continue
        if base.source != "full_visible_book_ioc":
            non_full_base += 1
            continue
        if challenger.source != "full_visible_book_ioc":
            non_full_challenger += 1
            continue
        try:
            paired.append(_evaluate_pair(trade, base, challenger))
        except DelayedEntryPairError:
            lineage_mismatches += 1

    items = tuple(paired)
    by_side = {
        side: _summary(
            tuple(item for item in items if item.direction == side)
        )
        for side in ("long", "short")
    }
    long_count = sum(
        1 for item in items if item.direction == "long"
    )
    short_count = sum(
        1 for item in items if item.direction == "short"
    )
    ready = (
        len(prospective_trades) >= MIN_PROSPECTIVE_CLOSED_TRADES
        and len(items) >= MIN_PAIRED_FULL_FILLS
        and long_count >= MIN_LONG_PAIRED_FULL_FILLS
        and short_count >= MIN_SHORT_PAIRED_FULL_FILLS
        and missing_base_outcome == 0
        and missing_challenger_outcome == 0
        and lineage_mismatches == 0
    )
    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "claim_scope": "paired_same_exit_trade_contribution_only",
        "base_delay_ms": BASE_DELAY_MS,
        "challenger_delay_ms": CHALLENGER_DELAY_MS,
        "started_at_ms": started_at_ms,
        "prospective_closed_trades": len(prospective_trades),
        "paired_full_fills": len(items),
        "missing_base_outcome": missing_base_outcome,
        "missing_challenger_outcome": missing_challenger_outcome,
        "non_full_base": non_full_base,
        "non_full_challenger": non_full_challenger,
        "lineage_mismatches": lineage_mismatches,
        "overall": _summary(items),
        "by_side": by_side,
        "readiness": {
            "ready_for_review": ready,
            "min_prospective_closed_trades": (
                MIN_PROSPECTIVE_CLOSED_TRADES
            ),
            "min_paired_full_fills": MIN_PAIRED_FULL_FILLS,
            "min_long_paired_full_fills": (
                MIN_LONG_PAIRED_FULL_FILLS
            ),
            "min_short_paired_full_fills": (
                MIN_SHORT_PAIRED_FULL_FILLS
            ),
            "missing_prospective_closed_trades": max(
                0,
                MIN_PROSPECTIVE_CLOSED_TRADES
                - len(prospective_trades),
            ),
            "missing_paired_full_fills": max(
                0,
                MIN_PAIRED_FULL_FILLS - len(items),
            ),
            "missing_long_paired_full_fills": max(
                0,
                MIN_LONG_PAIRED_FULL_FILLS - long_count,
            ),
            "missing_short_paired_full_fills": max(
                0,
                MIN_SHORT_PAIRED_FULL_FILLS - short_count,
            ),
        },
    }
