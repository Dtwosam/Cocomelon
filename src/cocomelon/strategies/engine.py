from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from cocomelon.domain.strategy import (
    Direction,
    StrategyContext,
    StrategyDecision,
    StrategySignal,
)
from cocomelon.strategies.breakout import evaluate_breakout
from cocomelon.strategies.decision import combine_signals
from cocomelon.strategies.funding_oi import evaluate_funding_oi
from cocomelon.strategies.mean_reversion import evaluate_mean_reversion
from cocomelon.strategies.order_flow import evaluate_order_flow
from cocomelon.strategies.trend import evaluate_trend


ENTRY_QUALITY_MIN_SCORE = Decimal("75")
ENTRY_QUALITY_MAX_SCORE = Decimal("80")


@dataclass(frozen=True, slots=True)
class StrategyEvaluation:
    signals: tuple[StrategySignal, ...]
    decision: StrategyDecision


def _apply_entry_quality_challenger(decision: StrategyDecision) -> StrategyDecision:
    if decision.direction is Direction.NO_TRADE:
        return decision
    if (
        decision.lead_strategy == "trend"
        and decision.direction is Direction.SHORT
        and ENTRY_QUALITY_MIN_SCORE <= decision.score <= ENTRY_QUALITY_MAX_SCORE
    ):
        return decision
    return StrategyDecision(
        market=decision.market,
        direction=Direction.NO_TRADE,
        score=decision.score,
        timestamp_ms=decision.timestamp_ms,
        feature_snapshot_id=decision.feature_snapshot_id,
        lead_strategy=None,
        invalidation_price=None,
        signal_ids=decision.signal_ids,
        reason_codes=("entry_quality_challenger_filter",),
    )


def evaluate_strategies(context: StrategyContext) -> StrategyEvaluation:
    generated = (
        evaluate_trend(context),
        evaluate_breakout(context),
        evaluate_mean_reversion(context),
        evaluate_funding_oi(context),
        evaluate_order_flow(context),
    )
    signals = tuple(sorted(generated, key=lambda signal: signal.strategy))
    decision = _apply_entry_quality_challenger(combine_signals(context, signals))
    return StrategyEvaluation(signals=signals, decision=decision)
