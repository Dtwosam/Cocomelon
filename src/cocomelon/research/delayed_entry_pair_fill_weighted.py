from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.journal.store import JournalStore
from cocomelon.research.delayed_entry_execution_shadow import (
    DelayedEntryOutcome,
)
from cocomelon.research.delayed_entry_fill_weighted import (
    EVALUABLE_SOURCES,
    DelayedEntryFillWeightedError,
    evaluate_delayed_entry_fill_weighted_outcome,
)
from cocomelon.research.delayed_entry_pair import (
    BASE_DELAY_MS,
    CHALLENGER_DELAY_MS,
    MIN_LONG_PAIRED_FULL_FILLS,
    MIN_PROSPECTIVE_CLOSED_TRADES,
    MIN_SHORT_PAIRED_FULL_FILLS,
)

ZERO: Final = Decimal("0")
MIN_PAIRED_EVALUABLE_ATTEMPTS: Final = 20


class DelayedEntryPairFillWeightedError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DelayedEntryPairFillWeightedOutcome:
    trade_id: str
    opening_plan_id: str
    market: str
    direction: str
    actual_net_pnl: Decimal
    actual_net_r: Decimal
    base_source: str
    challenger_source: str
    base_fill_fraction: Decimal
    challenger_fill_fraction: Decimal
    base_candidate_net_pnl: Decimal
    challenger_candidate_net_pnl: Decimal
    base_candidate_r_contribution: Decimal
    challenger_candidate_r_contribution: Decimal
    challenger_minus_base_pnl: Decimal
    challenger_minus_base_r: Decimal

    def __post_init__(self) -> None:
        for identity in (
            self.trade_id,
            self.opening_plan_id,
            self.market,
            self.direction,
            self.base_source,
            self.challenger_source,
        ):
            if not identity.strip():
                raise ValueError(
                    "paired fill-weighted identity must not be empty"
                )
        if self.direction not in {"long", "short"}:
            raise ValueError(
                "paired fill-weighted direction must be long or short"
            )
        for fraction in (
            self.base_fill_fraction,
            self.challenger_fill_fraction,
        ):
            if not ZERO <= fraction <= Decimal("1"):
                raise ValueError(
                    "paired fill fraction must be between zero and one"
                )
        for metric in (
            self.actual_net_pnl,
            self.actual_net_r,
            self.base_candidate_net_pnl,
            self.challenger_candidate_net_pnl,
            self.base_candidate_r_contribution,
            self.challenger_candidate_r_contribution,
            self.challenger_minus_base_pnl,
            self.challenger_minus_base_r,
        ):
            if not metric.is_finite():
                raise ValueError(
                    "paired fill-weighted economics must be finite"
                )


def _trade_map(
    journal: JournalStore,
) -> dict[str, TradeJournalEntry]:
    trades = tuple(journal.iter_trades())
    by_id = {trade.trade_id: trade for trade in trades}
    if len(by_id) != len(trades):
        raise DelayedEntryPairFillWeightedError(
            "journal contains duplicate trade ids"
        )
    return by_id


def _outcome_map(
    outcomes: tuple[DelayedEntryOutcome, ...],
    *,
    label: str,
) -> dict[str, DelayedEntryOutcome]:
    by_id = {outcome.trade_id: outcome for outcome in outcomes}
    if len(by_id) != len(outcomes):
        raise DelayedEntryPairFillWeightedError(
            f"{label} delayed-entry outcomes contain duplicate trade ids"
        )
    return by_id


def _evaluate_pair(
    trade: TradeJournalEntry,
    base: DelayedEntryOutcome,
    challenger: DelayedEntryOutcome,
) -> DelayedEntryPairFillWeightedOutcome:
    try:
        base_item = evaluate_delayed_entry_fill_weighted_outcome(
            trade,
            base,
        )
        challenger_item = (
            evaluate_delayed_entry_fill_weighted_outcome(
                trade,
                challenger,
            )
        )
    except DelayedEntryFillWeightedError as exc:
        raise DelayedEntryPairFillWeightedError(str(exc)) from exc

    return DelayedEntryPairFillWeightedOutcome(
        trade_id=trade.trade_id,
        opening_plan_id=trade.opening_plan_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        actual_net_pnl=trade.net_pnl,
        actual_net_r=trade.net_r,
        base_source=base_item.source,
        challenger_source=challenger_item.source,
        base_fill_fraction=base_item.fill_fraction,
        challenger_fill_fraction=challenger_item.fill_fraction,
        base_candidate_net_pnl=(
            base_item.candidate_net_pnl_estimate
        ),
        challenger_candidate_net_pnl=(
            challenger_item.candidate_net_pnl_estimate
        ),
        base_candidate_r_contribution=(
            base_item.candidate_net_r_contribution
        ),
        challenger_candidate_r_contribution=(
            challenger_item.candidate_net_r_contribution
        ),
        challenger_minus_base_pnl=(
            challenger_item.candidate_net_pnl_estimate
            - base_item.candidate_net_pnl_estimate
        ),
        challenger_minus_base_r=(
            challenger_item.candidate_net_r_contribution
            - base_item.candidate_net_r_contribution
        ),
    )


def _summary(
    items: tuple[DelayedEntryPairFillWeightedOutcome, ...],
) -> dict[str, object]:
    count = len(items)
    actual_pnl = sum(
        (item.actual_net_pnl for item in items),
        ZERO,
    )
    base_pnl = sum(
        (item.base_candidate_net_pnl for item in items),
        ZERO,
    )
    challenger_pnl = sum(
        (item.challenger_candidate_net_pnl for item in items),
        ZERO,
    )
    incremental = challenger_pnl - base_pnl
    return {
        "trades": count,
        "challenger_better": sum(
            1
            for item in items
            if item.challenger_minus_base_pnl > ZERO
        ),
        "base_better": sum(
            1
            for item in items
            if item.challenger_minus_base_pnl < ZERO
        ),
        "equal": sum(
            1
            for item in items
            if item.challenger_minus_base_pnl == ZERO
        ),
        "actual_net_pnl": str(actual_pnl),
        "base_fill_weighted_net_pnl": str(base_pnl),
        "challenger_fill_weighted_net_pnl": str(challenger_pnl),
        "challenger_minus_base_pnl": str(incremental),
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
        "mean_base_fill_fraction": (
            None
            if count == 0
            else str(
                sum(
                    (item.base_fill_fraction for item in items),
                    ZERO,
                )
                / Decimal(count)
            )
        ),
        "mean_challenger_fill_fraction": (
            None
            if count == 0
            else str(
                sum(
                    (
                        item.challenger_fill_fraction
                        for item in items
                    ),
                    ZERO,
                )
                / Decimal(count)
            )
        ),
        "challenger_loses_fill_fraction": sum(
            1
            for item in items
            if item.challenger_fill_fraction
            < item.base_fill_fraction
        ),
        "challenger_gains_fill_fraction": sum(
            1
            for item in items
            if item.challenger_fill_fraction
            > item.base_fill_fraction
        ),
        "equal_fill_fraction": sum(
            1
            for item in items
            if item.challenger_fill_fraction
            == item.base_fill_fraction
        ),
    }


def delayed_entry_pair_fill_weighted_summary(
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

    paired: list[DelayedEntryPairFillWeightedOutcome] = []
    missing_base_outcome = 0
    missing_challenger_outcome = 0
    non_evaluable_base = 0
    non_evaluable_challenger = 0
    lineage_mismatches = 0
    source_pairs: dict[str, int] = {}

    for trade in prospective_trades:
        base = base_map.get(trade.trade_id)
        challenger = challenger_map.get(trade.trade_id)
        if base is None:
            missing_base_outcome += 1
            continue
        if challenger is None:
            missing_challenger_outcome += 1
            continue

        base_evaluable = base.source in EVALUABLE_SOURCES
        challenger_evaluable = (
            challenger.source in EVALUABLE_SOURCES
        )
        if not base_evaluable:
            non_evaluable_base += 1
        if not challenger_evaluable:
            non_evaluable_challenger += 1
        if not base_evaluable or not challenger_evaluable:
            continue

        try:
            item = _evaluate_pair(
                trade,
                base,
                challenger,
            )
        except DelayedEntryPairFillWeightedError:
            lineage_mismatches += 1
            continue
        paired.append(item)
        pair_label = (
            f"{item.base_source}->{item.challenger_source}"
        )
        source_pairs[pair_label] = source_pairs.get(
            pair_label,
            0,
        ) + 1

    items = tuple(paired)
    long_count = sum(
        1 for item in items if item.direction == "long"
    )
    short_count = sum(
        1 for item in items if item.direction == "short"
    )
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

    ready = (
        len(prospective_trades) >= MIN_PROSPECTIVE_CLOSED_TRADES
        and len(items) >= MIN_PAIRED_EVALUABLE_ATTEMPTS
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
        "claim_scope": (
            "paired_fill_weighted_same_exit_trade_contribution_only"
        ),
        "base_delay_ms": BASE_DELAY_MS,
        "challenger_delay_ms": CHALLENGER_DELAY_MS,
        "started_at_ms": started_at_ms,
        "prospective_closed_trades": len(prospective_trades),
        "paired_evaluable_attempts": len(items),
        "missing_base_outcome": missing_base_outcome,
        "missing_challenger_outcome": missing_challenger_outcome,
        "non_evaluable_base": non_evaluable_base,
        "non_evaluable_challenger": non_evaluable_challenger,
        "lineage_mismatches": lineage_mismatches,
        "source_pairs": dict(sorted(source_pairs.items())),
        "overall": _summary(items),
        "by_side": by_side,
        "readiness": {
            "ready_for_review": ready,
            "min_prospective_closed_trades": (
                MIN_PROSPECTIVE_CLOSED_TRADES
            ),
            "min_paired_evaluable_attempts": (
                MIN_PAIRED_EVALUABLE_ATTEMPTS
            ),
            "min_long_paired_evaluable_attempts": (
                MIN_LONG_PAIRED_FULL_FILLS
            ),
            "min_short_paired_evaluable_attempts": (
                MIN_SHORT_PAIRED_FULL_FILLS
            ),
            "missing_prospective_closed_trades": max(
                0,
                MIN_PROSPECTIVE_CLOSED_TRADES
                - len(prospective_trades),
            ),
            "missing_paired_evaluable_attempts": max(
                0,
                MIN_PAIRED_EVALUABLE_ATTEMPTS - len(items),
            ),
            "missing_long_paired_evaluable_attempts": max(
                0,
                MIN_LONG_PAIRED_FULL_FILLS - long_count,
            ),
            "missing_short_paired_evaluable_attempts": max(
                0,
                MIN_SHORT_PAIRED_FULL_FILLS - short_count,
            ),
        },
    }
