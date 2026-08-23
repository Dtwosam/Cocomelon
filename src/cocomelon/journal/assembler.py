from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext

from cocomelon.domain.execution import (
    ExecutionAttempt,
    OrderSide,
    PaperFill,
    PaperOrderPlan,
    PositionAction,
)
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.replay import EvidenceClass, ReplayRecord
from cocomelon.domain.strategy import Direction
from cocomelon.execution.funding import FundingAccrual
from cocomelon.journal.analytics import compute_trade_analytics

ZERO = Decimal("0")
AUTHORITATIVE_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)


@dataclass(frozen=True, slots=True)
class JournalInconsistency:
    reason: str
    detail: str | None = None

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("reason must not be empty")
        if self.detail is not None and not self.detail.strip():
            raise ValueError("detail must not be empty when provided")


@dataclass(frozen=True, slots=True)
class TradeLifecycleInput:
    feature_snapshot_id: str
    opening_plan: PaperOrderPlan
    opening_attempt: ExecutionAttempt
    exit_plans: tuple[PaperOrderPlan, ...]
    exit_attempts: tuple[ExecutionAttempt, ...]
    fills: tuple[PaperFill, ...]
    position_actions: tuple[PositionAction, ...]
    funding_accruals: tuple[FundingAccrual, ...]
    equity_before: Decimal
    equity_after: Decimal
    exit_reason: str
    mark_observations: tuple[ReplayRecord, ...]
    known_gap_intervals: tuple[tuple[int, int | None], ...]
    evidence_class: EvidenceClass
    replay_run_id: str | None
    health_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.feature_snapshot_id.strip():
            raise ValueError("feature_snapshot_id must not be empty")
        if not self.exit_reason.strip():
            raise ValueError("exit_reason must not be empty")
        if self.replay_run_id is not None and not self.replay_run_id.strip():
            raise ValueError("replay_run_id must not be empty")
        for field in ("equity_before", "equity_after"):
            value = getattr(self, field)
            if not value.is_finite() or value <= ZERO:
                raise ValueError(f"{field} must be positive and finite")
        if any(not value.strip() for value in self.health_refs):
            raise ValueError("health_refs values must not be empty")


def _inconsistency(reason: str, detail: str | None = None) -> JournalInconsistency:
    return JournalInconsistency(reason=reason, detail=detail)


def _action_id(action: PositionAction) -> str:
    payload = {
        "action_type": action.action_type.value,
        "market": action.market.canonical,
        "quantity": None if action.quantity is None else str(action.quantity),
        "new_stop_price": None if action.new_stop_price is None else str(action.new_stop_price),
        "reason_codes": action.reason_codes,
        "timestamp_ms": action.timestamp_ms,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


def _direction(side: OrderSide) -> Direction:
    return Direction.LONG if side is OrderSide.BUY else Direction.SHORT


def _vwap(fills: tuple[PaperFill, ...]) -> tuple[Decimal, Decimal, Decimal]:
    with localcontext(AUTHORITATIVE_CONTEXT):
        quantity = sum((fill.quantity for fill in fills), ZERO)
        notional = sum((fill.notional for fill in fills), ZERO)
        fees = sum((fill.taker_fee for fill in fills), ZERO)
        if quantity <= ZERO:
            raise ValueError("fill quantity must be positive")
        return notional / quantity, quantity, fees


def _validate_fill_notional(fill: PaperFill) -> bool:
    with localcontext(AUTHORITATIVE_CONTEXT):
        return fill.notional == fill.price * fill.quantity


def assemble_trade_journal_entry(
    lifecycle: TradeLifecycleInput,
) -> TradeJournalEntry | JournalInconsistency:
    opening_plan = lifecycle.opening_plan
    market = opening_plan.market

    if opening_plan.reduce_only:
        return _inconsistency("OPENING_PLAN_REDUCE_ONLY")
    if opening_plan.stop_price is None or opening_plan.approved_risk_amount_ceiling is None:
        return _inconsistency("INCOMPLETE_OPENING_RISK_ENVELOPE")
    if lifecycle.opening_attempt.plan_id != opening_plan.plan_id:
        return _inconsistency("OPENING_ATTEMPT_PLAN_MISMATCH")
    if not lifecycle.exit_plans:
        return _inconsistency("MISSING_EXIT_PLAN")
    if not lifecycle.exit_attempts:
        return _inconsistency("MISSING_EXIT_ATTEMPT")
    if not lifecycle.fills:
        return _inconsistency("MISSING_FILLS")

    exit_plans = tuple(
        sorted(lifecycle.exit_plans, key=lambda item: (item.created_at_ms, item.plan_id))
    )
    exit_plan_by_id = {plan.plan_id: plan for plan in exit_plans}
    if len(exit_plan_by_id) != len(exit_plans):
        return _inconsistency("DUPLICATE_EXIT_PLAN")
    for plan in exit_plans:
        if not plan.reduce_only:
            return _inconsistency("EXIT_PLAN_NOT_REDUCE_ONLY")
        if plan.market != market:
            return _inconsistency("EXIT_PLAN_MARKET_MISMATCH")
        if plan.side is opening_plan.side:
            return _inconsistency("EXIT_PLAN_SIDE_MISMATCH")
        if plan.risk_decision_id != opening_plan.risk_decision_id:
            return _inconsistency("EXIT_PLAN_RISK_DECISION_MISMATCH")
        if plan.strategy_decision_id != opening_plan.strategy_decision_id:
            return _inconsistency("EXIT_PLAN_STRATEGY_DECISION_MISMATCH")

    exit_attempts = tuple(
        sorted(
            lifecycle.exit_attempts,
            key=lambda item: (item.attempt_timestamp_ms, item.attempt_id),
        )
    )
    exit_attempt_by_id = {attempt.attempt_id: attempt for attempt in exit_attempts}
    if len(exit_attempt_by_id) != len(exit_attempts):
        return _inconsistency("DUPLICATE_EXIT_ATTEMPT")
    for attempt in exit_attempts:
        if attempt.plan_id not in exit_plan_by_id:
            return _inconsistency("EXIT_ATTEMPT_PLAN_MISMATCH")

    known_attempt_plan = {
        lifecycle.opening_attempt.attempt_id: opening_plan.plan_id,
        **{attempt.attempt_id: attempt.plan_id for attempt in exit_attempts},
    }
    known_plans = {opening_plan.plan_id: opening_plan, **exit_plan_by_id}

    ordered_fills = tuple(sorted(lifecycle.fills, key=lambda item: (item.timestamp_ms, item.fill_id)))
    for fill in ordered_fills:
        if fill.market != market:
            return _inconsistency("FILL_MARKET_MISMATCH")
        plan = known_plans.get(fill.plan_id)
        if plan is None:
            return _inconsistency("FILL_PLAN_MISMATCH")
        expected_plan_id = known_attempt_plan.get(fill.attempt_id)
        if expected_plan_id != fill.plan_id:
            return _inconsistency("FILL_ATTEMPT_MISMATCH")
        if fill.side is not plan.side:
            return _inconsistency("FILL_SIDE_MISMATCH")
        if not _validate_fill_notional(fill):
            return _inconsistency("FILL_NOTIONAL_MISMATCH")

    opening_fills = tuple(fill for fill in ordered_fills if fill.plan_id == opening_plan.plan_id)
    exit_fills = tuple(fill for fill in ordered_fills if fill.plan_id != opening_plan.plan_id)
    if not opening_fills:
        return _inconsistency("MISSING_OPENING_FILL")
    if not exit_fills:
        return _inconsistency("MISSING_EXIT_FILL")

    try:
        entry_price, opened_quantity, entry_fees = _vwap(opening_fills)
        exit_price, closed_quantity, exit_fees = _vwap(exit_fills)
    except ValueError as exc:
        return _inconsistency("INVALID_FILL_AGGREGATE", str(exc))
    if closed_quantity != opened_quantity:
        return _inconsistency("POSITION_NOT_FULLY_CLOSED")

    opened_at_ms = min(fill.timestamp_ms for fill in opening_fills)
    closed_at_ms = max(fill.timestamp_ms for fill in exit_fills)
    if closed_at_ms < opened_at_ms:
        return _inconsistency("LIFECYCLE_TIME_REGRESSION")

    direction = _direction(opening_plan.side)
    with localcontext(AUTHORITATIVE_CONTEXT):
        if direction is Direction.LONG:
            gross_realized_pnl = (exit_price - entry_price) * opened_quantity
        else:
            gross_realized_pnl = (entry_price - exit_price) * opened_quantity

    funding_accruals = tuple(
        sorted(
            lifecycle.funding_accruals,
            key=lambda item: (item.boundary_ms, item.accrual_id),
        )
    )
    for accrual in funding_accruals:
        if accrual.market != market:
            return _inconsistency("FUNDING_MARKET_MISMATCH")
        if not opened_at_ms <= accrual.boundary_ms <= closed_at_ms:
            return _inconsistency("FUNDING_OUTSIDE_LIFECYCLE")
        if direction is Direction.LONG and accrual.signed_quantity <= ZERO:
            return _inconsistency("FUNDING_POSITION_DIRECTION_MISMATCH")
        if direction is Direction.SHORT and accrual.signed_quantity >= ZERO:
            return _inconsistency("FUNDING_POSITION_DIRECTION_MISMATCH")

    position_actions = tuple(
        sorted(
            lifecycle.position_actions,
            key=lambda item: (item.timestamp_ms, _action_id(item)),
        )
    )
    for action in position_actions:
        if action.market != market:
            return _inconsistency("POSITION_ACTION_MARKET_MISMATCH")
        if not opened_at_ms <= action.timestamp_ms <= closed_at_ms:
            return _inconsistency("POSITION_ACTION_OUTSIDE_LIFECYCLE")

    with localcontext(AUTHORITATIVE_CONTEXT):
        funding_cash_pnl = sum((item.cash_delta for item in funding_accruals), ZERO)

    try:
        analytics = compute_trade_analytics(
            direction=direction,
            entry_price=entry_price,
            entry_reference_price=opening_plan.execution_reference_price,
            exit_price=exit_price,
            exit_reference_price=exit_plans[-1].execution_reference_price,
            opened_quantity=opened_quantity,
            gross_realized_pnl=gross_realized_pnl,
            entry_fees=entry_fees,
            exit_fees=exit_fees,
            funding_cash_pnl=funding_cash_pnl,
            initial_risk_amount=opening_plan.approved_risk_amount_ceiling,
            opened_at_ms=opened_at_ms,
            closed_at_ms=closed_at_ms,
            mark_observations=lifecycle.mark_observations,
            known_gap_intervals=lifecycle.known_gap_intervals,
        )
    except ValueError as exc:
        return _inconsistency("TRADE_ANALYTICS_INVALID", str(exc))

    with localcontext(AUTHORITATIVE_CONTEXT):
        if lifecycle.equity_after - lifecycle.equity_before != analytics.net_pnl:
            return _inconsistency("EQUITY_RECONCILIATION_MISMATCH")

    return TradeJournalEntry(
        market=market,
        direction=direction,
        opened_at_ms=opened_at_ms,
        closed_at_ms=closed_at_ms,
        feature_snapshot_id=lifecycle.feature_snapshot_id,
        strategy_decision_id=opening_plan.strategy_decision_id,
        risk_decision_id=opening_plan.risk_decision_id,
        opening_plan_id=opening_plan.plan_id,
        opening_attempt_id=lifecycle.opening_attempt.attempt_id,
        exit_plan_ids=tuple(plan.plan_id for plan in exit_plans),
        exit_attempt_ids=tuple(attempt.attempt_id for attempt in exit_attempts),
        fill_ids=tuple(fill.fill_id for fill in ordered_fills),
        position_action_ids=tuple(_action_id(action) for action in position_actions),
        funding_event_ids=tuple(accrual.accrual_id for accrual in funding_accruals),
        initial_stop=opening_plan.stop_price,
        initial_risk_amount=opening_plan.approved_risk_amount_ceiling,
        entry_price=entry_price,
        exit_price=exit_price,
        filled_quantity=opened_quantity,
        gross_realized_pnl=gross_realized_pnl,
        entry_fees=entry_fees,
        exit_fees=exit_fees,
        funding_cash_pnl=funding_cash_pnl,
        net_pnl=analytics.net_pnl,
        entry_slippage_fraction=analytics.entry_slippage_fraction,
        exit_slippage_fraction=analytics.exit_slippage_fraction,
        mfe=analytics.mfe,
        mae=analytics.mae,
        net_r=analytics.net_r,
        equity_before=lifecycle.equity_before,
        equity_after=lifecycle.equity_after,
        exit_reason=lifecycle.exit_reason,
        health_refs=lifecycle.health_refs,
        evidence_class=lifecycle.evidence_class,
        replay_run_id=lifecycle.replay_run_id,
    )
