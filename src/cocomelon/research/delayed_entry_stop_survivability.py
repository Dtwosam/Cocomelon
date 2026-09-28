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
    DelayedEntryFillWeightedOutcome,
    evaluate_delayed_entry_fill_weighted_outcome,
)

ZERO: Final = Decimal("0")
MIN_CLOSED_SHADOW_OUTCOMES: Final = 30
MIN_EVALUATED_FILLED_CANDIDATES: Final = 20


class DelayedEntryStopSurvivabilityError(RuntimeError):
    pass


class DelayedEntryStopTimingError(
    DelayedEntryStopSurvivabilityError
):
    pass


@dataclass(frozen=True, slots=True)
class DelayedEntryStopOutcome:
    trade_id: str
    market: str
    direction: str
    source: str
    candidate_open_ms: int
    actual_close_ms: int
    original_stop: Decimal
    delayed_entry_price: Decimal
    delayed_filled_quantity: Decimal
    first_stop_hit_ms: int | None
    first_stop_mark_px: Decimal | None

    def __post_init__(self) -> None:
        for identity in (
            self.trade_id,
            self.market,
            self.direction,
            self.source,
        ):
            if not identity.strip():
                raise ValueError(
                    "stop-survivability identity must not be empty"
                )
        if self.direction not in {"long", "short"}:
            raise ValueError("direction must be long or short")
        if (
            self.candidate_open_ms < 0
            or self.actual_close_ms <= self.candidate_open_ms
        ):
            raise ValueError(
                "candidate stop-survivability timestamps are invalid"
            )
        for metric, field in (
            (self.original_stop, "original_stop"),
            (self.delayed_entry_price, "delayed_entry_price"),
            (
                self.delayed_filled_quantity,
                "delayed_filled_quantity",
            ),
        ):
            if not metric.is_finite() or metric <= ZERO:
                raise ValueError(f"{field} must be positive and finite")
        if (
            self.direction == "long"
            and self.delayed_entry_price <= self.original_stop
        ):
            raise ValueError(
                "long delayed entry must remain above original stop"
            )
        if (
            self.direction == "short"
            and self.delayed_entry_price >= self.original_stop
        ):
            raise ValueError(
                "short delayed entry must remain below original stop"
            )
        if (self.first_stop_hit_ms is None) != (
            self.first_stop_mark_px is None
        ):
            raise ValueError(
                "stop hit timestamp and mark must be jointly present"
            )
        if self.first_stop_hit_ms is not None:
            if not (
                self.candidate_open_ms
                < self.first_stop_hit_ms
                <= self.actual_close_ms
            ):
                raise ValueError(
                    "stop hit must follow delayed open inside lifecycle"
                )
            mark_px = self.first_stop_mark_px
            if (
                mark_px is None
                or not mark_px.is_finite()
                or mark_px <= ZERO
            ):
                raise ValueError(
                    "stop hit mark must be positive and finite"
                )

    @property
    def stop_hit(self) -> bool:
        return self.first_stop_hit_ms is not None

    @property
    def time_to_stop_ms(self) -> int | None:
        if self.first_stop_hit_ms is None:
            return None
        return self.first_stop_hit_ms - self.candidate_open_ms


def _decimal(value: object, field: str) -> Decimal:
    try:
        resolved = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise DelayedEntryStopSurvivabilityError(
            f"{field} must be a decimal"
        ) from exc
    if not resolved.is_finite():
        raise DelayedEntryStopSurvivabilityError(
            f"{field} must be finite"
        )
    return resolved


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DelayedEntryStopSurvivabilityError(
            f"{field} must be an integer"
        )
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DelayedEntryStopSurvivabilityError(
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
            raise DelayedEntryStopSurvivabilityError(
                "duplicate exact trade path"
            )
        result[trade_id] = raw
    return result


def _validated_marks(
    trade: TradeJournalEntry,
    raw: Mapping[str, object],
) -> tuple[tuple[int, Decimal], ...]:
    expected = {
        "trade_id": trade.trade_id,
        "market": trade.market.canonical,
        "direction": trade.direction.value,
        "opened_at_ms": trade.opened_at_ms,
        "closed_at_ms": trade.closed_at_ms,
        "entry_price": str(trade.entry_price),
        "exit_price": str(trade.exit_price),
        "initial_stop": str(trade.initial_stop),
        "initial_risk_amount": str(trade.initial_risk_amount),
        "filled_quantity": str(trade.filled_quantity),
    }
    observed = {
        "trade_id": raw.get("trade_id"),
        "market": raw.get("market"),
        "direction": raw.get("direction"),
        "opened_at_ms": raw.get("opened_at_ms"),
        "closed_at_ms": raw.get("closed_at_ms"),
        "entry_price": raw.get("entry_price"),
        "exit_price": raw.get("exit_price"),
        "initial_stop": raw.get("initial_stop"),
        "initial_risk_amount": raw.get("initial_risk_amount"),
        "filled_quantity": raw.get("filled_quantity"),
    }
    if observed != expected:
        raise DelayedEntryStopSurvivabilityError(
            "trade path lineage does not match journal"
        )
    if raw.get("path_complete") is not True:
        raise DelayedEntryStopSurvivabilityError(
            "trade path is incomplete"
        )

    gaps = raw.get("known_gap_intervals")
    if not isinstance(gaps, list) or gaps:
        raise DelayedEntryStopSurvivabilityError(
            "stop survivability requires a gap-free trade path"
        )

    marks_raw = raw.get("marks")
    if not isinstance(marks_raw, list):
        raise DelayedEntryStopSurvivabilityError(
            "trade path marks must be an array"
        )

    marks: list[tuple[int, Decimal]] = []
    previous = trade.opened_at_ms
    for item in marks_raw:
        if not isinstance(item, Mapping):
            raise DelayedEntryStopSurvivabilityError(
                "trade path mark must be an object"
            )
        timestamp_ms = _integer(
            item.get("available_at_ms"),
            "available_at_ms",
        )
        mark_px = _decimal(item.get("mark_px"), "mark_px")
        if (
            timestamp_ms < trade.opened_at_ms
            or timestamp_ms > trade.closed_at_ms
            or timestamp_ms < previous
            or mark_px <= ZERO
        ):
            raise DelayedEntryStopSurvivabilityError(
                "trade path mark is invalid"
            )
        previous = timestamp_ms
        marks.append((timestamp_ms, mark_px))
    if not marks:
        raise DelayedEntryStopSurvivabilityError(
            "trade path has no observed marks"
        )
    return tuple(marks)


def _first_stop_hit(
    *,
    direction: str,
    stop_price: Decimal,
    candidate_open_ms: int,
    actual_close_ms: int,
    marks: Sequence[tuple[int, Decimal]],
) -> tuple[int, Decimal] | None:
    for timestamp_ms, mark_px in marks:
        if timestamp_ms <= candidate_open_ms:
            continue
        if timestamp_ms > actual_close_ms:
            break
        crossed = (
            mark_px <= stop_price
            if direction == "long"
            else mark_px >= stop_price
        )
        if crossed:
            return timestamp_ms, mark_px
    return None


def evaluate_delayed_entry_stop_outcome(
    trade: TradeJournalEntry,
    outcome: DelayedEntryOutcome,
    weighted: DelayedEntryFillWeightedOutcome,
    raw_path: Mapping[str, object],
    *,
    delay_ms: int = DELAY_MS,
) -> DelayedEntryStopOutcome | None:
    if delay_ms <= 0:
        raise ValueError("delay_ms must be positive")
    if weighted.trade_id != trade.trade_id:
        raise DelayedEntryStopSurvivabilityError(
            "fill-weighted outcome does not match journal trade"
        )
    if weighted.delayed_filled_quantity == ZERO:
        return None

    marks = _validated_marks(trade, raw_path)
    delayed_price = weighted.delayed_average_fill_price
    lag_ms = outcome.observation_lag_ms
    if (
        delayed_price is None
        or lag_ms is None
        or lag_ms < 0
    ):
        raise DelayedEntryStopSurvivabilityError(
            "filled delayed outcome is missing valid timing"
        )

    candidate_open_ms = (
        trade.opened_at_ms + delay_ms + lag_ms
    )
    if candidate_open_ms >= trade.closed_at_ms:
        raise DelayedEntryStopTimingError(
            "filled delayed outcome opens after trade close"
        )

    hit = _first_stop_hit(
        direction=trade.direction.value,
        stop_price=trade.initial_stop,
        candidate_open_ms=candidate_open_ms,
        actual_close_ms=trade.closed_at_ms,
        marks=marks,
    )
    return DelayedEntryStopOutcome(
        trade_id=trade.trade_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        source=outcome.source,
        candidate_open_ms=candidate_open_ms,
        actual_close_ms=trade.closed_at_ms,
        original_stop=trade.initial_stop,
        delayed_entry_price=delayed_price,
        delayed_filled_quantity=(
            weighted.delayed_filled_quantity
        ),
        first_stop_hit_ms=(
            None if hit is None else hit[0]
        ),
        first_stop_mark_px=(
            None if hit is None else hit[1]
        ),
    )


def _mean_int(values: Sequence[int]) -> int | None:
    if not values:
        return None
    return sum(values) // len(values)


def _median_int(values: Sequence[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) // 2


def _summary(
    items: Sequence[DelayedEntryStopOutcome],
) -> dict[str, object]:
    values = tuple(items)
    hit_times = [
        item.time_to_stop_ms
        for item in values
        if item.time_to_stop_ms is not None
    ]
    resolved_hit_times = [
        value for value in hit_times if value is not None
    ]
    return {
        "filled_candidates": len(values),
        "definite_original_stop_crossings": sum(
            1 for item in values if item.stop_hit
        ),
        "survived_observed_path_to_actual_close": sum(
            1 for item in values if not item.stop_hit
        ),
        "crossing_fraction": (
            None
            if not values
            else str(
                Decimal(
                    sum(1 for item in values if item.stop_hit)
                )
                / Decimal(len(values))
            )
        ),
        "mean_time_to_stop_ms": _mean_int(
            resolved_hit_times
        ),
        "median_time_to_stop_ms": _median_int(
            resolved_hit_times
        ),
        "min_time_to_stop_ms": (
            None
            if not resolved_hit_times
            else min(resolved_hit_times)
        ),
    }


def delayed_entry_stop_survivability(
    journal: JournalStore,
    outcomes: tuple[DelayedEntryOutcome, ...],
    path_store: ContinuousPaperTradePathStore,
    *,
    delay_ms: int = DELAY_MS,
) -> dict[str, object]:
    if delay_ms <= 0:
        raise ValueError("delay_ms must be positive")

    trades = tuple(journal.iter_trades())
    trade_by_id = {trade.trade_id: trade for trade in trades}
    if len(trade_by_id) != len(trades):
        raise DelayedEntryStopSurvivabilityError(
            "journal contains duplicate trade ids"
        )
    if len({outcome.trade_id for outcome in outcomes}) != len(
        outcomes
    ):
        raise DelayedEntryStopSurvivabilityError(
            "delayed shadow contains duplicate trade ids"
        )

    paths = _path_map(path_store)
    evaluated: list[DelayedEntryStopOutcome] = []
    unresolved_outcomes = 0
    candidate_no_fill = 0
    missing_journal = 0
    missing_paths = 0
    incomplete_or_gapped_paths = 0
    lineage_mismatches = 0
    invalid_candidate_timing = 0

    for outcome in outcomes:
        if outcome.source not in EVALUABLE_SOURCES:
            unresolved_outcomes += 1
            continue
        trade = trade_by_id.get(outcome.trade_id)
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
            stop_outcome = evaluate_delayed_entry_stop_outcome(
                trade,
                outcome,
                weighted,
                raw_path,
                delay_ms=delay_ms,
            )
        except DelayedEntryStopTimingError:
            invalid_candidate_timing += 1
            continue
        except (
            DelayedEntryStopSurvivabilityError,
            ValueError,
        ):
            lineage_mismatches += 1
            continue
        if stop_outcome is None:
            lineage_mismatches += 1
            continue
        evaluated.append(stop_outcome)

    values = tuple(evaluated)
    by_side = {
        side: _summary(
            tuple(
                item
                for item in values
                if item.direction == side
            )
        )
        for side in ("long", "short")
    }
    by_source = {
        source: _summary(
            tuple(
                item
                for item in values
                if item.source == source
            )
        )
        for source in (
            "full_visible_book_ioc",
            "partial_visible_book_ioc",
        )
    }

    ready = (
        len(outcomes) >= MIN_CLOSED_SHADOW_OUTCOMES
        and len(values) >= MIN_EVALUATED_FILLED_CANDIDATES
        and unresolved_outcomes == 0
        and missing_journal == 0
        and missing_paths == 0
        and incomplete_or_gapped_paths == 0
        and lineage_mismatches == 0
        and invalid_candidate_timing == 0
    )

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "claim_scope": (
            "delayed_entry_original_stop_survivability_only"
        ),
        "delay_ms": delay_ms,
        "mark_ordering_assumption": (
            "only_marks_strictly_after_delayed_open_are_causal"
        ),
        "stop_price_source": "immutable_closed_trade_initial_stop",
        "stop_fill_price_modeled": False,
        "full_exit_policy_modeled": False,
        "replacement_trades_modeled": False,
        "closed_shadow_outcomes": len(outcomes),
        "evaluated_filled_candidates": len(values),
        "candidate_no_fill_trades": candidate_no_fill,
        "unresolved_outcomes": unresolved_outcomes,
        "missing_journal_trades": missing_journal,
        "missing_exact_paths": missing_paths,
        "incomplete_or_gapped_paths": (
            incomplete_or_gapped_paths
        ),
        "lineage_mismatches": lineage_mismatches,
        "invalid_candidate_timing": invalid_candidate_timing,
        "overall": _summary(values),
        "by_side": by_side,
        "by_source": by_source,
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
                MIN_EVALUATED_FILLED_CANDIDATES - len(values),
            ),
        },
    }
