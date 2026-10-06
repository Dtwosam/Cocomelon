from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from cocomelon.domain.execution import (
    ExecutionResult,
    PaperExecutionConfig,
    PositionAction,
    PositionActionType,
)
from cocomelon.execution.accounting import PositionSide
from cocomelon.execution.ioc import simulate_ioc
from cocomelon.execution.planner import (
    PlanningRejection,
    plan_reduce_only_order,
)
from cocomelon.research.continuous_paper_capacity_release_books import (
    CapacityReleaseBookEvidence,
)

ZERO: Final = Decimal("0")
BPS: Final = Decimal("10000")
RELEASE_REASON: Final = "correlation_capacity_release_shadow"


class CapacityReleaseExecutionShadowError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CapacityReleaseExecutionRow:
    registration_id: str
    opportunity_id: str
    opportunity_timestamp_ms: int
    opportunity_market: str
    opportunity_direction: str
    release_market: str
    release_direction: str
    release_opening_plan_id: str
    holder_quantity: Decimal
    holder_average_entry_price: Decimal
    plan_observed_at_ms: int
    plan_reference_price: Decimal
    execution_observed_at_ms: int
    planning_approved: bool
    planning_rejection: str | None
    execution_result: str | None
    execution_reason_codes: tuple[str, ...]
    requested_quantity: Decimal | None
    filled_quantity: Decimal | None
    unfilled_quantity: Decimal | None
    average_fill_price: Decimal | None
    gross_fill_notional: Decimal | None
    taker_fee: Decimal | None
    full_slot_release: bool
    gross_release_delta_vs_plan_mark: Decimal | None
    net_release_delta_vs_plan_mark: Decimal | None
    gross_close_pnl_vs_entry: Decimal | None
    net_close_pnl_vs_entry: Decimal | None
    favorable_execution_bps_vs_plan_mark: Decimal | None

    def to_dict(self) -> dict[str, object]:
        return {
            "registration_id": self.registration_id,
            "opportunity_id": self.opportunity_id,
            "opportunity_timestamp_ms": self.opportunity_timestamp_ms,
            "opportunity_market": self.opportunity_market,
            "opportunity_direction": self.opportunity_direction,
            "release_market": self.release_market,
            "release_direction": self.release_direction,
            "release_opening_plan_id": self.release_opening_plan_id,
            "holder_quantity": str(self.holder_quantity),
            "holder_average_entry_price": str(
                self.holder_average_entry_price
            ),
            "plan_observed_at_ms": self.plan_observed_at_ms,
            "plan_reference_price": str(self.plan_reference_price),
            "execution_observed_at_ms": self.execution_observed_at_ms,
            "planning_approved": self.planning_approved,
            "planning_rejection": self.planning_rejection,
            "execution_result": self.execution_result,
            "execution_reason_codes": self.execution_reason_codes,
            "requested_quantity": (
                None
                if self.requested_quantity is None
                else str(self.requested_quantity)
            ),
            "filled_quantity": (
                None
                if self.filled_quantity is None
                else str(self.filled_quantity)
            ),
            "unfilled_quantity": (
                None
                if self.unfilled_quantity is None
                else str(self.unfilled_quantity)
            ),
            "average_fill_price": (
                None
                if self.average_fill_price is None
                else str(self.average_fill_price)
            ),
            "gross_fill_notional": (
                None
                if self.gross_fill_notional is None
                else str(self.gross_fill_notional)
            ),
            "taker_fee": (
                None if self.taker_fee is None else str(self.taker_fee)
            ),
            "full_slot_release": self.full_slot_release,
            "gross_release_delta_vs_plan_mark": (
                None
                if self.gross_release_delta_vs_plan_mark is None
                else str(self.gross_release_delta_vs_plan_mark)
            ),
            "net_release_delta_vs_plan_mark": (
                None
                if self.net_release_delta_vs_plan_mark is None
                else str(self.net_release_delta_vs_plan_mark)
            ),
            "gross_close_pnl_vs_entry": (
                None
                if self.gross_close_pnl_vs_entry is None
                else str(self.gross_close_pnl_vs_entry)
            ),
            "net_close_pnl_vs_entry": (
                None
                if self.net_close_pnl_vs_entry is None
                else str(self.net_close_pnl_vs_entry)
            ),
            "favorable_execution_bps_vs_plan_mark": (
                None
                if self.favorable_execution_bps_vs_plan_mark is None
                else str(self.favorable_execution_bps_vs_plan_mark)
            ),
        }


def _execution_deltas(
    evidence: CapacityReleaseBookEvidence,
    *,
    filled_quantity: Decimal,
    average_fill_price: Decimal,
    fee: Decimal,
) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
    position = evidence.release_position
    reference = evidence.pending.plan_reference_price
    if filled_quantity <= ZERO:
        raise CapacityReleaseExecutionShadowError(
            "filled quantity must be positive"
        )
    if position.side is PositionSide.LONG:
        gross_release_delta = (
            average_fill_price - reference
        ) * filled_quantity
        gross_close_pnl = (
            average_fill_price - position.average_entry_price
        ) * filled_quantity
    else:
        gross_release_delta = (
            reference - average_fill_price
        ) * filled_quantity
        gross_close_pnl = (
            position.average_entry_price - average_fill_price
        ) * filled_quantity
    net_release_delta = gross_release_delta - fee
    net_close_pnl = gross_close_pnl - fee
    reference_notional = reference * filled_quantity
    favorable_bps = (
        gross_release_delta / reference_notional
    ) * BPS
    return (
        gross_release_delta,
        net_release_delta,
        gross_close_pnl,
        net_close_pnl,
        favorable_bps,
    )


def evaluate_capacity_release_execution_shadow(
    records: tuple[CapacityReleaseBookEvidence, ...],
    *,
    execution_config: PaperExecutionConfig,
) -> dict[str, object]:
    ids = tuple(
        record.registration.registration_id for record in records
    )
    if len(ids) != len(set(ids)):
        raise CapacityReleaseExecutionShadowError(
            "duplicate capacity release evidence identity"
        )

    rows: list[CapacityReleaseExecutionRow] = []
    by_result: Counter[str] = Counter()
    by_release_market: Counter[str] = Counter()
    full_release_delta = ZERO
    full_release_fees = ZERO

    for evidence in sorted(
        records,
        key=lambda item: (
            item.registration.opportunity_timestamp_ms,
            item.registration.opportunity_id,
            item.registration.release_market,
            item.registration.registration_id,
        ),
    ):
        pending = evidence.pending
        registration = evidence.registration
        position = evidence.release_position

        expected_earliest = (
            pending.plan_observed_at_ms + execution_config.latency_ms
        )
        if evidence.execution_observed_at_ms < expected_earliest:
            raise CapacityReleaseExecutionShadowError(
                "captured execution book precedes configured latency"
            )
        if (
            evidence.execution_observed_at_ms - expected_earliest
            > execution_config.max_book_age_ms
        ):
            raise CapacityReleaseExecutionShadowError(
                "captured execution book exceeds configured freshness"
            )

        action = PositionAction(
            action_type=PositionActionType.REDUCE,
            market=position.market,
            quantity=position.quantity,
            new_stop_price=None,
            reason_codes=(RELEASE_REASON,),
            timestamp_ms=registration.opportunity_timestamp_ms,
        )
        planned = plan_reduce_only_order(
            position,
            action,
            pending.plan_instrument,
            execution_config,
            originating_risk_decision_id=(
                position.initial_risk_decision_id
            ),
            originating_strategy_decision_id=(
                registration.strategy_decision_id
            ),
            reference_price=pending.plan_reference_price,
            created_at_ms=pending.plan_observed_at_ms,
        )
        if isinstance(planned, PlanningRejection):
            rows.append(
                CapacityReleaseExecutionRow(
                    registration_id=registration.registration_id,
                    opportunity_id=registration.opportunity_id,
                    opportunity_timestamp_ms=(
                        registration.opportunity_timestamp_ms
                    ),
                    opportunity_market=registration.opportunity_market,
                    opportunity_direction=(
                        registration.opportunity_direction
                    ),
                    release_market=registration.release_market,
                    release_direction=registration.release_direction,
                    release_opening_plan_id=position.opening_plan_id,
                    holder_quantity=position.quantity,
                    holder_average_entry_price=(
                        position.average_entry_price
                    ),
                    plan_observed_at_ms=pending.plan_observed_at_ms,
                    plan_reference_price=(
                        pending.plan_reference_price
                    ),
                    execution_observed_at_ms=(
                        evidence.execution_observed_at_ms
                    ),
                    planning_approved=False,
                    planning_rejection=planned.reason,
                    execution_result=None,
                    execution_reason_codes=(),
                    requested_quantity=None,
                    filled_quantity=None,
                    unfilled_quantity=None,
                    average_fill_price=None,
                    gross_fill_notional=None,
                    taker_fee=None,
                    full_slot_release=False,
                    gross_release_delta_vs_plan_mark=None,
                    net_release_delta_vs_plan_mark=None,
                    gross_close_pnl_vs_entry=None,
                    net_close_pnl_vs_entry=None,
                    favorable_execution_bps_vs_plan_mark=None,
                )
            )
            by_result["planning_rejected"] += 1
            by_release_market[registration.release_market] += 1
            continue

        simulation = simulate_ioc(
            planned,
            evidence.execution_book_event,
            evidence.execution_instrument,
            execution_config,
            attempt_timestamp_ms=evidence.execution_observed_at_ms,
        )
        attempt = simulation.attempt
        full_slot_release = (
            attempt.result is ExecutionResult.FULL
            and attempt.filled_quantity == position.quantity
            and attempt.unfilled_quantity == ZERO
        )

        gross_release_delta: Decimal | None = None
        net_release_delta: Decimal | None = None
        gross_close_pnl: Decimal | None = None
        net_close_pnl: Decimal | None = None
        favorable_bps: Decimal | None = None
        if (
            attempt.filled_quantity > ZERO
            and attempt.average_fill_price is not None
        ):
            (
                gross_release_delta,
                net_release_delta,
                gross_close_pnl,
                net_close_pnl,
                favorable_bps,
            ) = _execution_deltas(
                evidence,
                filled_quantity=attempt.filled_quantity,
                average_fill_price=attempt.average_fill_price,
                fee=attempt.fee,
            )

        rows.append(
            CapacityReleaseExecutionRow(
                registration_id=registration.registration_id,
                opportunity_id=registration.opportunity_id,
                opportunity_timestamp_ms=(
                    registration.opportunity_timestamp_ms
                ),
                opportunity_market=registration.opportunity_market,
                opportunity_direction=registration.opportunity_direction,
                release_market=registration.release_market,
                release_direction=registration.release_direction,
                release_opening_plan_id=position.opening_plan_id,
                holder_quantity=position.quantity,
                holder_average_entry_price=position.average_entry_price,
                plan_observed_at_ms=pending.plan_observed_at_ms,
                plan_reference_price=pending.plan_reference_price,
                execution_observed_at_ms=(
                    evidence.execution_observed_at_ms
                ),
                planning_approved=True,
                planning_rejection=None,
                execution_result=attempt.result.value,
                execution_reason_codes=attempt.reason_codes,
                requested_quantity=attempt.requested_quantity,
                filled_quantity=attempt.filled_quantity,
                unfilled_quantity=attempt.unfilled_quantity,
                average_fill_price=attempt.average_fill_price,
                gross_fill_notional=attempt.gross_fill_notional,
                taker_fee=attempt.fee,
                full_slot_release=full_slot_release,
                gross_release_delta_vs_plan_mark=(
                    gross_release_delta
                ),
                net_release_delta_vs_plan_mark=net_release_delta,
                gross_close_pnl_vs_entry=gross_close_pnl,
                net_close_pnl_vs_entry=net_close_pnl,
                favorable_execution_bps_vs_plan_mark=(
                    favorable_bps
                ),
            )
        )
        by_result[attempt.result.value] += 1
        by_release_market[registration.release_market] += 1
        if full_slot_release:
            assert net_release_delta is not None
            full_release_delta += net_release_delta
            full_release_fees += attempt.fee

    ordered = tuple(rows)
    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_risk_limits": False,
        "changes_entry_priority": False,
        "actual_orders_submitted": False,
        "portfolio_counterfactual_complete": False,
        "claim_scope": (
            "correlation_holder_reduce_only_execution_shadow"
        ),
        "execution_config": {
            "config_version": execution_config.config_version,
            "latency_ms": execution_config.latency_ms,
            "max_book_age_ms": execution_config.max_book_age_ms,
            "max_ioc_slippage_bps": str(
                execution_config.max_ioc_slippage_bps
            ),
            "taker_fee_rate": str(
                execution_config.taker_fee_rate
            ),
            "fee_schedule_id": execution_config.fee_schedule_id,
        },
        "evidence_rows": len(records),
        "planning_approved": sum(
            row.planning_approved for row in ordered
        ),
        "planning_rejected": sum(
            not row.planning_approved for row in ordered
        ),
        "full_slot_releases": sum(
            row.full_slot_release for row in ordered
        ),
        "partial_or_failed_releases": sum(
            row.planning_approved and not row.full_slot_release
            for row in ordered
        ),
        "full_release_net_delta_vs_plan_mark": str(
            full_release_delta
        ),
        "full_release_taker_fees": str(full_release_fees),
        "by_execution_result": dict(sorted(by_result.items())),
        "by_release_market": dict(
            sorted(by_release_market.items())
        ),
        "rows": tuple(row.to_dict() for row in ordered),
    }
