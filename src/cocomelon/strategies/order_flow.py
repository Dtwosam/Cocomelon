from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class OrderFlowAssessment:
    direction: Direction
    score: Decimal
    reason_codes: tuple[str, ...]
    veto_directions: tuple[Direction, ...] = ()


def assess_order_flow(
    window: MicrostructureWindow | None,
) -> OrderFlowAssessment:
    if window is None:
        return OrderFlowAssessment(
            direction=Direction.NO_TRADE,
            score=ZERO,
            reason_codes=("missing_microstructure",),
        )
    if window.latest_event_age_ms is None or window.latest_event_age_ms > MAX_EVENT_AGE_MS:
        return OrderFlowAssessment(
            direction=Direction.NO_TRADE,
            score=ZERO,
            reason_codes=("stale_microstructure",),
        )
    if window.trade_count < MIN_TRADE_COUNT:
        return OrderFlowAssessment(
            direction=Direction.NO_TRADE,
            score=ZERO,
            reason_codes=("insufficient_trade_count",),
        )

    flow = window.trade_flow_imbalance
    book = window.latest_book_imbalance
    if flow is None or book is None:
        return OrderFlowAssessment(
            direction=Direction.NO_TRADE,
            score=ZERO,
            reason_codes=("missing_flow_or_book_imbalance",),
        )

    if flow >= VETO_FLOW and book >= VETO_BOOK:
        return OrderFlowAssessment(
            direction=Direction.LONG,
            score=Decimal("100"),
            reason_codes=("strong_buy_flow", "strong_bid_book"),
            veto_directions=(Direction.SHORT,),
        )
    if flow <= -VETO_FLOW and book <= -VETO_BOOK:
        return OrderFlowAssessment(
            direction=Direction.SHORT,
            score=Decimal("100"),
            reason_codes=("strong_sell_flow", "strong_ask_book"),
            veto_directions=(Direction.LONG,),
        )
    if flow >= SUPPORT_FLOW and book >= SUPPORT_BOOK:
        return OrderFlowAssessment(
            direction=Direction.LONG,
            score=Decimal("75"),
            reason_codes=("buy_flow_support", "bid_book_support"),
        )
    if flow <= -SUPPORT_FLOW and book <= -SUPPORT_BOOK:
        return OrderFlowAssessment(
            direction=Direction.SHORT,
            score=Decimal("75"),
            reason_codes=("sell_flow_support", "ask_book_support"),
        )

    return OrderFlowAssessment(
        direction=Direction.NO_TRADE,
        score=ZERO,
        reason_codes=("neutral_order_flow",),
    )


def evaluate_order_flow(context: StrategyContext) -> StrategySignal:
    assessment = assess_order_flow(context.microstructure)
    return _signal(
        context,
        direction=assessment.direction,
        score=assessment.score,
        reasons=assessment.reason_codes,
        veto_directions=assessment.veto_directions,
    )
