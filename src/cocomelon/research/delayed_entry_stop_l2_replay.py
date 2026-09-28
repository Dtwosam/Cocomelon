from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Final

from cocomelon.domain.execution import (
    ExecutionResult,
    PaperExecutionConfig,
    PositionAction,
    PositionActionType,
)
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.execution.accounting import (
    PaperPosition,
    PositionSide,
)
from cocomelon.execution.funding import funding_cash_delta
from cocomelon.execution.ioc import simulate_ioc
from cocomelon.execution.planner import (
    PlanningRejection,
    plan_reduce_only_order,
)
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
from cocomelon.research.delayed_entry_fill_weighted_funding import (
    DelayedEntryFundingCorrectedFillError,
    FundingCorrectedFillOutcome,
    evaluate_delayed_entry_funding_corrected_fill_weighted_outcome,
)
from cocomelon.research.delayed_entry_funding import (
    DelayedEntryFundingError,
    DelayedEntryFundingMissingError,
    FundingLoader,
    trade_funding_accruals,
)
from cocomelon.research.delayed_entry_stop_survivability import (
    DelayedEntryStopOutcome,
    DelayedEntryStopSurvivabilityError,
    DelayedEntryStopTimingError,
    evaluate_delayed_entry_stop_outcome,
)
from cocomelon.research.original_stop_book_evidence import (
    OriginalStopBookEvidence,
    OriginalStopBookEvidenceError,
    OriginalStopBookEvidenceStore,
)

ZERO: Final = Decimal("0")
MIN_FULL_STOP_EXITS_FOR_DESCRIPTIVE_REVIEW: Final = 5


class DelayedEntryStopL2ReplayError(RuntimeError):
    pass


def _decimal(value: object, field: str) -> Decimal:
    try:
        resolved = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise DelayedEntryStopL2ReplayError(
            f"{field} must be a decimal"
        ) from exc
    if not resolved.is_finite():
        raise DelayedEntryStopL2ReplayError(
            f"{field} must be finite"
        )
    return resolved


@dataclass(frozen=True, slots=True)
class DelayedEntryStopL2Outcome:
    trade_id: str
    market: str
    direction: str
    source: str
    status: str
    mark_stop_crossed: bool
    stop_plan_captured: bool
    actual_net_pnl: Decimal
    same_exit_candidate_net_pnl: Decimal
    candidate_open_ms: int
    delayed_entry_price: Decimal
    delayed_filled_quantity: Decimal
    first_mark_cross_ms: int | None = None
    stop_action_mark_ms: int | None = None
    stop_action_mark_price: Decimal | None = None
    execution_result: str | None = None
    stop_requested_quantity: Decimal | None = None
    stop_filled_quantity: Decimal | None = None
    stop_unfilled_quantity: Decimal | None = None
    stop_position_remainder_quantity: Decimal | None = None
    stop_average_fill_price: Decimal | None = None
    stop_exit_fee: Decimal | None = None
    funding_through_execution: Decimal | None = None
    late_funding_boundaries_excluded: int | None = None
    exact_full_stop_candidate_net_pnl: Decimal | None = None

    def __post_init__(self) -> None:
        for text_value, field in (
            (self.trade_id, "trade_id"),
            (self.market, "market"),
            (self.direction, "direction"),
            (self.source, "source"),
            (self.status, "status"),
        ):
            if not text_value.strip():
                raise ValueError(f"{field} must not be empty")
        if self.direction not in {"long", "short"}:
            raise ValueError("direction must be long or short")
        if self.candidate_open_ms < 0:
            raise ValueError(
                "candidate_open_ms must be non-negative"
            )
        for metric in (
            self.actual_net_pnl,
            self.same_exit_candidate_net_pnl,
            self.delayed_entry_price,
            self.delayed_filled_quantity,
        ):
            if not metric.is_finite():
                raise ValueError(
                    "stop L2 replay economics must be finite"
                )
        if (
            self.delayed_entry_price <= ZERO
            or self.delayed_filled_quantity <= ZERO
        ):
            raise ValueError(
                "delayed entry price/quantity must be positive"
            )
        if self.mark_stop_crossed != (
            self.first_mark_cross_ms is not None
        ):
            raise ValueError(
                "mark crossing flag/timestamp must reconcile"
            )
        if self.first_mark_cross_ms is not None and (
            self.first_mark_cross_ms <= self.candidate_open_ms
        ):
            raise ValueError(
                "first mark crossing must follow candidate open"
            )
        if self.stop_plan_captured:
            if (
                self.stop_action_mark_ms is None
                or self.stop_action_mark_price is None
            ):
                raise ValueError(
                    "captured stop plan requires action mark"
                )
            if (
                self.stop_action_mark_ms <= self.candidate_open_ms
                or not self.stop_action_mark_price.is_finite()
                or self.stop_action_mark_price <= ZERO
            ):
                raise ValueError(
                    "captured stop action mark is invalid"
                )
        elif (
            self.stop_action_mark_ms is not None
            or self.stop_action_mark_price is not None
        ):
            raise ValueError(
                "uncaptured stop plan must not have action mark"
            )
        if self.status == "full_stop_exit":
            if (
                self.execution_result != ExecutionResult.FULL.value
                or self.exact_full_stop_candidate_net_pnl is None
            ):
                raise ValueError(
                    "full stop exit requires full execution/PnL"
                )
        elif self.exact_full_stop_candidate_net_pnl is not None:
            raise ValueError(
                "only full stop exit may claim total stop PnL"
            )
        if self.execution_result is None:
            return
        for optional_metric, field in (
            (
                self.stop_requested_quantity,
                "stop_requested_quantity",
            ),
            (
                self.stop_filled_quantity,
                "stop_filled_quantity",
            ),
            (
                self.stop_unfilled_quantity,
                "stop_unfilled_quantity",
            ),
            (
                self.stop_position_remainder_quantity,
                "stop_position_remainder_quantity",
            ),
            (self.stop_exit_fee, "stop_exit_fee"),
            (
                self.funding_through_execution,
                "funding_through_execution",
            ),
        ):
            if (
                not isinstance(optional_metric, Decimal)
                or not optional_metric.is_finite()
            ):
                raise ValueError(
                    f"{field} must be present and finite"
                )
        requested = self.stop_requested_quantity
        filled = self.stop_filled_quantity
        unfilled = self.stop_unfilled_quantity
        position_remainder = (
            self.stop_position_remainder_quantity
        )
        if (
            not isinstance(requested, Decimal)
            or not isinstance(filled, Decimal)
            or not isinstance(unfilled, Decimal)
            or not isinstance(position_remainder, Decimal)
        ):
            raise ValueError(
                "stop quantities must be decimal values"
            )
        if (
            requested <= ZERO
            or filled < ZERO
            or unfilled < ZERO
            or position_remainder < ZERO
        ):
            raise ValueError(
                "stop quantities are outside valid bounds"
            )
        if filled + unfilled != requested:
            raise ValueError(
                "stop fill and IOC remainder must reconcile"
            )
        if (
            filled + position_remainder
            != self.delayed_filled_quantity
        ):
            raise ValueError(
                "stop fill and position remainder must reconcile"
            )
        if filled > ZERO:
            if (
                self.stop_average_fill_price is None
                or not self.stop_average_fill_price.is_finite()
                or self.stop_average_fill_price <= ZERO
            ):
                raise ValueError(
                    "positive stop fill requires average fill price"
                )
        elif self.stop_average_fill_price is not None:
            raise ValueError(
                "zero stop fill must not have average fill price"
            )


def _trade_map(
    journal: JournalStore,
) -> dict[str, TradeJournalEntry]:
    trades = tuple(journal.iter_trades())
    by_id = {trade.trade_id: trade for trade in trades}
    if len(by_id) != len(trades):
        raise DelayedEntryStopL2ReplayError(
            "journal contains duplicate trade ids"
        )
    return by_id


def _path_map(
    store: ContinuousPaperTradePathStore,
) -> dict[str, Mapping[str, object]]:
    result: dict[str, Mapping[str, object]] = {}
    for raw in store.iter_payloads():
        trade_id = raw.get("trade_id")
        if not isinstance(trade_id, str) or not trade_id.strip():
            raise DelayedEntryStopL2ReplayError(
                "trade path trade_id must be non-empty"
            )
        if trade_id in result:
            raise DelayedEntryStopL2ReplayError(
                "duplicate exact trade path"
            )
        result[trade_id] = raw
    return result


def _path_contains_action_mark(
    raw_path: Mapping[str, object],
    evidence: OriginalStopBookEvidence,
) -> bool:
    marks = raw_path.get("marks")
    if not isinstance(marks, list):
        raise DelayedEntryStopL2ReplayError(
            "trade path marks must be an array"
        )
    crossing = evidence.crossing
    for raw in marks:
        if not isinstance(raw, Mapping):
            raise DelayedEntryStopL2ReplayError(
                "trade path mark must be an object"
            )
        if raw.get("event_key") != crossing.crossing_mark_event_key:
            continue
        return (
            raw.get("available_at_ms")
            == crossing.crossing_mark_received_ms
            and _decimal(
                raw.get("mark_px"),
                "trade path mark price",
            )
            == crossing.crossing_mark_price
        )
    return False


def _funding_through_execution(
    trade: TradeJournalEntry,
    weighted: DelayedEntryFillWeightedOutcome,
    funding_loader: FundingLoader,
    *,
    candidate_open_ms: int,
    execution_ms: int,
) -> tuple[Decimal, int]:
    accruals = trade_funding_accruals(
        trade,
        funding_loader,
    )
    eligible = tuple(
        accrual
        for accrual in accruals
        if (
            candidate_open_ms
            < accrual.boundary_ms
            <= execution_ms
        )
    )
    available = tuple(
        accrual
        for accrual in eligible
        if accrual.funding_received_at_ms <= execution_ms
    )
    late_count = len(eligible) - len(available)
    funding = sum(
        (
            funding_cash_delta(
                accrual.signed_quantity
                * weighted.fill_fraction,
                accrual.oracle_price,
                accrual.funding_rate,
            )
            for accrual in available
        ),
        ZERO,
    )
    return funding, late_count


def _candidate_position(
    trade: TradeJournalEntry,
    weighted: DelayedEntryFillWeightedOutcome,
    *,
    candidate_open_ms: int,
    stop_action_mark_price: Decimal,
    venue_max_leverage: Decimal,
) -> PaperPosition:
    entry_price = weighted.delayed_average_fill_price
    if entry_price is None:
        raise DelayedEntryStopL2ReplayError(
            "filled delayed candidate lost entry price"
        )
    side = (
        PositionSide.LONG
        if trade.direction.value == "long"
        else PositionSide.SHORT
    )
    return PaperPosition(
        market=trade.market,
        side=side,
        quantity=weighted.delayed_filled_quantity,
        average_entry_price=entry_price,
        stop_price=trade.initial_stop,
        opening_plan_id=trade.opening_plan_id,
        opened_at_ms=candidate_open_ms,
        updated_at_ms=candidate_open_ms,
        initial_risk_decision_id=trade.risk_decision_id,
        correlation_bucket="crypto_beta",
        cost_buffer_fraction=ZERO,
        planned_risk=(
            trade.initial_risk_amount
            * weighted.fill_fraction
        ),
        cumulative_fees=weighted.delayed_entry_fee,
        venue_max_leverage=venue_max_leverage,
        latest_mark=stop_action_mark_price,
    )


def _validate_stop_book_lineage(
    trade: TradeJournalEntry,
    stop: DelayedEntryStopOutcome,
    raw_path: Mapping[str, object],
    evidence: OriginalStopBookEvidence,
) -> None:
    crossing = evidence.crossing
    if (
        crossing.opening_plan_id != trade.opening_plan_id
        or crossing.market != trade.market.canonical
        or crossing.direction != trade.direction.value
        or crossing.original_stop != trade.initial_stop
        or crossing.opened_at_ms != trade.opened_at_ms
    ):
        raise DelayedEntryStopL2ReplayError(
            "stop-book evidence lineage mismatch"
        )
    if not (
        stop.candidate_open_ms
        < crossing.crossing_mark_received_ms
        <= trade.closed_at_ms
    ):
        raise DelayedEntryStopL2ReplayError(
            "stop plan action is outside delayed lifecycle"
        )
    if not _path_contains_action_mark(raw_path, evidence):
        raise DelayedEntryStopL2ReplayError(
            "stop action mark is absent from exact trade path"
        )
    crossed = (
        crossing.crossing_mark_price
        <= trade.initial_stop
        if trade.direction.value == "long"
        else crossing.crossing_mark_price
        >= trade.initial_stop
    )
    if not crossed:
        raise DelayedEntryStopL2ReplayError(
            "captured stop action mark does not cross original stop"
        )
    if (
        evidence.execution_book_received_ms
        > trade.closed_at_ms
    ):
        raise DelayedEntryStopL2ReplayError(
            "stop execution book follows actual trade close"
        )


def _gross_pnl(
    *,
    direction: str,
    entry_price: Decimal,
    exit_price: Decimal,
    quantity: Decimal,
) -> Decimal:
    if direction == "long":
        return (exit_price - entry_price) * quantity
    return (entry_price - exit_price) * quantity


def _same_exit_outcome(
    trade: TradeJournalEntry,
    outcome: DelayedEntryOutcome,
    weighted: DelayedEntryFillWeightedOutcome,
    funding_loader: FundingLoader,
    *,
    delay_ms: int,
) -> FundingCorrectedFillOutcome:
    return evaluate_delayed_entry_funding_corrected_fill_weighted_outcome(
        trade,
        outcome,
        weighted,
        funding_loader,
        delay_ms=delay_ms,
    )


def _same_exit_result(
    trade: TradeJournalEntry,
    outcome: DelayedEntryOutcome,
    weighted: DelayedEntryFillWeightedOutcome,
    stop: DelayedEntryStopOutcome,
    funding_loader: FundingLoader,
    *,
    status: str,
    mark_stop_crossed: bool,
    delay_ms: int,
) -> DelayedEntryStopL2Outcome:
    corrected = _same_exit_outcome(
        trade,
        outcome,
        weighted,
        funding_loader,
        delay_ms=delay_ms,
    )
    return DelayedEntryStopL2Outcome(
        trade_id=trade.trade_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        source=outcome.source,
        status=status,
        mark_stop_crossed=mark_stop_crossed,
        stop_plan_captured=False,
        actual_net_pnl=trade.net_pnl,
        same_exit_candidate_net_pnl=(
            corrected.corrected_candidate_net_pnl
        ),
        candidate_open_ms=stop.candidate_open_ms,
        delayed_entry_price=stop.delayed_entry_price,
        delayed_filled_quantity=(
            stop.delayed_filled_quantity
        ),
        first_mark_cross_ms=stop.first_stop_hit_ms,
    )


def evaluate_delayed_entry_stop_l2_outcome(
    trade: TradeJournalEntry,
    outcome: DelayedEntryOutcome,
    weighted: DelayedEntryFillWeightedOutcome,
    raw_path: Mapping[str, object],
    stop_book_store: OriginalStopBookEvidenceStore,
    funding_loader: FundingLoader,
    config: PaperExecutionConfig,
    *,
    capture_error: str | None,
    delay_ms: int = DELAY_MS,
) -> DelayedEntryStopL2Outcome | None:
    if weighted.delayed_filled_quantity == ZERO:
        return None

    stop = evaluate_delayed_entry_stop_outcome(
        trade,
        outcome,
        weighted,
        raw_path,
        delay_ms=delay_ms,
    )
    if stop is None:
        raise DelayedEntryStopL2ReplayError(
            "filled delayed candidate lost stop outcome"
        )

    evidence = stop_book_store.evidence_for(
        trade.opening_plan_id
    )
    pending = stop_book_store.pending_for(
        trade.opening_plan_id
    )

    if evidence is None:
        if pending is not None:
            corrected = _same_exit_outcome(
                trade,
                outcome,
                weighted,
                funding_loader,
                delay_ms=delay_ms,
            )
            return DelayedEntryStopL2Outcome(
                trade_id=trade.trade_id,
                market=trade.market.canonical,
                direction=trade.direction.value,
                source=outcome.source,
                status="pending_stop_evidence",
                mark_stop_crossed=stop.stop_hit,
                stop_plan_captured=pending.plan_staged,
                actual_net_pnl=trade.net_pnl,
                same_exit_candidate_net_pnl=(
                    corrected.corrected_candidate_net_pnl
                ),
                candidate_open_ms=stop.candidate_open_ms,
                delayed_entry_price=stop.delayed_entry_price,
                delayed_filled_quantity=(
                    stop.delayed_filled_quantity
                ),
                first_mark_cross_ms=(
                    stop.first_stop_hit_ms
                ),
                stop_action_mark_ms=(
                    pending.crossing.crossing_mark_received_ms
                    if pending.plan_staged
                    else None
                ),
                stop_action_mark_price=(
                    pending.crossing.crossing_mark_price
                    if pending.plan_staged
                    else None
                ),
            )
        if (
            capture_error is not None
            or stop_book_store.capture_started_at_ms is None
        ):
            corrected = _same_exit_outcome(
                trade,
                outcome,
                weighted,
                funding_loader,
                delay_ms=delay_ms,
            )
            return DelayedEntryStopL2Outcome(
                trade_id=trade.trade_id,
                market=trade.market.canonical,
                direction=trade.direction.value,
                source=outcome.source,
                status="stop_capture_unreliable",
                mark_stop_crossed=stop.stop_hit,
                stop_plan_captured=False,
                actual_net_pnl=trade.net_pnl,
                same_exit_candidate_net_pnl=(
                    corrected.corrected_candidate_net_pnl
                ),
                candidate_open_ms=stop.candidate_open_ms,
                delayed_entry_price=stop.delayed_entry_price,
                delayed_filled_quantity=(
                    stop.delayed_filled_quantity
                ),
                first_mark_cross_ms=(
                    stop.first_stop_hit_ms
                ),
            )
        return _same_exit_result(
            trade,
            outcome,
            weighted,
            stop,
            funding_loader,
            status=(
                "transient_mark_crossing_same_exit"
                if stop.stop_hit
                else "observed_path_survivor"
            ),
            mark_stop_crossed=stop.stop_hit,
            delay_ms=delay_ms,
        )

    _validate_stop_book_lineage(
        trade,
        stop,
        raw_path,
        evidence,
    )
    corrected = _same_exit_outcome(
        trade,
        outcome,
        weighted,
        funding_loader,
        delay_ms=delay_ms,
    )
    crossing = evidence.crossing
    plan_instrument = evidence.plan_instrument_spec()
    execution_instrument = (
        evidence.execution_instrument_spec()
    )
    position = _candidate_position(
        trade,
        weighted,
        candidate_open_ms=stop.candidate_open_ms,
        stop_action_mark_price=(
            crossing.crossing_mark_price
        ),
        venue_max_leverage=(
            plan_instrument.venue_max_leverage
        ),
    )
    action = PositionAction(
        action_type=PositionActionType.EXIT_STOP,
        market=trade.market,
        quantity=weighted.delayed_filled_quantity,
        new_stop_price=None,
        reason_codes=("MARK_STOP_TRIGGERED",),
        timestamp_ms=crossing.crossing_mark_received_ms,
    )
    planned = plan_reduce_only_order(
        position,
        action,
        plan_instrument,
        config,
        originating_risk_decision_id=(
            trade.risk_decision_id
        ),
        originating_strategy_decision_id=(
            trade.strategy_decision_id
        ),
        reference_price=evidence.reference_price,
        created_at_ms=crossing.crossing_mark_received_ms,
    )
    if isinstance(planned, PlanningRejection):
        return DelayedEntryStopL2Outcome(
            trade_id=trade.trade_id,
            market=trade.market.canonical,
            direction=trade.direction.value,
            source=outcome.source,
            status="planning_rejected",
            mark_stop_crossed=stop.stop_hit,
            stop_plan_captured=True,
            actual_net_pnl=trade.net_pnl,
            same_exit_candidate_net_pnl=(
                corrected.corrected_candidate_net_pnl
            ),
            candidate_open_ms=stop.candidate_open_ms,
            delayed_entry_price=stop.delayed_entry_price,
            delayed_filled_quantity=(
                stop.delayed_filled_quantity
            ),
            first_mark_cross_ms=stop.first_stop_hit_ms,
            stop_action_mark_ms=(
                crossing.crossing_mark_received_ms
            ),
            stop_action_mark_price=(
                crossing.crossing_mark_price
            ),
        )

    execution_ms = evidence.execution_book_received_ms
    (
        funding,
        late_funding_boundaries_excluded,
    ) = _funding_through_execution(
        trade,
        weighted,
        funding_loader,
        candidate_open_ms=stop.candidate_open_ms,
        execution_ms=execution_ms,
    )
    simulation = simulate_ioc(
        planned,
        evidence.book_event(),
        execution_instrument,
        config,
        attempt_timestamp_ms=execution_ms,
    )
    attempt = simulation.attempt
    position_remainder = (
        weighted.delayed_filled_quantity
        - attempt.filled_quantity
    )
    if position_remainder < ZERO:
        raise DelayedEntryStopL2ReplayError(
            "stop fill exceeds delayed candidate position"
        )
    if (
        attempt.result is ExecutionResult.FULL
        and position_remainder == ZERO
    ):
        status = "full_stop_exit"
    elif attempt.result is ExecutionResult.FULL:
        status = "full_ioc_position_remainder"
    elif attempt.result is ExecutionResult.PARTIAL:
        status = "partial_stop_exit"
    elif attempt.result is ExecutionResult.NO_FILL:
        status = "no_fill_stop_exit"
    else:
        status = "execution_rejected"

    exact_net: Decimal | None = None
    if status == "full_stop_exit":
        exit_price = attempt.average_fill_price
        if exit_price is None:
            raise DelayedEntryStopL2ReplayError(
                "full stop exit lost average fill price"
            )
        exact_net = (
            _gross_pnl(
                direction=trade.direction.value,
                entry_price=stop.delayed_entry_price,
                exit_price=exit_price,
                quantity=attempt.filled_quantity,
            )
            - weighted.delayed_entry_fee
            - attempt.fee
            + funding
        )

    return DelayedEntryStopL2Outcome(
        trade_id=trade.trade_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        source=outcome.source,
        status=status,
        mark_stop_crossed=stop.stop_hit,
        stop_plan_captured=True,
        actual_net_pnl=trade.net_pnl,
        same_exit_candidate_net_pnl=(
            corrected.corrected_candidate_net_pnl
        ),
        candidate_open_ms=stop.candidate_open_ms,
        delayed_entry_price=stop.delayed_entry_price,
        delayed_filled_quantity=(
            stop.delayed_filled_quantity
        ),
        first_mark_cross_ms=stop.first_stop_hit_ms,
        stop_action_mark_ms=(
            crossing.crossing_mark_received_ms
        ),
        stop_action_mark_price=(
            crossing.crossing_mark_price
        ),
        execution_result=attempt.result.value,
        stop_requested_quantity=(
            attempt.requested_quantity
        ),
        stop_filled_quantity=attempt.filled_quantity,
        stop_unfilled_quantity=(
            attempt.unfilled_quantity
        ),
        stop_position_remainder_quantity=(
            position_remainder
        ),
        stop_average_fill_price=(
            attempt.average_fill_price
        ),
        stop_exit_fee=attempt.fee,
        funding_through_execution=funding,
        late_funding_boundaries_excluded=(
            late_funding_boundaries_excluded
        ),
        exact_full_stop_candidate_net_pnl=exact_net,
    )


def _summary(
    items: Sequence[DelayedEntryStopL2Outcome],
) -> dict[str, object]:
    values = tuple(items)
    survivors = tuple(
        item
        for item in values
        if item.status == "observed_path_survivor"
    )
    transient = tuple(
        item
        for item in values
        if item.status
        == "transient_mark_crossing_same_exit"
    )
    full = tuple(
        item
        for item in values
        if item.status == "full_stop_exit"
    )
    partial = tuple(
        item
        for item in values
        if item.status == "partial_stop_exit"
    )
    quantized_remainder = tuple(
        item
        for item in values
        if item.status == "full_ioc_position_remainder"
    )
    no_fill = tuple(
        item
        for item in values
        if item.status == "no_fill_stop_exit"
    )
    rejected = tuple(
        item
        for item in values
        if item.status in {
            "planning_rejected",
            "execution_rejected",
        }
    )
    pending = tuple(
        item
        for item in values
        if item.status == "pending_stop_evidence"
    )
    unreliable = tuple(
        item
        for item in values
        if item.status == "stop_capture_unreliable"
    )
    same_exit_resolved = survivors + transient
    resolved = same_exit_resolved + full

    resolved_actual = sum(
        (item.actual_net_pnl for item in resolved),
        ZERO,
    )
    survivor_candidate = sum(
        (
            item.same_exit_candidate_net_pnl
            for item in same_exit_resolved
        ),
        ZERO,
    )
    full_exact = sum(
        (
            item.exact_full_stop_candidate_net_pnl
            for item in full
            if (
                item.exact_full_stop_candidate_net_pnl
                is not None
            )
        ),
        ZERO,
    )
    resolved_candidate = survivor_candidate + full_exact
    full_same_exit = sum(
        (
            item.same_exit_candidate_net_pnl
            for item in full
        ),
        ZERO,
    )
    unresolved = (
        len(partial)
        + len(quantized_remainder)
        + len(no_fill)
        + len(rejected)
        + len(pending)
        + len(unreliable)
    )

    return {
        "evaluated_filled_candidates": len(values),
        "mark_stop_crossings": sum(
            1 for item in values if item.mark_stop_crossed
        ),
        "observed_path_survivors": len(survivors),
        "transient_mark_crossings_without_stop_plan": (
            len(transient)
        ),
        "captured_stop_plans": sum(
            1 for item in values if item.stop_plan_captured
        ),
        "full_stop_exits": len(full),
        "partial_stop_exits": len(partial),
        "full_ioc_position_remainders": (
            len(quantized_remainder)
        ),
        "no_fill_stop_exits": len(no_fill),
        "planning_or_execution_rejections": len(rejected),
        "pending_stop_evidence": len(pending),
        "stop_capture_unreliable": len(unreliable),
        "resolved_candidates": len(resolved),
        "unresolved_stop_actions": unresolved,
        "resolved_actual_net_pnl": str(resolved_actual),
        "resolved_candidate_net_pnl": str(
            resolved_candidate
        ),
        "resolved_delta_vs_actual": str(
            resolved_candidate - resolved_actual
        ),
        "same_exit_pnl_on_full_stop_exits": str(
            full_same_exit
        ),
        "exact_pnl_on_full_stop_exits": str(
            full_exact
        ),
        "same_exit_minus_exact_on_full_stop_exits": str(
            full_same_exit - full_exact
        ),
        "late_funding_boundaries_excluded": sum(
            (
                item.late_funding_boundaries_excluded
                for item in values
                if (
                    item.late_funding_boundaries_excluded
                    is not None
                )
            ),
            0,
        ),
        "mean_full_stop_fill_price": (
            None
            if not full
            else str(
                sum(
                    (
                        item.stop_average_fill_price
                        for item in full
                        if item.stop_average_fill_price
                        is not None
                    ),
                    ZERO,
                )
                / Decimal(len(full))
            )
        ),
    }


def delayed_entry_stop_l2_replay(
    journal: JournalStore,
    outcomes: tuple[DelayedEntryOutcome, ...],
    path_store: ContinuousPaperTradePathStore,
    stop_book_store: OriginalStopBookEvidenceStore,
    funding_loader: FundingLoader,
    config: PaperExecutionConfig,
    *,
    capture_error: str | None = None,
    delay_ms: int = DELAY_MS,
) -> dict[str, object]:
    if delay_ms <= 0:
        raise ValueError("delay_ms must be positive")
    trades = _trade_map(journal)
    if len({outcome.trade_id for outcome in outcomes}) != len(
        outcomes
    ):
        raise DelayedEntryStopL2ReplayError(
            "delayed shadow contains duplicate trade ids"
        )
    paths = _path_map(path_store)
    capture_started_at_ms = (
        stop_book_store.capture_started_at_ms
    )

    evaluated: list[DelayedEntryStopL2Outcome] = []
    pre_capture_legacy_outcomes = 0
    unresolved_outcomes = 0
    candidate_no_fill = 0
    missing_journal = 0
    missing_paths = 0
    incomplete_or_gapped_paths = 0
    missing_funding_events = 0
    lineage_mismatches = 0
    invalid_candidate_timing = 0
    stop_book_capture_errors = 0

    for outcome in outcomes:
        if outcome.source not in EVALUABLE_SOURCES:
            unresolved_outcomes += 1
            continue
        trade = trades.get(outcome.trade_id)
        if trade is None:
            missing_journal += 1
            continue
        if (
            capture_started_at_ms is not None
            and trade.opened_at_ms < capture_started_at_ms
        ):
            pre_capture_legacy_outcomes += 1
            continue
        try:
            weighted = (
                evaluate_delayed_entry_fill_weighted_outcome(
                    trade,
                    outcome,
                )
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
            item = evaluate_delayed_entry_stop_l2_outcome(
                trade,
                outcome,
                weighted,
                raw_path,
                stop_book_store,
                funding_loader,
                config,
                capture_error=capture_error,
                delay_ms=delay_ms,
            )
        except DelayedEntryFundingMissingError:
            missing_funding_events += 1
            continue
        except DelayedEntryStopTimingError:
            invalid_candidate_timing += 1
            continue
        except OriginalStopBookEvidenceError:
            stop_book_capture_errors += 1
            continue
        except (
            DelayedEntryFundingCorrectedFillError,
            DelayedEntryFundingError,
            DelayedEntryStopSurvivabilityError,
            DelayedEntryStopL2ReplayError,
            ValueError,
        ):
            lineage_mismatches += 1
            continue

        if item is None:
            lineage_mismatches += 1
            continue
        evaluated.append(item)

    items = tuple(evaluated)
    overall = _summary(items)
    full_stop_exits = sum(
        1
        for item in items
        if item.status == "full_stop_exit"
    )
    unresolved_stop_actions = sum(
        1
        for item in items
        if item.status in {
            "partial_stop_exit",
            "full_ioc_position_remainder",
            "no_fill_stop_exit",
            "planning_rejected",
            "execution_rejected",
            "pending_stop_evidence",
            "stop_capture_unreliable",
        }
    )
    protocol_present = capture_started_at_ms is not None
    integrity_clean = (
        protocol_present
        and capture_error is None
        and unresolved_outcomes == 0
        and missing_journal == 0
        and missing_paths == 0
        and incomplete_or_gapped_paths == 0
        and missing_funding_events == 0
        and lineage_mismatches == 0
        and invalid_candidate_timing == 0
        and stop_book_capture_errors == 0
        and sum(
            1
            for item in items
            if item.status == "pending_stop_evidence"
        )
        == 0
    )

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "claim_scope": (
            "prospective_manager_triggered_original_stop_visible_l2_"
            "first_ioc_replay"
        ),
        "delay_ms": delay_ms,
        "capture_started_at_ms": capture_started_at_ms,
        "capture_error": capture_error,
        "stop_exit_policy": (
            "latest_mark_at_l2_manager_tick_then_paper_reduce_only_ioc"
        ),
        "transient_mark_crossing_policy": (
            "same_exit_when_no_stop_plan_was_created"
        ),
        "partial_remainder_modeled": False,
        "replacement_exit_modeled": False,
        "closed_shadow_outcomes": len(outcomes),
        "pre_capture_legacy_outcomes": (
            pre_capture_legacy_outcomes
        ),
        "candidate_no_fill_trades": candidate_no_fill,
        "unresolved_outcomes": unresolved_outcomes,
        "missing_journal_trades": missing_journal,
        "missing_exact_paths": missing_paths,
        "incomplete_or_gapped_paths": (
            incomplete_or_gapped_paths
        ),
        "missing_funding_events": missing_funding_events,
        "lineage_mismatches": lineage_mismatches,
        "invalid_candidate_timing": (
            invalid_candidate_timing
        ),
        "stop_book_capture_errors": (
            stop_book_capture_errors
        ),
        "overall": overall,
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
        "readiness": {
            "descriptive_review_only": True,
            "prospective_protocol_present": protocol_present,
            "integrity_clean": integrity_clean,
            "min_full_stop_exits": (
                MIN_FULL_STOP_EXITS_FOR_DESCRIPTIVE_REVIEW
            ),
            "missing_full_stop_exits": max(
                0,
                (
                    MIN_FULL_STOP_EXITS_FOR_DESCRIPTIVE_REVIEW
                    - full_stop_exits
                ),
            ),
            "ready_for_descriptive_review": (
                integrity_clean
                and full_stop_exits
                >= MIN_FULL_STOP_EXITS_FOR_DESCRIPTIVE_REVIEW
            ),
            "complete_counterfactual_cohort": (
                unresolved_stop_actions == 0
            ),
        },
    }
