from __future__ import annotations

from decimal import Decimal

from cocomelon.domain.market import Candle
from cocomelon.domain.strategy import Direction, StrategyContext

ZERO = Decimal("0")


def closed_candles(context: StrategyContext, interval: str) -> tuple[Candle, ...]:
    if interval == "5m":
        candles = context.candles_5m
    elif interval == "15m":
        candles = context.candles_15m
    else:
        raise ValueError(f"unsupported strategy candle interval: {interval}")

    market = context.feature_snapshot.market
    for candle in candles:
        if candle.market != market:
            raise ValueError("strategy candle market must match strategy context market")
        if candle.interval != interval:
            raise ValueError("strategy candle interval must match requested interval")

    eligible = (
        candle
        for candle in candles
        if candle.end_ms <= context.as_of_ms and candle.received_at_ms <= context.as_of_ms
    )
    return tuple(sorted(eligible, key=lambda candle: (candle.end_ms, candle.start_ms)))


def reference_price(context: StrategyContext) -> Decimal | None:
    market_context = context.market_snapshot.context
    for value in (market_context.mid_px, market_context.mark_px):
        if value is not None and value.is_finite() and value > ZERO:
            return value
    return None


def swing_invalidation(
    context: StrategyContext,
    direction: Direction,
    *,
    window: int = 4,
) -> Decimal | None:
    if window <= 0:
        raise ValueError("window must be positive")
    if direction is Direction.NO_TRADE:
        return None

    candles = closed_candles(context, "15m")
    if len(candles) < window:
        return None
    reference = reference_price(context)
    if reference is None:
        return None

    recent = candles[-window:]
    if direction is Direction.LONG:
        candidate = min(candle.low_px for candle in recent)
        if not candidate.is_finite() or candidate <= ZERO or candidate >= reference:
            return None
        return candidate

    candidate = max(candle.high_px for candle in recent)
    if not candidate.is_finite() or candidate <= ZERO or candidate <= reference:
        return None
    return candidate
