from __future__ import annotations

from decimal import Decimal

from cocomelon.domain.execution import PaperExecutionConfig, PositionAction, PositionActionType
from cocomelon.domain.strategy import Direction, StrategyDecision
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.execution.accounting import PaperPosition, PositionSide

ZERO = Decimal("0")


def _receive_time_ms(event: StreamEvent) -> int:
    return int(event.receive_time.timestamp() * 1000)


def _fresh_mark(
    position: PaperPosition,
    event: StreamEvent | None,
    config: PaperExecutionConfig,
    timestamp_ms: int,
) -> Decimal | None:
    if event is None or event.kind is not StreamKind.ACTIVE_ASSET_CTX:
        return None
    if event.market != position.market:
        return None
    received_ms = _receive_time_ms(event)
    if received_ms > timestamp_ms:
        return None
    if timestamp_ms - received_ms > config.max_asset_ctx_age_ms:
        return None
    mark = event.payload.get("mark_px")
    if not isinstance(mark, Decimal) or not mark.is_finite() or mark <= ZERO:
        return None
    return mark


def _position_direction(position: PaperPosition) -> Direction:
    return Direction.LONG if position.side is PositionSide.LONG else Direction.SHORT


def evaluate_position(
    position: PaperPosition,
    *,
    mark_event: StreamEvent | None,
    strategy_decision: StrategyDecision | None,
    strategy_fresh: bool,
    critical_health: bool,
    explicit_reduction_quantity: Decimal | None,
    config: PaperExecutionConfig,
    timestamp_ms: int,
) -> PositionAction:
    if timestamp_ms < position.updated_at_ms:
        raise ValueError("timestamp_ms must not move backward")

    mark = _fresh_mark(position, mark_event, config, timestamp_ms)

    if critical_health:
        return PositionAction(
            action_type=PositionActionType.EXIT_EMERGENCY,
            market=position.market,
            quantity=position.quantity,
            new_stop_price=None,
            reason_codes=("CRITICAL_EXECUTION_OR_ACCOUNT_HEALTH",),
            timestamp_ms=timestamp_ms,
        )

    if mark is not None:
        stop_triggered = (
            position.side is PositionSide.LONG and mark <= position.stop_price
        ) or (
            position.side is PositionSide.SHORT and mark >= position.stop_price
        )
        if stop_triggered:
            return PositionAction(
                action_type=PositionActionType.EXIT_STOP,
                market=position.market,
                quantity=position.quantity,
                new_stop_price=None,
                reason_codes=("MARK_STOP_TRIGGERED",),
                timestamp_ms=timestamp_ms,
            )

    current_direction = _position_direction(position)
    if (
        strategy_decision is not None
        and strategy_fresh
        and strategy_decision.market == position.market
        and strategy_decision.timestamp_ms <= timestamp_ms
    ):
        if (
            strategy_decision.direction is not Direction.NO_TRADE
            and strategy_decision.direction is not current_direction
        ):
            return PositionAction(
                action_type=PositionActionType.EXIT_THESIS,
                market=position.market,
                quantity=position.quantity,
                new_stop_price=None,
                reason_codes=("OPPOSITE_FRESH_THESIS",),
                timestamp_ms=timestamp_ms,
            )

        invalidation = strategy_decision.invalidation_price
        if strategy_decision.direction is current_direction and invalidation is not None:
            tighter = (
                position.side is PositionSide.LONG and invalidation > position.stop_price
            ) or (
                position.side is PositionSide.SHORT and invalidation < position.stop_price
            )
            if tighter:
                return PositionAction(
                    action_type=PositionActionType.TIGHTEN_STOP,
                    market=position.market,
                    quantity=None,
                    new_stop_price=invalidation,
                    reason_codes=("TIGHTER_SAME_DIRECTION_INVALIDATION",),
                    timestamp_ms=timestamp_ms,
                )

    if explicit_reduction_quantity is not None:
        if not explicit_reduction_quantity.is_finite() or explicit_reduction_quantity <= ZERO:
            raise ValueError("explicit_reduction_quantity must be positive and finite")
        return PositionAction(
            action_type=PositionActionType.REDUCE,
            market=position.market,
            quantity=min(explicit_reduction_quantity, position.quantity),
            new_stop_price=None,
            reason_codes=("EXPLICIT_VALIDATED_REDUCTION",),
            timestamp_ms=timestamp_ms,
        )

    reasons = ("HOLD",) if mark is not None else ("MARK_CONTEXT_UNUSABLE",)
    return PositionAction(
        action_type=PositionActionType.HOLD,
        market=position.market,
        quantity=None,
        new_stop_price=None,
        reason_codes=reasons,
        timestamp_ms=timestamp_ms,
    )
