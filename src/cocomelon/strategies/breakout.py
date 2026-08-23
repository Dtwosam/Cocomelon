from __future__ import annotations

from decimal import Decimal

from cocomelon.domain.strategy import (
    Direction,
    StrategyContext,
    StrategyRole,
    StrategySignal,
)
from cocomelon.strategies.candles import closed_candles, reference_price

ZERO = Decimal("0")
THRESHOLD = Decimal("70")
MAX_SCORE = Decimal("100")
RELATIVE_VOLUME_THRESHOLD = Decimal("1.20")
RANGE_EXPANSION_THRESHOLD = Decimal("1.10")


def _no_trade(
    context: StrategyContext,
    *,
    score: Decimal = ZERO,
    reasons: tuple[str, ...],
) -> StrategySignal:
    return StrategySignal(
        strategy="breakout",
        role=StrategyRole.PRIMARY,
        market=context.feature_snapshot.market,
        direction=Direction.NO_TRADE,
        score=min(score, MAX_SCORE),
        timestamp_ms=context.as_of_ms,
        reason_codes=reasons,
        feature_snapshot_id=context.feature_snapshot.snapshot_id,
        invalidation_price=None,
        veto_directions=(),
    )


def _aligned(value: Decimal, direction: Direction) -> bool:
    if direction is Direction.LONG:
        return value > ZERO
    if direction is Direction.SHORT:
        return value < ZERO
    return False


def evaluate_breakout(context: StrategyContext) -> StrategySignal:
    feature = context.feature_snapshot
    if not context.eligibility.rankable:
        return _no_trade(context, reasons=("not_rankable",))
    if not context.eligibility.deep_ready:
        return _no_trade(context, reasons=("not_deep_ready",))

    candles = closed_candles(context, "15m")
    if len(candles) < 21:
        return _no_trade(context, reasons=("insufficient_15m_candles",))

    prior = candles[-21:-1]
    trigger = candles[-1]
    upper_boundary = max(candle.high_px for candle in prior)
    lower_boundary = min(candle.low_px for candle in prior)

    if trigger.close_px > upper_boundary:
        direction = Direction.LONG
        score = Decimal("50")
        reasons = ["breakout_up"]
    elif trigger.close_px < lower_boundary:
        direction = Direction.SHORT
        score = Decimal("50")
        reasons = ["breakout_down"]
    else:
        return _no_trade(context, reasons=("no_breakout",))

    volume_confirmation = (
        feature.relative_volume_15m is not None
        and feature.relative_volume_15m >= RELATIVE_VOLUME_THRESHOLD
    )
    range_confirmation = (
        feature.range_expansion_15m is not None
        and feature.range_expansion_15m >= RANGE_EXPANSION_THRESHOLD
    )
    if not volume_confirmation and not range_confirmation:
        return _no_trade(
            context,
            score=score,
            reasons=(*reasons, "missing_expansion_confirmation"),
        )

    if volume_confirmation:
        score += Decimal("20")
        reasons.append("relative_volume_confirmation")
    if range_confirmation:
        score += Decimal("20")
        reasons.append("range_expansion_confirmation")
    if feature.return_1h is not None and _aligned(feature.return_1h, direction):
        score += Decimal("10")
        reasons.append("return_1h_aligned")
    score = min(score, MAX_SCORE)

    reference = reference_price(context)
    if reference is None:
        return _no_trade(
            context,
            score=score,
            reasons=(*reasons, "invalid_invalidation"),
        )

    if direction is Direction.LONG:
        invalidation = trigger.low_px
        valid_invalidation = (
            invalidation.is_finite() and invalidation > ZERO and invalidation < reference
        )
    else:
        invalidation = trigger.high_px
        valid_invalidation = (
            invalidation.is_finite() and invalidation > ZERO and invalidation > reference
        )
    if not valid_invalidation:
        return _no_trade(
            context,
            score=score,
            reasons=(*reasons, "invalid_invalidation"),
        )

    if score < THRESHOLD:
        return _no_trade(
            context,
            score=score,
            reasons=(*reasons, "below_strategy_threshold"),
        )

    return StrategySignal(
        strategy="breakout",
        role=StrategyRole.PRIMARY,
        market=feature.market,
        direction=direction,
        score=score,
        timestamp_ms=context.as_of_ms,
        reason_codes=tuple(reasons),
        feature_snapshot_id=feature.snapshot_id,
        invalidation_price=invalidation,
        veto_directions=(),
    )
