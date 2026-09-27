from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.strategy import Direction
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.journal.store import JournalStore
from cocomelon.research.continuous_paper_trade_paths import (
    ContinuousPaperTradePathStore,
)

ZERO: Final = Decimal("0")
EXCURSION_THRESHOLDS_R: Final = (
    Decimal("0.25"),
    Decimal("0.5"),
    Decimal("1"),
)
MIN_COMPLETE_PATHS_FOR_REVIEW: Final = 30


class ExcursionTimingError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ExcursionTimingTrade:
    trade_id: str
    market: str
    direction: str
    lead_strategy: str
    exit_reason: str
    holding_duration_ms: int
    time_to_mfe_ms: int
    time_to_mae_ms: int
    peak_to_close_ms: int
    peak_to_close_fraction_of_hold: Decimal
    final_net_r: Decimal
    threshold_first_hit_ms: tuple[tuple[Decimal, int | None], ...]

    def __post_init__(self) -> None:
        for identity in (
            self.trade_id,
            self.market,
            self.direction,
            self.lead_strategy,
            self.exit_reason,
        ):
            if not identity.strip():
                raise ValueError("excursion timing identity must not be empty")
        if self.direction not in {"long", "short"}:
            raise ValueError("direction must be long or short")
        if self.holding_duration_ms <= 0:
            raise ValueError("holding_duration_ms must be positive")
        for timing_ms in (
            self.time_to_mfe_ms,
            self.time_to_mae_ms,
            self.peak_to_close_ms,
        ):
            if timing_ms < 0 or timing_ms > self.holding_duration_ms:
                raise ValueError(
                    "excursion timing must remain inside lifecycle"
                )
        if (
            not self.peak_to_close_fraction_of_hold.is_finite()
            or self.peak_to_close_fraction_of_hold < ZERO
            or self.peak_to_close_fraction_of_hold > Decimal("1")
        ):
            raise ValueError(
                "peak_to_close_fraction_of_hold must be within [0,1]"
            )
        if not self.final_net_r.is_finite():
            raise ValueError("final_net_r must be finite")


def _decimal(value: object, field: str) -> Decimal:
    try:
        resolved = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ExcursionTimingError(
            f"{field} must be a decimal"
        ) from exc
    if not resolved.is_finite():
        raise ExcursionTimingError(f"{field} must be finite")
    return resolved


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ExcursionTimingError(f"{field} must be an integer")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExcursionTimingError(
            f"{field} must be a non-empty string"
        )
    return value


def _marks(
    raw: Mapping[str, object],
) -> tuple[tuple[int, Decimal], ...]:
    value = raw.get("marks")
    if not isinstance(value, list):
        raise ExcursionTimingError("trade path marks must be an array")
    output: list[tuple[int, Decimal]] = []
    previous: int | None = None
    for item in value:
        if not isinstance(item, dict):
            raise ExcursionTimingError(
                "trade path mark must be an object"
            )
        timestamp_ms = _integer(
            item.get("available_at_ms"),
            "available_at_ms",
        )
        mark_px = _decimal(item.get("mark_px"), "mark_px")
        if mark_px <= ZERO:
            raise ExcursionTimingError(
                "trade path mark_px must be positive"
            )
        if previous is not None and timestamp_ms < previous:
            raise ExcursionTimingError(
                "trade path marks must be ordered"
            )
        previous = timestamp_ms
        output.append((timestamp_ms, mark_px))
    return tuple(output)


def _verify_path_identity(
    raw: Mapping[str, object],
    trade: TradeJournalEntry,
) -> None:
    expected = {
        "trade_id": trade.trade_id,
        "market": trade.market.canonical,
        "direction": trade.direction.value,
        "opened_at_ms": trade.opened_at_ms,
        "closed_at_ms": trade.closed_at_ms,
        "entry_price": str(trade.entry_price),
        "initial_risk_amount": str(trade.initial_risk_amount),
        "filled_quantity": str(trade.filled_quantity),
    }
    actual = {
        "trade_id": raw.get("trade_id"),
        "market": raw.get("market"),
        "direction": raw.get("direction"),
        "opened_at_ms": raw.get("opened_at_ms"),
        "closed_at_ms": raw.get("closed_at_ms"),
        "entry_price": raw.get("entry_price"),
        "initial_risk_amount": raw.get("initial_risk_amount"),
        "filled_quantity": raw.get("filled_quantity"),
    }
    if actual != expected:
        raise ExcursionTimingError(
            "excursion timing trade-path identity mismatch"
        )


def _lead_strategy(
    trade: TradeJournalEntry,
    fact_store: EvaluationFactStore,
) -> str | None:
    if trade.replay_run_id is None:
        return None
    fact = fact_store.load_decision_by_strategy_id(
        trade.strategy_decision_id,
        trade.replay_run_id,
    )
    if fact is None:
        return None
    if (
        fact.market != trade.market
        or fact.direction is not trade.direction
        or fact.feature_snapshot_id != trade.feature_snapshot_id
    ):
        raise ExcursionTimingError(
            "excursion timing decision lineage mismatch"
        )
    return fact.lead_strategy


def _gross_r(
    trade: TradeJournalEntry,
    mark_px: Decimal,
) -> Decimal:
    if trade.initial_risk_amount <= ZERO:
        raise ExcursionTimingError(
            "initial_risk_amount must be positive"
        )
    signed_move = (
        mark_px - trade.entry_price
        if trade.direction is Direction.LONG
        else trade.entry_price - mark_px
    )
    return (
        signed_move
        * trade.filled_quantity
        / trade.initial_risk_amount
    )


def _first_hit_ms(
    trade: TradeJournalEntry,
    marks: Sequence[tuple[int, Decimal]],
    threshold_r: Decimal,
) -> int | None:
    for timestamp_ms, mark_px in marks:
        if _gross_r(trade, mark_px) >= threshold_r:
            return timestamp_ms - trade.opened_at_ms
    return None


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


def _threshold_summary(
    items: Sequence[ExcursionTimingTrade],
    threshold_r: Decimal,
) -> dict[str, object]:
    hits: list[tuple[ExcursionTimingTrade, int]] = []
    for item in items:
        value = dict(item.threshold_first_hit_ms)[threshold_r]
        if value is not None:
            hits.append((item, value))
    hit_times = [value for _, value in hits]
    losing_hits = [
        (item, value)
        for item, value in hits
        if item.final_net_r < ZERO
    ]
    losing_reach_to_close = [
        item.holding_duration_ms - value
        for item, value in losing_hits
    ]
    return {
        "threshold_r": str(threshold_r),
        "evaluated_trades": len(items),
        "reached": len(hits),
        "reach_fraction": (
            None
            if not items
            else str(Decimal(len(hits)) / Decimal(len(items)))
        ),
        "mean_first_hit_ms": _mean_int(hit_times),
        "median_first_hit_ms": _median_int(hit_times),
        "max_first_hit_ms": (
            None if not hit_times else max(hit_times)
        ),
        "losing_closes_after_reach": len(losing_hits),
        "mean_reach_to_close_ms_for_losers": _mean_int(
            losing_reach_to_close
        ),
    }


def _group_summary(
    items: Sequence[ExcursionTimingTrade],
) -> dict[str, object]:
    values = tuple(items)
    time_to_mfe = [item.time_to_mfe_ms for item in values]
    time_to_mae = [item.time_to_mae_ms for item in values]
    peak_to_close = [item.peak_to_close_ms for item in values]
    fractions = [
        item.peak_to_close_fraction_of_hold
        for item in values
    ]
    return {
        "trades": len(values),
        "wins": sum(
            1 for item in values if item.final_net_r > ZERO
        ),
        "losses": sum(
            1 for item in values if item.final_net_r < ZERO
        ),
        "mean_time_to_mfe_ms": _mean_int(time_to_mfe),
        "median_time_to_mfe_ms": _median_int(time_to_mfe),
        "mean_time_to_mae_ms": _mean_int(time_to_mae),
        "mean_peak_to_close_ms": _mean_int(peak_to_close),
        "median_peak_to_close_ms": _median_int(
            peak_to_close
        ),
        "mean_peak_to_close_fraction_of_hold": (
            None
            if not fractions
            else str(
                sum(fractions, ZERO)
                / Decimal(len(fractions))
            )
        ),
        "thresholds": {
            str(threshold): _threshold_summary(
                values,
                threshold,
            )
            for threshold in EXCURSION_THRESHOLDS_R
        },
    }


def _grouped(
    items: Sequence[ExcursionTimingTrade],
    field: str,
) -> dict[str, dict[str, object]]:
    groups: dict[str, list[ExcursionTimingTrade]] = {}
    for item in items:
        label = getattr(item, field)
        if not isinstance(label, str):
            raise ExcursionTimingError(
                "excursion timing grouping field must be string"
            )
        groups.setdefault(label, []).append(item)
    return {
        label: _group_summary(tuple(group))
        for label, group in sorted(groups.items())
    }


def excursion_timing_summary(
    journal: JournalStore,
    fact_store: EvaluationFactStore,
    path_store: ContinuousPaperTradePathStore,
) -> dict[str, object]:
    trades = tuple(journal.iter_trades())
    trade_by_id = {trade.trade_id: trade for trade in trades}
    if len(trade_by_id) != len(trades):
        raise ExcursionTimingError("duplicate journal trade id")

    path_payloads = path_store.iter_payloads()
    evaluated: list[ExcursionTimingTrade] = []
    incomplete_paths = 0
    missing_journal_trade = 0
    missing_decision_attribution = 0
    missing_excursion_metric = 0

    for raw in path_payloads:
        trade_id = _string(raw.get("trade_id"), "trade_id")
        trade = trade_by_id.get(trade_id)
        if trade is None:
            missing_journal_trade += 1
            continue
        _verify_path_identity(raw, trade)
        if raw.get("path_complete") is not True:
            incomplete_paths += 1
            continue
        if (
            trade.mfe is None
            or trade.mae is None
            or not trade.mfe.complete
            or not trade.mae.complete
        ):
            missing_excursion_metric += 1
            continue
        if not (
            trade.opened_at_ms
            <= trade.mfe.timestamp_ms
            <= trade.closed_at_ms
            and trade.opened_at_ms
            <= trade.mae.timestamp_ms
            <= trade.closed_at_ms
        ):
            raise ExcursionTimingError(
                "excursion timestamp is outside trade lifecycle"
            )

        lead_strategy = _lead_strategy(trade, fact_store)
        if lead_strategy is None:
            missing_decision_attribution += 1
            lead_strategy = "unknown"

        marks = _marks(raw)
        threshold_hits = tuple(
            (
                threshold,
                _first_hit_ms(
                    trade,
                    marks,
                    threshold,
                ),
            )
            for threshold in EXCURSION_THRESHOLDS_R
        )
        peak_to_close_ms = (
            trade.closed_at_ms - trade.mfe.timestamp_ms
        )
        evaluated.append(
            ExcursionTimingTrade(
                trade_id=trade.trade_id,
                market=trade.market.canonical,
                direction=trade.direction.value,
                lead_strategy=lead_strategy,
                exit_reason=trade.exit_reason,
                holding_duration_ms=trade.holding_duration_ms,
                time_to_mfe_ms=(
                    trade.mfe.timestamp_ms
                    - trade.opened_at_ms
                ),
                time_to_mae_ms=(
                    trade.mae.timestamp_ms
                    - trade.opened_at_ms
                ),
                peak_to_close_ms=peak_to_close_ms,
                peak_to_close_fraction_of_hold=(
                    Decimal(peak_to_close_ms)
                    / Decimal(trade.holding_duration_ms)
                ),
                final_net_r=trade.net_r,
                threshold_first_hit_ms=threshold_hits,
            )
        )

    ready = (
        len(evaluated) >= MIN_COMPLETE_PATHS_FOR_REVIEW
        and missing_journal_trade == 0
        and missing_decision_attribution == 0
        and missing_excursion_metric == 0
    )
    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "complete_paths_evaluated": len(evaluated),
        "incomplete_paths_skipped": incomplete_paths,
        "missing_journal_trade": missing_journal_trade,
        "missing_decision_attribution": (
            missing_decision_attribution
        ),
        "missing_excursion_metric": (
            missing_excursion_metric
        ),
        "evidence_gate": {
            "min_complete_paths": (
                MIN_COMPLETE_PATHS_FOR_REVIEW
            ),
            "missing_complete_paths": max(
                0,
                MIN_COMPLETE_PATHS_FOR_REVIEW
                - len(evaluated),
            ),
            "ready_for_review": ready,
        },
        "overall": _group_summary(tuple(evaluated)),
        "by_side": _grouped(tuple(evaluated), "direction"),
        "by_lead_strategy": _grouped(
            tuple(evaluated),
            "lead_strategy",
        ),
        "by_exit_reason": _grouped(
            tuple(evaluated),
            "exit_reason",
        ),
    }
