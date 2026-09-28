from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Final

from cocomelon.domain.execution import OrderSide, PaperOrderPlan
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.risk import RiskLimits
from cocomelon.domain.strategy import Direction
from cocomelon.evidence.openings import paper_liquidation_surrogate
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
from cocomelon.research.opening_fill_liquidity import (
    OpeningFillLiquidityEvidence,
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
    stop_price: Decimal
    venue_max_leverage: Decimal
    opening_reference_notional: Decimal
    entry_side_depth_25bps: Decimal
    exit_side_depth_25bps: Decimal
    entry_fee: Decimal
    close_realized_increment: Decimal
    marks: tuple[tuple[int, Decimal], ...]
    opening_kind: str

    def __post_init__(self) -> None:
        for identity in (
            self.trade_id,
            self.market,
            self.direction,
            self.opening_kind,
        ):
            if not identity.strip():
                raise ValueError("position identity must not be empty")
        if self.direction not in {"long", "short"}:
            raise ValueError("direction must be long or short")
        if self.open_ms < 0 or self.close_ms <= self.open_ms:
            raise ValueError("position timestamps are invalid")
        for metric, field in (
            (self.entry_price, "entry_price"),
            (self.quantity, "quantity"),
            (self.planned_risk, "planned_risk"),
            (self.stop_price, "stop_price"),
        ):
            if not metric.is_finite() or metric <= ZERO:
                raise ValueError(f"{field} must be positive and finite")
        if (
            not self.venue_max_leverage.is_finite()
            or self.venue_max_leverage <= ZERO
        ):
            raise ValueError(
                "venue_max_leverage must be positive and finite"
            )
        if (
            not self.opening_reference_notional.is_finite()
            or self.opening_reference_notional <= ZERO
        ):
            raise ValueError(
                "opening_reference_notional must be positive and finite"
            )
        for depth, field in (
            (self.entry_side_depth_25bps, "entry_side_depth_25bps"),
            (self.exit_side_depth_25bps, "exit_side_depth_25bps"),
        ):
            if not depth.is_finite() or depth < ZERO:
                raise ValueError(
                    f"{field} must be non-negative and finite"
                )
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
        plan.plan_id != trade.opening_plan_id
        or plan.reduce_only
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


def _effective_leverage(
    position: _Position,
    *,
    paper_max_gross_leverage: Decimal,
) -> Decimal:
    return min(
        paper_max_gross_leverage,
        position.venue_max_leverage,
    )


def _reserved_margin(
    active: Mapping[str, _Active],
    *,
    paper_max_gross_leverage: Decimal,
) -> Decimal:
    return sum(
        (
            _gross_notional(item)
            / _effective_leverage(
                item.position,
                paper_max_gross_leverage=paper_max_gross_leverage,
            )
            for item in active.values()
        ),
        ZERO,
    )


def _liquidation_buffer_check(
    position: _Position,
    *,
    limits: RiskLimits,
    paper_max_gross_leverage: Decimal,
) -> tuple[Decimal, bool]:
    direction = (
        Direction.LONG
        if position.direction == "long"
        else Direction.SHORT
    )
    liquidation = paper_liquidation_surrogate(
        position.entry_price,
        direction,
        paper_max_leverage=paper_max_gross_leverage,
        venue_max_leverage=position.venue_max_leverage,
    )
    if direction is Direction.LONG:
        side_safe = liquidation < position.stop_price
        stop_distance = position.entry_price - position.stop_price
        liquidation_distance = position.entry_price - liquidation
    else:
        side_safe = liquidation > position.stop_price
        stop_distance = position.stop_price - position.entry_price
        liquidation_distance = liquidation - position.entry_price
    if stop_distance <= ZERO or liquidation_distance <= ZERO:
        return ZERO, False
    multiple = liquidation_distance / stop_distance
    return (
        multiple,
        side_safe
        and multiple >= limits.min_liquidation_stop_multiple,
    )


def _path_venue_max_leverage(
    raw: Mapping[str, object],
) -> Decimal | None:
    value = raw.get("venue_max_leverage")
    if value is None:
        return None
    resolved = _decimal(value, "venue_max_leverage")
    if resolved <= ZERO:
        raise DelayedEntryCapacityOverlayError(
            "venue_max_leverage must be positive"
        )
    return resolved


def _liquidity_capacity(
    position: _Position,
    limits: RiskLimits,
) -> Decimal:
    return (
        min(
            position.entry_side_depth_25bps,
            position.exit_side_depth_25bps,
        )
        * limits.max_visible_depth_fraction
    )


def _capacity_timeline(
    positions: tuple[_Position, ...],
    *,
    reference_equity: Decimal,
    limits: RiskLimits,
    paper_max_gross_leverage: Decimal,
    native_perp_min_notional: Decimal,
) -> dict[str, object]:
    if not reference_equity.is_finite() or reference_equity <= ZERO:
        raise DelayedEntryCapacityOverlayError(
            "reference equity must be positive"
        )
    if (
        not paper_max_gross_leverage.is_finite()
        or paper_max_gross_leverage <= ZERO
    ):
        raise DelayedEntryCapacityOverlayError(
            "paper max gross leverage must be positive"
        )
    if (
        not native_perp_min_notional.is_finite()
        or native_perp_min_notional <= ZERO
    ):
        raise DelayedEntryCapacityOverlayError(
            "native perp min notional must be positive"
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
    margin_capacity_violations = 0
    liquidity_capacity_violations = 0
    venue_min_notional_violations = 0
    liquidation_buffer_violations = 0
    non_positive_equity = 0
    max_aggregate_risk_utilization = ZERO
    max_bucket_risk_utilization = ZERO
    max_gross_leverage = ZERO
    max_margin_capacity_utilization = ZERO
    max_liquidity_capacity_utilization = ZERO
    min_aggregate_risk_headroom: Decimal | None = None
    min_bucket_risk_headroom: Decimal | None = None
    min_gross_notional_headroom: Decimal | None = None
    min_margin_notional_headroom: Decimal | None = None
    min_liquidity_notional_headroom: Decimal | None = None
    min_venue_notional_headroom: Decimal | None = None
    min_liquidation_stop_multiple: Decimal | None = None
    min_liquidation_stop_headroom: Decimal | None = None

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
        effective_leverage = min(
            limits.max_gross_leverage,
            position.venue_max_leverage,
        )
        reserved_margin = _reserved_margin(
            active,
            paper_max_gross_leverage=paper_max_gross_leverage,
        )
        liquidity_capacity = _liquidity_capacity(
            position,
            limits,
        )
        liquidity_notional = position.opening_reference_notional
        liquidity_headroom = (
            liquidity_capacity - liquidity_notional
        )
        liquidity_bad = liquidity_headroom < ZERO
        venue_notional_headroom = (
            position.opening_reference_notional
            - native_perp_min_notional
        )
        venue_min_bad = venue_notional_headroom < ZERO
        min_venue_notional_headroom = (
            venue_notional_headroom
            if min_venue_notional_headroom is None
            else min(
                min_venue_notional_headroom,
                venue_notional_headroom,
            )
        )
        min_liquidity_notional_headroom = (
            liquidity_headroom
            if min_liquidity_notional_headroom is None
            else min(
                min_liquidity_notional_headroom,
                liquidity_headroom,
            )
        )
        if liquidity_capacity > ZERO:
            max_liquidity_capacity_utilization = max(
                max_liquidity_capacity_utilization,
                liquidity_notional / liquidity_capacity,
            )
        (
            liquidation_multiple,
            liquidation_ok,
        ) = _liquidation_buffer_check(
            position,
            limits=limits,
            paper_max_gross_leverage=paper_max_gross_leverage,
        )
        liquidation_bad = not liquidation_ok
        liquidation_headroom = (
            liquidation_multiple
            - limits.min_liquidation_stop_multiple
        )
        min_liquidation_stop_multiple = (
            liquidation_multiple
            if min_liquidation_stop_multiple is None
            else min(
                min_liquidation_stop_multiple,
                liquidation_multiple,
            )
        )
        min_liquidation_stop_headroom = (
            liquidation_headroom
            if min_liquidation_stop_headroom is None
            else min(
                min_liquidation_stop_headroom,
                liquidation_headroom,
            )
        )

        if equity <= ZERO:
            non_positive_equity += 1
            violated = True
            aggregate_bad = True
            bucket_bad = True
            gross_bad = True
            margin_bad = True
            aggregate_headroom = -after_risk
            bucket_headroom = -after_risk
            gross_headroom = -after_notional
            margin_headroom = -new_notional
        else:
            aggregate_ceiling = equity * limits.max_open_risk
            bucket_ceiling = (
                equity * limits.correlation_bucket_risk_limit
            )
            gross_ceiling = equity * effective_leverage
            available_margin = max(
                ZERO,
                equity - reserved_margin,
            )
            margin_capacity = (
                available_margin
                * limits.max_available_margin_fraction
                * effective_leverage
            )
            aggregate_headroom = aggregate_ceiling - after_risk
            bucket_headroom = bucket_ceiling - after_risk
            gross_headroom = gross_ceiling - after_notional
            margin_headroom = margin_capacity - new_notional
            aggregate_bad = aggregate_headroom < ZERO
            bucket_bad = bucket_headroom < ZERO
            gross_bad = gross_headroom < ZERO
            margin_bad = margin_headroom < ZERO
            violated = (
                aggregate_bad
                or bucket_bad
                or gross_bad
                or margin_bad
                or liquidity_bad
                or venue_min_bad
                or liquidation_bad
            )
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
            if margin_capacity > ZERO:
                max_margin_capacity_utilization = max(
                    max_margin_capacity_utilization,
                    new_notional / margin_capacity,
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
        min_margin_notional_headroom = (
            margin_headroom
            if min_margin_notional_headroom is None
            else min(
                min_margin_notional_headroom,
                margin_headroom,
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
        if margin_bad:
            margin_capacity_violations += 1
        if liquidity_bad:
            liquidity_capacity_violations += 1
        if venue_min_bad:
            venue_min_notional_violations += 1
        if liquidation_bad:
            liquidation_buffer_violations += 1

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
        "margin_capacity_violations": margin_capacity_violations,
        "liquidity_capacity_violations": (
            liquidity_capacity_violations
        ),
        "venue_min_notional_violations": (
            venue_min_notional_violations
        ),
        "liquidation_buffer_violations": (
            liquidation_buffer_violations
        ),
        "non_positive_equity_events": non_positive_equity,
        "max_aggregate_risk_utilization": str(
            max_aggregate_risk_utilization
        ),
        "max_correlation_bucket_risk_utilization": str(
            max_bucket_risk_utilization
        ),
        "max_gross_leverage": str(max_gross_leverage),
        "max_margin_capacity_utilization": str(
            max_margin_capacity_utilization
        ),
        "max_liquidity_capacity_utilization": str(
            max_liquidity_capacity_utilization
        ),
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
        "min_margin_notional_headroom": str(
            ZERO
            if min_margin_notional_headroom is None
            else min_margin_notional_headroom
        ),
        "min_liquidity_notional_headroom": str(
            ZERO
            if min_liquidity_notional_headroom is None
            else min_liquidity_notional_headroom
        ),
        "min_venue_notional_headroom": str(
            ZERO
            if min_venue_notional_headroom is None
            else min_venue_notional_headroom
        ),
        "min_liquidation_stop_multiple": str(
            ZERO
            if min_liquidation_stop_multiple is None
            else min_liquidation_stop_multiple
        ),
        "min_liquidation_stop_headroom": str(
            ZERO
            if min_liquidation_stop_headroom is None
            else min_liquidation_stop_headroom
        ),
    }


def _admission_timeline(
    positions: tuple[_Position, ...],
    *,
    reference_equity: Decimal,
    limits: RiskLimits,
    paper_max_gross_leverage: Decimal,
    native_perp_min_notional: Decimal,
) -> dict[str, object]:
    if not reference_equity.is_finite() or reference_equity <= ZERO:
        raise DelayedEntryCapacityOverlayError(
            "reference equity must be positive"
        )
    if (
        not paper_max_gross_leverage.is_finite()
        or paper_max_gross_leverage <= ZERO
    ):
        raise DelayedEntryCapacityOverlayError(
            "paper max gross leverage must be positive"
        )
    if (
        not native_perp_min_notional.is_finite()
        or native_perp_min_notional <= ZERO
    ):
        raise DelayedEntryCapacityOverlayError(
            "native perp min notional must be positive"
        )

    active: dict[str, _Active] = {}
    rejected: set[str] = set()
    realized = ZERO
    opening_opportunities = 0
    overlap_opportunities = 0
    admitted_openings = 0
    rejected_openings = 0
    delayed_admitted = 0
    delayed_rejected = 0
    observed_admitted = 0
    observed_rejected = 0
    aggregate_rejections = 0
    bucket_rejections = 0
    leverage_rejections = 0
    margin_rejections = 0
    liquidity_rejections = 0
    venue_min_notional_rejections = 0
    liquidation_rejections = 0
    non_positive_equity_rejections = 0
    max_concurrent_positions = 0
    max_admitted_aggregate_utilization = ZERO
    max_admitted_bucket_utilization = ZERO
    max_admitted_gross_leverage = ZERO
    max_admitted_margin_utilization = ZERO
    max_admitted_liquidity_utilization = ZERO
    min_admitted_liquidation_multiple: Decimal | None = None

    for event in _position_events(positions):
        if event.kind == "close":
            item = active.pop(event.trade_id, None)
            if item is not None:
                realized += item.position.close_realized_increment
                continue
            if event.trade_id in rejected:
                rejected.remove(event.trade_id)
                continue
            raise DelayedEntryCapacityOverlayError(
                "admission close has no tracked position"
            )

        if event.kind == "mark":
            item = active.get(event.trade_id)
            if item is None:
                continue
            mark_px = event.mark_px
            if mark_px is None:
                raise DelayedEntryCapacityOverlayError(
                    "admission mark is missing price"
                )
            item.latest_mark = mark_px
            continue

        position = event.position
        if position is None:
            raise DelayedEntryCapacityOverlayError(
                "admission open is missing position"
            )
        if (
            position.trade_id in active
            or position.trade_id in rejected
        ):
            raise DelayedEntryCapacityOverlayError(
                "admission position opened twice"
            )

        opening_opportunities += 1
        if active:
            overlap_opportunities += 1

        unrealized = sum(
            (_unrealized(item) for item in active.values()),
            ZERO,
        )
        equity = reference_equity + realized + unrealized
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
        effective_leverage = min(
            limits.max_gross_leverage,
            position.venue_max_leverage,
        )
        reserved_margin = _reserved_margin(
            active,
            paper_max_gross_leverage=paper_max_gross_leverage,
        )
        liquidity_capacity = _liquidity_capacity(
            position,
            limits,
        )
        liquidity_notional = position.opening_reference_notional
        liquidity_bad = liquidity_notional > liquidity_capacity
        venue_min_bad = (
            position.opening_reference_notional
            < native_perp_min_notional
        )
        (
            liquidation_multiple,
            liquidation_ok,
        ) = _liquidation_buffer_check(
            position,
            limits=limits,
            paper_max_gross_leverage=paper_max_gross_leverage,
        )
        liquidation_bad = not liquidation_ok

        if equity <= ZERO:
            aggregate_bad = True
            bucket_bad = True
            leverage_bad = True
            margin_bad = True
            margin_capacity = ZERO
            non_positive_equity_rejections += 1
        else:
            aggregate_ceiling = equity * limits.max_open_risk
            bucket_ceiling = (
                equity * limits.correlation_bucket_risk_limit
            )
            gross_ceiling = equity * effective_leverage
            available_margin = max(
                ZERO,
                equity - reserved_margin,
            )
            margin_capacity = (
                available_margin
                * limits.max_available_margin_fraction
                * effective_leverage
            )
            aggregate_bad = after_risk > aggregate_ceiling
            bucket_bad = after_risk > bucket_ceiling
            leverage_bad = after_notional > gross_ceiling
            margin_bad = new_notional > margin_capacity

        rejected_now = (
            aggregate_bad
            or bucket_bad
            or leverage_bad
            or margin_bad
            or liquidity_bad
            or venue_min_bad
            or liquidation_bad
        )
        if rejected_now:
            rejected_openings += 1
            rejected.add(position.trade_id)
            if position.opening_kind == "delayed_candidate":
                delayed_rejected += 1
            else:
                observed_rejected += 1
            if aggregate_bad:
                aggregate_rejections += 1
            if bucket_bad:
                bucket_rejections += 1
            if leverage_bad:
                leverage_rejections += 1
            if margin_bad:
                margin_rejections += 1
            if liquidity_bad:
                liquidity_rejections += 1
            if venue_min_bad:
                venue_min_notional_rejections += 1
            if liquidation_bad:
                liquidation_rejections += 1
            continue

        admitted_openings += 1
        if position.opening_kind == "delayed_candidate":
            delayed_admitted += 1
        else:
            observed_admitted += 1
        if equity > ZERO:
            max_admitted_aggregate_utilization = max(
                max_admitted_aggregate_utilization,
                after_risk / (equity * limits.max_open_risk),
            )
            max_admitted_bucket_utilization = max(
                max_admitted_bucket_utilization,
                after_risk
                / (
                    equity
                    * limits.correlation_bucket_risk_limit
                ),
            )
            max_admitted_gross_leverage = max(
                max_admitted_gross_leverage,
                after_notional / equity,
            )
            if margin_capacity > ZERO:
                max_admitted_margin_utilization = max(
                    max_admitted_margin_utilization,
                    new_notional / margin_capacity,
                )
            if liquidity_capacity > ZERO:
                max_admitted_liquidity_utilization = max(
                    max_admitted_liquidity_utilization,
                    liquidity_notional / liquidity_capacity,
                )
            min_admitted_liquidation_multiple = (
                liquidation_multiple
                if min_admitted_liquidation_multiple is None
                else min(
                    min_admitted_liquidation_multiple,
                    liquidation_multiple,
                )
            )

        realized -= position.entry_fee
        active[position.trade_id] = _Active(
            position=position,
            latest_mark=position.entry_price,
        )
        max_concurrent_positions = max(
            max_concurrent_positions,
            len(active),
        )

    if active or rejected:
        raise DelayedEntryCapacityOverlayError(
            "admission timeline did not finish flat"
        )

    return {
        "opening_opportunities": opening_opportunities,
        "overlap_opening_opportunities": overlap_opportunities,
        "admitted_openings": admitted_openings,
        "rejected_openings": rejected_openings,
        "delayed_candidate_admitted": delayed_admitted,
        "delayed_candidate_rejected": delayed_rejected,
        "observed_schedule_admitted": observed_admitted,
        "observed_schedule_rejected": observed_rejected,
        "aggregate_risk_rejections": aggregate_rejections,
        "correlation_bucket_risk_rejections": bucket_rejections,
        "gross_leverage_rejections": leverage_rejections,
        "margin_capacity_rejections": margin_rejections,
        "liquidity_capacity_rejections": liquidity_rejections,
        "venue_min_notional_rejections": (
            venue_min_notional_rejections
        ),
        "liquidation_buffer_rejections": liquidation_rejections,
        "non_positive_equity_rejections": (
            non_positive_equity_rejections
        ),
        "max_concurrent_positions": max_concurrent_positions,
        "max_admitted_aggregate_risk_utilization": str(
            max_admitted_aggregate_utilization
        ),
        "max_admitted_correlation_bucket_risk_utilization": str(
            max_admitted_bucket_utilization
        ),
        "max_admitted_gross_leverage": str(
            max_admitted_gross_leverage
        ),
        "max_admitted_margin_capacity_utilization": str(
            max_admitted_margin_utilization
        ),
        "max_admitted_liquidity_capacity_utilization": str(
            max_admitted_liquidity_utilization
        ),
        "min_admitted_liquidation_stop_multiple": str(
            ZERO
            if min_admitted_liquidation_multiple is None
            else min_admitted_liquidation_multiple
        ),
        "final_realized_contribution": str(realized),
    }


def _fixed_realized_contribution(
    positions: tuple[_Position, ...],
) -> Decimal:
    return sum(
        (
            position.close_realized_increment
            - position.entry_fee
            for position in positions
        ),
        ZERO,
    )


def _validate_opening_liquidity(
    trade: TradeJournalEntry,
    evidence: OpeningFillLiquidityEvidence,
) -> None:
    if (
        evidence.opening_plan_id != trade.opening_plan_id
        or evidence.strategy_decision_id != trade.strategy_decision_id
        or evidence.feature_snapshot_id != trade.feature_snapshot_id
        or evidence.market != trade.market.canonical
        or evidence.direction != trade.direction.value
        or evidence.opened_at_ms != trade.opened_at_ms
    ):
        raise DelayedEntryCapacityOverlayError(
            "opening liquidity lineage is invalid"
        )


def _actual_position(
    trade: TradeJournalEntry,
    marks: tuple[tuple[int, Decimal], ...],
    plan: PaperOrderPlan,
    venue_max_leverage: Decimal,
    liquidity: OpeningFillLiquidityEvidence,
) -> _Position:
    _validate_plan(trade, plan)
    _validate_opening_liquidity(trade, liquidity)
    stop_price = plan.stop_price
    if stop_price is None:
        raise DelayedEntryCapacityOverlayError(
            "opening plan is missing stop price"
        )
    planned_risk = (
        _risk_per_quantity(plan, trade.entry_price)
        * trade.filled_quantity
    )
    if (
        plan.approved_risk_amount_ceiling is not None
        and planned_risk > plan.approved_risk_amount_ceiling
    ):
        raise DelayedEntryCapacityOverlayError(
            "observed filled risk exceeds approved opening ceiling"
        )
    return _Position(
        trade_id=trade.trade_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        open_ms=trade.opened_at_ms,
        close_ms=trade.closed_at_ms,
        entry_price=trade.entry_price,
        quantity=trade.filled_quantity,
        planned_risk=planned_risk,
        stop_price=stop_price,
        venue_max_leverage=venue_max_leverage,
        opening_reference_notional=(
            plan.requested_quantity
            * plan.execution_reference_price
        ),
        entry_side_depth_25bps=(
            liquidity.entry_side_depth_25bps
        ),
        exit_side_depth_25bps=(
            liquidity.exit_side_depth_25bps
        ),
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
    liquidity_loader: Callable[
        [str],
        OpeningFillLiquidityEvidence | None,
    ],
    *,
    limits: RiskLimits,
    paper_max_gross_leverage: Decimal,
    native_perp_min_notional: Decimal,
    delay_ms: int = DELAY_MS,
) -> dict[str, object]:
    if delay_ms <= 0:
        raise ValueError("delay_ms must be positive")
    if (
        not paper_max_gross_leverage.is_finite()
        or paper_max_gross_leverage <= ZERO
    ):
        raise ValueError(
            "paper_max_gross_leverage must be positive and finite"
        )
    if (
        not native_perp_min_notional.is_finite()
        or native_perp_min_notional <= ZERO
    ):
        raise ValueError(
            "native_perp_min_notional must be positive and finite"
        )

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
            "changed_admissions_modeled": True,
            "admission_policy": (
                "reject_opening_when_configured_risk_or_capacity_gate_breached"
            ),
            "replacement_trades_modeled": False,
            "intratrade_funding_timing_modeled": False,
            "available_margin_capacity_modeled": True,
            "visible_liquidity_capacity_modeled": True,
            "venue_min_notional_modeled": True,
            "liquidation_buffer_modeled": True,
            "closed_shadow_outcomes": len(outcomes),
            "candidate_filled_positions": 0,
            "background_positions": 0,
            "unresolved_outcomes": len(outcomes),
            "missing_journal_trades": len(outcomes),
            "missing_opening_plans": 0,
            "missing_venue_max_leverage": 0,
            "missing_opening_liquidity_evidence": 0,
            "missing_delayed_liquidity_evidence": 0,
            "missing_delayed_reference_price": 0,
            "missing_exact_paths": 0,
            "incomplete_exact_paths": 0,
            "lineage_mismatches": 0,
            "actual": _capacity_timeline(
                (),
                reference_equity=Decimal("1"),
                limits=limits,
                paper_max_gross_leverage=paper_max_gross_leverage,
                native_perp_min_notional=native_perp_min_notional,
            ),
            "candidate": _capacity_timeline(
                (),
                reference_equity=Decimal("1"),
                limits=limits,
                paper_max_gross_leverage=paper_max_gross_leverage,
                native_perp_min_notional=native_perp_min_notional,
            ),
            "actual_admission": _admission_timeline(
                (),
                reference_equity=Decimal("1"),
                limits=limits,
                paper_max_gross_leverage=paper_max_gross_leverage,
                native_perp_min_notional=native_perp_min_notional,
            ),
            "candidate_admission": _admission_timeline(
                (),
                reference_equity=Decimal("1"),
                limits=limits,
                paper_max_gross_leverage=paper_max_gross_leverage,
                native_perp_min_notional=native_perp_min_notional,
            ),
            "fixed_candidate_final_realized_contribution": "0",
            "admitted_candidate_final_realized_contribution": "0",
            "admission_delta_vs_fixed_schedule": "0",
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
    venue_max_leverage_by_trade_id: dict[str, Decimal] = {}
    missing_paths = 0
    missing_venue_max_leverage = 0
    incomplete_paths = 0
    lineage_mismatches = 0
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
            venue_max_leverage = _path_venue_max_leverage(raw)
        except DelayedEntryCapacityOverlayError:
            lineage_mismatches += 1
            continue
        if venue_max_leverage is None:
            missing_venue_max_leverage += 1
            continue
        venue_max_leverage_by_trade_id[
            trade.trade_id
        ] = venue_max_leverage

    missing_plan = 0
    missing_opening_liquidity = 0
    opening_liquidity_by_trade_id: dict[
        str,
        OpeningFillLiquidityEvidence,
    ] = {}
    plans_by_trade_id: dict[str, PaperOrderPlan] = {}
    actual_positions: list[_Position] = []
    for trade in relevant_trades:
        marks = exact_marks.get(trade.trade_id)
        venue_max_leverage = venue_max_leverage_by_trade_id.get(
            trade.trade_id
        )
        if marks is None or venue_max_leverage is None:
            continue
        plan = plan_loader(trade.opening_plan_id)
        if plan is None:
            missing_plan += 1
            continue
        liquidity = liquidity_loader(trade.opening_plan_id)
        if liquidity is None:
            missing_opening_liquidity += 1
            continue
        try:
            _validate_plan(trade, plan)
            _validate_opening_liquidity(trade, liquidity)
            actual_position = _actual_position(
                trade,
                marks,
                plan,
                venue_max_leverage,
                liquidity,
            )
        except DelayedEntryCapacityOverlayError:
            lineage_mismatches += 1
            continue
        plans_by_trade_id[trade.trade_id] = plan
        opening_liquidity_by_trade_id[
            trade.trade_id
        ] = liquidity
        actual_positions.append(actual_position)

    candidate_positions: list[_Position] = []
    background_positions = 0
    missing_journal = 0
    unresolved_outcomes = 0
    candidate_filled = 0
    candidate_no_fill = 0
    missing_delayed_liquidity = 0
    missing_delayed_reference_price = 0

    outcome_by_id = {
        outcome.trade_id: outcome for outcome in outcomes
    }
    for trade in relevant_trades:
        marks = exact_marks.get(trade.trade_id)
        venue_max_leverage = venue_max_leverage_by_trade_id.get(
            trade.trade_id
        )
        if marks is None or venue_max_leverage is None:
            continue
        plan = plans_by_trade_id.get(trade.trade_id)
        liquidity = opening_liquidity_by_trade_id.get(
            trade.trade_id
        )
        if plan is None or liquidity is None:
            continue
        outcome = outcome_by_id.get(trade.trade_id)
        if outcome is None:
            candidate_positions.append(
                _actual_position(
                    trade,
                    marks,
                    plan,
                    venue_max_leverage,
                    liquidity,
                )
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
        try:
            weighted = evaluate_delayed_entry_fill_weighted_outcome(
                trade,
                outcome,
            )
        except DelayedEntryFillWeightedError:
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
        stop_price = plan.stop_price
        if stop_price is None:
            lineage_mismatches += 1
            continue
        delayed_reference_price = outcome.delayed_reference_price
        if delayed_reference_price is None:
            missing_delayed_reference_price += 1
            continue
        delayed_entry_depth = (
            outcome.delayed_entry_side_depth_25bps
        )
        delayed_exit_depth = (
            outcome.delayed_exit_side_depth_25bps
        )
        if (
            delayed_entry_depth is None
            or delayed_exit_depth is None
        ):
            missing_delayed_liquidity += 1
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
                stop_price=stop_price,
                venue_max_leverage=venue_max_leverage,
                opening_reference_notional=(
                    trade.filled_quantity
                    * delayed_reference_price
                ),
                entry_side_depth_25bps=delayed_entry_depth,
                exit_side_depth_25bps=delayed_exit_depth,
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
        paper_max_gross_leverage=paper_max_gross_leverage,
        native_perp_min_notional=native_perp_min_notional,
    )
    candidate_tuple = tuple(candidate_positions)
    actual_tuple = tuple(actual_positions)
    candidate = _capacity_timeline(
        candidate_tuple,
        reference_equity=reference_equity,
        limits=limits,
        paper_max_gross_leverage=paper_max_gross_leverage,
        native_perp_min_notional=native_perp_min_notional,
    )
    actual_admission = _admission_timeline(
        actual_tuple,
        reference_equity=reference_equity,
        limits=limits,
        paper_max_gross_leverage=paper_max_gross_leverage,
        native_perp_min_notional=native_perp_min_notional,
    )
    candidate_admission = _admission_timeline(
        candidate_tuple,
        reference_equity=reference_equity,
        limits=limits,
        paper_max_gross_leverage=paper_max_gross_leverage,
        native_perp_min_notional=native_perp_min_notional,
    )
    fixed_candidate_final = _fixed_realized_contribution(
        candidate_tuple
    )
    admitted_candidate_final = Decimal(
        str(candidate_admission["final_realized_contribution"])
    )

    actual_violations_raw = actual["capacity_violations"]
    candidate_overlap_raw = candidate["overlap_openings"]
    if (
        isinstance(actual_violations_raw, bool)
        or not isinstance(actual_violations_raw, int)
        or isinstance(candidate_overlap_raw, bool)
        or not isinstance(candidate_overlap_raw, int)
    ):
        raise DelayedEntryCapacityOverlayError(
            "capacity timeline counters must be integers"
        )
    actual_violations = actual_violations_raw
    candidate_overlap = candidate_overlap_raw
    actual_admission_rejections_raw = actual_admission[
        "rejected_openings"
    ]
    if (
        isinstance(actual_admission_rejections_raw, bool)
        or not isinstance(actual_admission_rejections_raw, int)
    ):
        raise DelayedEntryCapacityOverlayError(
            "actual admission rejection count must be integer"
        )
    actual_admission_rejections = (
        actual_admission_rejections_raw
    )
    ready = (
        len(outcomes) >= MIN_CLOSED_SHADOW_OUTCOMES
        and candidate_filled >= MIN_CANDIDATE_FILLED_POSITIONS
        and candidate_overlap >= MIN_CANDIDATE_OVERLAP_OPENINGS
        and unresolved_outcomes == 0
        and missing_journal == 0
        and missing_plan == 0
        and missing_venue_max_leverage == 0
        and missing_opening_liquidity == 0
        and missing_delayed_liquidity == 0
        and missing_delayed_reference_price == 0
        and missing_paths == 0
        and incomplete_paths == 0
        and lineage_mismatches == 0
        and actual_violations == 0
        and actual_admission_rejections == 0
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
        "observed_planned_risk_basis": (
            "actual_fill_notional_stop_distance_plus_plan_cost_buffer"
        ),
        "limits": {
            "max_open_risk": str(limits.max_open_risk),
            "correlation_bucket_risk_limit": str(
                limits.correlation_bucket_risk_limit
            ),
            "max_gross_leverage": str(
                limits.max_gross_leverage
            ),
            "max_available_margin_fraction": str(
                limits.max_available_margin_fraction
            ),
            "paper_max_gross_leverage": str(
                paper_max_gross_leverage
            ),
            "min_liquidation_stop_multiple": str(
                limits.min_liquidation_stop_multiple
            ),
            "max_visible_depth_fraction": str(
                limits.max_visible_depth_fraction
            ),
            "native_perp_min_notional": str(
                native_perp_min_notional
            ),
        },
        "changed_admissions_modeled": True,
        "admission_policy": (
            "reject_opening_when_configured_risk_or_capacity_gate_breached"
        ),
        "replacement_trades_modeled": False,
        "intratrade_funding_timing_modeled": False,
        "available_margin_capacity_modeled": True,
        "visible_liquidity_capacity_modeled": True,
        "venue_min_notional_modeled": True,
        "liquidation_buffer_modeled": True,
        "closed_shadow_outcomes": len(outcomes),
        "candidate_filled_positions": candidate_filled,
        "candidate_no_fill_trades": candidate_no_fill,
        "background_positions": background_positions,
        "unresolved_outcomes": unresolved_outcomes,
        "missing_journal_trades": missing_journal,
        "missing_opening_plans": missing_plan,
        "missing_venue_max_leverage": (
            missing_venue_max_leverage
        ),
        "missing_opening_liquidity_evidence": (
            missing_opening_liquidity
        ),
        "missing_delayed_liquidity_evidence": (
            missing_delayed_liquidity
        ),
        "missing_delayed_reference_price": (
            missing_delayed_reference_price
        ),
        "missing_exact_paths": missing_paths,
        "incomplete_exact_paths": incomplete_paths,
        "lineage_mismatches": lineage_mismatches,
        "actual": actual,
        "candidate": candidate,
        "actual_admission": actual_admission,
        "candidate_admission": candidate_admission,
        "fixed_candidate_final_realized_contribution": str(
            fixed_candidate_final
        ),
        "admitted_candidate_final_realized_contribution": str(
            admitted_candidate_final
        ),
        "admission_delta_vs_fixed_schedule": str(
            admitted_candidate_final - fixed_candidate_final
        ),
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
