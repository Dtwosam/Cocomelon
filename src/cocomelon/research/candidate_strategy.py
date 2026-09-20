from __future__ import annotations

from decimal import Decimal

from cocomelon.domain.strategy import Direction, StrategyContext, StrategyDecision
from cocomelon.strategies.engine import evaluate_strategies

MIN_SHORT_TREND_SCORE = Decimal("72")
MAX_SHORT_TREND_SCORE = Decimal("81")


def _veto(decision: StrategyDecision, reason: str) -> StrategyDecision:
    return StrategyDecision(
        market=decision.market,
        direction=Direction.NO_TRADE,
        score=decision.score,
        timestamp_ms=decision.timestamp_ms,
        feature_snapshot_id=decision.feature_snapshot_id,
        lead_strategy=None,
        invalidation_price=None,
        signal_ids=decision.signal_ids,
        reason_codes=decision.reason_codes + (reason,),
    )


def apply_short_trend_quality_filter(decision: StrategyDecision) -> StrategyDecision:
    """Apply the precommitted touched-data entry-quality challenger filter."""
    if decision.direction is Direction.NO_TRADE:
        return decision
    if decision.direction is Direction.LONG:
        return _veto(decision, "research_quality_long_veto")
    if decision.lead_strategy != "trend":
        return _veto(decision, "research_quality_nontrend_veto")
    if decision.score < MIN_SHORT_TREND_SCORE or decision.score > MAX_SHORT_TREND_SCORE:
        return _veto(decision, "research_quality_score_veto")
    return decision


def evaluate_candidate_strategy(context: StrategyContext) -> StrategyDecision:
    baseline = evaluate_strategies(context).decision
    return apply_short_trend_quality_filter(baseline)
