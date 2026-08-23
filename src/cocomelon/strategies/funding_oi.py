from __future__ import annotations

from decimal import Decimal

from cocomelon.domain.strategy import (
    Direction,
    StrategyContext,
    StrategyRole,
    StrategySignal,
)

ZERO = Decimal("0")
OI_SUPPORT_THRESHOLD = Decimal("0.01")
OI_EXTREME_THRESHOLD = Decimal("0.03")
FUNDING_CROWDED_THRESHOLD = Decimal("0.0001")
FUNDING_EXTREME_THRESHOLD = Decimal("0.0002")


def _signal(
    context: StrategyContext,
    *,
    direction: Direction,
    score: Decimal,
    reasons: tuple[str, ...],
    veto_directions: tuple[Direction, ...] = (),
) -> StrategySignal:
    return StrategySignal(
        strategy="funding_oi",
        role=StrategyRole.CONTEXT,
        market=context.feature_snapshot.market,
        direction=direction,
        score=score,
        timestamp_ms=context.as_of_ms,
        reason_codes=reasons,
        feature_snapshot_id=context.feature_snapshot.snapshot_id,
        invalidation_price=None,
        veto_directions=veto_directions,
    )


def evaluate_funding_oi(context: StrategyContext) -> StrategySignal:
    feature = context.feature_snapshot
    oi_change = feature.oi_change_fraction
    if oi_change is None or oi_change <= ZERO:
        return _signal(
            context,
            direction=Direction.NO_TRADE,
            score=ZERO,
            reasons=("missing_or_nonpositive_oi_change",),
        )

    funding = feature.funding
    if oi_change >= OI_EXTREME_THRESHOLD and funding >= FUNDING_EXTREME_THRESHOLD:
        return _signal(
            context,
            direction=Direction.NO_TRADE,
            score=Decimal("100"),
            reasons=("extreme_long_crowding",),
            veto_directions=(Direction.LONG,),
        )
    if oi_change >= OI_EXTREME_THRESHOLD and funding <= -FUNDING_EXTREME_THRESHOLD:
        return _signal(
            context,
            direction=Direction.NO_TRADE,
            score=Decimal("100"),
            reasons=("extreme_short_crowding",),
            veto_directions=(Direction.SHORT,),
        )

    returns = (feature.return_15m, feature.return_1h)
    uncrowded = abs(funding) < FUNDING_CROWDED_THRESHOLD
    if oi_change >= OI_SUPPORT_THRESHOLD and uncrowded and all(
        value is not None and value > ZERO for value in returns
    ):
        return _signal(
            context,
            direction=Direction.LONG,
            score=Decimal("70"),
            reasons=("oi_expansion_support_long", "funding_not_crowded"),
        )
    if oi_change >= OI_SUPPORT_THRESHOLD and uncrowded and all(
        value is not None and value < ZERO for value in returns
    ):
        return _signal(
            context,
            direction=Direction.SHORT,
            score=Decimal("70"),
            reasons=("oi_expansion_support_short", "funding_not_crowded"),
        )

    if abs(funding) >= FUNDING_CROWDED_THRESHOLD:
        return _signal(
            context,
            direction=Direction.NO_TRADE,
            score=Decimal("50"),
            reasons=("crowded_nonextreme_context",),
        )

    return _signal(
        context,
        direction=Direction.NO_TRADE,
        score=ZERO,
        reasons=("neutral_funding_oi",),
    )
