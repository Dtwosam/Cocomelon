from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from cocomelon.domain.features import TrendRegime, VolatilityRegime
from cocomelon.domain.strategy import (
    Direction,
    StrategyContext,
    StrategyDecision,
    StrategyRole,
    StrategySignal,
)
from cocomelon.strategies.candles import reference_price

ZERO = Decimal("0")
FIFTY = Decimal("50")
SIXTY = Decimal("60")
SIXTY_FIVE = Decimal("65")
HUNDRED = Decimal("100")
FIVE = Decimal("5")
TEN = Decimal("10")
FIFTEEN = Decimal("15")

_PRIMARY_STRATEGIES = ("breakout", "mean_reversion", "trend")
_CONTEXT_STRATEGIES = ("funding_oi", "order_flow")

_TREND_REGIME_WEIGHTS: dict[TrendRegime, dict[str, Decimal]] = {
    TrendRegime.UP: {
        "trend": Decimal("1.00"),
        "breakout": Decimal("0.90"),
        "mean_reversion": Decimal("0.35"),
    },
    TrendRegime.DOWN: {
        "trend": Decimal("1.00"),
        "breakout": Decimal("0.90"),
        "mean_reversion": Decimal("0.35"),
    },
    TrendRegime.MIXED: {
        "trend": Decimal("0.50"),
        "breakout": Decimal("0.80"),
        "mean_reversion": Decimal("1.00"),
    },
    TrendRegime.UNKNOWN: {
        "trend": Decimal("0.50"),
        "breakout": Decimal("0.60"),
        "mean_reversion": Decimal("0.50"),
    },
}

_VOLATILITY_WEIGHTS: dict[VolatilityRegime, dict[str, Decimal]] = {
    VolatilityRegime.HIGH: {
        "trend": Decimal("0.90"),
        "breakout": Decimal("1.00"),
        "mean_reversion": Decimal("0.25"),
    },
    VolatilityRegime.NORMAL: {
        "trend": Decimal("1.00"),
        "breakout": Decimal("1.00"),
        "mean_reversion": Decimal("1.00"),
    },
    VolatilityRegime.LOW: {
        "trend": Decimal("0.90"),
        "breakout": Decimal("0.75"),
        "mean_reversion": Decimal("1.00"),
    },
    VolatilityRegime.UNKNOWN: {
        "trend": Decimal("0.75"),
        "breakout": Decimal("0.75"),
        "mean_reversion": Decimal("0.75"),
    },
}


@dataclass(frozen=True, slots=True)
class _WeightedPrimary:
    signal: StrategySignal
    effective_score: Decimal


def _clamp(value: Decimal, lower: Decimal, upper: Decimal) -> Decimal:
    return max(lower, min(upper, value))


def _decision(
    context: StrategyContext,
    signals: tuple[StrategySignal, ...],
    *,
    direction: Direction,
    score: Decimal,
    reason: str,
    lead: StrategySignal | None = None,
) -> StrategyDecision:
    directional = direction is not Direction.NO_TRADE
    return StrategyDecision(
        market=context.feature_snapshot.market,
        direction=direction,
        score=_clamp(score, ZERO, HUNDRED),
        timestamp_ms=context.as_of_ms,
        feature_snapshot_id=context.feature_snapshot.snapshot_id,
        lead_strategy=lead.strategy if directional and lead is not None else None,
        invalidation_price=lead.invalidation_price if directional and lead is not None else None,
        signal_ids=tuple(sorted(signal.signal_id for signal in signals)),
        reason_codes=(reason,),
    )


def _validate_signals(context: StrategyContext, signals: tuple[StrategySignal, ...]) -> None:
    expected_market = context.feature_snapshot.market
    expected_feature = context.feature_snapshot.snapshot_id
    seen_roles: set[tuple[StrategyRole, str]] = set()

    for signal in signals:
        if signal.market != expected_market:
            raise ValueError("signal market must match strategy context market")
        if signal.feature_snapshot_id != expected_feature:
            raise ValueError("signal feature snapshot must match strategy context feature snapshot")
        if signal.timestamp_ms > context.as_of_ms:
            raise ValueError("signal timestamp cannot be after strategy context as_of_ms")
        if signal.role is StrategyRole.PRIMARY:
            if signal.strategy not in _PRIMARY_STRATEGIES:
                raise ValueError("unsupported primary strategy")
        elif signal.strategy not in _CONTEXT_STRATEGIES:
            raise ValueError("unsupported context strategy")

        identity = (signal.role, signal.strategy)
        if identity in seen_roles:
            raise ValueError("duplicate strategy role signal")
        seen_roles.add(identity)


def _effective_primary(context: StrategyContext, signal: StrategySignal) -> Decimal:
    trend_weights = _TREND_REGIME_WEIGHTS[context.feature_snapshot.trend_regime]
    volatility_weights = _VOLATILITY_WEIGHTS[context.feature_snapshot.volatility_regime]
    return signal.score * trend_weights[signal.strategy] * volatility_weights[signal.strategy]


def _context_strength(signal: StrategySignal) -> Decimal:
    if signal.score <= FIFTY:
        return ZERO
    return min(TEN, (signal.score - FIFTY) / FIVE)


def _invalidation_is_valid(context: StrategyContext, lead: StrategySignal) -> bool:
    reference = reference_price(context)
    invalidation = lead.invalidation_price
    if reference is None or invalidation is None:
        return False
    if lead.direction is Direction.LONG:
        return invalidation < reference
    if lead.direction is Direction.SHORT:
        return invalidation > reference
    return False


def combine_signals(
    context: StrategyContext,
    signals: list[StrategySignal] | tuple[StrategySignal, ...],
) -> StrategyDecision:
    ordered = tuple(
        sorted(
            signals,
            key=lambda signal: (
                signal.role.value,
                signal.strategy,
                signal.direction.value,
                signal.signal_id,
            ),
        )
    )
    _validate_signals(context, ordered)

    if not context.eligibility.rankable:
        return _decision(
            context,
            ordered,
            direction=Direction.NO_TRADE,
            score=ZERO,
            reason="not_rankable",
        )
    if not context.eligibility.deep_ready:
        return _decision(
            context,
            ordered,
            direction=Direction.NO_TRADE,
            score=ZERO,
            reason="not_deep_ready",
        )

    qualifying = tuple(
        _WeightedPrimary(signal, _effective_primary(context, signal))
        for signal in ordered
        if signal.role is StrategyRole.PRIMARY
        and signal.direction is not Direction.NO_TRADE
        and signal.score >= SIXTY
    )
    if not qualifying:
        return _decision(
            context,
            ordered,
            direction=Direction.NO_TRADE,
            score=ZERO,
            reason="no_primary_thesis",
        )

    ranked = tuple(
        sorted(
            qualifying,
            key=lambda item: (-item.effective_score, item.signal.strategy),
        )
    )
    lead_item = ranked[0]
    lead = lead_item.signal

    opposing = tuple(
        item for item in ranked if item.signal.direction is not lead.direction
    )
    if opposing and lead_item.effective_score - opposing[0].effective_score < FIFTEEN:
        return _decision(
            context,
            ordered,
            direction=Direction.NO_TRADE,
            score=lead_item.effective_score,
            reason="primary_conflict",
        )

    same_direction_qualifiers = sum(
        1
        for item in ranked[1:]
        if item.signal.direction is lead.direction and item.signal.score >= SIXTY
    )
    agreement_bonus = min(TEN, FIVE * Decimal(same_direction_qualifiers))
    candidate_score = lead_item.effective_score + agreement_bonus

    context_signals = tuple(
        signal for signal in ordered if signal.role is StrategyRole.CONTEXT
    )
    if any(lead.direction in signal.veto_directions for signal in context_signals):
        return _decision(
            context,
            ordered,
            direction=Direction.NO_TRADE,
            score=candidate_score,
            reason="context_veto",
        )

    adjustment = ZERO
    for signal in context_signals:
        strength = _context_strength(signal)
        if strength == ZERO or signal.direction is Direction.NO_TRADE:
            continue
        if signal.direction is lead.direction:
            adjustment += strength
        else:
            adjustment -= strength
    adjustment = _clamp(adjustment, -TEN, TEN)
    final_score = _clamp(candidate_score + adjustment, ZERO, HUNDRED)

    if final_score < SIXTY_FIVE:
        return _decision(
            context,
            ordered,
            direction=Direction.NO_TRADE,
            score=final_score,
            reason="below_decision_threshold",
        )

    if not _invalidation_is_valid(context, lead):
        return _decision(
            context,
            ordered,
            direction=Direction.NO_TRADE,
            score=final_score,
            reason="invalid_invalidation",
        )

    return _decision(
        context,
        ordered,
        direction=lead.direction,
        score=final_score,
        reason="decision_threshold_met",
        lead=lead,
    )
