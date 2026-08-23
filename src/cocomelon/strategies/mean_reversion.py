from __future__ import annotations

from decimal import Decimal

from cocomelon.domain.features import TrendRegime, VolatilityRegime
from cocomelon.domain.strategy import (
    Direction,
    StrategyContext,
    StrategyRole,
    StrategySignal,
)
from cocomelon.strategies.candles import closed_candles, swing_invalidation

ZERO = Decimal("0")
THRESHOLD = Decimal("65")
STRETCH_TRIGGER = Decimal("1.75")
STRONG_STRETCH = Decimal("2.25")
RANGE_EXPANSION_THRESHOLD = Decimal("1.10")
MAX_SCORE = Decimal("100")


def _no_trade(
    context: StrategyContext,
    *,
    score: Decimal = ZERO,
    reasons: tuple[str, ...],
) -> StrategySignal:
    return StrategySignal(
        strategy="mean_reversion",
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


def evaluate_mean_reversion(context: StrategyContext) -> StrategySignal:
    feature = context.feature_snapshot
    if not context.eligibility.rankable:
        return _no_trade(context, reasons=("not_rankable",))
    if not context.eligibility.deep_ready:
        return _no_trade(context, reasons=("not_deep_ready",))
    if feature.trend_regime is not TrendRegime.MIXED:
        return _no_trade(context, reasons=("incompatible_trend_regime",))
    if feature.volatility_regime not in (VolatilityRegime.LOW, VolatilityRegime.NORMAL):
        return _no_trade(context, reasons=("incompatible_volatility_regime",))
    if (
        feature.return_15m is None
        or feature.return_15m == ZERO
        or feature.realized_vol_15m is None
        or not feature.realized_vol_15m.is_finite()
        or feature.realized_vol_15m <= ZERO
    ):
        return _no_trade(context, reasons=("missing_primary_data",))

    stretch = abs(feature.return_15m) / feature.realized_vol_15m
    if stretch < STRETCH_TRIGGER:
        return _no_trade(context, reasons=("stretch_below_threshold",))

    direction = Direction.SHORT if feature.return_15m > ZERO else Direction.LONG
    score = Decimal("45")
    reasons = ["stretched_move", "mixed_regime"]

    if stretch >= STRONG_STRETCH:
        score += Decimal("20")
        reasons.append("strong_stretch")
    if (
        feature.range_expansion_15m is not None
        and feature.range_expansion_15m >= RANGE_EXPANSION_THRESHOLD
    ):
        score += Decimal("15")
        reasons.append("range_expansion")
    if feature.return_5m is not None and _aligned(feature.return_5m, direction):
        score += Decimal("10")
        reasons.append("return_5m_reversion_support")
    if feature.return_1h is not None and _aligned(feature.return_1h, direction):
        score += Decimal("10")
        reasons.append("return_1h_reversion_support")
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
        strategy="mean_reversion",
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
