from __future__ import annotations

from decimal import Decimal

from cocomelon.domain.features import TrendRegime
from cocomelon.domain.strategy import (
    Direction,
    StrategyContext,
    StrategyRole,
    StrategySignal,
)
from cocomelon.strategies.candles import closed_candles, swing_invalidation

ZERO = Decimal("0")
THRESHOLD = Decimal("65")
MAX_SCORE = Decimal("100")


def _no_trade(
    context: StrategyContext,
    *,
    score: Decimal = ZERO,
    reasons: tuple[str, ...],
) -> StrategySignal:
    return StrategySignal(
        strategy="trend",
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


def evaluate_trend(context: StrategyContext) -> StrategySignal:
    feature = context.feature_snapshot

    if not context.eligibility.rankable:
        return _no_trade(context, reasons=("not_rankable",))
    if not context.eligibility.deep_ready:
        return _no_trade(context, reasons=("not_deep_ready",))

    if feature.trend_regime is TrendRegime.UP:
        direction = Direction.LONG
        score = Decimal("25")
        reasons = ["trend_up"]
    elif feature.trend_regime is TrendRegime.DOWN:
        direction = Direction.SHORT
        score = Decimal("25")
        reasons = ["trend_down"]
    else:
        return _no_trade(context, reasons=("trend_regime_not_directional",))

    if feature.return_15m is None or feature.return_1h is None:
        return _no_trade(
            context,
            score=score,
            reasons=(*reasons, "missing_primary_data"),
        )

    if not _aligned(feature.return_15m, direction):
        return _no_trade(
            context,
            score=score,
            reasons=(*reasons, "return_15m_opposes"),
        )
    score += Decimal("20")
    reasons.append("return_15m_aligned")

    if not _aligned(feature.return_1h, direction):
        return _no_trade(
            context,
            score=score,
            reasons=(*reasons, "return_1h_opposes"),
        )
    score += Decimal("20")
    reasons.append("return_1h_aligned")

    if feature.return_4h is not None and _aligned(feature.return_4h, direction):
        score += Decimal("10")
        reasons.append("return_4h_aligned")
    if feature.return_5m is not None and _aligned(feature.return_5m, direction):
        score += Decimal("5")
        reasons.append("return_5m_aligned")
    if (
        feature.relative_volume_15m is not None
        and feature.relative_volume_15m >= Decimal("1.00")
    ):
        score += Decimal("5")
        reasons.append("relative_volume_support")
    if feature.book_imbalance is not None:
        book_supports = (
            direction is Direction.LONG and feature.book_imbalance >= Decimal("0.10")
        ) or (
            direction is Direction.SHORT and feature.book_imbalance <= Decimal("-0.10")
        )
        if book_supports:
            score += Decimal("5")
            reasons.append("book_imbalance_support")

    score = min(score, MAX_SCORE)
    candles = closed_candles(context, "15m")
    if len(candles) < 4:
        return _no_trade(
            context,
            score=score,
            reasons=(*reasons, "insufficient_15m_candles"),
        )

    invalidation = swing_invalidation(context, direction)
    if invalidation is None:
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
        strategy="trend",
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
