from __future__ import annotations

from collections import Counter
from decimal import Decimal
from typing import Final

from cocomelon.domain.execution import (
    ExecutionResult,
    PaperExecutionConfig,
    PositionAction,
    PositionActionType,
)
from cocomelon.execution.accounting import PaperPosition, PositionSide
from cocomelon.execution.ioc import simulate_ioc
from cocomelon.execution.planner import (
    PlanningRejection,
    plan_reduce_only_order,
)
from cocomelon.research.continuous_paper_capacity_release_books import (
    CapacityReleaseBookEvidence,
    paper_execution_config_from_payload,
    paper_execution_config_payload,
)

ZERO: Final = Decimal("0")


class CorrelationHolderReleaseExecutionError(RuntimeError):
    pass


def _gross_pnl(
    *,
    side: PositionSide,
    entry_price: Decimal,
    exit_price: Decimal,
    quantity: Decimal,
) -> Decimal:
    if side is PositionSide.LONG:
        return (exit_price - entry_price) * quantity
    return (entry_price - exit_price) * quantity


def _resolved_config(
    evidence: CapacityReleaseBookEvidence,
    expected_config: PaperExecutionConfig | None,
) -> tuple[str | None, PaperExecutionConfig | None]:
    pending = evidence.pending
    if pending.execution_config is None:
        return "unbound_execution_config", None
    config = paper_execution_config_from_payload(
        pending.execution_config
    )
    if (
        expected_config is not None
        and pending.execution_config
        != paper_execution_config_payload(expected_config)
    ):
        return "execution_config_mismatch", None
    if pending.plan_observed_at_ms + config.latency_ms > (
        evidence.execution_observed_at_ms
    ):
        raise CorrelationHolderReleaseExecutionError(
            "release execution evidence predates configured paper latency"
        )
    if (
        evidence.execution_observed_at_ms
        - int(evidence.execution_book_event.receive_time.timestamp() * 1000)
        > config.max_book_age_ms
    ):
        raise CorrelationHolderReleaseExecutionError(
            "release execution book exceeds configured freshness"
        )
    if (
        pending.plan_instrument.minimum_order_notional
        != config.native_perp_min_notional
        or evidence.execution_instrument.minimum_order_notional
        != config.native_perp_min_notional
    ):
        raise CorrelationHolderReleaseExecutionError(
            "release execution config does not match captured instrument"
        )
    return None, config


def _terminal_contribution(
    position: PaperPosition,
    *,
    close_gross_pnl: Decimal,
    close_fee: Decimal,
) -> Decimal:
    return (
        position.cumulative_realized_gross_pnl
        + close_gross_pnl
        - position.cumulative_fees
        + position.cumulative_funding
        - close_fee
    )


def correlation_holder_release_execution_summary(
    evidence: tuple[CapacityReleaseBookEvidence, ...],
    config: PaperExecutionConfig | None = None,
) -> dict[str, object]:
    seen_registration_ids: set[str] = set()
    by_execution_result: Counter[str] = Counter()
    by_release_market: Counter[str] = Counter()
    by_opportunity_market: Counter[str] = Counter()
    rows: list[dict[str, object]] = []
    full_close_terminal_contribution_by_plan: dict[str, str] = {}

    exact_config_records = 0
    unbound_execution_config_records = 0
    execution_config_mismatch_records = 0
    planned = 0
    planning_rejected = 0
    full_fills = 0
    partial_fills = 0
    no_fills = 0
    execution_rejections = 0
    gross_realized_pnl = ZERO
    close_fees = ZERO
    fully_closed_terminal_contribution = ZERO
    unclosed_quantity = ZERO

    for item in sorted(
        evidence,
        key=lambda value: (
            value.registration.opportunity_timestamp_ms,
            value.registration.opportunity_id,
            value.release_opening_plan_id,
        ),
    ):
        registration = item.registration
        registration_id = registration.registration_id
        if registration_id in seen_registration_ids:
            raise CorrelationHolderReleaseExecutionError(
                "duplicate capacity release execution evidence"
            )
        seen_registration_ids.add(registration_id)
        config_status, replay_config = _resolved_config(item, config)
        if config_status is not None:
            if config_status == "unbound_execution_config":
                unbound_execution_config_records += 1
            else:
                execution_config_mismatch_records += 1
            rows.append(
                {
                    "registration_id": registration_id,
                    "opportunity_id": registration.opportunity_id,
                    "opportunity_timestamp_ms": (
                        registration.opportunity_timestamp_ms
                    ),
                    "opportunity_market": registration.opportunity_market,
                    "opportunity_direction": registration.opportunity_direction,
                    "release_market": registration.release_market,
                    "release_direction": registration.release_direction,
                    "release_correlation_bucket": (
                        registration.release_correlation_bucket
                    ),
                    "release_opening_plan_id": item.release_opening_plan_id,
                    "status": config_status,
                    "planning_approved": False,
                    "execution_result": None,
                    "complete_close": False,
                }
            )
            continue
        exact_config_records += 1
        if replay_config is None:
            raise CorrelationHolderReleaseExecutionError(
                "resolved execution config is unexpectedly missing"
            )

        position = item.release_position
        if position.quantity <= ZERO:
            raise CorrelationHolderReleaseExecutionError(
                "release position quantity must be positive"
            )
        if (
            position.market.canonical != registration.release_market
            or position.side.value != registration.release_direction
        ):
            raise CorrelationHolderReleaseExecutionError(
                "release position lineage mismatch"
            )

        action = PositionAction(
            action_type=PositionActionType.EXIT_THESIS,
            market=position.market,
            quantity=position.quantity,
            new_stop_price=None,
            reason_codes=("correlation_slot_replacement_shadow",),
            timestamp_ms=item.pending.plan_observed_at_ms,
        )
        plan = plan_reduce_only_order(
            position,
            action,
            item.pending.plan_instrument,
            replay_config,
            originating_risk_decision_id=(
                position.initial_risk_decision_id
                if position.initial_risk_decision_id
                else None
            ),
            reference_price=item.pending.plan_reference_price,
            created_at_ms=item.pending.plan_observed_at_ms,
        )
        row: dict[str, object] = {
            "registration_id": registration_id,
            "opportunity_id": registration.opportunity_id,
            "opportunity_timestamp_ms": registration.opportunity_timestamp_ms,
            "opportunity_market": registration.opportunity_market,
            "opportunity_direction": registration.opportunity_direction,
            "release_market": registration.release_market,
            "release_direction": registration.release_direction,
            "release_correlation_bucket": (
                registration.release_correlation_bucket
            ),
            "release_opening_plan_id": item.release_opening_plan_id,
            "plan_observed_at_ms": item.pending.plan_observed_at_ms,
            "execution_observed_at_ms": item.execution_observed_at_ms,
            "requested_quantity": str(position.quantity),
            "status": "eligible_exact_replay",
            "planning_approved": False,
            "planning_rejection": None,
            "execution_result": None,
            "filled_quantity": None,
            "unfilled_quantity": None,
            "average_exit_price": None,
            "gross_exit_notional": None,
            "gross_realized_pnl": None,
            "close_fee": None,
            "incremental_release_net_pnl": None,
            "full_close_terminal_contribution": None,
            "complete_close": False,
        }

        if isinstance(plan, PlanningRejection):
            planning_rejected += 1
            by_execution_result["planning_rejected"] += 1
            row["planning_rejection"] = plan.reason
            rows.append(row)
            continue

        planned += 1
        row["planning_approved"] = True
        simulation = simulate_ioc(
            plan,
            item.execution_book_event,
            item.execution_instrument,
            replay_config,
            attempt_timestamp_ms=item.execution_observed_at_ms,
        )
        attempt = simulation.attempt
        by_execution_result[attempt.result.value] += 1
        by_release_market[registration.release_market] += 1
        by_opportunity_market[registration.opportunity_market] += 1

        close_gross = sum(
            (
                _gross_pnl(
                    side=position.side,
                    entry_price=position.average_entry_price,
                    exit_price=fill.price,
                    quantity=fill.quantity,
                )
                for fill in simulation.fills
            ),
            ZERO,
        )
        close_fee = attempt.fee
        incremental_net = close_gross - close_fee
        unclosed = position.quantity - attempt.filled_quantity
        complete_close = unclosed == ZERO

        if complete_close:
            full_fills += 1
            terminal = _terminal_contribution(
                position,
                close_gross_pnl=close_gross,
                close_fee=close_fee,
            )
            existing = full_close_terminal_contribution_by_plan.get(
                position.opening_plan_id
            )
            encoded_terminal = str(terminal)
            if existing is not None and existing != encoded_terminal:
                raise CorrelationHolderReleaseExecutionError(
                    "conflicting full-close terminal contribution"
                )
            full_close_terminal_contribution_by_plan[
                position.opening_plan_id
            ] = encoded_terminal
            fully_closed_terminal_contribution += terminal
            row["full_close_terminal_contribution"] = encoded_terminal
        elif attempt.filled_quantity > ZERO:
            partial_fills += 1
        elif attempt.result is ExecutionResult.NO_FILL:
            no_fills += 1
        else:
            execution_rejections += 1

        gross_realized_pnl += close_gross
        close_fees += close_fee
        unclosed_quantity += unclosed
        row.update(
            {
                "execution_result": attempt.result.value,
                "filled_quantity": str(attempt.filled_quantity),
                "unfilled_quantity": str(attempt.unfilled_quantity),
                "average_exit_price": (
                    None
                    if attempt.average_fill_price is None
                    else str(attempt.average_fill_price)
                ),
                "gross_exit_notional": str(attempt.gross_fill_notional),
                "gross_realized_pnl": str(close_gross),
                "close_fee": str(close_fee),
                "incremental_release_net_pnl": str(incremental_net),
                "complete_close": complete_close,
            }
        )
        rows.append(row)

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_risk_limits": False,
        "changes_positions": False,
        "captured_release_books": len(evidence),
        "exact_execution_config_records": exact_config_records,
        "unbound_execution_config_records": (
            unbound_execution_config_records
        ),
        "execution_config_mismatch_records": (
            execution_config_mismatch_records
        ),
        "planned_release_exits": planned,
        "planning_rejected_release_exits": planning_rejected,
        "full_release_fills": full_fills,
        "partial_release_fills": partial_fills,
        "no_release_fills": no_fills,
        "execution_rejected_release_exits": execution_rejections,
        "gross_realized_pnl": str(gross_realized_pnl),
        "close_fees": str(close_fees),
        "fully_closed_terminal_contribution": str(
            fully_closed_terminal_contribution
        ),
        "unclosed_quantity": str(unclosed_quantity),
        "full_close_terminal_contribution_by_plan": (
            full_close_terminal_contribution_by_plan
        ),
        "by_execution_result": dict(sorted(by_execution_result.items())),
        "by_release_market": dict(sorted(by_release_market.items())),
        "by_opportunity_market": dict(
            sorted(by_opportunity_market.items())
        ),
        "execution_config_authority": "bound_per_record",
        "expected_config_enforced": config is not None,
        "release_results": rows,
        "holder_release_execution_modeled": True,
        "exact_execution_config_required": True,
        "newcomer_entry_modeled": False,
        "newcomer_exit_modeled": False,
        "replacement_trade_modeled": False,
        "schema_version": 1,
    }
