from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
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
from cocomelon.research.delayed_entry_funding import (
    DelayedEntryFundingError,
    DelayedEntryFundingMissingError,
    FundingLoader,
    trade_funding_accruals,
)
from cocomelon.research.delayed_entry_stop_exit_proxy import (
    DelayedEntryStopExitProxyError,
    DelayedEntryStopExitTimingAmbiguityError,
    evaluate_delayed_entry_stop_exit_proxy,
)
from cocomelon.research.delayed_entry_stop_survivability import (
    DelayedEntryStopSurvivabilityError,
    DelayedEntryStopTimingError,
)
from cocomelon.research.original_stop_book_evidence import (
    OriginalStopBookEvidence,
    OriginalStopBookEvidenceError,
    OriginalStopBookEvidenceStore,
)

ZERO: Final = Decimal("0")
ONE: Final = Decimal("1")
MIN_FULL_STOP_EXITS_FOR_DESCRIPTIVE_REVIEW: Final = 5


class DelayedEntryStopL2ReplayError(RuntimeError):
    pass


class DelayedEntryStopL2FundingTimingAmbiguityError(
    DelayedEntryStopL2ReplayError
):
    pass


@dataclass(frozen=True, slots=True)
class DelayedEntryStopL2Outcome:
    trade_id: str
    market: str
    direction: str
    source: str
    stop_hit: bool
    status: str
    actual_net_pnl: Decimal
    same_exit_candidate_net_pnl: Decimal
    candidate_open_ms: int
    delayed_entry_price: Decimal
    delayed_filled_quantity: Decimal
    stop_hit_ms: int | None
    stop_crossing_mark: Decimal | None
    execution_result: str | None
    stop_requested_quantity: Decimal | None
    stop_filled_quantity: Decimal | None
    stop_unfilled_quantity: Decimal | None
    stop_average_fill_price: Decimal | None
    stop_exit_fee: Decimal | None
    funding_through_execution: Decimal | None
    exact_full_stop_candidate_net_pnl: Decimal | None

    def __post_init__(self) -> None:
        for value, field in (
            (self.trade_id, "trade_id"),
            (self.market, "market"),
            (self.direction, "direction"),
            (self.source, "source"),
            (self.status, "status"),
        ):
            if not value.strip():
                raise ValueError(f"{field} must not be empty")
        if self.direction not in {"long", "short"}:
            raise ValueError("direction must be long or short")
        if self.candidate_open_ms < 0:
            raise ValueError(
                "candidate_open_ms must be non-negative"
            )
        for value in (
            self.actual_net_pnl,
            self.same_exit_candidate_net_pnl,
            self.delayed_entry_price,
            self.delayed_filled_quantity,
        ):
            if not value.is_finite():
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

        stop_values = (
            self.stop_hit_ms,
            self.stop_crossing_mark,
            self.execution_result,
            self.stop_requested_quantity,
            self.stop_filled_quantity,
            self.stop_unfilled_quantity,
            self.stop_exit_fee,
            self.funding_through_execution,
        )
        if not self.stop_hit:
            if any(value is not None for value in stop_values):
                raise ValueError(
                    "survivor outcome must not contain stop execution"
                )
            if self.stop_average_fill_price is not None:
                raise ValueError(
                    "survivor outcome must not contain stop fill price"
                )
            if self.exact_full_stop_candidate_net_pnl is not None:
                raise ValueError(
                    "survivor outcome must not contain exact stop PnL"
                )
            return

        if self.stop_hit_ms is None or self.stop_crossing_mark is None:
            raise ValueError(
                "stop-hit outcome requires crossing evidence"
            )
        if self.stop_hit_ms <= self.candidate_open_ms:
            raise ValueError(
                "stop hit must follow delayed candidate open"
            )
        if not self.stop_crossing_mark.is_finite():
            raise ValueError(
                "stop crossing mark must be finite"
            )

        if self.status == "stop_book_missing":
            if any(
                value is not None
                for value in (
                    self.execution_result,
                    self.stop_requested_quantity,
                    self.stop_filled_quantity,
                    self.stop_unfilled_quantity,
                    self.stop_average_fill_price,
                    self.stop_exit_fee,
                    self.funding_through_execution,
                    self.exact_full_stop_candidate_net_pnl,
                )
            ):
                raise ValueError(
                    "missing stop book must not invent execution"
                )
            return

        if self.execution_result is None:
            if self.status != "planning_rejected":
                raise ValueError(
                    "non-planning-rejection requires execution result"
                )
            return

        for value, field in (
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
            (self.stop_exit_fee, "stop_exit_fee"),
            (
                self.funding_through_execution,
                "funding_through_execution",
            ),
        ):
            if not isinstance(value, Decimal) or not value.is_finite():
                raise ValueError(
                    f"{field} must be present and finite"
                )
        requested = self.stop_requested_quantity
        filled = self.stop_filled_quantity
        unfilled = self.stop_unfilled_quantity
        if (
            not isinstance(requested, Decimal)
            or not isinstance(filled, Decimal)
            or not isinstance(unfilled, Decimal)
        ):
            raise ValueError(
                "stop quantities must be decimal values"
            )
        if requested <= ZERO or filled < ZERO or unfilled < ZERO:
            raise ValueError(
                "stop quantities are outside valid bounds"
            )
        if filled + unfilled != requested:
            raise ValueError(
                "stop fill and remainder must reconcile"
            )
        if self.stop_average_fill_price is not None and (
            not self.stop_average_fill_price.is_finite()
            or self.stop_average_fill_price <= ZERO
        ):
            raise ValueError(
                "stop average fill price must be positive"
            )
        if filled == ZERO and self.stop_average_fill_price is not None:
            raise ValueError(
                "zero stop fill must not have average fill price"
            )
        if filled > ZERO and self.stop_average_fill_price is None:
            raise ValueError(
                "positive stop fill requires average fill price"
            )

        exact = self.exact_full_stop_candidate_net_pnl
        if self.status == "full_stop_exit":
            if filled != requested or unfilled != ZERO:
                raise ValueError(
                    "full stop exit must fill requested quantity"
                )
            if exact is None or not exact.is_finite():
                raise ValueError(
                    "full stop exit requires exact candidate PnL"
                )
        elif exact is not None:
            raise ValueError(
                "non-full stop exit must not claim total candidate PnL"
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


def _funding_through_execution(
    trade: TradeJournalEntry,
    weighted: DelayedEntryFillWeightedOutcome,
    funding_loader: FundingLoader,
    *,
    candidate_open_ms: int,
    execution_ms: int,
) -> Decimal:
    accruals = trade_funding_accruals(
        trade,
        funding_loader,
    )
    if any(
        accrual.boundary_ms == execution_ms
        for accrual in accruals
    ):
        raise DelayedEntryStopL2FundingTimingAmbiguityError(
            "funding boundary coincides with stop execution"
        )
    return sum(
        (
            funding_cash_delta(
                accrual.signed_quantity
                * weighted.fill_fraction,
                accrual.oracle_price,
                accrual.funding_rate,
            )
            for accrual in accruals
            if (
                candidate_open_ms
                < accrual.boundary_ms
                < execution_ms
            )
        ),
        ZERO,
    )


def _candidate_position(
    trade: TradeJournalEntry,
    weighted: DelayedEntryFillWeightedOutcome,
    *,
    candidate_open_ms: int,
    stop_crossing_mark: Decimal,
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
        latest_mark=stop_crossing_mark,
    )


def _validate_stop_book_lineage(
    trade: TradeJournalEntry,
    proxy_stop_hit_ms: int,
    proxy_crossing_mark: Decimal,
    evidence: OriginalStopBookEvidence,
) -> None:
    crossing = evidence.crossing
    if (
        crossing.opening_plan_id != trade.opening_plan_id
        or crossing.market != trade.market.canonical
        or crossing.direction != trade.direction.value
        or crossing.original_stop != trade.initial_stop
        or crossing.crossing_mark_received_ms
        != proxy_stop_hit_ms
        or crossing.crossing_mark_price
        != proxy_crossing_mark
    ):
        raise DelayedEntryStopL2ReplayError(
            "stop-book evidence lineage mismatch"
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


def evaluate_delayed_entry_stop_l2_outcome(
    trade: TradeJournalEntry,
    outcome: DelayedEntryOutcome,
    weighted: DelayedEntryFillWeightedOutcome,
    raw_path: Mapping[str, object],
    stop_book_store: OriginalStopBookEvidenceStore,
    funding_loader: FundingLoader,
    config: PaperExecutionConfig,
    *,
    delay_ms: int = DELAY_MS,
) -> DelayedEntryStopL2Outcome | None:
    if weighted.delayed_filled_quantity == ZERO:
        return None

    proxy = evaluate_delayed_entry_stop_exit_proxy(
        trade,
        outcome,
        weighted,
        raw_path,
        funding_loader,
        config,
        delay_ms=delay_ms,
    )
    if proxy is None:
        raise DelayedEntryStopL2ReplayError(
            "filled delayed candidate lost stop proxy"
        )

    if not proxy.stop_hit:
        return DelayedEntryStopL2Outcome(
            trade_id=trade.trade_id,
            market=trade.market.canonical,
            direction=trade.direction.value,
            source=outcome.source,
            stop_hit=False,
            status="survived_same_exit",
            actual_net_pnl=trade.net_pnl,
            same_exit_candidate_net_pnl=(
                proxy.same_exit_candidate_net_pnl
            ),
            candidate_open_ms=proxy.candidate_open_ms,
            delayed_entry_price=proxy.delayed_entry_price,
            delayed_filled_quantity=(
                proxy.delayed_filled_quantity
            ),
            stop_hit_ms=None,
            stop_crossing_mark=None,
            execution_result=None,
            stop_requested_quantity=None,
            stop_filled_quantity=None,
            stop_unfilled_quantity=None,
            stop_average_fill_price=None,
            stop_exit_fee=None,
            funding_through_execution=None,
            exact_full_stop_candidate_net_pnl=None,
        )

    stop_hit_ms = proxy.stop_hit_ms
    crossing_mark = proxy.first_crossing_mark
    if stop_hit_ms is None or crossing_mark is None:
        raise DelayedEntryStopL2ReplayError(
            "stop proxy lost crossing evidence"
        )

    evidence = stop_book_store.evidence_for(
        trade.opening_plan_id
    )
    if evidence is None:
        return DelayedEntryStopL2Outcome(
            trade_id=trade.trade_id,
            market=trade.market.canonical,
            direction=trade.direction.value,
            source=outcome.source,
            stop_hit=True,
            status="stop_book_missing",
            actual_net_pnl=trade.net_pnl,
            same_exit_candidate_net_pnl=(
                proxy.same_exit_candidate_net_pnl
            ),
            candidate_open_ms=proxy.candidate_open_ms,
            delayed_entry_price=proxy.delayed_entry_price,
            delayed_filled_quantity=(
                proxy.delayed_filled_quantity
            ),
            stop_hit_ms=stop_hit_ms,
            stop_crossing_mark=crossing_mark,
            execution_result=None,
            stop_requested_quantity=None,
            stop_filled_quantity=None,
            stop_unfilled_quantity=None,
            stop_average_fill_price=None,
            stop_exit_fee=None,
            funding_through_execution=None,
            exact_full_stop_candidate_net_pnl=None,
        )

    _validate_stop_book_lineage(
        trade,
        stop_hit_ms,
        crossing_mark,
        evidence,
    )
    plan_instrument = evidence.plan_instrument_spec()
    execution_instrument = (
        evidence.execution_instrument_spec()
    )
    position = _candidate_position(
        trade,
        weighted,
        candidate_open_ms=proxy.candidate_open_ms,
        stop_crossing_mark=crossing_mark,
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
        timestamp_ms=stop_hit_ms,
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
        created_at_ms=stop_hit_ms,
    )
    if isinstance(planned, PlanningRejection):
        return DelayedEntryStopL2Outcome(
            trade_id=trade.trade_id,
            market=trade.market.canonical,
            direction=trade.direction.value,
            source=outcome.source,
            stop_hit=True,
            status="planning_rejected",
            actual_net_pnl=trade.net_pnl,
            same_exit_candidate_net_pnl=(
                proxy.same_exit_candidate_net_pnl
            ),
            candidate_open_ms=proxy.candidate_open_ms,
            delayed_entry_price=proxy.delayed_entry_price,
            delayed_filled_quantity=(
                proxy.delayed_filled_quantity
            ),
            stop_hit_ms=stop_hit_ms,
            stop_crossing_mark=crossing_mark,
            execution_result=None,
            stop_requested_quantity=None,
            stop_filled_quantity=None,
            stop_unfilled_quantity=None,
            stop_average_fill_price=None,
            stop_exit_fee=None,
            funding_through_execution=None,
            exact_full_stop_candidate_net_pnl=None,
        )

    execution_ms = evidence.execution_book_received_ms
    funding = _funding_through_execution(
        trade,
        weighted,
        funding_loader,
        candidate_open_ms=proxy.candidate_open_ms,
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
    status = {
        ExecutionResult.FULL: "full_stop_exit",
        ExecutionResult.PARTIAL: "partial_stop_exit",
        ExecutionResult.NO_FILL: "no_fill_stop_exit",
        ExecutionResult.REJECTED: "execution_rejected",
    }[attempt.result]

    exact_net: Decimal | None = None
    if attempt.result is ExecutionResult.FULL:
        exit_price = attempt.average_fill_price
        if exit_price is None:
            raise DelayedEntryStopL2ReplayError(
                "full stop exit lost average fill price"
            )
        exact_net = (
            _gross_pnl(
                direction=trade.direction.value,
                entry_price=proxy.delayed_entry_price,
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
        stop_hit=True,
        status=status,
        actual_net_pnl=trade.net_pnl,
        same_exit_candidate_net_pnl=(
            proxy.same_exit_candidate_net_pnl
        ),
        candidate_open_ms=proxy.candidate_open_ms,
        delayed_entry_price=proxy.delayed_entry_price,
        delayed_filled_quantity=(
            proxy.delayed_filled_quantity
        ),
        stop_hit_ms=stop_hit_ms,
        stop_crossing_mark=crossing_mark,
        execution_result=attempt.result.value,
        stop_requested_quantity=(
            attempt.requested_quantity
        ),
        stop_filled_quantity=attempt.filled_quantity,
        stop_unfilled_quantity=(
            attempt.unfilled_quantity
        ),
        stop_average_fill_price=(
            attempt.average_fill_price
        ),
        stop_exit_fee=attempt.fee,
        funding_through_execution=funding,
        exact_full_stop_candidate_net_pnl=exact_net,
    )


def _summary(
    items: Sequence[DelayedEntryStopL2Outcome],
) -> dict[str, object]:
    values = tuple(items)
    survivors = tuple(
        item for item in values
        if item.status == "survived_same_exit"
    )
    full = tuple(
        item for item in values
        if item.status == "full_stop_exit"
    )
    partial = tuple(
        item for item in values
        if item.status == "partial_stop_exit"
    )
    no_fill = tuple(
        item for item in values
        if item.status == "no_fill_stop_exit"
    )
    rejected = tuple(
        item for item in values
        if item.status in {
            "planning_rejected",
            "execution_rejected",
        }
    )
    missing = tuple(
        item for item in values
        if item.status == "stop_book_missing"
    )

    survivor_pnl = sum(
        (
            item.same_exit_candidate_net_pnl
            for item in survivors
        ),
        ZERO,
    )
    full_exact_pnl = sum(
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
    full_same_exit_pnl = sum(
        (
            item.same_exit_candidate_net_pnl
            for item in full
        ),
        ZERO,
    )
    resolved = survivors + full
    resolved_actual = sum(
        (item.actual_net_pnl for item in resolved),
        ZERO,
    )
    resolved_candidate = survivor_pnl + full_exact_pnl

    return {
        "evaluated_filled_candidates": len(values),
        "survived_same_exit": len(survivors),
        "stop_crossings": sum(
            1 for item in values if item.stop_hit
        ),
        "stop_book_missing": len(missing),
        "full_stop_exits": len(full),
        "partial_stop_exits": len(partial),
        "no_fill_stop_exits": len(no_fill),
        "planning_or_execution_rejections": len(rejected),
        "resolved_candidates": len(resolved),
        "unresolved_stop_crossings": (
            len(missing)
            + len(partial)
            + len(no_fill)
            + len(rejected)
        ),
        "resolved_actual_net_pnl": str(resolved_actual),
        "resolved_candidate_net_pnl": str(
            resolved_candidate
        ),
        "resolved_delta_vs_actual": str(
            resolved_candidate - resolved_actual
        ),
        "same_exit_pnl_on_full_stop_exits": str(
            full_same_exit_pnl
        ),
        "exact_pnl_on_full_stop_exits": str(
            full_exact_pnl
        ),
        "same_exit_minus_exact_on_full_stop_exits": str(
            full_same_exit_pnl - full_exact_pnl
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

    evaluated: list[DelayedEntryStopL2Outcome] = []
    unresolved_outcomes = 0
    candidate_no_fill = 0
    missing_journal = 0
    missing_paths = 0
    incomplete_or_gapped_paths = 0
    missing_funding_events = 0
    ambiguous_funding_timing = 0
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
                delay_ms=delay_ms,
            )
        except DelayedEntryFundingMissingError:
            missing_funding_events += 1
            continue
        except (
            DelayedEntryStopExitTimingAmbiguityError,
            DelayedEntryStopL2FundingTimingAmbiguityError,
        ):
            ambiguous_funding_timing += 1
            continue
        except DelayedEntryStopTimingError:
            invalid_candidate_timing += 1
            continue
        except OriginalStopBookEvidenceError:
            stop_book_capture_errors += 1
            continue
        except (
            DelayedEntryFundingError,
            DelayedEntryStopSurvivabilityError,
            DelayedEntryStopExitProxyError,
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
    full_stop_exits = int(
        overall["full_stop_exits"]
    )
    integrity_clean = (
        unresolved_outcomes == 0
        and missing_journal == 0
        and missing_paths == 0
        and incomplete_or_gapped_paths == 0
        and missing_funding_events == 0
        and ambiguous_funding_timing == 0
        and lineage_mismatches == 0
        and invalid_candidate_timing == 0
        and stop_book_capture_errors == 0
    )

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "claim_scope": (
            "prospective_original_stop_visible_l2_first_ioc_replay"
        ),
        "delay_ms": delay_ms,
        "stop_exit_policy": (
            "paper_reduce_only_plan_plus_visible_book_ioc"
        ),
        "partial_remainder_modeled": False,
        "replacement_exit_modeled": False,
        "closed_shadow_outcomes": len(outcomes),
        "candidate_no_fill_trades": candidate_no_fill,
        "unresolved_outcomes": unresolved_outcomes,
        "missing_journal_trades": missing_journal,
        "missing_exact_paths": missing_paths,
        "incomplete_or_gapped_paths": (
            incomplete_or_gapped_paths
        ),
        "missing_funding_events": missing_funding_events,
        "ambiguous_funding_timing": (
            ambiguous_funding_timing
        ),
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
            "complete_stop_crossing_cohort": (
                int(overall["stop_book_missing"]) == 0
            ),
        },
    }
