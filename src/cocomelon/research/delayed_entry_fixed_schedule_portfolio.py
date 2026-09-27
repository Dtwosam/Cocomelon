from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from cocomelon.domain.execution import OrderSide, PaperOrderPlan
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.strategy import Direction
from cocomelon.journal.store import JournalStore
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
HOUR_MS: Final = Decimal("3600000")
MIN_CLOSED_SHADOW_OUTCOMES: Final = 30
MIN_EVALUATED_DELAYED_ATTEMPTS: Final = 20
MIN_ACTUAL_OVERLAP_OPENINGS: Final = 5


class DelayedEntryFixedSchedulePortfolioError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _CohortTrade:
    trade_id: str
    direction: str
    actual_open_ms: int
    candidate_open_ms: int | None
    close_ms: int
    actual_notional: Decimal
    candidate_notional: Decimal
    actual_risk: Decimal
    candidate_risk: Decimal
    actual_net_pnl: Decimal
    candidate_net_pnl: Decimal
    source: str

    def __post_init__(self) -> None:
        if not self.trade_id.strip():
            raise ValueError("trade_id must not be empty")
        if self.direction not in {"long", "short"}:
            raise ValueError("direction must be long or short")
        if self.actual_open_ms < 0 or self.close_ms < self.actual_open_ms:
            raise ValueError("actual trade timestamps are invalid")
        if (
            self.candidate_open_ms is not None
            and not self.actual_open_ms <= self.candidate_open_ms < self.close_ms
        ):
            raise ValueError("candidate open timestamp is invalid")
        for value in (
            self.actual_notional,
            self.candidate_notional,
            self.actual_risk,
            self.candidate_risk,
        ):
            if not value.is_finite() or value < ZERO:
                raise ValueError("portfolio exposure metrics must be non-negative")
        for value in (self.actual_net_pnl, self.candidate_net_pnl):
            if not value.is_finite():
                raise ValueError("portfolio contribution metrics must be finite")


@dataclass(frozen=True, slots=True)
class _Event:
    timestamp_ms: int
    order: int
    count_delta: int
    notional_delta: Decimal
    risk_delta: Decimal
    realized_pnl_delta: Decimal

    def __post_init__(self) -> None:
        if self.timestamp_ms < 0:
            raise ValueError("event timestamp must be non-negative")
        for value in (
            self.notional_delta,
            self.risk_delta,
            self.realized_pnl_delta,
        ):
            if not value.is_finite():
                raise ValueError("event economics must be finite")


def _risk_per_quantity(
    plan: PaperOrderPlan,
    price: Decimal,
) -> Decimal:
    if plan.stop_price is None:
        raise DelayedEntryFixedSchedulePortfolioError(
            "opening plan is missing stop price"
        )
    cost_buffer = plan.cost_buffer_fraction
    if cost_buffer is None:
        raise DelayedEntryFixedSchedulePortfolioError(
            "opening plan is missing cost buffer"
        )
    if plan.side is OrderSide.BUY:
        risk = price * (Decimal("1") + cost_buffer) - plan.stop_price
    else:
        risk = plan.stop_price - price * (Decimal("1") - cost_buffer)
    if not risk.is_finite() or risk <= ZERO:
        raise DelayedEntryFixedSchedulePortfolioError(
            "delayed entry has invalid unit risk"
        )
    return risk


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
        plan.plan_id != trade.opening_plan_id
        or plan.reduce_only
        or plan.market != trade.market
        or plan.side is not expected_side
        or plan.stop_price != trade.initial_stop
        or plan.cost_buffer_fraction is None
    ):
        raise DelayedEntryFixedSchedulePortfolioError(
            "opening plan lineage does not match journal trade"
        )


def _timeline(events: tuple[_Event, ...]) -> dict[str, object]:
    if not events:
        return {
            "final_realized_contribution": "0",
            "max_realized_drawdown": "0",
            "max_concurrent_positions": 0,
            "overlap_openings": 0,
            "max_gross_notional": "0",
            "max_planned_risk": "0",
            "position_exposure_hours": "0",
            "notional_exposure_hours": "0",
            "risk_exposure_hours": "0",
        }

    count = 0
    notional = ZERO
    risk = ZERO
    realized = ZERO
    peak = ZERO
    max_drawdown = ZERO
    max_count = 0
    max_notional = ZERO
    max_risk = ZERO
    overlap_openings = 0
    position_ms = Decimal("0")
    notional_ms = ZERO
    risk_ms = ZERO
    previous_ms = min(event.timestamp_ms for event in events)

    for event in sorted(
        events,
        key=lambda item: (item.timestamp_ms, item.order),
    ):
        elapsed = event.timestamp_ms - previous_ms
        if elapsed < 0:
            raise DelayedEntryFixedSchedulePortfolioError(
                "portfolio timeline moved backward"
            )
        elapsed_decimal = Decimal(elapsed)
        position_ms += Decimal(count) * elapsed_decimal
        notional_ms += notional * elapsed_decimal
        risk_ms += risk * elapsed_decimal
        previous_ms = event.timestamp_ms

        if event.count_delta > 0 and count > 0:
            overlap_openings += 1
        count += event.count_delta
        notional += event.notional_delta
        risk += event.risk_delta
        realized += event.realized_pnl_delta

        if count < 0 or notional < ZERO or risk < ZERO:
            raise DelayedEntryFixedSchedulePortfolioError(
                "portfolio exposure became negative"
            )
        max_count = max(max_count, count)
        max_notional = max(max_notional, notional)
        max_risk = max(max_risk, risk)
        peak = max(peak, realized)
        max_drawdown = max(max_drawdown, peak - realized)

    if count != 0 or notional != ZERO or risk != ZERO:
        raise DelayedEntryFixedSchedulePortfolioError(
            "portfolio timeline did not finish flat"
        )

    return {
        "final_realized_contribution": str(realized),
        "max_realized_drawdown": str(max_drawdown),
        "max_concurrent_positions": max_count,
        "overlap_openings": overlap_openings,
        "max_gross_notional": str(max_notional),
        "max_planned_risk": str(max_risk),
        "position_exposure_hours": str(position_ms / HOUR_MS),
        "notional_exposure_hours": str(notional_ms / HOUR_MS),
        "risk_exposure_hours": str(risk_ms / HOUR_MS),
    }


def _actual_events(
    items: tuple[_CohortTrade, ...],
) -> tuple[_Event, ...]:
    events: list[_Event] = []
    for item in items:
        events.extend(
            (
                _Event(
                    timestamp_ms=item.actual_open_ms,
                    order=1,
                    count_delta=1,
                    notional_delta=item.actual_notional,
                    risk_delta=item.actual_risk,
                    realized_pnl_delta=ZERO,
                ),
                _Event(
                    timestamp_ms=item.close_ms,
                    order=0,
                    count_delta=-1,
                    notional_delta=-item.actual_notional,
                    risk_delta=-item.actual_risk,
                    realized_pnl_delta=item.actual_net_pnl,
                ),
            )
        )
    return tuple(events)


def _candidate_events(
    items: tuple[_CohortTrade, ...],
) -> tuple[_Event, ...]:
    events: list[_Event] = []
    for item in items:
        if item.candidate_open_ms is not None:
            events.append(
                _Event(
                    timestamp_ms=item.candidate_open_ms,
                    order=1,
                    count_delta=1,
                    notional_delta=item.candidate_notional,
                    risk_delta=item.candidate_risk,
                    realized_pnl_delta=ZERO,
                )
            )
            events.append(
                _Event(
                    timestamp_ms=item.close_ms,
                    order=0,
                    count_delta=-1,
                    notional_delta=-item.candidate_notional,
                    risk_delta=-item.candidate_risk,
                    realized_pnl_delta=item.candidate_net_pnl,
                )
            )
        else:
            events.append(
                _Event(
                    timestamp_ms=item.close_ms,
                    order=0,
                    count_delta=0,
                    notional_delta=ZERO,
                    risk_delta=ZERO,
                    realized_pnl_delta=item.candidate_net_pnl,
                )
            )
    return tuple(events)


def delayed_entry_fixed_schedule_portfolio(
    journal: JournalStore,
    outcomes: tuple[DelayedEntryOutcome, ...],
    plan_loader: Callable[[str], PaperOrderPlan | None],
    *,
    delay_ms: int = DELAY_MS,
) -> dict[str, object]:
    if delay_ms <= 0:
        raise ValueError("delay_ms must be positive")

    trades = tuple(journal.iter_trades())
    trade_by_id = {trade.trade_id: trade for trade in trades}
    if len(trade_by_id) != len(trades):
        raise DelayedEntryFixedSchedulePortfolioError(
            "journal contains duplicate trade ids"
        )
    if len({outcome.trade_id for outcome in outcomes}) != len(outcomes):
        raise DelayedEntryFixedSchedulePortfolioError(
            "delayed shadow contains duplicate trade ids"
        )

    items: list[_CohortTrade] = []
    missing_journal = 0
    missing_plan = 0
    lineage_mismatches = 0
    unresolved_outcomes = 0
    risk_ceiling_exceeded = 0
    source_counts: dict[str, int] = {}

    for outcome in outcomes:
        source_counts[outcome.source] = source_counts.get(outcome.source, 0) + 1
        if outcome.source not in EVALUABLE_SOURCES:
            unresolved_outcomes += 1
            continue
        trade = trade_by_id.get(outcome.trade_id)
        if trade is None:
            missing_journal += 1
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
            DelayedEntryFixedSchedulePortfolioError,
            DelayedEntryFillWeightedError,
        ):
            lineage_mismatches += 1
            continue

        candidate_notional = ZERO
        candidate_risk = ZERO
        candidate_open_ms: int | None = None
        if weighted.delayed_filled_quantity > ZERO:
            delayed_price = weighted.delayed_average_fill_price
            if delayed_price is None:
                lineage_mismatches += 1
                continue
            lag_ms = outcome.observation_lag_ms
            if lag_ms is None or lag_ms < 0:
                lineage_mismatches += 1
                continue
            candidate_open_ms = trade.opened_at_ms + delay_ms + lag_ms
            if candidate_open_ms >= trade.closed_at_ms:
                lineage_mismatches += 1
                continue
            candidate_notional = (
                delayed_price * weighted.delayed_filled_quantity
            )
            candidate_risk = (
                _risk_per_quantity(plan, delayed_price)
                * weighted.delayed_filled_quantity
            )
            if candidate_risk > trade.initial_risk_amount:
                risk_ceiling_exceeded += 1

        items.append(
            _CohortTrade(
                trade_id=trade.trade_id,
                direction=trade.direction.value,
                actual_open_ms=trade.opened_at_ms,
                candidate_open_ms=candidate_open_ms,
                close_ms=trade.closed_at_ms,
                actual_notional=(
                    trade.entry_price * trade.filled_quantity
                ),
                candidate_notional=candidate_notional,
                actual_risk=trade.initial_risk_amount,
                candidate_risk=candidate_risk,
                actual_net_pnl=trade.net_pnl,
                candidate_net_pnl=(
                    weighted.candidate_net_pnl_estimate
                ),
                source=outcome.source,
            )
        )

    resolved = tuple(
        sorted(
            items,
            key=lambda item: (
                item.actual_open_ms,
                item.close_ms,
                item.trade_id,
            ),
        )
    )
    actual = _timeline(_actual_events(resolved))
    candidate = _timeline(_candidate_events(resolved))
    actual_final = Decimal(
        str(actual["final_realized_contribution"])
    )
    candidate_final = Decimal(
        str(candidate["final_realized_contribution"])
    )
    reference_equity = (
        None
        if not resolved
        else min(
            (
                trade_by_id[item.trade_id]
                for item in resolved
            ),
            key=lambda trade: (
                trade.opened_at_ms,
                trade.trade_id,
            ),
        ).equity_before
    )
    raw_actual_overlap = actual["overlap_openings"]
    if isinstance(raw_actual_overlap, bool) or not isinstance(
        raw_actual_overlap,
        int,
    ):
        raise DelayedEntryFixedSchedulePortfolioError(
            "actual overlap count must be an integer"
        )
    actual_overlap = raw_actual_overlap

    ready = (
        len(outcomes) >= MIN_CLOSED_SHADOW_OUTCOMES
        and len(resolved) >= MIN_EVALUATED_DELAYED_ATTEMPTS
        and actual_overlap >= MIN_ACTUAL_OVERLAP_OPENINGS
        and missing_journal == 0
        and missing_plan == 0
        and lineage_mismatches == 0
        and risk_ceiling_exceeded == 0
    )

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "claim_scope": (
            "fixed_observed_schedule_portfolio_contribution_only"
        ),
        "delay_ms": delay_ms,
        "exit_assumption": "actual_trade_close_timestamp_and_exit_economics",
        "replacement_trades_modeled": False,
        "changed_exit_timing_modeled": False,
        "unrealized_equity_modeled": False,
        "closed_shadow_outcomes": len(outcomes),
        "evaluated_delayed_attempts": len(resolved),
        "unresolved_outcomes": unresolved_outcomes,
        "missing_journal_trades": missing_journal,
        "missing_opening_plans": missing_plan,
        "lineage_mismatches": lineage_mismatches,
        "candidate_risk_ceiling_exceeded": risk_ceiling_exceeded,
        "source_counts": source_counts,
        "candidate_no_fill_trades": sum(
            1 for item in resolved if item.candidate_open_ms is None
        ),
        "cohort_reference_equity": (
            None if reference_equity is None else str(reference_equity)
        ),
        "actual": actual,
        "candidate": candidate,
        "delta_final_realized_contribution": str(
            candidate_final - actual_final
        ),
        "delta_max_realized_drawdown": str(
            Decimal(str(candidate["max_realized_drawdown"]))
            - Decimal(str(actual["max_realized_drawdown"]))
        ),
        "delta_max_gross_notional": str(
            Decimal(str(candidate["max_gross_notional"]))
            - Decimal(str(actual["max_gross_notional"]))
        ),
        "delta_max_planned_risk": str(
            Decimal(str(candidate["max_planned_risk"]))
            - Decimal(str(actual["max_planned_risk"]))
        ),
        "readiness": {
            "ready_for_review": ready,
            "min_closed_shadow_outcomes": MIN_CLOSED_SHADOW_OUTCOMES,
            "min_evaluated_delayed_attempts": (
                MIN_EVALUATED_DELAYED_ATTEMPTS
            ),
            "min_actual_overlap_openings": MIN_ACTUAL_OVERLAP_OPENINGS,
            "missing_closed_shadow_outcomes": max(
                0,
                MIN_CLOSED_SHADOW_OUTCOMES - len(outcomes),
            ),
            "missing_evaluated_delayed_attempts": max(
                0,
                MIN_EVALUATED_DELAYED_ATTEMPTS - len(resolved),
            ),
            "missing_actual_overlap_openings": max(
                0,
                MIN_ACTUAL_OVERLAP_OPENINGS - actual_overlap,
            ),
        },
    }
