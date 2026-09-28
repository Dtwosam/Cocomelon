from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Final

from cocomelon.domain.execution import OrderSide, PaperOrderPlan
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.risk import RiskLimits
from cocomelon.domain.strategy import Direction
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
ONE: Final = Decimal("1")
MIN_CLOSED_SHADOW_OUTCOMES: Final = 30
MIN_CANDIDATE_FILLED_POSITIONS: Final = 20
MIN_CANDIDATE_OVERLAP_OPENINGS: Final = 5


class DelayedEntryCapacityOverlayError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _Position:
    trade_id: str
    market: str
    direction: str
    open_ms: int
    close_ms: int
    entry_price: Decimal
    quantity: Decimal
    planned_risk: Decimal
    entry_fee: Decimal
    close_realized_increment: Decimal
    marks: tuple[tuple[int, Decimal], ...]
    opening_kind: str

    def __post_init__(self) -> None:
        for value in (
            self.trade_id,
            self.market,
            self.direction,
            self.opening_kind,
        ):
            if not value.strip():
                raise ValueError("position identity must not be empty")
        if self.direction not in {"long", "short"}:
            raise ValueError("direction must be long or short")
        if self.open_ms < 0 or self.close_ms <= self.open_ms:
            raise ValueError("position timestamps are invalid")
        for value, field in (
            (self.entry_price, "entry_price"),
            (self.quantity, "quantity"),
            (self.planned_risk, "planned_risk"),
        ):
            if not value.is_finite() or value <= ZERO:
                raise ValueError(f"{field} must be positive and finite")
        if not self.entry_fee.is_finite() or self.entry_fee < ZERO:
            raise ValueError("entry_fee must be non-negative")
        if not self.close_realized_increment.is_finite():
            raise ValueError("close increment must be finite")


@dataclass(frozen=True, slots=True)
class _Event:
    timestamp_ms: int
    order: int
    kind: str
    trade_id: str
    position: _Position | None = None
    mark_px: Decimal | None = None

    def __post_init__(self) -> None:
        if self.timestamp_ms < 0:
            raise ValueError("event timestamp must be non-negative")
        if self.kind not in {"close", "mark", "open"}:
            raise ValueError("unsupported event kind")
        if not self.trade_id.strip():
            raise ValueError("event trade_id must not be empty")
        if self.kind == "open" and self.position is None:
            raise ValueError("open event requires a position")
        if self.kind == "mark" and self.mark_px is None:
            raise ValueError("mark event requires mark_px")


@dataclass(slots=True)
class _Active:
    position: _Position
    latest_mark: Decimal


def _decimal(value: object, field: str) -> Decimal:
    try:
        resolved = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise DelayedEntryCapacityOverlayError(
            f"{field} must be a decimal"
        ) from exc
    if not resolved.is_finite():
        raise DelayedEntryCapacityOverlayError(
            f"{field} must be finite"
        )
    return resolved


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DelayedEntryCapacityOverlayError(
            f"{field} must be an integer"
        )
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DelayedEntryCapacityOverlayError(
            f"{field} must be a non-empty string"
        )
    return value


def _risk_per_quantity(
    plan: PaperOrderPlan,
    price: Decimal,
) -> Decimal:
    if plan.stop_price is None:
        raise DelayedEntryCapacityOverlayError(
            "opening plan is missing stop price"
        )
    cost_buffer = plan.cost_buffer_fraction
    if cost_buffer is None:
        raise DelayedEntryCapacityOverlayError(
            "opening plan is missing cost buffer"
        )
    if plan.side is OrderSide.BUY:
        value = (
            price * (ONE + cost_buffer)
            - plan.stop_price
        )
    else:
        value = (
            plan.stop_price
            - price * (ONE - cost_buffer)
        )
    if not value.is_finite() or value <= ZERO:
        raise DelayedEntryCapacityOverlayError(
            "opening plan has invalid per-unit risk"
        )
    return value


def _validate_plan(
    trade: TradeJournalEntry,
    plan: PaperOrderPlan,
) -> None:
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
        raise DelayedEntryCapacityOverlayError(
            "opening plan lineage is invalid"
        )


def _path_map(
    store: ContinuousPaperTradePathStore,
) -> dict[str, Mapping[str, object]]:
    result: dict[str, Mapping[str, object]] = {}
    for raw in store.iter_payloads():
        trade_id = _string(raw.get("trade_id"), "trade_id")
        if trade_id in result:
            raise DelayedEntryCapacityOverlayError(
                "duplicate exact trade path"
            )
        result[trade_id] = raw
    return result


def _marks(
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
        raise DelayedEntryCapacityOverlayError(
            "trade path lineage does not match journal"
        )
    marks_raw = raw.get("marks")
    if not isinstance(marks_raw, list):
        raise DelayedEntryCapacityOverlayError(
            "trade path marks must be an array"
        )
    output: list[tuple[int, Decimal]] = []
    previous = trade.opened_at_ms
    for item in marks_raw:
        if not isinstance(item, Mapping):
            raise DelayedEntryCapacityOverlayError(
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
            raise DelayedEntryCapacityOverlayError(
                "trade path mark is invalid"
            )
        previous = timestamp_ms
        output.append((timestamp_ms, mark_px))
    return tuple(output)


def _position_events(
    positions: tuple[_Position, ...],
) -> tuple[_Event, ...]:
    events: list[_Event] = []
    for position in positions:
        events.append(
            _Event(
                timestamp_ms=position.open_ms,
                order=2,
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
                    order=1,
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


def _unrealized(active: _Active) -> Decimal:
    position = active.position
    move = (
        active.latest_mark - position.entry_price
        if position.direction == "long"
        else position.entry_price - active.latest_mark
    )
    return move * position.quantity


def _gross_notional(active: _Active) -> Decimal:
    return active.latest_mark * active.position.quantity


def _capacity_timeline(
    positions: tuple[_Position, ...],
    *,
    reference_equity: Decimal,
    limits: RiskLimits,
) -> dict[str, object]:
    if not reference_equity.is_finite() or reference_equity <= ZERO:
        raise DelayedEntryCapacityOverlayError(
            "reference equity must be positive"
        )

    active: dict[str, _Active] = {}
    realized = ZERO
    opening_checks = 0
    overlap_openings = 0
    violations = 0
    delayed_opening_violations = 0
    background_opening_violations = 0
    aggregate_risk_violations = 0
    bucket_risk_violations = 0
    gross_leverage_violations = 0
    non_positive_equity = 0
    max_aggregate_risk_utilization = ZERO
    max_bucket_risk_utilization = ZERO
    max_gross_leverage = ZERO
    min_aggregate_risk_headroom: Decimal | None = None
    min_bucket_risk_headroom: Decimal | None = None
    min_gross_notional_headroom: Decimal | None = None

    for event in _position_events(positions):
        if event.kind == "close":
            item = active.pop(event.trade_id, None)
            if item is None:
                raise DelayedEntryCapacityOverlayError(
                    "close event has no active position"
                )
            realized += item.position.close_realized_increment
            continue

        if event.kind == "mark":
            item = active.get(event.trade_id)
            if item is None:
                continue
            mark_px = event.mark_px
            if mark_px is None:
                raise DelayedEntryCapacityOverlayError(
                    "mark event is missing price"
                )
            item.latest_mark = mark_px
            continue

        position = event.position
        if position is None:
            raise DelayedEntryCapacityOverlayError(
                "open event is missing position"
            )
        unrealized = sum(
            (_unrealized(item) for item in active.values()),
            ZERO,
        )
        equity = reference_equity + realized + unrealized
        opening_checks += 1
        if active:
            overlap_openings += 1

        existing_risk = sum(
            (
                item.position.planned_risk
                for item in active.values()
            ),
            ZERO,
        )
        existing_notional = sum(
            (_gross_notional(item) for item in active.values()),
            ZERO,
        )
        new_notional = position.entry_price * position.quantity
        after_risk = existing_risk + position.planned_risk
        after_notional = existing_notional + new_notional

        if equity <= ZERO:
            non_positive_equity += 1
            violated = True
            aggregate_bad = True
            bucket_bad = True
            gross_bad = True
            aggregate_headroom = -after_risk
            bucket_headroom = -after_risk
            gross_headroom = -after_notional
        else:
            aggregate_ceiling = equity * limits.max_open_risk
            bucket_ceiling = (
                equity * limits.correlation_bucket_risk_limit
            )
            gross_ceiling = equity * limits.max_gross_leverage
            aggregate_headroom = aggregate_ceiling - after_risk
            bucket_headroom = bucket_ceiling - after_risk
            gross_headroom = gross_ceiling - after_notional
            aggregate_bad = aggregate_headroom < ZERO
            bucket_bad = bucket_headroom < ZERO
            gross_bad = gross_headroom < ZERO
            violated = aggregate_bad or bucket_bad or gross_bad
            max_aggregate_risk_utilization = max(
                max_aggregate_risk_utilization,
                after_risk / aggregate_ceiling,
            )
            max_bucket_risk_utilization = max(
                max_bucket_risk_utilization,
                after_risk / bucket_ceiling,
            )
            max_gross_leverage = max(
                max_gross_leverage,
                after_notional / equity,
            )

        min_aggregate_risk_headroom = (
            aggregate_headroom
            if min_aggregate_risk_headroom is None
            else min(
                min_aggregate_risk_headroom,
                aggregate_headroom,
            )
        )
        min_bucket_risk_headroom = (
            bucket_headroom
            if min_bucket_risk_headroom is None
            else min(
                min_bucket_risk_headroom,
                bucket_headroom,
            )
        )
        min_gross_notional_headroom = (
            gross_headroom
            if min_gross_notional_headroom is None
            else min(
                min_gross_notional_headroom,
                gross_headroom,
            )
        )

        if violated:
            violations += 1
            if position.opening_kind == "delayed_candidate":
                delayed_opening_violations += 1
            else:
                background_opening_violations += 1
        if aggregate_bad:
            aggregate_risk_violations += 1
        if bucket_bad:
            bucket_risk_violations += 1
        if gross_bad:
            gross_leverage_violations += 1

        realized -= position.entry_fee
        active[event.trade_id] = _Active(
            position=position,
            latest_mark=position.entry_price,
        )

    if active:
        raise DelayedEntryCapacityOverlayError(
            "capacity timeline did not finish flat"
        )

    return {
        "opening_checks": opening_checks,
        "overlap_openings": overlap_openings,
        "capacity_violations": violations,
        "delayed_opening_violations": delayed_opening_violations,
        "background_opening_violations": (
            background_opening_violations
        ),
        "aggregate_risk_violations": aggregate_risk_violations,
        "correlation_bucket_risk_violations": (
            bucket_risk_violations
        ),
        "gross_leverage_violations": gross_leverage_violations,
        "non_positive_equity_events": non_positive_equity,
        "max_aggregate_risk_utilization": str(
            max_aggregate_risk_utilization
        ),
        "max_correlation_bucket_risk_utilization": str(
            max_bucket_risk_utilization
        ),
        "max_gross_leverage": str(max_gross_leverage),
        "min_aggregate_risk_headroom": str(
            ZERO
            if min_aggregate_risk_headroom is None
            else min_aggregate_risk_headroom
        ),
        "min_correlation_bucket_risk_headroom": str(
            ZERO
            if min_bucket_risk_headroom is None
            else min_bucket_risk_headroom
        ),
        "min_gross_notional_headroom": str(
            ZERO
            if min_gross_notional_headroom is None
            else min_gross_notional_headroom
        ),
    }


def _actual_position(
    trade: TradeJournalEntry,
    marks: tuple[tuple[int, Decimal], ...],
) -> _Position:
    return _Position(
        trade_id=trade.trade_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        open_ms=trade.opened_at_ms,
        close_ms=trade.closed_at_ms,
        entry_price=trade.entry_price,
        quantity=trade.filled_quantity,
        planned_risk=trade.initial_risk_amount,
        entry_fee=trade.entry_fees,
        close_realized_increment=(
            trade.net_pnl + trade.entry_fees
        ),
        marks=marks,
        opening_kind="observed",
    )


def delayed_entry_portfolio_capacity_overlay(
    journal: JournalStore,
    outcomes: tuple[DelayedEntryOutcome, ...],
    path_store: ContinuousPaperTradePathStore,
    plan_loader: Callable[[str], PaperOrderPlan | None],
    *,
    limits: RiskLimits,
    delay_ms: int = DELAY_MS,
) -> dict[str, object]:
    if delay_ms <= 0:
        raise ValueError("delay_ms must be positive")

    trades = tuple(journal.iter_trades())
    trades_by_id = {trade.trade_id: trade for trade in trades}
    if len(trades_by_id) != len(trades):
        raise DelayedEntryCapacityOverlayError(
            "journal contains duplicate trade ids"
        )
    if len({outcome.trade_id for outcome in outcomes}) != len(
        outcomes
    ):
        raise DelayedEntryCapacityOverlayError(
            "delayed outcomes contain duplicate trade ids"
        )

    path_by_id = _path_map(path_store)
    cohort_ids = {outcome.trade_id for outcome in outcomes}
    cohort_trades = tuple(
        trade
        for trade in trades
        if trade.trade_id in cohort_ids
    )
    if not cohort_trades:
        return {
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "claim_scope": (
                "fixed_observed_schedule_portfolio_capacity_overlay"
            ),
            "delay_ms": delay_ms,
            "closed_shadow_outcomes": len(outcomes),
            "candidate_filled_positions": 0,
            "background_positions": 0,
            "unresolved_outcomes": len(outcomes),
            "missing_journal_trades": 0,
            "missing_opening_plans": 0,
            "missing_exact_paths": 0,
            "incomplete_exact_paths": 0,
            "lineage_mismatches": 0,
            "actual": _capacity_timeline(
                (),
                reference_equity=Decimal("1"),
                limits=limits,
            ),
            "candidate": _capacity_timeline(
                (),
                reference_equity=Decimal("1"),
                limits=limits,
            ),
            "readiness": {
                "ready_for_review": False,
                "min_closed_shadow_outcomes": (
                    MIN_CLOSED_SHADOW_OUTCOMES
                ),
                "min_candidate_filled_positions": (
                    MIN_CANDIDATE_FILLED_POSITIONS
                ),
                "min_candidate_overlap_openings": (
                    MIN_CANDIDATE_OVERLAP_OPENINGS
                ),
                "missing_closed_shadow_outcomes": max(
                    0,
                    MIN_CLOSED_SHADOW_OUTCOMES - len(outcomes),
                ),
                "missing_candidate_filled_positions": (
                    MIN_CANDIDATE_FILLED_POSITIONS
                ),
                "missing_candidate_overlap_openings": (
                    MIN_CANDIDATE_OVERLAP_OPENINGS
                ),
            },
        }

    cohort_start = min(
        trade.opened_at_ms for trade in cohort_trades
    )
    cohort_end = max(
        trade.closed_at_ms for trade in cohort_trades
    )
    relevant_trades = tuple(
        trade
        for trade in trades
        if (
            trade.closed_at_ms >= cohort_start
            and trade.opened_at_ms <= cohort_end
        )
    )
    earliest = min(
        relevant_trades,
        key=lambda trade: (
            trade.opened_at_ms,
            trade.trade_id,
        ),
    )
    reference_equity = earliest.equity_before

    exact_marks: dict[str, tuple[tuple[int, Decimal], ...]] = {}
    missing_paths = 0
    incomplete_paths = 0
    for trade in relevant_trades:
        raw = path_by_id.get(trade.trade_id)
        if raw is None:
            missing_paths += 1
            continue
        if raw.get("path_complete") is not True:
            incomplete_paths += 1
            continue
        try:
            exact_marks[trade.trade_id] = _marks(trade, raw)
        except DelayedEntryCapacityOverlayError:
            incomplete_paths += 1

    actual_positions: list[_Position] = []
    for trade in relevant_trades:
        marks = exact_marks.get(trade.trade_id)
        if marks is None:
            continue
        actual_positions.append(_actual_position(trade, marks))

    candidate_positions: list[_Position] = []
    background_positions = 0
    missing_journal = 0
    missing_plan = 0
    lineage_mismatches = 0
    unresolved_outcomes = 0
    candidate_filled = 0
    candidate_no_fill = 0

    outcome_by_id = {
        outcome.trade_id: outcome for outcome in outcomes
    }
    for trade in relevant_trades:
        marks = exact_marks.get(trade.trade_id)
        if marks is None:
            continue
        outcome = outcome_by_id.get(trade.trade_id)
        if outcome is None:
            candidate_positions.append(
                _actual_position(trade, marks)
            )
            background_positions += 1
            continue
        if outcome.source not in EVALUABLE_SOURCES:
            unresolved_outcomes += 1
            continue
        if (
            outcome.opening_plan_id != trade.opening_plan_id
            or outcome.market != trade.market.canonical
            or outcome.direction != trade.direction.value
        ):
            lineage_mismatches += 1
            continue
        plan = plan_loader(outcome.opening_plan_id)
        if plan is None:
            missing_plan += 1
            continue
        try:
            _validate_plan(trade, plan)
            weighted = evaluate_delayed_entry_fill_weighted_outcome(
                trade,
                outcome,
            )
        except (
            DelayedEntryCapacityOverlayError,
            DelayedEntryFillWeightedError,
        ):
            lineage_mismatches += 1
            continue

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
            continue
        open_ms = trade.opened_at_ms + delay_ms + lag_ms
        if open_ms >= trade.closed_at_ms:
            lineage_mismatches += 1
            continue
        planned_risk = (
            _risk_per_quantity(plan, delayed_price)
            * weighted.delayed_filled_quantity
        )
        candidate_positions.append(
            _Position(
                trade_id=trade.trade_id,
                market=trade.market.canonical,
                direction=trade.direction.value,
                open_ms=open_ms,
                close_ms=trade.closed_at_ms,
                entry_price=delayed_price,
                quantity=weighted.delayed_filled_quantity,
                planned_risk=planned_risk,
                entry_fee=weighted.delayed_entry_fee,
                close_realized_increment=(
                    weighted.candidate_net_pnl_estimate
                    + weighted.delayed_entry_fee
                ),
                marks=marks,
                opening_kind="delayed_candidate",
            )
        )
        candidate_filled += 1

    for outcome in outcomes:
        if outcome.trade_id not in trades_by_id:
            missing_journal += 1

    actual = _capacity_timeline(
        tuple(actual_positions),
        reference_equity=reference_equity,
        limits=limits,
    )
    candidate = _capacity_timeline(
        tuple(candidate_positions),
        reference_equity=reference_equity,
        limits=limits,
    )

    actual_violations = int(actual["capacity_violations"])
    candidate_overlap = int(candidate["overlap_openings"])
    ready = (
        len(outcomes) >= MIN_CLOSED_SHADOW_OUTCOMES
        and candidate_filled >= MIN_CANDIDATE_FILLED_POSITIONS
        and candidate_overlap >= MIN_CANDIDATE_OVERLAP_OPENINGS
        and unresolved_outcomes == 0
        and missing_journal == 0
        and missing_plan == 0
        and missing_paths == 0
        and incomplete_paths == 0
        and lineage_mismatches == 0
        and actual_violations == 0
    )

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "claim_scope": (
            "fixed_observed_schedule_portfolio_capacity_overlay"
        ),
        "delay_ms": delay_ms,
        "reference_equity": str(reference_equity),
        "correlation_bucket_assumption": (
            "single_runtime_configured_bucket"
        ),
        "limits": {
            "max_open_risk": str(limits.max_open_risk),
            "correlation_bucket_risk_limit": str(
                limits.correlation_bucket_risk_limit
            ),
            "max_gross_leverage": str(
                limits.max_gross_leverage
            ),
        },
        "changed_admissions_modeled": False,
        "replacement_trades_modeled": False,
        "intratrade_funding_timing_modeled": False,
        "closed_shadow_outcomes": len(outcomes),
        "candidate_filled_positions": candidate_filled,
        "candidate_no_fill_trades": candidate_no_fill,
        "background_positions": background_positions,
        "unresolved_outcomes": unresolved_outcomes,
        "missing_journal_trades": missing_journal,
        "missing_opening_plans": missing_plan,
        "missing_exact_paths": missing_paths,
        "incomplete_exact_paths": incomplete_paths,
        "lineage_mismatches": lineage_mismatches,
        "actual": actual,
        "candidate": candidate,
        "readiness": {
            "ready_for_review": ready,
            "min_closed_shadow_outcomes": (
                MIN_CLOSED_SHADOW_OUTCOMES
            ),
            "min_candidate_filled_positions": (
                MIN_CANDIDATE_FILLED_POSITIONS
            ),
            "min_candidate_overlap_openings": (
                MIN_CANDIDATE_OVERLAP_OPENINGS
            ),
            "missing_closed_shadow_outcomes": max(
                0,
                MIN_CLOSED_SHADOW_OUTCOMES - len(outcomes),
            ),
            "missing_candidate_filled_positions": max(
                0,
                MIN_CANDIDATE_FILLED_POSITIONS - candidate_filled,
            ),
            "missing_candidate_overlap_openings": max(
                0,
                MIN_CANDIDATE_OVERLAP_OPENINGS - candidate_overlap,
            ),
        },
    }
