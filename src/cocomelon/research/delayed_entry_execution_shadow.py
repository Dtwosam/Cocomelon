from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from typing import Final

from cocomelon.domain.execution import (
    ExecutionResult,
    InstrumentExecutionSpec,
    OrderSide,
    OrderType,
    PaperExecutionConfig,
    PaperOrderPlan,
)
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.execution.accounting import PaperPosition, PositionSide
from cocomelon.execution.ioc import simulate_ioc

ZERO: Final = Decimal("0")
ONE: Final = Decimal("1")
BPS: Final = Decimal("10000")
DELAY_MS: Final = 60_000
MAX_DELAY_OBSERVATION_LAG_MS: Final = 60_000
STATE_SCHEMA_VERSION: Final = 2
MIN_CLOSED_ELIGIBLE_TRADES: Final = 30
MIN_FULL_DELAYED_FILLS: Final = 20


class DelayedEntryShadowError(RuntimeError):
    pass


def _decimal(value: object, field: str) -> Decimal:
    try:
        resolved = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise DelayedEntryShadowError(
            f"{field} must be a decimal"
        ) from exc
    if not resolved.is_finite():
        raise DelayedEntryShadowError(f"{field} must be finite")
    return resolved


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DelayedEntryShadowError(
            f"{field} must be an integer"
        )
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DelayedEntryShadowError(
            f"{field} must be a non-empty string"
        )
    return value


def _optional_decimal(
    value: object,
    field: str,
) -> Decimal | None:
    if value is None:
        return None
    return _decimal(value, field)


def _optional_integer(
    value: object,
    field: str,
) -> int | None:
    if value is None:
        return None
    return _integer(value, field)


def _floor_quantity(
    value: Decimal,
    quantum: Decimal,
) -> Decimal:
    if value <= ZERO:
        return ZERO
    return value.quantize(quantum, rounding=ROUND_DOWN)


def _liquidity_capacity_cause(
    plan: PaperOrderPlan,
    book: StreamEvent,
    instrument: InstrumentExecutionSpec,
    config: PaperExecutionConfig,
) -> str | None:
    if book.kind is not StreamKind.L2_BOOK:
        return None
    raw_levels = (
        book.payload.get("asks")
        if plan.side is OrderSide.BUY
        else book.payload.get("bids")
    )
    if not isinstance(raw_levels, Sequence) or isinstance(
        raw_levels,
        (str, bytes),
    ):
        return None

    slippage_bps = min(
        plan.max_slippage_bps,
        config.max_ioc_slippage_bps,
    )
    fraction = slippage_bps / BPS
    boundary = (
        plan.execution_reference_price * (ONE + fraction)
        if plan.side is OrderSide.BUY
        else plan.execution_reference_price * (ONE - fraction)
    )
    eligible_quantity = ZERO
    total_quantity = ZERO
    has_outside_boundary = False
    for raw in raw_levels:
        if not isinstance(raw, Mapping):
            return None
        price = raw.get("px")
        quantity = raw.get("sz")
        if not isinstance(price, Decimal) or not isinstance(
            quantity,
            Decimal,
        ):
            return None
        if (
            not price.is_finite()
            or not quantity.is_finite()
            or price <= ZERO
            or quantity <= ZERO
        ):
            return None
        visible = _floor_quantity(
            quantity,
            instrument.size_quantum,
        )
        total_quantity += visible
        inside = (
            price <= boundary
            if plan.side is OrderSide.BUY
            else price >= boundary
        )
        if inside:
            eligible_quantity += visible
        else:
            has_outside_boundary = True

    requested = _floor_quantity(
        plan.requested_quantity,
        instrument.size_quantum,
    )
    if eligible_quantity >= requested:
        return "eligible_depth_sufficient"
    if has_outside_boundary and total_quantity > eligible_quantity:
        return "slippage_boundary_reached"
    return "visible_depth_exhausted"


def _market_from_canonical(value: str) -> MarketId:
    if ":" in value:
        dex = value.split(":", 1)[0]
        return MarketId.from_wire_name(dex, value)
    return MarketId.from_wire_name("", value)


def _config_payload(
    config: PaperExecutionConfig,
) -> dict[str, object]:
    return {
        "config_version": config.config_version,
        "latency_ms": config.latency_ms,
        "max_book_age_ms": config.max_book_age_ms,
        "max_ioc_slippage_bps": str(
            config.max_ioc_slippage_bps
        ),
        "taker_fee_rate": str(config.taker_fee_rate),
        "native_perp_min_notional": str(
            config.native_perp_min_notional
        ),
    }


@dataclass(slots=True)
class _OpenState:
    opening_plan_id: str
    market: MarketId
    side: PositionSide
    quantity: Decimal
    actual_entry_price: Decimal
    initial_stop_price: Decimal
    cost_buffer_fraction: Decimal
    planned_risk: Decimal
    opened_at_ms: int
    target_ms: int
    eligible: bool
    exclusion_reason: str | None
    attempted_at_ms: int | None = None
    attempt_result: str | None = None
    attempt_reason: str | None = None
    attempt_capacity_cause: str | None = None
    delayed_filled_quantity: Decimal = ZERO
    delayed_average_fill_price: Decimal | None = None
    delayed_fee: Decimal = ZERO
    observation_lag_ms: int | None = None


@dataclass(frozen=True, slots=True)
class DelayedEntryOutcome:
    trade_id: str
    opening_plan_id: str
    market: str
    direction: str
    source: str
    delayed_filled_quantity: Decimal
    delayed_average_fill_price: Decimal | None
    delayed_fee: Decimal
    observation_lag_ms: int | None
    signed_price_improvement_bps: Decimal | None
    gross_r_improvement: Decimal | None
    attempt_reason: str | None = None
    capacity_cause: str | None = None

    def __post_init__(self) -> None:
        for value in (
            self.trade_id,
            self.opening_plan_id,
            self.market,
            self.direction,
            self.source,
        ):
            if not value.strip():
                raise ValueError(
                    "delayed-entry outcome identity must not be empty"
                )
        if self.direction not in {"long", "short"}:
            raise ValueError(
                "delayed-entry direction must be long or short"
            )
        if self.delayed_filled_quantity < ZERO:
            raise ValueError(
                "delayed_filled_quantity must be non-negative"
            )
        if self.delayed_average_fill_price is not None:
            if (
                not self.delayed_average_fill_price.is_finite()
                or self.delayed_average_fill_price <= ZERO
            ):
                raise ValueError(
                    "delayed_average_fill_price must be positive"
                )
        if (
            not self.delayed_fee.is_finite()
            or self.delayed_fee < ZERO
        ):
            raise ValueError(
                "delayed_fee must be non-negative"
            )
        if (
            self.observation_lag_ms is not None
            and self.observation_lag_ms < 0
        ):
            raise ValueError(
                "observation_lag_ms must be non-negative"
            )
        metrics = (
            self.signed_price_improvement_bps,
            self.gross_r_improvement,
        )
        if any(value is None for value in metrics) and not all(
            value is None for value in metrics
        ):
            raise ValueError(
                "delayed-entry comparison metrics must reconcile"
            )
        for metric in metrics:
            if metric is not None and not metric.is_finite():
                raise ValueError(
                    "delayed-entry comparison metric must be finite"
                )
        if self.attempt_reason is not None and not self.attempt_reason.strip():
            raise ValueError(
                "delayed-entry attempt_reason must be null or non-empty"
            )
        if self.capacity_cause is not None and not self.capacity_cause.strip():
            raise ValueError(
                "delayed-entry capacity_cause must be null or non-empty"
            )

    def payload(self) -> dict[str, object]:
        return {
            "trade_id": self.trade_id,
            "opening_plan_id": self.opening_plan_id,
            "market": self.market,
            "direction": self.direction,
            "source": self.source,
            "delayed_filled_quantity": str(
                self.delayed_filled_quantity
            ),
            "delayed_average_fill_price": (
                None
                if self.delayed_average_fill_price is None
                else str(self.delayed_average_fill_price)
            ),
            "delayed_fee": str(self.delayed_fee),
            "observation_lag_ms": self.observation_lag_ms,
            "signed_price_improvement_bps": (
                None
                if self.signed_price_improvement_bps is None
                else str(self.signed_price_improvement_bps)
            ),
            "gross_r_improvement": (
                None
                if self.gross_r_improvement is None
                else str(self.gross_r_improvement)
            ),
            "attempt_reason": self.attempt_reason,
            "capacity_cause": self.capacity_cause,
        }

    @classmethod
    def from_payload(
        cls,
        raw: object,
    ) -> DelayedEntryOutcome:
        if not isinstance(raw, Mapping):
            raise DelayedEntryShadowError(
                "delayed-entry outcome must be an object"
            )
        return cls(
            trade_id=_string(raw.get("trade_id"), "trade_id"),
            opening_plan_id=_string(
                raw.get("opening_plan_id"),
                "opening_plan_id",
            ),
            market=_string(raw.get("market"), "market"),
            direction=_string(
                raw.get("direction"),
                "direction",
            ),
            source=_string(raw.get("source"), "source"),
            delayed_filled_quantity=_decimal(
                raw.get("delayed_filled_quantity"),
                "delayed_filled_quantity",
            ),
            delayed_average_fill_price=_optional_decimal(
                raw.get("delayed_average_fill_price"),
                "delayed_average_fill_price",
            ),
            delayed_fee=_decimal(
                raw.get("delayed_fee"),
                "delayed_fee",
            ),
            observation_lag_ms=_optional_integer(
                raw.get("observation_lag_ms"),
                "observation_lag_ms",
            ),
            signed_price_improvement_bps=_optional_decimal(
                raw.get("signed_price_improvement_bps"),
                "signed_price_improvement_bps",
            ),
            gross_r_improvement=_optional_decimal(
                raw.get("gross_r_improvement"),
                "gross_r_improvement",
            ),
            attempt_reason=(
                None
                if raw.get("attempt_reason") is None
                else _string(
                    raw.get("attempt_reason"),
                    "attempt_reason",
                )
            ),
            capacity_cause=(
                None
                if raw.get("capacity_cause") is None
                else _string(
                    raw.get("capacity_cause"),
                    "capacity_cause",
                )
            ),
        )


class DelayedEntryExecutionShadow:
    def __init__(
        self,
        config: PaperExecutionConfig,
        *,
        started_at_ms: int,
        delay_ms: int = DELAY_MS,
        max_observation_lag_ms: int = MAX_DELAY_OBSERVATION_LAG_MS,
    ) -> None:
        if started_at_ms < 0:
            raise ValueError(
                "started_at_ms must be non-negative"
            )
        if delay_ms <= 0:
            raise ValueError("delay_ms must be positive")
        if max_observation_lag_ms <= 0:
            raise ValueError(
                "max_observation_lag_ms must be positive"
            )
        self._config = config
        self._started_at_ms = started_at_ms
        self._delay_ms = delay_ms
        self._max_observation_lag_ms = max_observation_lag_ms
        self._open: dict[str, _OpenState] = {}
        self._outcomes: list[DelayedEntryOutcome] = []
        self._excluded_closed_trades = 0
        self._lineage_mismatch_closed_trades = 0
        self._orphaned_restored_positions = 0
        self._state_restored = False
        self._state_restore_error: str | None = None

    def _state_for_position(
        self,
        position: PaperPosition,
    ) -> _OpenState:
        existing = self._open.get(
            position.opening_plan_id
        )
        if existing is not None:
            if (
                existing.market != position.market
                or existing.side != position.side
                or existing.actual_entry_price
                != position.average_entry_price
            ):
                raise DelayedEntryShadowError(
                    "delayed-entry position identity drifted"
                )
            return existing

        eligible = (
            position.opened_at_ms >= self._started_at_ms
            and position.planned_risk > ZERO
        )
        reason: str | None = None
        if position.opened_at_ms < self._started_at_ms:
            reason = "PRE_OBSERVER_POSITION"
        elif position.planned_risk <= ZERO:
            reason = "NON_POSITIVE_PLANNED_RISK"

        state = _OpenState(
            opening_plan_id=position.opening_plan_id,
            market=position.market,
            side=position.side,
            quantity=position.quantity,
            actual_entry_price=(
                position.average_entry_price
            ),
            initial_stop_price=position.stop_price,
            cost_buffer_fraction=(
                position.cost_buffer_fraction
            ),
            planned_risk=position.planned_risk,
            opened_at_ms=position.opened_at_ms,
            target_ms=position.opened_at_ms + self._delay_ms,
            eligible=eligible,
            exclusion_reason=reason,
        )
        self._open[position.opening_plan_id] = state
        return state

    def observe_mark(
        self,
        positions: Sequence[PaperPosition],
        _mark_event: StreamEvent,
        *,
        now_ms: int,
    ) -> None:
        if now_ms < 0:
            raise ValueError("now_ms must be non-negative")
        for position in positions:
            self._state_for_position(position)

    def _plan(
        self,
        state: _OpenState,
        instrument: InstrumentExecutionSpec,
        reference_price: Decimal,
    ) -> PaperOrderPlan:
        if (
            not reference_price.is_finite()
            or reference_price <= ZERO
        ):
            raise DelayedEntryShadowError(
                "delayed-entry reference price must be positive"
            )
        stop_distance = abs(
            reference_price - state.initial_stop_price
        ) / reference_price
        if stop_distance <= ZERO:
            stop_distance = Decimal("1e-18")
        effective_loss = (
            stop_distance + state.cost_buffer_fraction
        )
        slippage = (
            self._config.max_ioc_slippage_bps / BPS
        )
        notional_ceiling = (
            state.quantity
            * reference_price
            * (ONE + slippage)
        )
        side = (
            OrderSide.BUY
            if state.side is PositionSide.LONG
            else OrderSide.SELL
        )
        return PaperOrderPlan(
            risk_decision_id=(
                f"delay-shadow:{self._delay_ms}:{state.opening_plan_id}"
            ),
            strategy_decision_id=(
                f"delay-shadow:{self._delay_ms}:{state.opening_plan_id}"
            ),
            market=state.market,
            side=side,
            requested_quantity=state.quantity,
            order_type=OrderType.MARKETABLE_IOC,
            reduce_only=False,
            execution_reference_price=reference_price,
            max_slippage_bps=(
                self._config.max_ioc_slippage_bps
            ),
            stop_price=state.initial_stop_price,
            approved_notional_ceiling=notional_ceiling,
            created_at_ms=state.target_ms,
            earliest_execution_ms=(
                state.target_ms + self._config.latency_ms
            ),
            execution_config_version=(
                self._config.config_version
            ),
            instrument_metadata_received_at_ms=(
                instrument.metadata_received_at_ms
            ),
            approved_risk_amount_ceiling=(
                state.planned_risk
            ),
            stop_distance_fraction=stop_distance,
            effective_loss_fraction=effective_loss,
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
                "delayed-entry shadow requires L2 book"
            )
        if instrument.market != book.market:
            raise ValueError(
                "delayed-entry instrument/book mismatch"
            )
        matches = tuple(
            position
            for position in positions
            if position.market == book.market
        )
        if not matches:
            return
        if len(matches) != 1:
            raise DelayedEntryShadowError(
                "duplicate delayed-entry market positions"
            )
        state = self._state_for_position(matches[0])
        if (
            not state.eligible
            or state.attempt_result is not None
        ):
            return
        if now_ms < state.target_ms + self._config.latency_ms:
            return
        lag_ms = now_ms - state.target_ms
        if lag_ms > self._max_observation_lag_ms:
            state.attempted_at_ms = now_ms
            state.attempt_result = "expired"
            state.attempt_reason = "NO_FRESH_BOOK_WITHIN_WINDOW"
            state.observation_lag_ms = lag_ms
            return

        plan = self._plan(
            state,
            instrument,
            reference_price,
        )
        simulation = simulate_ioc(
            plan,
            book,
            instrument,
            self._config,
            attempt_timestamp_ms=now_ms,
        )
        state.attempted_at_ms = now_ms
        state.attempt_result = (
            simulation.attempt.result.value
        )
        state.attempt_reason = ",".join(
            simulation.attempt.reason_codes
        )
        state.attempt_capacity_cause = _liquidity_capacity_cause(
            plan,
            book,
            instrument,
            self._config,
        )
        state.observation_lag_ms = lag_ms
        state.delayed_filled_quantity = (
            simulation.attempt.filled_quantity
        )
        state.delayed_average_fill_price = (
            simulation.attempt.average_fill_price
        )
        state.delayed_fee = simulation.attempt.fee

    def reconcile_open_positions(
        self,
        positions: Sequence[PaperPosition],
    ) -> None:
        current_ids = {
            position.opening_plan_id
            for position in positions
        }
        if self._state_restored:
            orphaned = tuple(
                opening_plan_id
                for opening_plan_id in self._open
                if opening_plan_id not in current_ids
            )
            for opening_plan_id in orphaned:
                del self._open[opening_plan_id]
                self._orphaned_restored_positions += 1
        for position in positions:
            self._state_for_position(position)

    def record_closed_trade(
        self,
        trade: TradeJournalEntry,
    ) -> None:
        state = self._open.pop(
            trade.opening_plan_id,
            None,
        )
        if state is None or not state.eligible:
            self._excluded_closed_trades += 1
            return
        if (
            state.market != trade.market
            or state.side.value != trade.direction.value
            or state.quantity != trade.filled_quantity
            or state.actual_entry_price != trade.entry_price
            or state.opened_at_ms != trade.opened_at_ms
        ):
            self._lineage_mismatch_closed_trades += 1
            return

        result = state.attempt_result
        source: str
        improvement_bps: Decimal | None = None
        improvement_r: Decimal | None = None
        if result is None:
            if trade.closed_at_ms < state.target_ms:
                source = "censored_before_delay"
            else:
                source = "missing_delayed_book"
        elif (
            result == ExecutionResult.FULL.value
            and state.delayed_average_fill_price
            is not None
            and state.delayed_filled_quantity
            == state.quantity
        ):
            source = "full_visible_book_ioc"
            signed_price = (
                state.actual_entry_price
                - state.delayed_average_fill_price
                if state.side is PositionSide.LONG
                else state.delayed_average_fill_price
                - state.actual_entry_price
            )
            improvement_bps = (
                signed_price
                / state.actual_entry_price
                * BPS
            )
            improvement_r = (
                signed_price
                * state.quantity
                / state.planned_risk
            )
        elif result == ExecutionResult.PARTIAL.value:
            source = "partial_visible_book_ioc"
        elif result == ExecutionResult.NO_FILL.value:
            source = "no_fill"
        elif result == ExecutionResult.REJECTED.value:
            source = "rejected"
        elif result == "expired":
            source = "expired"
        else:
            raise DelayedEntryShadowError(
                "unsupported delayed-entry result"
            )

        self._outcomes.append(
            DelayedEntryOutcome(
                trade_id=trade.trade_id,
                opening_plan_id=trade.opening_plan_id,
                market=trade.market.canonical,
                direction=trade.direction.value,
                source=source,
                delayed_filled_quantity=(
                    state.delayed_filled_quantity
                ),
                delayed_average_fill_price=(
                    state.delayed_average_fill_price
                ),
                delayed_fee=state.delayed_fee,
                observation_lag_ms=state.observation_lag_ms,
                signed_price_improvement_bps=improvement_bps,
                gross_r_improvement=improvement_r,
                attempt_reason=state.attempt_reason,
                capacity_cause=state.attempt_capacity_cause,
            )
        )

    @property
    def outcomes(self) -> tuple[DelayedEntryOutcome, ...]:
        return tuple(self._outcomes)

    def open_attempt_capacity_payload(self) -> dict[str, object]:
        rows: list[dict[str, object]] = []
        for state in sorted(
            self._open.values(),
            key=lambda item: (
                item.market.canonical,
                item.opening_plan_id,
            ),
        ):
            if (
                not state.eligible
                or state.attempt_result is None
            ):
                continue
            fill_fraction = (
                ZERO
                if state.quantity <= ZERO
                else (
                    state.delayed_filled_quantity
                    / state.quantity
                )
            )
            rows.append(
                {
                    "opening_plan_id": state.opening_plan_id,
                    "market": state.market.canonical,
                    "side": state.side.value,
                    "attempted_at_ms": state.attempted_at_ms,
                    "result": state.attempt_result,
                    "attempt_reason": state.attempt_reason,
                    "capacity_cause": (
                        state.attempt_capacity_cause
                    ),
                    "requested_quantity": str(
                        state.quantity
                    ),
                    "filled_quantity": str(
                        state.delayed_filled_quantity
                    ),
                    "fill_fraction": str(fill_fraction),
                    "observation_lag_ms": (
                        state.observation_lag_ms
                    ),
                }
            )
        return {
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "attempted_open_positions": len(rows),
            "rows": rows,
        }

    def summary_payload(self) -> dict[str, object]:
        outcomes = tuple(self._outcomes)
        full = tuple(
            outcome
            for outcome in outcomes
            if outcome.source == "full_visible_book_ioc"
        )
        mean_bps = (
            None
            if not full
            else sum(
                (
                    outcome.signed_price_improvement_bps
                    for outcome in full
                    if outcome.signed_price_improvement_bps
                    is not None
                ),
                ZERO,
            )
            / Decimal(len(full))
        )
        mean_r = (
            None
            if not full
            else sum(
                (
                    outcome.gross_r_improvement
                    for outcome in full
                    if outcome.gross_r_improvement
                    is not None
                ),
                ZERO,
            )
            / Decimal(len(full))
        )
        ready = (
            len(outcomes) >= MIN_CLOSED_ELIGIBLE_TRADES
            and len(full) >= MIN_FULL_DELAYED_FILLS
            and self._lineage_mismatch_closed_trades == 0
            and self._orphaned_restored_positions == 0
        )
        return {
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "enabled": True,
            "durable_state": True,
            "state_restored": self._state_restored,
            "state_restore_error": self._state_restore_error,
            "state_schema_version": STATE_SCHEMA_VERSION,
            "started_at_ms": self._started_at_ms,
            "delay_ms": self._delay_ms,
            "max_observation_lag_ms": (
                self._max_observation_lag_ms
            ),
            "open_tracked_positions": len(self._open),
            "eligible_open_positions": sum(
                1
                for state in self._open.values()
                if state.eligible
            ),
            "excluded_open_positions": sum(
                1
                for state in self._open.values()
                if not state.eligible
            ),
            "closed_eligible_trades": len(outcomes),
            "full_delayed_fills": len(full),
            "partial_delayed_fills": sum(
                1
                for outcome in outcomes
                if outcome.source
                == "partial_visible_book_ioc"
            ),
            "no_fills": sum(
                1
                for outcome in outcomes
                if outcome.source == "no_fill"
            ),
            "rejections": sum(
                1
                for outcome in outcomes
                if outcome.source == "rejected"
            ),
            "expired": sum(
                1
                for outcome in outcomes
                if outcome.source == "expired"
            ),
            "censored_before_delay": sum(
                1
                for outcome in outcomes
                if outcome.source
                == "censored_before_delay"
            ),
            "missing_delayed_book": sum(
                1
                for outcome in outcomes
                if outcome.source
                == "missing_delayed_book"
            ),
            "better_price_full_fills": sum(
                1
                for outcome in full
                if (
                    outcome.signed_price_improvement_bps
                    is not None
                    and outcome.signed_price_improvement_bps
                    > ZERO
                )
            ),
            "worse_price_full_fills": sum(
                1
                for outcome in full
                if (
                    outcome.signed_price_improvement_bps
                    is not None
                    and outcome.signed_price_improvement_bps
                    < ZERO
                )
            ),
            "mean_signed_price_improvement_bps": (
                None if mean_bps is None else str(mean_bps)
            ),
            "mean_gross_r_improvement": (
                None if mean_r is None else str(mean_r)
            ),
            "excluded_closed_trades": (
                self._excluded_closed_trades
            ),
            "lineage_mismatch_closed_trades": (
                self._lineage_mismatch_closed_trades
            ),
            "orphaned_restored_positions": (
                self._orphaned_restored_positions
            ),
            "readiness": {
                "ready_for_review": ready,
                "min_closed_eligible_trades": (
                    MIN_CLOSED_ELIGIBLE_TRADES
                ),
                "min_full_delayed_fills": (
                    MIN_FULL_DELAYED_FILLS
                ),
                "missing_closed_eligible_trades": max(
                    0,
                    MIN_CLOSED_ELIGIBLE_TRADES
                    - len(outcomes),
                ),
                "missing_full_delayed_fills": max(
                    0,
                    MIN_FULL_DELAYED_FILLS - len(full),
                ),
            },
        }

    def state_payload(self) -> dict[str, object]:
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "started_at_ms": self._started_at_ms,
            "execution_config": _config_payload(
                self._config
            ),
            "delay_ms": self._delay_ms,
            "max_observation_lag_ms": (
                self._max_observation_lag_ms
            ),
            "open": [
                {
                    "opening_plan_id": state.opening_plan_id,
                    "market": state.market.canonical,
                    "side": state.side.value,
                    "quantity": str(state.quantity),
                    "actual_entry_price": str(
                        state.actual_entry_price
                    ),
                    "initial_stop_price": str(
                        state.initial_stop_price
                    ),
                    "cost_buffer_fraction": str(
                        state.cost_buffer_fraction
                    ),
                    "planned_risk": str(
                        state.planned_risk
                    ),
                    "opened_at_ms": state.opened_at_ms,
                    "target_ms": state.target_ms,
                    "eligible": state.eligible,
                    "exclusion_reason": (
                        state.exclusion_reason
                    ),
                    "attempted_at_ms": (
                        state.attempted_at_ms
                    ),
                    "attempt_result": state.attempt_result,
                    "attempt_reason": state.attempt_reason,
                    "attempt_capacity_cause": (
                        state.attempt_capacity_cause
                    ),
                    "delayed_filled_quantity": str(
                        state.delayed_filled_quantity
                    ),
                    "delayed_average_fill_price": (
                        None
                        if state.delayed_average_fill_price
                        is None
                        else str(
                            state.delayed_average_fill_price
                        )
                    ),
                    "delayed_fee": str(
                        state.delayed_fee
                    ),
                    "observation_lag_ms": (
                        state.observation_lag_ms
                    ),
                }
                for state in sorted(
                    self._open.values(),
                    key=lambda item: item.opening_plan_id,
                )
            ],
            "outcomes": [
                outcome.payload()
                for outcome in sorted(
                    self._outcomes,
                    key=lambda item: (
                        item.trade_id,
                        item.opening_plan_id,
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

    def restore_state(self, raw: object) -> None:
        if not isinstance(raw, Mapping):
            raise DelayedEntryShadowError(
                "delayed-entry state must be an object"
            )
        if raw.get("schema_version") != STATE_SCHEMA_VERSION:
            raise DelayedEntryShadowError(
                "unsupported delayed-entry state schema"
            )
        if raw.get("execution_config") != _config_payload(
            self._config
        ):
            raise DelayedEntryShadowError(
                "delayed-entry execution config mismatch"
            )
        if raw.get("delay_ms") != self._delay_ms:
            raise DelayedEntryShadowError(
                "delayed-entry delay mismatch"
            )
        if raw.get("max_observation_lag_ms") != (
            self._max_observation_lag_ms
        ):
            raise DelayedEntryShadowError(
                "delayed-entry lag bound mismatch"
            )
        started_at_ms = _integer(
            raw.get("started_at_ms"),
            "started_at_ms",
        )
        open_raw = raw.get("open")
        outcomes_raw = raw.get("outcomes")
        if not isinstance(open_raw, list):
            raise DelayedEntryShadowError(
                "delayed-entry open state must be an array"
            )
        if not isinstance(outcomes_raw, list):
            raise DelayedEntryShadowError(
                "delayed-entry outcomes must be an array"
            )

        restored_open: dict[str, _OpenState] = {}
        for item in open_raw:
            if not isinstance(item, Mapping):
                raise DelayedEntryShadowError(
                    "delayed-entry open item must be an object"
                )
            eligible = item.get("eligible")
            if not isinstance(eligible, bool):
                raise DelayedEntryShadowError(
                    "eligible must be boolean"
                )
            exclusion = item.get("exclusion_reason")
            attempt_result = item.get("attempt_result")
            attempt_reason = item.get("attempt_reason")
            attempt_capacity_cause = item.get(
                "attempt_capacity_cause"
            )
            for value, field in (
                (exclusion, "exclusion_reason"),
                (attempt_result, "attempt_result"),
                (attempt_reason, "attempt_reason"),
                (
                    attempt_capacity_cause,
                    "attempt_capacity_cause",
                ),
            ):
                if value is not None and not isinstance(
                    value,
                    str,
                ):
                    raise DelayedEntryShadowError(
                        f"{field} must be string or null"
                    )
            opening_plan_id = _string(
                item.get("opening_plan_id"),
                "opening_plan_id",
            )
            state = _OpenState(
                opening_plan_id=opening_plan_id,
                market=_market_from_canonical(
                    _string(item.get("market"), "market")
                ),
                side=PositionSide(
                    _string(item.get("side"), "side")
                ),
                quantity=_decimal(
                    item.get("quantity"),
                    "quantity",
                ),
                actual_entry_price=_decimal(
                    item.get("actual_entry_price"),
                    "actual_entry_price",
                ),
                initial_stop_price=_decimal(
                    item.get("initial_stop_price"),
                    "initial_stop_price",
                ),
                cost_buffer_fraction=_decimal(
                    item.get("cost_buffer_fraction"),
                    "cost_buffer_fraction",
                ),
                planned_risk=_decimal(
                    item.get("planned_risk"),
                    "planned_risk",
                ),
                opened_at_ms=_integer(
                    item.get("opened_at_ms"),
                    "opened_at_ms",
                ),
                target_ms=_integer(
                    item.get("target_ms"),
                    "target_ms",
                ),
                eligible=eligible,
                exclusion_reason=exclusion,
                attempted_at_ms=_optional_integer(
                    item.get("attempted_at_ms"),
                    "attempted_at_ms",
                ),
                attempt_result=attempt_result,
                attempt_reason=attempt_reason,
                attempt_capacity_cause=attempt_capacity_cause,
                delayed_filled_quantity=_decimal(
                    item.get("delayed_filled_quantity"),
                    "delayed_filled_quantity",
                ),
                delayed_average_fill_price=_optional_decimal(
                    item.get("delayed_average_fill_price"),
                    "delayed_average_fill_price",
                ),
                delayed_fee=_decimal(
                    item.get("delayed_fee"),
                    "delayed_fee",
                ),
                observation_lag_ms=_optional_integer(
                    item.get("observation_lag_ms"),
                    "observation_lag_ms",
                ),
            )
            if (
                state.quantity <= ZERO
                or state.actual_entry_price <= ZERO
                or state.initial_stop_price <= ZERO
                or state.cost_buffer_fraction < ZERO
                or state.planned_risk < ZERO
                or state.opened_at_ms < 0
                or state.target_ms
                != state.opened_at_ms + self._delay_ms
            ):
                raise DelayedEntryShadowError(
                    "invalid restored delayed-entry economics"
                )
            if opening_plan_id in restored_open:
                raise DelayedEntryShadowError(
                    "duplicate delayed-entry opening plan"
                )
            restored_open[opening_plan_id] = state

        outcomes = [
            DelayedEntryOutcome.from_payload(item)
            for item in outcomes_raw
        ]
        outcome_ids = {
            outcome.trade_id
            for outcome in outcomes
        }
        if len(outcome_ids) != len(outcomes):
            raise DelayedEntryShadowError(
                "duplicate delayed-entry outcome"
            )

        excluded = _integer(
            raw.get("excluded_closed_trades"),
            "excluded_closed_trades",
        )
        mismatches = _integer(
            raw.get("lineage_mismatch_closed_trades"),
            "lineage_mismatch_closed_trades",
        )
        orphaned = _integer(
            raw.get("orphaned_restored_positions", 0),
            "orphaned_restored_positions",
        )
        if excluded < 0 or mismatches < 0 or orphaned < 0:
            raise DelayedEntryShadowError(
                "delayed-entry counters must be non-negative"
            )

        self._started_at_ms = started_at_ms
        self._open = restored_open
        self._outcomes = outcomes
        self._excluded_closed_trades = excluded
        self._lineage_mismatch_closed_trades = mismatches
        self._orphaned_restored_positions = orphaned
        self._state_restored = True
        self._state_restore_error = None

    def mark_state_restore_error(self, error: str) -> None:
        if not error.strip():
            raise ValueError(
                "restore error must not be empty"
            )
        self._state_restore_error = error
