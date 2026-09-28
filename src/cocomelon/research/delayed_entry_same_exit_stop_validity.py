from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.journal.store import JournalStore
from cocomelon.research.continuous_paper_trade_paths import (
    ContinuousPaperTradePathStore,
)
from cocomelon.research.delayed_entry_execution_shadow import (
    DELAY_MS,
    DelayedEntryOutcome,
)
from cocomelon.research.delayed_entry_fill_weighted import (
    EVALUABLE_SOURCES,
    DelayedEntryFillWeightedError,
    evaluate_delayed_entry_fill_weighted_outcome,
)
from cocomelon.research.delayed_entry_fill_weighted_funding import (
    DelayedEntryFundingCorrectedFillError,
    evaluate_delayed_entry_funding_corrected_fill_weighted_outcome,
)
from cocomelon.research.delayed_entry_funding import (
    DelayedEntryFundingError,
    DelayedEntryFundingMissingError,
    FundingLoader,
)
from cocomelon.research.delayed_entry_stop_survivability import (
    DelayedEntryStopSurvivabilityError,
    DelayedEntryStopTimingError,
    evaluate_delayed_entry_stop_outcome,
)

ZERO: Final = Decimal("0")
MIN_CLOSED_SHADOW_OUTCOMES: Final = 30
MIN_EVALUATED_FILLED_CANDIDATES: Final = 20


class DelayedEntrySameExitStopValidityError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DelayedEntrySameExitStopValidityOutcome:
    trade_id: str
    market: str
    direction: str
    source: str
    stop_hit: bool
    time_to_stop_ms: int | None
    actual_net_pnl: Decimal
    same_exit_candidate_net_pnl: Decimal
    same_exit_delta_vs_actual: Decimal

    def __post_init__(self) -> None:
        for identity in (
            self.trade_id,
            self.market,
            self.direction,
            self.source,
        ):
            if not identity.strip():
                raise ValueError(
                    "same-exit stop-validity identity must not be empty"
                )
        if self.direction not in {"long", "short"}:
            raise ValueError("direction must be long or short")
        if self.stop_hit != (self.time_to_stop_ms is not None):
            raise ValueError(
                "stop-hit state must reconcile with time_to_stop_ms"
            )
        if self.time_to_stop_ms is not None and self.time_to_stop_ms <= 0:
            raise ValueError("time_to_stop_ms must be positive")
        for metric in (
            self.actual_net_pnl,
            self.same_exit_candidate_net_pnl,
            self.same_exit_delta_vs_actual,
        ):
            if not metric.is_finite():
                raise ValueError(
                    "same-exit stop-validity economics must be finite"
                )
        if (
            self.same_exit_candidate_net_pnl - self.actual_net_pnl
            != self.same_exit_delta_vs_actual
        ):
            raise ValueError(
                "same-exit delta must reconcile with candidate and actual"
            )


def _trade_map(
    journal: JournalStore,
) -> dict[str, TradeJournalEntry]:
    trades = tuple(journal.iter_trades())
    by_id = {trade.trade_id: trade for trade in trades}
    if len(by_id) != len(trades):
        raise DelayedEntrySameExitStopValidityError(
            "journal contains duplicate trade ids"
        )
    return by_id


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DelayedEntrySameExitStopValidityError(
            f"{field} must be a non-empty string"
        )
    return value


def _path_map(
    store: ContinuousPaperTradePathStore,
) -> dict[str, Mapping[str, object]]:
    result: dict[str, Mapping[str, object]] = {}
    for raw in store.iter_payloads():
        trade_id = _string(raw.get("trade_id"), "trade_id")
        if trade_id in result:
            raise DelayedEntrySameExitStopValidityError(
                "duplicate exact trade path"
            )
        result[trade_id] = raw
    return result


def _summary(
    items: Sequence[DelayedEntrySameExitStopValidityOutcome],
) -> dict[str, object]:
    values = tuple(items)
    crossed = tuple(item for item in values if item.stop_hit)
    survived = tuple(item for item in values if not item.stop_hit)

    candidate_total = sum(
        (item.same_exit_candidate_net_pnl for item in values),
        ZERO,
    )
    crossed_candidate = sum(
        (
            item.same_exit_candidate_net_pnl
            for item in crossed
        ),
        ZERO,
    )
    survived_candidate = sum(
        (
            item.same_exit_candidate_net_pnl
            for item in survived
        ),
        ZERO,
    )
    actual_total = sum(
        (item.actual_net_pnl for item in values),
        ZERO,
    )
    delta_total = sum(
        (item.same_exit_delta_vs_actual for item in values),
        ZERO,
    )
    crossed_delta = sum(
        (
            item.same_exit_delta_vs_actual
            for item in crossed
        ),
        ZERO,
    )
    survived_delta = sum(
        (
            item.same_exit_delta_vs_actual
            for item in survived
        ),
        ZERO,
    )
    absolute_candidate = sum(
        (abs(item.same_exit_candidate_net_pnl) for item in values),
        ZERO,
    )
    crossed_absolute_candidate = sum(
        (
            abs(item.same_exit_candidate_net_pnl)
            for item in crossed
        ),
        ZERO,
    )
    if candidate_total != crossed_candidate + survived_candidate:
        raise DelayedEntrySameExitStopValidityError(
            "candidate stop-validity partition does not reconcile"
        )
    if delta_total != crossed_delta + survived_delta:
        raise DelayedEntrySameExitStopValidityError(
            "delta stop-validity partition does not reconcile"
        )
    if actual_total + delta_total != candidate_total:
        raise DelayedEntrySameExitStopValidityError(
            "same-exit candidate and actual totals do not reconcile"
        )

    return {
        "filled_candidates": len(values),
        "definite_original_stop_crossings": len(crossed),
        "survived_observed_path_to_actual_close": len(survived),
        "crossing_fraction": (
            None
            if not values
            else str(Decimal(len(crossed)) / Decimal(len(values)))
        ),
        "actual_net_pnl": str(actual_total),
        "same_exit_candidate_net_pnl": str(candidate_total),
        "same_exit_delta_vs_actual": str(delta_total),
        "same_exit_candidate_pnl_on_definite_stop_crossings": str(
            crossed_candidate
        ),
        "same_exit_candidate_pnl_on_observed_survivors": str(
            survived_candidate
        ),
        "same_exit_delta_on_definite_stop_crossings": str(
            crossed_delta
        ),
        "same_exit_delta_on_observed_survivors": str(
            survived_delta
        ),
        "absolute_candidate_pnl_on_stop_crossings_fraction": (
            None
            if absolute_candidate == ZERO
            else str(
                crossed_absolute_candidate / absolute_candidate
            )
        ),
        "positive_same_exit_candidate_pnl_on_stop_crossings": str(
            sum(
                (
                    item.same_exit_candidate_net_pnl
                    for item in crossed
                    if item.same_exit_candidate_net_pnl > ZERO
                ),
                ZERO,
            )
        ),
        "negative_same_exit_candidate_pnl_on_stop_crossings": str(
            sum(
                (
                    item.same_exit_candidate_net_pnl
                    for item in crossed
                    if item.same_exit_candidate_net_pnl < ZERO
                ),
                ZERO,
            )
        ),
        "mean_time_to_stop_ms": (
            None
            if not crossed
            else sum(
                (
                    item.time_to_stop_ms
                    for item in crossed
                    if item.time_to_stop_ms is not None
                )
            )
            // len(crossed)
        ),
    }


def delayed_entry_same_exit_stop_validity(
    journal: JournalStore,
    outcomes: tuple[DelayedEntryOutcome, ...],
    path_store: ContinuousPaperTradePathStore,
    funding_loader: FundingLoader,
    *,
    delay_ms: int = DELAY_MS,
) -> dict[str, object]:
    if delay_ms <= 0:
        raise ValueError("delay_ms must be positive")

    trades = _trade_map(journal)
    if len({outcome.trade_id for outcome in outcomes}) != len(
        outcomes
    ):
        raise DelayedEntrySameExitStopValidityError(
            "delayed shadow contains duplicate trade ids"
        )
    paths = _path_map(path_store)

    evaluated: list[DelayedEntrySameExitStopValidityOutcome] = []
    unresolved_outcomes = 0
    candidate_no_fill = 0
    missing_journal = 0
    missing_paths = 0
    incomplete_or_gapped_paths = 0
    missing_funding_events = 0
    lineage_mismatches = 0
    invalid_candidate_timing = 0

    for outcome in outcomes:
        if outcome.source not in EVALUABLE_SOURCES:
            unresolved_outcomes += 1
            continue
        trade = trades.get(outcome.trade_id)
        if trade is None:
            missing_journal += 1
            continue

        try:
            weighted = evaluate_delayed_entry_fill_weighted_outcome(
                trade,
                outcome,
            )
        except DelayedEntryFillWeightedError:
            lineage_mismatches += 1
            continue

        if weighted.delayed_filled_quantity == ZERO:
            candidate_no_fill += 1
            continue

        raw_path = paths.get(trade.trade_id)
        if raw_path is None:
            missing_paths += 1
            continue
        if (
            raw_path.get("path_complete") is not True
            or raw_path.get("known_gap_intervals") != []
        ):
            incomplete_or_gapped_paths += 1
            continue

        try:
            corrected = (
                evaluate_delayed_entry_funding_corrected_fill_weighted_outcome(
                    trade,
                    outcome,
                    weighted,
                    funding_loader,
                    delay_ms=delay_ms,
                )
            )
            stop = evaluate_delayed_entry_stop_outcome(
                trade,
                outcome,
                weighted,
                raw_path,
                delay_ms=delay_ms,
            )
        except DelayedEntryFundingMissingError:
            missing_funding_events += 1
            continue
        except DelayedEntryStopTimingError:
            invalid_candidate_timing += 1
            continue
        except (
            DelayedEntryFundingCorrectedFillError,
            DelayedEntryFundingError,
            DelayedEntryStopSurvivabilityError,
            ValueError,
        ):
            lineage_mismatches += 1
            continue

        if stop is None:
            lineage_mismatches += 1
            continue
        try:
            evaluated.append(
                DelayedEntrySameExitStopValidityOutcome(
                    trade_id=trade.trade_id,
                    market=trade.market.canonical,
                    direction=trade.direction.value,
                    source=outcome.source,
                    stop_hit=stop.stop_hit,
                    time_to_stop_ms=stop.time_to_stop_ms,
                    actual_net_pnl=trade.net_pnl,
                    same_exit_candidate_net_pnl=(
                        corrected.corrected_candidate_net_pnl
                    ),
                    same_exit_delta_vs_actual=(
                        corrected.corrected_delta_net_pnl
                    ),
                )
            )
        except ValueError:
            lineage_mismatches += 1

    items = tuple(evaluated)
    ready = (
        len(outcomes) >= MIN_CLOSED_SHADOW_OUTCOMES
        and len(items) >= MIN_EVALUATED_FILLED_CANDIDATES
        and unresolved_outcomes == 0
        and missing_journal == 0
        and missing_paths == 0
        and incomplete_or_gapped_paths == 0
        and missing_funding_events == 0
        and lineage_mismatches == 0
        and invalid_candidate_timing == 0
    )

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "claim_scope": (
            "funding_corrected_same_exit_stop_validity_partition_only"
        ),
        "delay_ms": delay_ms,
        "same_exit_pnl_interpretation": (
            "stop_crossed_candidate_pnl_is_flagged_as_path_invalid_"
            "rather_than_repriced"
        ),
        "stop_fill_price_modeled": False,
        "changed_exit_timing_modeled": False,
        "replacement_trades_modeled": False,
        "closed_shadow_outcomes": len(outcomes),
        "evaluated_filled_candidates": len(items),
        "candidate_no_fill_trades": candidate_no_fill,
        "unresolved_outcomes": unresolved_outcomes,
        "missing_journal_trades": missing_journal,
        "missing_exact_paths": missing_paths,
        "incomplete_or_gapped_paths": (
            incomplete_or_gapped_paths
        ),
        "missing_funding_events": missing_funding_events,
        "lineage_mismatches": lineage_mismatches,
        "invalid_candidate_timing": invalid_candidate_timing,
        "overall": _summary(items),
        "by_side": {
            side: _summary(
                tuple(
                    item
                    for item in items
                    if item.direction == side
                )
            )
            for side in ("long", "short")
        },
        "by_source": {
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
            )
        },
        "readiness": {
            "ready_for_review": ready,
            "min_closed_shadow_outcomes": (
                MIN_CLOSED_SHADOW_OUTCOMES
            ),
            "min_evaluated_filled_candidates": (
                MIN_EVALUATED_FILLED_CANDIDATES
            ),
            "missing_closed_shadow_outcomes": max(
                0,
                MIN_CLOSED_SHADOW_OUTCOMES - len(outcomes),
            ),
            "missing_evaluated_filled_candidates": max(
                0,
                MIN_EVALUATED_FILLED_CANDIDATES - len(items),
            ),
        },
    }
