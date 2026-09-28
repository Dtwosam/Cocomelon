from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
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

ZERO: Final = Decimal("0")
MIN_CLOSED_SHADOW_OUTCOMES: Final = 30
MIN_EVALUATED_MTM_TRADES: Final = 20
MIN_ACTUAL_OVERLAP_OPENINGS: Final = 5


class DelayedEntryMtmPortfolioError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _PositionPath:
    trade_id: str
    direction: str
    open_ms: int
    close_ms: int
    entry_price: Decimal
    quantity: Decimal
    entry_fee: Decimal
    close_realized_increment: Decimal
    marks: tuple[tuple[int, Decimal], ...]

    def __post_init__(self) -> None:
        if not self.trade_id.strip():
            raise ValueError("trade_id must not be empty")
        if self.direction not in {"long", "short"}:
            raise ValueError("direction must be long or short")
        if self.open_ms < 0 or self.close_ms <= self.open_ms:
            raise ValueError("position timestamps are invalid")
        if (
            not self.entry_price.is_finite()
            or self.entry_price <= ZERO
            or not self.quantity.is_finite()
            or self.quantity <= ZERO
        ):
            raise ValueError("position price/quantity must be positive")
        if not self.entry_fee.is_finite() or self.entry_fee < ZERO:
            raise ValueError("entry_fee must be non-negative")
        if not self.close_realized_increment.is_finite():
            raise ValueError("close increment must be finite")
        previous = self.open_ms
        for timestamp_ms, mark_px in self.marks:
            if not self.open_ms <= timestamp_ms <= self.close_ms:
                raise ValueError("mark is outside position lifetime")
            if timestamp_ms < previous:
                raise ValueError("marks must be ordered")
            if not mark_px.is_finite() or mark_px <= ZERO:
                raise ValueError("mark price must be positive")
            previous = timestamp_ms


@dataclass(frozen=True, slots=True)
class _Event:
    timestamp_ms: int
    order: int
    kind: str
    trade_id: str
    position: _PositionPath | None = None
    mark_px: Decimal | None = None

    def __post_init__(self) -> None:
        if self.timestamp_ms < 0:
            raise ValueError("event timestamp must be non-negative")
        if self.kind not in {"open", "mark", "close"}:
            raise ValueError("unsupported event kind")
        if not self.trade_id.strip():
            raise ValueError("event trade_id must not be empty")
        if self.kind == "open" and self.position is None:
            raise ValueError("open event requires position")
        if self.kind == "mark" and self.mark_px is None:
            raise ValueError("mark event requires mark_px")


@dataclass(slots=True)
class _Active:
    position: _PositionPath
    latest_mark: Decimal
    latest_mark_ms: int


def _decimal(value: object, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (ValueError, ArithmeticError) as exc:
        raise DelayedEntryMtmPortfolioError(
            f"{field} must be a decimal"
        ) from exc
    if not result.is_finite():
        raise DelayedEntryMtmPortfolioError(
            f"{field} must be finite"
        )
    return result


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DelayedEntryMtmPortfolioError(
            f"{field} must be an integer"
        )
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DelayedEntryMtmPortfolioError(
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
            raise DelayedEntryMtmPortfolioError(
                "duplicate exact trade path"
            )
        result[trade_id] = raw
    return result


def _validate_path(
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
        "initial_risk_amount": raw.get("initial_risk_amount"),
        "filled_quantity": raw.get("filled_quantity"),
    }
    if observed != expected:
        raise DelayedEntryMtmPortfolioError(
            "trade path lineage does not match journal"
        )
    marks_raw = raw.get("marks")
    if not isinstance(marks_raw, list):
        raise DelayedEntryMtmPortfolioError(
            "trade path marks must be an array"
        )
    marks: list[tuple[int, Decimal]] = []
    previous = trade.opened_at_ms
    for item in marks_raw:
        if not isinstance(item, Mapping):
            raise DelayedEntryMtmPortfolioError(
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
            raise DelayedEntryMtmPortfolioError(
                "trade path mark is invalid"
            )
        previous = timestamp_ms
        marks.append((timestamp_ms, mark_px))
    return tuple(marks)


def _events(
    positions: tuple[_PositionPath, ...],
) -> tuple[_Event, ...]:
    events: list[_Event] = []
    for position in positions:
        events.append(
            _Event(
                timestamp_ms=position.open_ms,
                order=1,
                kind="open",
                trade_id=position.trade_id,
                position=position,
            )
        )
        for timestamp_ms, mark_px in position.marks:
            if timestamp_ms < position.open_ms:
                continue
            events.append(
                _Event(
                    timestamp_ms=timestamp_ms,
                    order=2,
                    kind="mark",
                    trade_id=position.trade_id,
                    mark_px=mark_px,
                )
            )
        events.append(
            _Event(
                timestamp_ms=position.close_ms,
                order=0,
                kind="close",
                trade_id=position.trade_id,
            )
        )
    return tuple(
        sorted(
            events,
            key=lambda item: (
                item.timestamp_ms,
                item.order,
                item.trade_id,
            ),
        )
    )


def _signed_unrealized(active: _Active) -> Decimal:
    position = active.position
    move = (
        active.latest_mark - position.entry_price
        if position.direction == "long"
        else position.entry_price - active.latest_mark
    )
    return move * position.quantity


def _timeline(
    positions: tuple[_PositionPath, ...],
) -> dict[str, object]:
    if not positions:
        return {
            "final_realized_contribution": "0",
            "max_observed_equity_drawdown": "0",
            "min_observed_equity_contribution": "0",
            "max_observed_equity_contribution": "0",
            "max_concurrent_positions": 0,
            "overlap_openings": 0,
            "observation_events": 0,
            "max_mark_carry_age_ms": 0,
        }

    active: dict[str, _Active] = {}
    realized = ZERO
    peak = ZERO
    min_equity = ZERO
    max_equity = ZERO
    max_drawdown = ZERO
    max_positions = 0
    overlap_openings = 0
    max_mark_carry_age_ms = 0
    observations = 0

    for event in _events(positions):
        if event.kind == "close":
            item = active.pop(event.trade_id, None)
            if item is None:
                raise DelayedEntryMtmPortfolioError(
                    "close event has no active position"
                )
            realized += item.position.close_realized_increment
        elif event.kind == "open":
            position = event.position
            if position is None:
                raise DelayedEntryMtmPortfolioError(
                    "open event is missing position"
                )
            if event.trade_id in active:
                raise DelayedEntryMtmPortfolioError(
                    "position opened twice"
                )
            if active:
                overlap_openings += 1
            realized -= position.entry_fee
            active[event.trade_id] = _Active(
                position=position,
                latest_mark=position.entry_price,
                latest_mark_ms=position.open_ms,
            )
        else:
            item = active.get(event.trade_id)
            if item is None:
                continue
            mark_px = event.mark_px
            if mark_px is None:
                raise DelayedEntryMtmPortfolioError(
                    "mark event is missing price"
                )
            item.latest_mark = mark_px
            item.latest_mark_ms = event.timestamp_ms

        unrealized = sum(
            (_signed_unrealized(item) for item in active.values()),
            ZERO,
        )
        equity = realized + unrealized
        peak = max(peak, equity)
        min_equity = min(min_equity, equity)
        max_equity = max(max_equity, equity)
        max_drawdown = max(max_drawdown, peak - equity)
        max_positions = max(max_positions, len(active))
        if active:
            max_mark_carry_age_ms = max(
                max_mark_carry_age_ms,
                max(
                    event.timestamp_ms - item.latest_mark_ms
                    for item in active.values()
                ),
            )
        observations += 1

    if active:
        raise DelayedEntryMtmPortfolioError(
            "portfolio timeline did not finish flat"
        )
    return {
        "final_realized_contribution": str(realized),
        "max_observed_equity_drawdown": str(max_drawdown),
        "min_observed_equity_contribution": str(min_equity),
        "max_observed_equity_contribution": str(max_equity),
        "max_concurrent_positions": max_positions,
        "overlap_openings": overlap_openings,
        "observation_events": observations,
        "max_mark_carry_age_ms": max_mark_carry_age_ms,
    }


def delayed_entry_mtm_portfolio(
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
        raise DelayedEntryMtmPortfolioError(
            "journal contains duplicate trade ids"
        )
    if len({outcome.trade_id for outcome in outcomes}) != len(outcomes):
        raise DelayedEntryMtmPortfolioError(
            "delayed shadow contains duplicate trade ids"
        )
    paths = _path_map(path_store)

    actual_positions: list[_PositionPath] = []
    candidate_positions: list[_PositionPath] = []
    unresolved_outcomes = 0
    missing_journal = 0
    missing_paths = 0
    incomplete_paths = 0
    lineage_mismatches = 0
    candidate_no_fill = 0

    for outcome in outcomes:
        if outcome.source not in EVALUABLE_SOURCES:
            unresolved_outcomes += 1
            continue
        trade = trade_by_id.get(outcome.trade_id)
        if trade is None:
            missing_journal += 1
            continue
        raw_path = paths.get(trade.trade_id)
        if raw_path is None:
            missing_paths += 1
            continue
        if raw_path.get("path_complete") is not True:
            incomplete_paths += 1
            continue

        try:
            marks = _validate_path(trade, raw_path)
            weighted = evaluate_delayed_entry_fill_weighted_outcome(
                trade,
                outcome,
            )
        except (
            DelayedEntryMtmPortfolioError,
            DelayedEntryFillWeightedError,
        ):
            lineage_mismatches += 1
            continue

        actual_positions.append(
            _PositionPath(
                trade_id=trade.trade_id,
                direction=trade.direction.value,
                open_ms=trade.opened_at_ms,
                close_ms=trade.closed_at_ms,
                entry_price=trade.entry_price,
                quantity=trade.filled_quantity,
                entry_fee=trade.entry_fees,
                close_realized_increment=(
                    trade.net_pnl + trade.entry_fees
                ),
                marks=marks,
            )
        )

        if weighted.delayed_filled_quantity == ZERO:
            candidate_no_fill += 1
            continue
        delayed_price = weighted.delayed_average_fill_price
        lag_ms = outcome.observation_lag_ms
        if (
            delayed_price is None
            or lag_ms is None
            or lag_ms < 0
        ):
            lineage_mismatches += 1
            actual_positions.pop()
            continue
        candidate_open_ms = (
            trade.opened_at_ms + delay_ms + lag_ms
        )
        if candidate_open_ms >= trade.closed_at_ms:
            lineage_mismatches += 1
            actual_positions.pop()
            continue

        candidate_positions.append(
            _PositionPath(
                trade_id=trade.trade_id,
                direction=trade.direction.value,
                open_ms=candidate_open_ms,
                close_ms=trade.closed_at_ms,
                entry_price=delayed_price,
                quantity=weighted.delayed_filled_quantity,
                entry_fee=weighted.delayed_entry_fee,
                close_realized_increment=(
                    weighted.candidate_net_pnl_estimate
                    + weighted.delayed_entry_fee
                ),
                marks=marks,
            )
        )

    actual_tuple = tuple(actual_positions)
    candidate_tuple = tuple(candidate_positions)
    actual = _timeline(actual_tuple)
    candidate = _timeline(candidate_tuple)

    actual_final = Decimal(
        str(actual["final_realized_contribution"])
    )
    candidate_final = Decimal(
        str(candidate["final_realized_contribution"])
    )
    actual_drawdown = Decimal(
        str(actual["max_observed_equity_drawdown"])
    )
    candidate_drawdown = Decimal(
        str(candidate["max_observed_equity_drawdown"])
    )
    actual_overlap = actual["overlap_openings"]
    if isinstance(actual_overlap, bool) or not isinstance(
        actual_overlap,
        int,
    ):
        raise DelayedEntryMtmPortfolioError(
            "actual overlap count must be an integer"
        )

    ready = (
        len(outcomes) >= MIN_CLOSED_SHADOW_OUTCOMES
        and len(actual_tuple) >= MIN_EVALUATED_MTM_TRADES
        and actual_overlap >= MIN_ACTUAL_OVERLAP_OPENINGS
        and unresolved_outcomes == 0
        and missing_journal == 0
        and missing_paths == 0
        and incomplete_paths == 0
        and lineage_mismatches == 0
    )

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "claim_scope": (
            "fixed_observed_schedule_mark_to_market_contribution_only"
        ),
        "delay_ms": delay_ms,
        "mark_model": (
            "latest_observed_exact_path_mark_carried_forward"
        ),
        "entry_fee_timing_modeled": True,
        "exit_fee_and_funding_settled_at_actual_close": True,
        "intratrade_funding_timing_modeled": False,
        "replacement_trades_modeled": False,
        "changed_exit_timing_modeled": False,
        "closed_shadow_outcomes": len(outcomes),
        "evaluated_complete_path_trades": len(actual_tuple),
        "candidate_filled_positions": len(candidate_tuple),
        "candidate_no_fill_trades": candidate_no_fill,
        "unresolved_outcomes": unresolved_outcomes,
        "missing_journal_trades": missing_journal,
        "missing_exact_paths": missing_paths,
        "incomplete_exact_paths": incomplete_paths,
        "lineage_mismatches": lineage_mismatches,
        "actual": actual,
        "candidate": candidate,
        "delta_final_realized_contribution": str(
            candidate_final - actual_final
        ),
        "delta_max_observed_equity_drawdown": str(
            candidate_drawdown - actual_drawdown
        ),
        "readiness": {
            "ready_for_review": ready,
            "min_closed_shadow_outcomes": (
                MIN_CLOSED_SHADOW_OUTCOMES
            ),
            "min_evaluated_complete_path_trades": (
                MIN_EVALUATED_MTM_TRADES
            ),
            "min_actual_overlap_openings": (
                MIN_ACTUAL_OVERLAP_OPENINGS
            ),
            "missing_closed_shadow_outcomes": max(
                0,
                MIN_CLOSED_SHADOW_OUTCOMES - len(outcomes),
            ),
            "missing_evaluated_complete_path_trades": max(
                0,
                MIN_EVALUATED_MTM_TRADES - len(actual_tuple),
            ),
            "missing_actual_overlap_openings": max(
                0,
                MIN_ACTUAL_OVERLAP_OPENINGS - actual_overlap,
            ),
        },
    }
