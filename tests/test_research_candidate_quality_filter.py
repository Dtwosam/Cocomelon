from __future__ import annotations

from decimal import Decimal

import pytest

from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction, StrategyDecision
from cocomelon.research.candidate_strategy import apply_short_trend_quality_filter


def _decision(
    *,
    direction: Direction = Direction.SHORT,
    score: str = "76.5",
    lead_strategy: str | None = "trend",
) -> StrategyDecision:
    return StrategyDecision(
        market=MarketId(dex="", coin="ETH"),
        direction=direction,
        score=Decimal(score),
        timestamp_ms=1_000,
        feature_snapshot_id="feature-1",
        lead_strategy=lead_strategy,
        invalidation_price=None if direction is Direction.NO_TRADE else Decimal("101"),
        signal_ids=("signal-1", "signal-2"),
        reason_codes=("decision_threshold_met",),
    )


@pytest.mark.parametrize("score", ["72", "76.5", "81"])
def test_short_trend_quality_filter_keeps_precommitted_band(score: str) -> None:
    decision = _decision(score=score)

    assert apply_short_trend_quality_filter(decision) == decision


@pytest.mark.parametrize(
    ("decision", "reason"),
    [
        (_decision(direction=Direction.LONG), "research_quality_long_veto"),
        (_decision(lead_strategy="breakout"), "research_quality_nontrend_veto"),
        (_decision(score="71.999"), "research_quality_score_veto"),
        (_decision(score="81.001"), "research_quality_score_veto"),
    ],
)
def test_short_trend_quality_filter_converts_outside_setups_to_no_trade(
    decision: StrategyDecision,
    reason: str,
) -> None:
    filtered = apply_short_trend_quality_filter(decision)

    assert filtered.direction is Direction.NO_TRADE
    assert filtered.score == decision.score
    assert filtered.timestamp_ms == decision.timestamp_ms
    assert filtered.feature_snapshot_id == decision.feature_snapshot_id
    assert filtered.signal_ids == decision.signal_ids
    assert filtered.lead_strategy is None
    assert filtered.invalidation_price is None
    assert filtered.reason_codes == decision.reason_codes + (reason,)


def test_short_trend_quality_filter_preserves_existing_no_trade() -> None:
    decision = _decision(
        direction=Direction.NO_TRADE,
        score="65",
        lead_strategy=None,
    )

    assert apply_short_trend_quality_filter(decision) == decision
