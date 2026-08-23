from __future__ import annotations

from dataclasses import dataclass

from cocomelon.domain.strategy import StrategyContext, StrategyDecision, StrategySignal
from cocomelon.strategies.breakout import evaluate_breakout
from cocomelon.strategies.decision import combine_signals
from cocomelon.strategies.funding_oi import evaluate_funding_oi
from cocomelon.strategies.mean_reversion import evaluate_mean_reversion
from cocomelon.strategies.order_flow import evaluate_order_flow
from cocomelon.strategies.trend import evaluate_trend


@dataclass(frozen=True, slots=True)
class StrategyEvaluation:
    signals: tuple[StrategySignal, ...]
    decision: StrategyDecision


def evaluate_strategies(context: StrategyContext) -> StrategyEvaluation:
    generated = (
        evaluate_trend(context),
        evaluate_breakout(context),
        evaluate_mean_reversion(context),
        evaluate_funding_oi(context),
        evaluate_order_flow(context),
    )
    signals = tuple(sorted(generated, key=lambda signal: signal.strategy))
    decision = combine_signals(context, signals)
    return StrategyEvaluation(signals=signals, decision=decision)
