from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation
from typing import Final

from cocomelon.domain.execution import (
    InstrumentExecutionSpec,
    PaperExecutionConfig,
    PaperOrderPlan,
    PositionAction,
    PositionActionType,
)
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.execution.accounting import PaperPosition, PositionSide
from cocomelon.execution.ioc import simulate_ioc
from cocomelon.execution.planner import PlanningRejection, plan_reduce_only_order
from cocomelon.research.profit_lock_counterfactual import (
    DEFAULT_PROFIT_LOCK_COSTS,
    DEFAULT_PROFIT_LOCK_RULES,
    ProfitLockRule,
)

ZERO: Final = Decimal("0")
EXECUTION_SHADOW_STATE_SCHEMA_VERSION: Final = 2


class ProfitLockExecutionShadowError(RuntimeError):
    pass


def _market_from_canonical(value: str) -> MarketId:
    if ":" in value:
        dex = value.split(":", 1)[0]
        return MarketId.from_wire_name(dex, value)
    return MarketId.from_wire_name("", value)


def _decimal(value: object, field_name: str) -> Decimal:
    try:
        resolved = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ProfitLockExecutionShadowError(
            f"{field_name} must be a decimal"
        ) from exc
    if not resolved.is_finite():
        raise ProfitLockExecutionShadowError(
            f"{field_name} must be finite"
        )
    return resolved


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProfitLockExecutionShadowError(
            f"{field_name} must be an integer"
        )
    return value


def _string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProfitLockExecutionShadowError(
            f"{field_name} must be a non-empty string"
        )
    return value


def _optional_integer(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _integer(value, field_name)


def _optional_decimal(value: object, field_name: str) -> Decimal | None:
    if value is None:
        return None
    return _decimal(value, field_name)


def _execution_config_payload(
    config: PaperExecutionConfig,
) -> dict[str, object]:
    return {
        "config_version": config.config_version,
        "latency_ms": config.latency_ms,
        "max_book_age_ms": config.max_book_age_ms,
        "max_asset_ctx_age_ms": config.max_asset_ctx_age_ms,
        "max_position_age_ms": config.max_position_age_ms,
        "funding_reconciliation_grace_ms": (
            config.funding_reconciliation_grace_ms
        ),
        "max_ioc_slippage_bps": str(config.max_ioc_slippage_bps),
        "taker_fee_rate": str(config.taker_fee_rate),
        "fee_schedule_id": config.fee_schedule_id,
        "native_perp_min_notional": str(
            config.native_perp_min_notional
        ),
        "paper_max_gross_leverage": str(
            config.paper_max_gross_leverage
        ),
    }


def _rules_payload(
    rules: Sequence[ProfitLockRule],
) -> list[dict[str, str]]:
    return [
        {
            "rule_id": rule.rule_id,
            "activate_at_r": str(rule.activate_at_r),
            "lock_at_r": str(rule.lock_at_r),
            **(
                {"exit_on_activation": "true"}
                if rule.exit_on_activation else {}
            ),
        }
        for rule in rules
    ]


def _gross_r(
    *,
    side: PositionSide,
    entry_price: Decimal,
    quantity: Decimal,
    planned_risk: Decimal,
    mark_px: Decimal,
) -> Decimal:
    if planned_risk <= ZERO:
        raise ValueError("planned_risk must be positive")
    gross = (
        (mark_px - entry_price) * quantity
        if side is PositionSide.LONG
        else (entry_price - mark_px) * quantity
    )
    return gross / planned_risk


def _lock_price(
    *,
    side: PositionSide,
    entry_price: Decimal,
    quantity: Decimal,
    planned_risk: Decimal,
    lock_at_r: Decimal,
) -> Decimal:
    per_unit = lock_at_r * planned_risk / quantity
    return (
        entry_price + per_unit
        if side is PositionSide.LONG
        else entry_price - per_unit
    )


def _crossed_lock(
    *,
    side: PositionSide,
    mark_px: Decimal,
    lock_px: Decimal,
) -> bool:
    if side is PositionSide.LONG:
        return mark_px <= lock_px
    return mark_px >= lock_px


@dataclass(slots=True)
class _RuleState:
    rule_id: str
    remaining_quantity: Decimal
    activated_at_ms: int | None = None
    triggered_at_ms: int | None = None
    trigger_mark_px: Decimal | None = None
    trigger_event_key: str | None = None
    latest_mark_timestamp_ms: int | None = None
    pending_plan: PaperOrderPlan | None = None
    filled_quantity: Decimal = ZERO
    fill_notional: Decimal = ZERO
    candidate_gross_pnl: Decimal = ZERO
    exit_fees: Decimal = ZERO
    completed_at_ms: int | None = None
    attempt_count: int = 0
    planning_rejection_count: int = 0
    no_fill_count: int = 0
    last_rejection: str | None = None
    last_attempt_result: str | None = None
    book_event_keys: list[str] = field(default_factory=list)


@dataclass(slots=True)
class _PositionState:
    opening_plan_id: str
    market: MarketId
    side: PositionSide
    initial_quantity: Decimal
    entry_price: Decimal
    planned_risk: Decimal
    opened_at_ms: int
    eligible: bool
    exclusion_reason: str | None
    rules: dict[str, _RuleState]


@dataclass(frozen=True, slots=True)
class ProfitLockExecutionOutcome:
    trade_id: str
    opening_plan_id: str
    market: str
    direction: str
    rule_id: str
    activated: bool
    triggered: bool
    simulated_close_complete: bool
    activation_timestamp_ms: int | None
    trigger_timestamp_ms: int | None
    completion_timestamp_ms: int | None
    simulated_filled_quantity: Decimal
    simulated_average_exit_price: Decimal | None
    simulated_exit_fees: Decimal
    attempt_count: int
    planning_rejection_count: int
    no_fill_count: int
    actual_net_pnl: Decimal
    actual_net_r: Decimal
    candidate_net_pnl_estimate: Decimal | None
    candidate_net_r_estimate: Decimal | None
    delta_net_pnl_estimate: Decimal | None
    delta_net_r_estimate: Decimal | None
    candidate_source: str

    def __post_init__(self) -> None:
        for identity_value in (
            self.trade_id,
            self.opening_plan_id,
            self.market,
            self.rule_id,
            self.candidate_source,
        ):
            if not identity_value.strip():
                raise ValueError("outcome identity must not be empty")
        if self.direction not in {"long", "short"}:
            raise ValueError("direction must be long or short")
        if self.triggered and not self.activated:
            raise ValueError("triggered outcome must be activated")
        if self.simulated_close_complete and not self.triggered:
            raise ValueError(
                "simulated close completion requires a trigger"
            )
        if self.activated != (self.activation_timestamp_ms is not None):
            raise ValueError("activation timestamp must reconcile")
        if self.triggered != (self.trigger_timestamp_ms is not None):
            raise ValueError("trigger timestamp must reconcile")
        if (
            self.simulated_close_complete
            != (self.completion_timestamp_ms is not None)
        ):
            raise ValueError("completion timestamp must reconcile")
        if self.simulated_filled_quantity < ZERO:
            raise ValueError(
                "simulated_filled_quantity must be non-negative"
            )
        if self.simulated_average_exit_price is not None:
            if (
                not self.simulated_average_exit_price.is_finite()
                or self.simulated_average_exit_price <= ZERO
            ):
                raise ValueError(
                    "simulated_average_exit_price must be positive"
                )
        if (
            not self.simulated_exit_fees.is_finite()
            or self.simulated_exit_fees < ZERO
        ):
            raise ValueError(
                "simulated_exit_fees must be non-negative"
            )
        for count_value in (
            self.attempt_count,
            self.planning_rejection_count,
            self.no_fill_count,
        ):
            if count_value < 0:
                raise ValueError("execution counts must be non-negative")
        for actual_value in (self.actual_net_pnl, self.actual_net_r):
            if not actual_value.is_finite():
                raise ValueError("actual economics must be finite")
        estimated = (
            self.candidate_net_pnl_estimate,
            self.candidate_net_r_estimate,
            self.delta_net_pnl_estimate,
            self.delta_net_r_estimate,
        )
        if any(value is None for value in estimated) and not all(
            value is None for value in estimated
        ):
            raise ValueError(
                "candidate economics must be all present or all absent"
            )
        for estimated_value in estimated:
            if (
                estimated_value is not None
                and not estimated_value.is_finite()
            ):
                raise ValueError(
                    "candidate economics must be finite when present"
                )
        if self.candidate_source == "actual_close":
            if self.triggered:
                raise ValueError(
                    "actual-close candidate cannot have triggered"
                )
            if self.candidate_net_pnl_estimate != self.actual_net_pnl:
                raise ValueError(
                    "actual-close candidate PnL must equal actual"
                )
            if self.candidate_net_r_estimate != self.actual_net_r:
                raise ValueError(
                    "actual-close candidate R must equal actual"
                )
        if self.candidate_source == "visible_book_ioc":
            if not self.simulated_close_complete:
                raise ValueError(
                    "visible-book candidate requires full simulated close"
                )
        if self.candidate_source == "triggered_incomplete":
            if not self.triggered or self.simulated_close_complete:
                raise ValueError(
                    "incomplete candidate state is inconsistent"
                )
            if self.candidate_net_pnl_estimate is not None:
                raise ValueError(
                    "incomplete triggered candidate cannot estimate PnL"
                )

    def payload(self) -> dict[str, object]:
        return {
            "trade_id": self.trade_id,
            "opening_plan_id": self.opening_plan_id,
            "market": self.market,
            "direction": self.direction,
            "rule_id": self.rule_id,
            "activated": self.activated,
            "triggered": self.triggered,
            "simulated_close_complete": self.simulated_close_complete,
            "activation_timestamp_ms": self.activation_timestamp_ms,
            "trigger_timestamp_ms": self.trigger_timestamp_ms,
            "completion_timestamp_ms": self.completion_timestamp_ms,
            "simulated_filled_quantity": str(
                self.simulated_filled_quantity
            ),
            "simulated_average_exit_price": (
                None
                if self.simulated_average_exit_price is None
                else str(self.simulated_average_exit_price)
            ),
            "simulated_exit_fees": str(self.simulated_exit_fees),
            "attempt_count": self.attempt_count,
            "planning_rejection_count": (
                self.planning_rejection_count
            ),
            "no_fill_count": self.no_fill_count,
            "actual_net_pnl": str(self.actual_net_pnl),
            "actual_net_r": str(self.actual_net_r),
            "candidate_net_pnl_estimate": (
                None
                if self.candidate_net_pnl_estimate is None
                else str(self.candidate_net_pnl_estimate)
            ),
            "candidate_net_r_estimate": (
                None
                if self.candidate_net_r_estimate is None
                else str(self.candidate_net_r_estimate)
            ),
            "delta_net_pnl_estimate": (
                None
                if self.delta_net_pnl_estimate is None
                else str(self.delta_net_pnl_estimate)
            ),
            "delta_net_r_estimate": (
                None
                if self.delta_net_r_estimate is None
                else str(self.delta_net_r_estimate)
            ),
            "candidate_source": self.candidate_source,
        }

    @classmethod
    def from_payload(
        cls,
        raw: object,
    ) -> ProfitLockExecutionOutcome:
        if not isinstance(raw, Mapping):
            raise ProfitLockExecutionShadowError(
                "execution-shadow outcome must be an object"
            )
        def boolean(name: str) -> bool:
            value = raw.get(name)
            if not isinstance(value, bool):
                raise ProfitLockExecutionShadowError(
                    f"{name} must be boolean"
                )
            return value

        return cls(
            trade_id=_string(raw.get("trade_id"), "trade_id"),
            opening_plan_id=_string(
                raw.get("opening_plan_id"),
                "opening_plan_id",
            ),
            market=_string(raw.get("market"), "market"),
            direction=_string(raw.get("direction"), "direction"),
            rule_id=_string(raw.get("rule_id"), "rule_id"),
            activated=boolean("activated"),
            triggered=boolean("triggered"),
            simulated_close_complete=boolean(
                "simulated_close_complete"
            ),
            activation_timestamp_ms=_optional_integer(
                raw.get("activation_timestamp_ms"),
                "activation_timestamp_ms",
            ),
            trigger_timestamp_ms=_optional_integer(
                raw.get("trigger_timestamp_ms"),
                "trigger_timestamp_ms",
            ),
            completion_timestamp_ms=_optional_integer(
                raw.get("completion_timestamp_ms"),
                "completion_timestamp_ms",
            ),
            simulated_filled_quantity=_decimal(
                raw.get("simulated_filled_quantity"),
                "simulated_filled_quantity",
            ),
            simulated_average_exit_price=_optional_decimal(
                raw.get("simulated_average_exit_price"),
                "simulated_average_exit_price",
            ),
            simulated_exit_fees=_decimal(
                raw.get("simulated_exit_fees"),
                "simulated_exit_fees",
            ),
            attempt_count=_integer(
                raw.get("attempt_count"),
                "attempt_count",
            ),
            planning_rejection_count=_integer(
                raw.get("planning_rejection_count"),
                "planning_rejection_count",
            ),
            no_fill_count=_integer(
                raw.get("no_fill_count"),
                "no_fill_count",
            ),
            actual_net_pnl=_decimal(
                raw.get("actual_net_pnl"),
                "actual_net_pnl",
            ),
            actual_net_r=_decimal(
                raw.get("actual_net_r"),
                "actual_net_r",
            ),
            candidate_net_pnl_estimate=_optional_decimal(
                raw.get("candidate_net_pnl_estimate"),
                "candidate_net_pnl_estimate",
            ),
            candidate_net_r_estimate=_optional_decimal(
                raw.get("candidate_net_r_estimate"),
                "candidate_net_r_estimate",
            ),
            delta_net_pnl_estimate=_optional_decimal(
                raw.get("delta_net_pnl_estimate"),
                "delta_net_pnl_estimate",
            ),
            delta_net_r_estimate=_optional_decimal(
                raw.get("delta_net_r_estimate"),
                "delta_net_r_estimate",
            ),
            candidate_source=_string(
                raw.get("candidate_source"),
                "candidate_source",
            ),
        )


class ProfitLockExecutionShadow:
    def __init__(
        self,
        execution_config: PaperExecutionConfig,
        *,
        started_at_ms: int,
        rules: Sequence[ProfitLockRule] = DEFAULT_PROFIT_LOCK_RULES,
    ) -> None:
        if started_at_ms < 0:
            raise ValueError("started_at_ms must be non-negative")
        resolved_rules = tuple(rules)
        if not resolved_rules:
            raise ValueError("rules must not be empty")
        if len({rule.rule_id for rule in resolved_rules}) != len(
            resolved_rules
        ):
            raise ValueError("rule ids must be unique")
        self._config = execution_config
        self._started_at_ms = started_at_ms
        self._rules = resolved_rules
        self._positions: dict[str, _PositionState] = {}
        self._outcomes: list[ProfitLockExecutionOutcome] = []
        self._excluded_closed_trades = 0
        self._lineage_mismatch_closed_trades = 0
        self._orphaned_restored_positions = 0
        self._state_restored = False
        self._state_restore_error: str | None = None

    @property
    def started_at_ms(self) -> int:
        return self._started_at_ms

    def _position_state(
        self,
        position: PaperPosition,
    ) -> _PositionState:
        existing = self._positions.get(position.opening_plan_id)
        if existing is not None:
            if (
                existing.market != position.market
                or existing.side != position.side
                or existing.entry_price != position.average_entry_price
            ):
                raise ProfitLockExecutionShadowError(
                    "open position identity drifted"
                )
            return existing

        eligible = (
            position.opened_at_ms >= self._started_at_ms
            and position.planned_risk > ZERO
        )
        exclusion_reason: str | None = None
        if position.opened_at_ms < self._started_at_ms:
            exclusion_reason = "PRE_OBSERVER_POSITION"
        elif position.planned_risk <= ZERO:
            exclusion_reason = "NON_POSITIVE_PLANNED_RISK"

        state = _PositionState(
            opening_plan_id=position.opening_plan_id,
            market=position.market,
            side=position.side,
            initial_quantity=position.quantity,
            entry_price=position.average_entry_price,
            planned_risk=position.planned_risk,
            opened_at_ms=position.opened_at_ms,
            eligible=eligible,
            exclusion_reason=exclusion_reason,
            rules={
                rule.rule_id: _RuleState(
                    rule_id=rule.rule_id,
                    remaining_quantity=position.quantity,
                )
                for rule in self._rules
            },
        )
        self._positions[position.opening_plan_id] = state
        return state

    def observe_mark(
        self,
        positions: Sequence[PaperPosition],
        mark_event: StreamEvent,
        *,
        now_ms: int,
    ) -> None:
        if mark_event.kind is not StreamKind.ACTIVE_ASSET_CTX:
            raise ValueError(
                "profit-lock execution shadow requires asset context mark"
            )
        matches = tuple(
            position
            for position in positions
            if position.market == mark_event.market
        )
        if not matches:
            return
        if len(matches) != 1:
            raise ProfitLockExecutionShadowError(
                "duplicate market positions in execution shadow"
            )
        position = matches[0]
        state = self._position_state(position)
        if not state.eligible:
            return
        raw_mark = mark_event.payload.get("mark_px")
        if not isinstance(raw_mark, Decimal):
            raise ProfitLockExecutionShadowError(
                "mark event is missing Decimal mark_px"
            )
        if not raw_mark.is_finite() or raw_mark <= ZERO:
            raise ProfitLockExecutionShadowError(
                "mark_px must be positive and finite"
            )
        if now_ms < state.opened_at_ms:
            raise ProfitLockExecutionShadowError(
                "mark precedes tracked opening"
            )

        rule_by_id = {rule.rule_id: rule for rule in self._rules}
        for rule_state in state.rules.values():
            rule_state.latest_mark_timestamp_ms = now_ms
            rule = rule_by_id[rule_state.rule_id]
            if rule_state.activated_at_ms is None:
                if _gross_r(
                    side=state.side,
                    entry_price=state.entry_price,
                    quantity=state.initial_quantity,
                    planned_risk=state.planned_risk,
                    mark_px=raw_mark,
                ) >= rule.activate_at_r:
                    rule_state.activated_at_ms = now_ms

            if (
                rule_state.activated_at_ms is not None
                and rule_state.triggered_at_ms is None
            ):
                lock_px = _lock_price(
                    side=state.side,
                    entry_price=state.entry_price,
                    quantity=state.initial_quantity,
                    planned_risk=state.planned_risk,
                    lock_at_r=rule.lock_at_r,
                )
                if (
                    rule.exit_on_activation
                    or _crossed_lock(
                        side=state.side,
                        mark_px=raw_mark,
                        lock_px=lock_px,
                    )
                ):
                    rule_state.triggered_at_ms = now_ms
                    rule_state.trigger_mark_px = raw_mark
                    rule_state.trigger_event_key = (
                        mark_event.event_key
                    )

    def observe_book(
        self,
        positions: Sequence[PaperPosition],
        instrument: InstrumentExecutionSpec,
        book: StreamEvent,
        *,
        reference_price: Decimal,
        now_ms: int,
    ) -> None:
        if book.kind is not StreamKind.L2_BOOK:
            raise ValueError(
                "profit-lock execution shadow requires L2 book"
            )
        if instrument.market != book.market:
            raise ValueError(
                "execution-shadow instrument/book market mismatch"
            )
        matches = tuple(
            position
            for position in positions
            if position.market == book.market
        )
        if not matches:
            return
        if len(matches) != 1:
            raise ProfitLockExecutionShadowError(
                "duplicate market positions in execution shadow"
            )
        actual_position = matches[0]
        state = self._position_state(actual_position)
        if not state.eligible:
            return
        if not reference_price.is_finite() or reference_price <= ZERO:
            raise ProfitLockExecutionShadowError(
                "reference_price must be positive and finite"
            )

        for rule_state in state.rules.values():
            if (
                rule_state.triggered_at_ms is None
                or rule_state.completed_at_ms is not None
                or rule_state.remaining_quantity <= ZERO
            ):
                continue

            plan = rule_state.pending_plan
            if plan is None:
                action_timestamp_ms = (
                    rule_state.latest_mark_timestamp_ms
                    if rule_state.latest_mark_timestamp_ms is not None
                    else rule_state.triggered_at_ms
                )
                shadow_position = replace(
                    actual_position,
                    quantity=rule_state.remaining_quantity,
                    average_entry_price=state.entry_price,
                    opened_at_ms=state.opened_at_ms,
                )
                action = PositionAction(
                    action_type=PositionActionType.EXIT_STOP,
                    market=state.market,
                    quantity=rule_state.remaining_quantity,
                    new_stop_price=None,
                    reason_codes=(
                        "PROFIT_LOCK_EXECUTION_SHADOW",
                        rule_state.rule_id,
                    ),
                    timestamp_ms=action_timestamp_ms,
                )
                planned = plan_reduce_only_order(
                    shadow_position,
                    action,
                    instrument,
                    self._config,
                    reference_price=reference_price,
                    created_at_ms=action_timestamp_ms,
                )
                if isinstance(planned, PlanningRejection):
                    rule_state.planning_rejection_count += 1
                    rule_state.last_rejection = planned.reason
                    continue
                plan = planned
                rule_state.pending_plan = plan

            simulation = simulate_ioc(
                plan,
                book,
                instrument,
                self._config,
                attempt_timestamp_ms=now_ms,
            )
            rule_state.attempt_count += 1
            rule_state.last_attempt_result = (
                simulation.attempt.result.value
            )
            if book.event_key not in rule_state.book_event_keys:
                rule_state.book_event_keys.append(book.event_key)

            if simulation.attempt.reason_codes == (
                "LATENCY_NOT_ELAPSED",
            ):
                continue

            rule_state.pending_plan = None
            if not simulation.fills:
                rule_state.no_fill_count += 1
                continue

            for fill in simulation.fills:
                rule_state.filled_quantity += fill.quantity
                rule_state.fill_notional += fill.notional
                rule_state.exit_fees += fill.taker_fee
                if state.side is PositionSide.LONG:
                    rule_state.candidate_gross_pnl += (
                        fill.price - state.entry_price
                    ) * fill.quantity
                else:
                    rule_state.candidate_gross_pnl += (
                        state.entry_price - fill.price
                    ) * fill.quantity
            rule_state.remaining_quantity -= (
                simulation.attempt.filled_quantity
            )
            if rule_state.remaining_quantity < ZERO:
                raise ProfitLockExecutionShadowError(
                    "shadow remaining quantity became negative"
                )
            if rule_state.remaining_quantity == ZERO:
                rule_state.completed_at_ms = now_ms

    def reconcile_open_positions(
        self,
        positions: Sequence[PaperPosition],
    ) -> None:
        active = {
            position.opening_plan_id
            for position in positions
        }
        orphaned = tuple(
            opening_plan_id
            for opening_plan_id in self._positions
            if opening_plan_id not in active
        )
        for opening_plan_id in orphaned:
            del self._positions[opening_plan_id]
        self._orphaned_restored_positions += len(orphaned)
        for position in positions:
            self._position_state(position)

    def record_closed_trade(
        self,
        trade: TradeJournalEntry,
    ) -> None:
        state = self._positions.pop(
            trade.opening_plan_id,
            None,
        )
        if state is None:
            self._excluded_closed_trades += 1
            return
        if not state.eligible:
            self._excluded_closed_trades += 1
            return
        if (
            state.market != trade.market
            or state.side.value != trade.direction.value
            or state.initial_quantity != trade.filled_quantity
            or state.entry_price != trade.entry_price
            or state.planned_risk != trade.initial_risk_amount
            or state.opened_at_ms != trade.opened_at_ms
        ):
            self._lineage_mismatch_closed_trades += 1
            return

        for rule in self._rules:
            rule_state = state.rules[rule.rule_id]
            activated = rule_state.activated_at_ms is not None
            triggered = rule_state.triggered_at_ms is not None
            complete = rule_state.completed_at_ms is not None

            average_exit: Decimal | None = None
            if rule_state.filled_quantity > ZERO:
                average_exit = (
                    rule_state.fill_notional
                    / rule_state.filled_quantity
                )

            candidate_net: Decimal | None
            candidate_r: Decimal | None
            delta_pnl: Decimal | None
            delta_r: Decimal | None
            source: str
            if not triggered:
                candidate_net = trade.net_pnl
                candidate_r = trade.net_r
                delta_pnl = ZERO
                delta_r = ZERO
                source = "actual_close"
            elif complete:
                if rule_state.filled_quantity != trade.filled_quantity:
                    raise ProfitLockExecutionShadowError(
                        "completed shadow fill quantity mismatch"
                    )
                completion_timestamp_ms = (
                    rule_state.completed_at_ms
                )
                if completion_timestamp_ms is None:
                    raise ProfitLockExecutionShadowError(
                        "completed shadow is missing completion timestamp"
                    )
                elapsed_ms = max(
                    1,
                    completion_timestamp_ms - trade.opened_at_ms,
                )
                funding_reserve = (
                    trade.entry_price
                    * trade.filled_quantity
                    * DEFAULT_PROFIT_LOCK_COSTS.funding_reserve_fraction_per_hour
                    * Decimal(elapsed_ms)
                    / Decimal(3_600_000)
                )
                candidate_net = (
                    rule_state.candidate_gross_pnl
                    - trade.entry_fees
                    - rule_state.exit_fees
                    - funding_reserve
                )
                candidate_r = (
                    candidate_net / trade.initial_risk_amount
                )
                delta_pnl = candidate_net - trade.net_pnl
                delta_r = candidate_r - trade.net_r
                source = "visible_book_ioc"
            else:
                candidate_net = None
                candidate_r = None
                delta_pnl = None
                delta_r = None
                source = "triggered_incomplete"

            self._outcomes.append(
                ProfitLockExecutionOutcome(
                    trade_id=trade.trade_id,
                    opening_plan_id=trade.opening_plan_id,
                    market=trade.market.canonical,
                    direction=trade.direction.value,
                    rule_id=rule.rule_id,
                    activated=activated,
                    triggered=triggered,
                    simulated_close_complete=complete,
                    activation_timestamp_ms=(
                        rule_state.activated_at_ms
                    ),
                    trigger_timestamp_ms=(
                        rule_state.triggered_at_ms
                    ),
                    completion_timestamp_ms=(
                        rule_state.completed_at_ms
                    ),
                    simulated_filled_quantity=(
                        rule_state.filled_quantity
                    ),
                    simulated_average_exit_price=average_exit,
                    simulated_exit_fees=rule_state.exit_fees,
                    attempt_count=rule_state.attempt_count,
                    planning_rejection_count=(
                        rule_state.planning_rejection_count
                    ),
                    no_fill_count=rule_state.no_fill_count,
                    actual_net_pnl=trade.net_pnl,
                    actual_net_r=trade.net_r,
                    candidate_net_pnl_estimate=candidate_net,
                    candidate_net_r_estimate=candidate_r,
                    delta_net_pnl_estimate=delta_pnl,
                    delta_net_r_estimate=delta_r,
                    candidate_source=source,
                )
            )

    def _rule_summary(
        self,
        rule: ProfitLockRule,
    ) -> dict[str, object]:
        outcomes = tuple(
            outcome
            for outcome in self._outcomes
            if outcome.rule_id == rule.rule_id
        )
        evaluated = tuple(
            outcome
            for outcome in outcomes
            if outcome.candidate_net_pnl_estimate is not None
        )
        actual_pnl = sum(
            (outcome.actual_net_pnl for outcome in evaluated),
            ZERO,
        )
        candidate_pnl = sum(
            (
                outcome.candidate_net_pnl_estimate
                for outcome in evaluated
                if outcome.candidate_net_pnl_estimate is not None
            ),
            ZERO,
        )
        actual_mean_r = (
            None
            if not evaluated
            else sum(
                (outcome.actual_net_r for outcome in evaluated),
                ZERO,
            )
            / Decimal(len(evaluated))
        )
        candidate_mean_r = (
            None
            if not evaluated
            else sum(
                (
                    outcome.candidate_net_r_estimate
                    for outcome in evaluated
                    if outcome.candidate_net_r_estimate is not None
                ),
                ZERO,
            )
            / Decimal(len(evaluated))
        )
        return {
            "rule_id": rule.rule_id,
            "activate_at_r": str(rule.activate_at_r),
            "lock_at_r": str(rule.lock_at_r),
            "closed_eligible_trades": len(outcomes),
            "economically_evaluated_trades": len(evaluated),
            "activated_trades": sum(
                1 for outcome in outcomes if outcome.activated
            ),
            "triggered_trades": sum(
                1 for outcome in outcomes if outcome.triggered
            ),
            "simulated_full_closes": sum(
                1
                for outcome in outcomes
                if outcome.simulated_close_complete
            ),
            "triggered_incomplete": sum(
                1
                for outcome in outcomes
                if outcome.candidate_source
                == "triggered_incomplete"
            ),
            "actual_positive_trades": sum(
                1
                for outcome in evaluated
                if outcome.actual_net_pnl > ZERO
            ),
            "candidate_positive_trades_estimate": sum(
                1
                for outcome in evaluated
                if (
                    outcome.candidate_net_pnl_estimate
                    is not None
                    and outcome.candidate_net_pnl_estimate > ZERO
                )
            ),
            "actual_net_pnl": str(actual_pnl),
            "candidate_net_pnl_estimate": str(candidate_pnl),
            "delta_net_pnl_estimate": str(
                candidate_pnl - actual_pnl
            ),
            "actual_mean_net_r": (
                None
                if actual_mean_r is None
                else str(actual_mean_r)
            ),
            "candidate_mean_net_r_estimate": (
                None
                if candidate_mean_r is None
                else str(candidate_mean_r)
            ),
            "delta_mean_net_r_estimate": (
                None
                if actual_mean_r is None
                or candidate_mean_r is None
                else str(candidate_mean_r - actual_mean_r)
            ),
        }

    def summary_payload(self) -> dict[str, object]:
        eligible_open = sum(
            1
            for state in self._positions.values()
            if state.eligible
        )
        excluded_open = len(self._positions) - eligible_open
        return {
            "research_only": True,
            "execution_authority": False,
            "enabled": True,
            "durable_state": True,
            "state_restored": self._state_restored,
            "state_restore_error": self._state_restore_error,
            "state_schema_version": (
                EXECUTION_SHADOW_STATE_SCHEMA_VERSION
            ),
            "started_at_ms": self._started_at_ms,
            "fill_model": (
                "visible_book_ioc_plus_actual_entry_fee_"
                "plus_funding_reserve"
            ),
            "eligible_open_positions": eligible_open,
            "excluded_pre_observer_open_positions": excluded_open,
            "excluded_closed_trades": self._excluded_closed_trades,
            "lineage_mismatch_closed_trades": (
                self._lineage_mismatch_closed_trades
            ),
            "orphaned_restored_positions": (
                self._orphaned_restored_positions
            ),
            "closed_outcome_count": len(self._outcomes),
            "rules": [
                self._rule_summary(rule)
                for rule in self._rules
            ],
        }

    def _rule_state_payload(
        self,
        state: _RuleState,
    ) -> dict[str, object]:
        return {
            "rule_id": state.rule_id,
            "remaining_quantity": str(
                state.remaining_quantity
            ),
            "activated_at_ms": state.activated_at_ms,
            "triggered_at_ms": state.triggered_at_ms,
            "trigger_mark_px": (
                None
                if state.trigger_mark_px is None
                else str(state.trigger_mark_px)
            ),
            "trigger_event_key": state.trigger_event_key,
            "latest_mark_timestamp_ms": (
                state.latest_mark_timestamp_ms
            ),
            "filled_quantity": str(state.filled_quantity),
            "fill_notional": str(state.fill_notional),
            "candidate_gross_pnl": str(
                state.candidate_gross_pnl
            ),
            "exit_fees": str(state.exit_fees),
            "completed_at_ms": state.completed_at_ms,
            "attempt_count": state.attempt_count,
            "planning_rejection_count": (
                state.planning_rejection_count
            ),
            "no_fill_count": state.no_fill_count,
            "last_rejection": state.last_rejection,
            "last_attempt_result": state.last_attempt_result,
            "book_event_keys": list(state.book_event_keys),
        }

    def open_rule_state_payloads(
        self,
        rule_id: str,
    ) -> tuple[dict[str, object], ...]:
        if rule_id not in {rule.rule_id for rule in self._rules}:
            raise ValueError(
                f"unknown profit-lock rule for open-state preview: {rule_id}"
            )
        rows: list[dict[str, object]] = []
        for state in sorted(
            self._positions.values(),
            key=lambda item: item.opening_plan_id,
        ):
            rows.append(
                {
                    "opening_plan_id": state.opening_plan_id,
                    "market": state.market.canonical,
                    "side": state.side.value,
                    "entry_price": str(state.entry_price),
                    "planned_risk": str(state.planned_risk),
                    "opened_at_ms": state.opened_at_ms,
                    "eligible": state.eligible,
                    "exclusion_reason": state.exclusion_reason,
                    "rule": self._rule_state_payload(
                        state.rules[rule_id]
                    ),
                }
            )
        return tuple(rows)

    def state_payload(self) -> dict[str, object]:
        positions = []
        for state in sorted(
            self._positions.values(),
            key=lambda item: item.opening_plan_id,
        ):
            positions.append(
                {
                    "opening_plan_id": state.opening_plan_id,
                    "market": state.market.canonical,
                    "side": state.side.value,
                    "initial_quantity": str(
                        state.initial_quantity
                    ),
                    "entry_price": str(state.entry_price),
                    "planned_risk": str(state.planned_risk),
                    "opened_at_ms": state.opened_at_ms,
                    "eligible": state.eligible,
                    "exclusion_reason": (
                        state.exclusion_reason
                    ),
                    "rules": [
                        self._rule_state_payload(
                            state.rules[rule.rule_id]
                        )
                        for rule in self._rules
                    ],
                }
            )
        return {
            "schema_version": (
                EXECUTION_SHADOW_STATE_SCHEMA_VERSION
            ),
            "started_at_ms": self._started_at_ms,
            "execution_config": _execution_config_payload(
                self._config
            ),
            "rules": _rules_payload(self._rules),
            "positions": positions,
            "outcomes": [
                outcome.payload()
                for outcome in sorted(
                    self._outcomes,
                    key=lambda item: (
                        item.trade_id,
                        item.rule_id,
                    ),
                )
            ],
            "excluded_closed_trades": (
                self._excluded_closed_trades
            ),
            "lineage_mismatch_closed_trades": (
                self._lineage_mismatch_closed_trades
            ),
            "orphaned_restored_positions": (
                self._orphaned_restored_positions
            ),
        }

    def _restore_rule_state(
        self,
        raw: object,
    ) -> _RuleState:
        if not isinstance(raw, Mapping):
            raise ProfitLockExecutionShadowError(
                "execution-shadow rule state must be an object"
            )
        keys = raw.get("book_event_keys")
        if not isinstance(keys, list) or not all(
            isinstance(value, str) and value.strip()
            for value in keys
        ):
            raise ProfitLockExecutionShadowError(
                "book_event_keys must be non-empty strings"
            )
        trigger_event_key = raw.get("trigger_event_key")
        if trigger_event_key is not None and (
            not isinstance(trigger_event_key, str)
            or not trigger_event_key.strip()
        ):
            raise ProfitLockExecutionShadowError(
                "trigger_event_key must be null or non-empty"
            )
        last_rejection = raw.get("last_rejection")
        last_attempt_result = raw.get("last_attempt_result")
        for value, field_name in (
            (last_rejection, "last_rejection"),
            (last_attempt_result, "last_attempt_result"),
        ):
            if value is not None and (
                not isinstance(value, str) or not value.strip()
            ):
                raise ProfitLockExecutionShadowError(
                    f"{field_name} must be null or non-empty"
                )

        state = _RuleState(
            rule_id=_string(
                raw.get("rule_id"),
                "rule_id",
            ),
            remaining_quantity=_decimal(
                raw.get("remaining_quantity"),
                "remaining_quantity",
            ),
            activated_at_ms=_optional_integer(
                raw.get("activated_at_ms"),
                "activated_at_ms",
            ),
            triggered_at_ms=_optional_integer(
                raw.get("triggered_at_ms"),
                "triggered_at_ms",
            ),
            trigger_mark_px=_optional_decimal(
                raw.get("trigger_mark_px"),
                "trigger_mark_px",
            ),
            trigger_event_key=trigger_event_key,
            latest_mark_timestamp_ms=_optional_integer(
                raw.get("latest_mark_timestamp_ms"),
                "latest_mark_timestamp_ms",
            ),
            filled_quantity=_decimal(
                raw.get("filled_quantity"),
                "filled_quantity",
            ),
            fill_notional=_decimal(
                raw.get("fill_notional"),
                "fill_notional",
            ),
            candidate_gross_pnl=_decimal(
                raw.get("candidate_gross_pnl"),
                "candidate_gross_pnl",
            ),
            exit_fees=_decimal(
                raw.get("exit_fees"),
                "exit_fees",
            ),
            completed_at_ms=_optional_integer(
                raw.get("completed_at_ms"),
                "completed_at_ms",
            ),
            attempt_count=_integer(
                raw.get("attempt_count"),
                "attempt_count",
            ),
            planning_rejection_count=_integer(
                raw.get("planning_rejection_count"),
                "planning_rejection_count",
            ),
            no_fill_count=_integer(
                raw.get("no_fill_count"),
                "no_fill_count",
            ),
            last_rejection=last_rejection,
            last_attempt_result=last_attempt_result,
            book_event_keys=list(keys),
        )
        if state.remaining_quantity < ZERO:
            raise ProfitLockExecutionShadowError(
                "remaining quantity must be non-negative"
            )
        for value, field_name in (
            (state.filled_quantity, "filled_quantity"),
            (state.fill_notional, "fill_notional"),
            (state.exit_fees, "exit_fees"),
        ):
            if value < ZERO:
                raise ProfitLockExecutionShadowError(
                    f"{field_name} must be non-negative"
                )
        if state.triggered_at_ms is not None and (
            state.activated_at_ms is None
            or state.trigger_mark_px is None
            or state.trigger_event_key is None
        ):
            raise ProfitLockExecutionShadowError(
                "trigger state is incomplete"
            )
        if state.completed_at_ms is not None and (
            state.triggered_at_ms is None
            or state.remaining_quantity != ZERO
        ):
            raise ProfitLockExecutionShadowError(
                "completion state is invalid"
            )
        return state

    def restore_state(self, raw: object) -> None:
        if not isinstance(raw, Mapping):
            raise ProfitLockExecutionShadowError(
                "execution-shadow state must be an object"
            )
        if raw.get("schema_version") != (
            EXECUTION_SHADOW_STATE_SCHEMA_VERSION
        ):
            raise ProfitLockExecutionShadowError(
                "unsupported execution-shadow state schema"
            )
        if raw.get("execution_config") != (
            _execution_config_payload(self._config)
        ):
            raise ProfitLockExecutionShadowError(
                "execution-shadow config mismatch"
            )
        if raw.get("rules") != _rules_payload(self._rules):
            raise ProfitLockExecutionShadowError(
                "execution-shadow rule mismatch"
            )
        started_at_ms = _integer(
            raw.get("started_at_ms"),
            "started_at_ms",
        )
        if started_at_ms < 0:
            raise ProfitLockExecutionShadowError(
                "started_at_ms must be non-negative"
            )

        raw_positions = raw.get("positions")
        raw_outcomes = raw.get("outcomes")
        if not isinstance(raw_positions, list):
            raise ProfitLockExecutionShadowError(
                "positions must be an array"
            )
        if not isinstance(raw_outcomes, list):
            raise ProfitLockExecutionShadowError(
                "outcomes must be an array"
            )

        positions: dict[str, _PositionState] = {}
        expected_rule_ids = tuple(
            rule.rule_id for rule in self._rules
        )
        for item in raw_positions:
            if not isinstance(item, Mapping):
                raise ProfitLockExecutionShadowError(
                    "position state must be an object"
                )
            eligible = item.get("eligible")
            if not isinstance(eligible, bool):
                raise ProfitLockExecutionShadowError(
                    "eligible must be boolean"
                )
            exclusion_reason = item.get("exclusion_reason")
            if exclusion_reason is not None and (
                not isinstance(exclusion_reason, str)
                or not exclusion_reason.strip()
            ):
                raise ProfitLockExecutionShadowError(
                    "exclusion_reason must be null or non-empty"
                )
            raw_rules = item.get("rules")
            if not isinstance(raw_rules, list):
                raise ProfitLockExecutionShadowError(
                    "position rules must be an array"
                )
            restored_rules = tuple(
                self._restore_rule_state(rule)
                for rule in raw_rules
            )
            if tuple(
                rule.rule_id for rule in restored_rules
            ) != expected_rule_ids:
                raise ProfitLockExecutionShadowError(
                    "position rule order/identity mismatch"
                )
            opening_plan_id = _string(
                item.get("opening_plan_id"),
                "opening_plan_id",
            )
            state = _PositionState(
                opening_plan_id=opening_plan_id,
                market=_market_from_canonical(
                    _string(item.get("market"), "market")
                ),
                side=PositionSide(
                    _string(item.get("side"), "side")
                ),
                initial_quantity=_decimal(
                    item.get("initial_quantity"),
                    "initial_quantity",
                ),
                entry_price=_decimal(
                    item.get("entry_price"),
                    "entry_price",
                ),
                planned_risk=_decimal(
                    item.get("planned_risk"),
                    "planned_risk",
                ),
                opened_at_ms=_integer(
                    item.get("opened_at_ms"),
                    "opened_at_ms",
                ),
                eligible=eligible,
                exclusion_reason=exclusion_reason,
                rules={
                    rule.rule_id: rule
                    for rule in restored_rules
                },
            )
            if (
                state.initial_quantity <= ZERO
                or state.entry_price <= ZERO
                or state.planned_risk < ZERO
                or state.opened_at_ms < 0
            ):
                raise ProfitLockExecutionShadowError(
                    "restored position economics are invalid"
                )
            if state.eligible != (state.exclusion_reason is None):
                raise ProfitLockExecutionShadowError(
                    "restored position eligibility is inconsistent"
                )
            for rule_state in state.rules.values():
                if (
                    rule_state.remaining_quantity
                    + rule_state.filled_quantity
                    != state.initial_quantity
                ):
                    raise ProfitLockExecutionShadowError(
                        "restored rule quantity does not reconcile"
                    )
                if (
                    rule_state.completed_at_ms is not None
                    and rule_state.filled_quantity
                    != state.initial_quantity
                ):
                    raise ProfitLockExecutionShadowError(
                        "restored completed rule quantity is invalid"
                    )
                if len(set(rule_state.book_event_keys)) != len(
                    rule_state.book_event_keys
                ):
                    raise ProfitLockExecutionShadowError(
                        "restored book event keys contain duplicates"
                    )
            if opening_plan_id in positions:
                raise ProfitLockExecutionShadowError(
                    "duplicate restored opening plan"
                )
            positions[opening_plan_id] = state

        outcomes = [
            ProfitLockExecutionOutcome.from_payload(item)
            for item in raw_outcomes
        ]
        outcome_keys = {
            (outcome.trade_id, outcome.rule_id)
            for outcome in outcomes
        }
        if len(outcome_keys) != len(outcomes):
            raise ProfitLockExecutionShadowError(
                "duplicate restored execution-shadow outcome"
            )
        excluded_closed = _integer(
            raw.get("excluded_closed_trades"),
            "excluded_closed_trades",
        )
        lineage_mismatch_closed = _integer(
            raw.get("lineage_mismatch_closed_trades", 0),
            "lineage_mismatch_closed_trades",
        )
        orphaned_restored = _integer(
            raw.get("orphaned_restored_positions", 0),
            "orphaned_restored_positions",
        )
        if (
            excluded_closed < 0
            or lineage_mismatch_closed < 0
            or orphaned_restored < 0
        ):
            raise ProfitLockExecutionShadowError(
                "closed trade counters must be non-negative"
            )

        self._started_at_ms = started_at_ms
        self._positions = positions
        self._outcomes = outcomes
        self._excluded_closed_trades = excluded_closed
        self._lineage_mismatch_closed_trades = (
            lineage_mismatch_closed
        )
        self._orphaned_restored_positions = orphaned_restored
        self._state_restored = True
        self._state_restore_error = None

    def mark_state_restore_error(self, error: str) -> None:
        if not error.strip():
            raise ValueError("restore error must not be empty")
        self._state_restore_error = error
