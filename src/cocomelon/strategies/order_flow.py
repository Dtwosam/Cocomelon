from __future__ import annotations

from decimal import Decimal

from cocomelon.domain.strategy import (
    Direction,
    StrategyContext,
    StrategyRole,
    StrategySignal,
)

MAX_EVENT_AGE_MS = 2_000
MIN_TRADE_COUNT = 5
SUPPORT_FLOW = Decimal("0.35")
SUPPORT_BOOK = Decimal("0.15")
VETO_FLOW = Decimal("0.60")
VETO_BOOK = Decimal("0.30")
ZERO = Decimal("0")


def _signal(
    context: StrategyContext,
    *,
    direction: Direction,
    score: Decimal,
    reasons: tuple[str, ...],
    veto_directions: tuple[Direction, ...] = (),
) -> StrategySignal:
    return StrategySignal(
        strategy="order_flow",
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


def evaluate_order_flow(context: StrategyContext) -> StrategySignal:
    window = context.microstructure
    if window is None:
        return _signal(
            context,
            direction=Direction.NO_TRADE,
            score=ZERO,
            reasons=("missing_microstructure",),
        )
    if window.latest_event_age_ms is None or window.latest_event_age_ms > MAX_EVENT_AGE_MS:
        return _signal(
            context,
            direction=Direction.NO_TRADE,
            score=ZERO,
            reasons=("stale_microstructure",),
        )
    if window.trade_count < MIN_TRADE_COUNT:
        return _signal(
            context,
            direction=Direction.NO_TRADE,
            score=ZERO,
            reasons=("insufficient_trade_count",),
        )

    flow = window.trade_flow_imbalance
    book = window.latest_book_imbalance
    if flow is None or book is None:
        return _signal(
            context,
            direction=Direction.NO_TRADE,
            score=ZERO,
            reasons=("missing_flow_or_book_imbalance",),
        )

    if flow >= VETO_FLOW and book >= VETO_BOOK:
        return _signal(
            context,
            direction=Direction.LONG,
            score=Decimal("100"),
            reasons=("strong_buy_flow", "strong_bid_book"),
            veto_directions=(Direction.SHORT,),
        )
    if flow <= -VETO_FLOW and book <= -VETO_BOOK:
        return _signal(
            context,
            direction=Direction.SHORT,
            score=Decimal("100"),
            reasons=("strong_sell_flow", "strong_ask_book"),
            veto_directions=(Direction.LONG,),
        )
    if flow >= SUPPORT_FLOW and book >= SUPPORT_BOOK:
        return _signal(
            context,
            direction=Direction.LONG,
            score=Decimal("75"),
            reasons=("buy_flow_support", "bid_book_support"),
        )
    if flow <= -SUPPORT_FLOW and book <= -SUPPORT_BOOK:
        return _signal(
            context,
            direction=Direction.SHORT,
            score=Decimal("75"),
            reasons=("sell_flow_support", "ask_book_support"),
        )

    return _signal(
        context,
        direction=Direction.NO_TRADE,
        score=ZERO,
        reasons=("neutral_order_flow",),
    )
