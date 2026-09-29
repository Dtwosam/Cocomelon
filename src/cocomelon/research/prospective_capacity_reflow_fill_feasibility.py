from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Final

from cocomelon.domain.execution import (
    ExecutionResult,
    PaperExecutionConfig,
    PaperOrderPlan,
)
from cocomelon.domain.risk import OpenPositionRisk, RiskRequest
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.evidence.openings import conservative_cost_estimate
from cocomelon.execution.accounting import (
    DAY_MS,
    PaperPosition,
    PositionSide,
)
from cocomelon.execution.ioc import simulate_ioc
from cocomelon.execution.planner import (
    PlanningRejection,
    plan_opening_order,
)
from cocomelon.journal.store import JournalStore
from cocomelon.research.continuous_paper_learning import (
    ContinuousPaperOpeningLineageStore,
)
from cocomelon.research.continuous_paper_opening_opportunity import (
    ContinuousPaperOpeningOpportunityEvidence,
    ContinuousPaperOpeningOpportunityStore,
)
from cocomelon.research.continuous_paper_opening_rank import (
    ContinuousPaperOpeningRankStore,
)
from cocomelon.research.exact_decimal_aggregation import (
    exact_decimal_sum,
)
from cocomelon.research.prospective_capacity_reflow_opportunities import (
    candidate_eligible_capacity_release_options,
)
from cocomelon.research.prospective_capacity_reflow_release_lineage import (
    CandidateCausedCapacityRelease,
    candidate_caused_capacity_release_options,
)
from cocomelon.research.prospective_combined_entry_filter import (
    ProspectiveCombinedEntryFilterState,
)
from cocomelon.risk.engine import evaluate_risk

ZERO: Final = Decimal("0")

PositionHistoryLoader = Callable[
    [str, int],
    tuple[PaperPosition, ...],
]


class ProspectiveCapacityReflowFillFeasibilityError(RuntimeError):
    pass


def _receive_ms(
    evidence: ContinuousPaperOpeningOpportunityEvidence,
) -> int:
    return int(
        evidence.book_event.receive_time.timestamp() * 1000
    )


def _position_cash_contribution(position: PaperPosition) -> Decimal:
    return (
        position.cumulative_realized_gross_pnl
        - position.cumulative_fees
        + position.cumulative_funding
    )


def _position_unrealized(position: PaperPosition) -> Decimal:
    mark = position.latest_mark
    if mark is None:
        raise ProspectiveCapacityReflowFillFeasibilityError(
            "release position is missing decision-time mark"
        )
    if position.side is PositionSide.LONG:
        return (
            mark - position.average_entry_price
        ) * position.quantity
    return (
        position.average_entry_price - mark
    ) * position.quantity


def _position_total_contribution(
    position: PaperPosition,
) -> Decimal:
    return (
        _position_cash_contribution(position)
        + _position_unrealized(position)
    )


def _risk_position(
    request: RiskRequest,
    release: CandidateCausedCapacityRelease,
) -> OpenPositionRisk:
    matches = tuple(
        position
        for position in request.open_positions
        if position.market.canonical == release.release_market
    )
    if len(matches) != 1:
        raise ProspectiveCapacityReflowFillFeasibilityError(
            "release risk position is missing or ambiguous"
        )
    return matches[0]


def _validate_position_lineage(
    risk_position: OpenPositionRisk,
    current: PaperPosition,
    release: CandidateCausedCapacityRelease,
    *,
    opportunity_timestamp_ms: int,
) -> None:
    if (
        current.opening_plan_id
        != release.release_opening_plan_id
        or current.market.canonical != release.release_market
        or current.correlation_bucket
        != release.release_correlation_bucket
        or current.updated_at_ms != opportunity_timestamp_ms
    ):
        raise ProspectiveCapacityReflowFillFeasibilityError(
            "release position history does not match opportunity"
        )
    expected_direction = (
        "long"
        if current.side is PositionSide.LONG
        else "short"
    )
    mark = current.latest_mark
    if mark is None:
        raise ProspectiveCapacityReflowFillFeasibilityError(
            "release position is missing decision-time mark"
        )
    if (
        risk_position.direction.value != expected_direction
        or risk_position.planned_risk != current.planned_risk
        or risk_position.notional != mark * current.quantity
        or risk_position.correlation_bucket
        != current.correlation_bucket
        or risk_position.entry_price
        != current.average_entry_price
        or risk_position.stop_price != current.stop_price
    ):
        raise ProspectiveCapacityReflowFillFeasibilityError(
            "release risk position does not match execution history"
        )


def _execution_config_compatible(
    evidence: ContinuousPaperOpeningOpportunityEvidence,
    config: PaperExecutionConfig,
) -> None:
    request = evidence.risk_request_object
    if request.cost_estimate != conservative_cost_estimate(config):
        raise ProspectiveCapacityReflowFillFeasibilityError(
            "execution config does not match captured cost estimate"
        )
    instrument = evidence.instrument_object
    if (
        instrument.minimum_order_notional
        != config.native_perp_min_notional
        or request.limits.max_gross_leverage
        != config.paper_max_gross_leverage
    ):
        raise ProspectiveCapacityReflowFillFeasibilityError(
            "execution config does not match captured risk envelope"
        )
    earliest_ms = (
        request.strategy_decision.timestamp_ms
        + config.latency_ms
    )
    if (
        request.timestamp_ms < earliest_ms
        or _receive_ms(evidence) < earliest_ms
    ):
        raise ProspectiveCapacityReflowFillFeasibilityError(
            "execution latency does not match captured opening timing"
        )


def _counterfactual_request(
    evidence: ContinuousPaperOpeningOpportunityEvidence,
    release: CandidateCausedCapacityRelease,
    history: tuple[PaperPosition, ...],
    config: PaperExecutionConfig,
) -> tuple[RiskRequest, Decimal]:
    if not history:
        raise ProspectiveCapacityReflowFillFeasibilityError(
            "release position history is missing"
        )
    request = evidence.risk_request_object
    if release.opportunity_id != evidence.opportunity_id:
        raise ProspectiveCapacityReflowFillFeasibilityError(
            "release opportunity id mismatch"
        )
    if (
        release.opportunity_timestamp_ms
        != evidence.opportunity_timestamp_ms
        or release.opportunity_market != evidence.market
    ):
        raise ProspectiveCapacityReflowFillFeasibilityError(
            "release opportunity lineage mismatch"
        )

    decision_time_states = tuple(
        position
        for position in history
        if position.updated_at_ms
        == evidence.opportunity_timestamp_ms
    )
    if len(decision_time_states) != 1:
        raise ProspectiveCapacityReflowFillFeasibilityError(
            "release position decision-time history is missing or ambiguous"
        )
    current = decision_time_states[0]
    risk_position = _risk_position(request, release)
    _validate_position_lineage(
        risk_position,
        current,
        release,
        opportunity_timestamp_ms=evidence.opportunity_timestamp_ms,
    )
    day_start_ms = (
        evidence.opportunity_timestamp_ms // DAY_MS
    ) * DAY_MS
    if current.opened_at_ms < day_start_ms:
        raise ProspectiveCapacityReflowFillFeasibilityError(
            "cross-day release position requires cash-boundary replay"
        )
    if any(
        position.opening_plan_id
        != release.release_opening_plan_id
        or position.opened_at_ms != current.opened_at_ms
        or position.updated_at_ms
        > evidence.opportunity_timestamp_ms
        for position in history
    ):
        raise ProspectiveCapacityReflowFillFeasibilityError(
            "release position history lineage mismatch"
        )

    account = request.account_state
    if account.available_margin <= ZERO:
        raise ProspectiveCapacityReflowFillFeasibilityError(
            "baseline reserved margin is not exactly recoverable"
        )
    mark = current.latest_mark
    assert mark is not None
    release_notional = mark * current.quantity
    baseline_reserved = (
        account.equity - account.available_margin
    )
    leverage = min(
        config.paper_max_gross_leverage,
        current.venue_max_leverage,
    )
    release_reserved = release_notional / leverage
    counterfactual_reserved = (
        baseline_reserved - release_reserved
    )
    counterfactual_gross = (
        account.gross_open_notional - release_notional
    )
    if (
        counterfactual_reserved < ZERO
        or counterfactual_gross < ZERO
    ):
        raise ProspectiveCapacityReflowFillFeasibilityError(
            "release position exceeds captured account capacity"
        )

    cash_contribution = _position_cash_contribution(current)
    total_contribution = _position_total_contribution(current)
    counterfactual_equity = (
        account.equity - total_contribution
    )
    counterfactual_daily = (
        account.daily_realized_pnl - cash_contribution
    )
    if counterfactual_equity <= ZERO:
        raise ProspectiveCapacityReflowFillFeasibilityError(
            "counterfactual equity is non-positive"
        )
    counterfactual_available = (
        counterfactual_equity - counterfactual_reserved
    )
    if counterfactual_available < ZERO:
        raise ProspectiveCapacityReflowFillFeasibilityError(
            "counterfactual available margin is negative"
        )

    contributions = tuple(
        _position_total_contribution(position)
        for position in history
    )
    minimum_contribution = min(contributions)
    peak_upper_bound = (
        account.rolling_7d_peak_equity
        + max(ZERO, -minimum_contribution)
    )
    peak_upper_bound = max(
        peak_upper_bound,
        counterfactual_equity,
    )

    counterfactual_account = replace(
        account,
        equity=counterfactual_equity,
        daily_realized_pnl=counterfactual_daily,
        rolling_7d_peak_equity=peak_upper_bound,
        available_margin=counterfactual_available,
        gross_open_notional=counterfactual_gross,
    )
    remaining_positions = tuple(
        position
        for position in request.open_positions
        if position.market.canonical
        != release.release_market
    )
    if len(remaining_positions) != len(
        request.open_positions
    ) - 1:
        raise ProspectiveCapacityReflowFillFeasibilityError(
            "release position removal did not change portfolio"
        )
    return (
        replace(
            request,
            account_state=counterfactual_account,
            open_positions=remaining_positions,
        ),
        counterfactual_equity - account.equity,
    )


@dataclass(frozen=True, slots=True)
class CandidateReplacementEntryFill:
    opportunity_id: str
    opportunity_timestamp_ms: int
    opportunity_market: str
    direction: str
    release_market: str
    release_opening_plan_id: str
    release_block_reason: str
    counterfactual_equity_delta: Decimal
    risk_approved: bool
    risk_reason_codes: tuple[str, ...]
    replacement_plan_id: str | None
    planning_rejection_reason: str | None
    execution_attempt_id: str | None
    execution_result: ExecutionResult | None
    execution_reason_codes: tuple[str, ...]
    requested_quantity: Decimal | None
    filled_quantity: Decimal
    average_fill_price: Decimal | None
    gross_fill_notional: Decimal
    taker_fee: Decimal
    fill_ids: tuple[str, ...]

    @property
    def fillable(self) -> bool:
        return (
            self.filled_quantity > ZERO
            and self.average_fill_price is not None
            and self.gross_fill_notional > ZERO
        )


def candidate_caused_replacement_entry_fill_records(
    opportunities: tuple[
        ContinuousPaperOpeningOpportunityEvidence,
        ...,
    ],
    releases: tuple[CandidateCausedCapacityRelease, ...],
    config: PaperExecutionConfig,
    *,
    position_history_loader: PositionHistoryLoader,
) -> tuple[CandidateReplacementEntryFill, ...]:
    by_id = {
        evidence.opportunity_id: evidence
        for evidence in opportunities
    }
    if len(by_id) != len(opportunities):
        raise ProspectiveCapacityReflowFillFeasibilityError(
            "duplicate opening opportunity ids"
        )

    output: list[CandidateReplacementEntryFill] = []
    for release in releases:
        evidence = by_id.get(release.opportunity_id)
        if evidence is None:
            raise ProspectiveCapacityReflowFillFeasibilityError(
                "candidate release opportunity evidence is missing"
            )
        _execution_config_compatible(evidence, config)
        history = position_history_loader(
            release.release_opening_plan_id,
            evidence.opportunity_timestamp_ms,
        )
        request, equity_delta = _counterfactual_request(
            evidence,
            release,
            history,
            config,
        )
        risk = evaluate_risk(request)

        def record(
            *,
            replacement_plan_id: str | None,
            planning_rejection_reason: str | None,
            execution_attempt_id: str | None,
            execution_result: ExecutionResult | None,
            execution_reason_codes: tuple[str, ...],
            requested_quantity: Decimal | None,
            filled_quantity: Decimal,
            average_fill_price: Decimal | None,
            gross_fill_notional: Decimal,
            taker_fee: Decimal,
            fill_ids: tuple[str, ...],
        ) -> CandidateReplacementEntryFill:
            return CandidateReplacementEntryFill(
                opportunity_id=evidence.opportunity_id,
                opportunity_timestamp_ms=(
                    evidence.opportunity_timestamp_ms
                ),
                opportunity_market=evidence.market,
                direction=evidence.direction,
                release_market=release.release_market,
                release_opening_plan_id=(
                    release.release_opening_plan_id
                ),
                release_block_reason=release.release_block_reason,
                counterfactual_equity_delta=equity_delta,
                risk_approved=risk.approved,
                risk_reason_codes=risk.reason_codes,
                replacement_plan_id=replacement_plan_id,
                planning_rejection_reason=(
                    planning_rejection_reason
                ),
                execution_attempt_id=execution_attempt_id,
                execution_result=execution_result,
                execution_reason_codes=execution_reason_codes,
                requested_quantity=requested_quantity,
                filled_quantity=filled_quantity,
                average_fill_price=average_fill_price,
                gross_fill_notional=gross_fill_notional,
                taker_fee=taker_fee,
                fill_ids=fill_ids,
            )
        if not risk.approved:
            output.append(
                record(
                    replacement_plan_id=None,
                    planning_rejection_reason=None,
                    execution_attempt_id=None,
                    execution_result=None,
                    execution_reason_codes=(),
                    requested_quantity=None,
                    filled_quantity=ZERO,
                    average_fill_price=None,
                    gross_fill_notional=ZERO,
                    taker_fee=ZERO,
                    fill_ids=(),
                )
            )
            continue

        plan = plan_opening_order(
            risk,
            evidence.instrument_object,
            config,
            request.entry_reference_price,
            request.strategy_decision.timestamp_ms,
        )
        if isinstance(plan, PlanningRejection):
            output.append(
                record(
                    replacement_plan_id=None,
                    planning_rejection_reason=plan.reason,
                    execution_attempt_id=None,
                    execution_result=None,
                    execution_reason_codes=(),
                    requested_quantity=None,
                    filled_quantity=ZERO,
                    average_fill_price=None,
                    gross_fill_notional=ZERO,
                    taker_fee=ZERO,
                    fill_ids=(),
                )
            )
            continue

        simulation = simulate_ioc(
            plan,
            evidence.book_event,
            evidence.instrument_object,
            config,
            attempt_timestamp_ms=request.timestamp_ms,
        )
        output.append(
            record(
                replacement_plan_id=plan.plan_id,
                planning_rejection_reason=None,
                execution_attempt_id=simulation.attempt.attempt_id,
                execution_result=simulation.attempt.result,
                execution_reason_codes=(
                    simulation.attempt.reason_codes
                ),
                requested_quantity=plan.requested_quantity,
                filled_quantity=(
                    simulation.attempt.filled_quantity
                ),
                average_fill_price=(
                    simulation.attempt.average_fill_price
                ),
                gross_fill_notional=(
                    simulation.attempt.gross_fill_notional
                ),
                taker_fee=simulation.attempt.fee,
                fill_ids=tuple(
                    fill.fill_id for fill in simulation.fills
                ),
            )
        )
    return tuple(output)


def prospective_capacity_reflow_fill_feasibility_summary(
    opportunities: tuple[
        ContinuousPaperOpeningOpportunityEvidence,
        ...,
    ],
    releases: tuple[CandidateCausedCapacityRelease, ...],
    config: PaperExecutionConfig,
    *,
    position_history_loader: PositionHistoryLoader,
) -> dict[str, object]:
    records = candidate_caused_replacement_entry_fill_records(
        opportunities,
        releases,
        config,
        position_history_loader=position_history_loader,
    )
    opportunity_ids = {
        record.opportunity_id for record in records
    }
    risk_approvals = sum(
        1 for record in records if record.risk_approved
    )
    planning_approvals = sum(
        1
        for record in records
        if record.replacement_plan_id is not None
    )
    fillable = sum(1 for record in records if record.fillable)
    full_fills = sum(
        1
        for record in records
        if record.execution_result is ExecutionResult.FULL
    )
    partial_fills = sum(
        1
        for record in records
        if record.execution_result is ExecutionResult.PARTIAL
    )
    no_fills = sum(
        1
        for record in records
        if record.execution_result is ExecutionResult.NO_FILL
    )
    execution_rejections = sum(
        1
        for record in records
        if record.execution_result is ExecutionResult.REJECTED
    )
    by_opportunity_market = Counter(
        record.opportunity_market for record in records
    )
    by_release_market = Counter(
        record.release_market for record in records
    )
    by_risk_rejection: Counter[str] = Counter()
    by_planning_rejection: Counter[str] = Counter()
    by_execution_result: Counter[str] = Counter()
    for record in records:
        if not record.risk_approved:
            by_risk_rejection[
                record.risk_reason_codes[0]
                if record.risk_reason_codes
                else "unknown"
            ] += 1
        if record.planning_rejection_reason is not None:
            by_planning_rejection[
                record.planning_rejection_reason
            ] += 1
        if record.execution_result is not None:
            by_execution_result[
                record.execution_result.value
            ] += 1

    equity_deltas = tuple(
        record.counterfactual_equity_delta
        for record in records
    )
    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "claim_scope": (
            "candidate_caused_single_release_"
            "decision_time_replacement_entry_fill_sensitivity"
        ),
        "portfolio_counterfactual": False,
        "other_baseline_positions_held_fixed": True,
        "other_positions_replayed": False,
        "counterfactual_account_scope": (
            "same_utc_day_single_release_exact_accounting_"
            "other_baseline_positions_fixed_conservative_peak_bound"
        ),
        "execution_config_compatibility": (
            "captured_cost_min_notional_leverage_and_latency"
        ),
        "candidate_caused_release_options": len(records),
        "candidate_caused_release_opportunities": len(
            opportunity_ids
        ),
        "conservative_risk_approvals": risk_approvals,
        "planning_approvals": planning_approvals,
        "fillable_options": fillable,
        "full_fill_options": full_fills,
        "partial_fill_options": partial_fills,
        "no_fill_options": no_fills,
        "execution_rejected_options": execution_rejections,
        "gross_fill_notional": str(
            exact_decimal_sum(
                record.gross_fill_notional
                for record in records
            )
        ),
        "taker_fees": str(
            exact_decimal_sum(
                record.taker_fee for record in records
            )
        ),
        "counterfactual_equity_delta_min": (
            None if not equity_deltas else str(min(equity_deltas))
        ),
        "counterfactual_equity_delta_max": (
            None if not equity_deltas else str(max(equity_deltas))
        ),
        "by_opportunity_market": dict(
            sorted(by_opportunity_market.items())
        ),
        "by_release_market": dict(
            sorted(by_release_market.items())
        ),
        "by_risk_rejection": dict(
            sorted(by_risk_rejection.items())
        ),
        "by_planning_rejection": dict(
            sorted(by_planning_rejection.items())
        ),
        "by_execution_result": dict(
            sorted(by_execution_result.items())
        ),
        "account_capacity_credit_mode": (
            "exact_single_release_accounting_other_positions_fixed"
        ),
        "replacement_entry_fills_modeled": True,
        "replacement_exits_modeled": False,
        "replacement_trades_modeled": False,
        "pnl_modeled": False,
    }

def evaluate_prospective_capacity_reflow_fill_feasibility(
    opportunity_store: ContinuousPaperOpeningOpportunityStore,
    lineage_store: ContinuousPaperOpeningLineageStore,
    journal: JournalStore,
    *,
    plan_loader: Callable[[str], PaperOrderPlan | None],
    fact_store: EvaluationFactStore,
    rank_store: ContinuousPaperOpeningRankStore,
    state: ProspectiveCombinedEntryFilterState,
    config: PaperExecutionConfig,
    position_history_loader: PositionHistoryLoader,
) -> dict[str, object]:
    options = candidate_eligible_capacity_release_options(
        opportunity_store.iter_records(),
        state,
    )
    releases = candidate_caused_capacity_release_options(
        options,
        lineage_store.iter_records(),
        tuple(journal.iter_trades()),
        plan_loader=plan_loader,
        fact_loader=fact_store.load_decision_by_strategy_id,
        rank_loader=rank_store.load,
    )
    return prospective_capacity_reflow_fill_feasibility_summary(
        opportunity_store.iter_records(),
        releases,
        config,
        position_history_loader=position_history_loader,
    )
