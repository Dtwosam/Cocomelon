from decimal import Decimal

import pytest
from cocomelon.evaluation.facts import account_equity_fact, decision_evaluation_fact

from cocomelon.domain.evaluation import EquityFactKind
from cocomelon.domain.features import FeatureSnapshot, TrendRegime, VolatilityRegime
from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction, StrategyDecision
from cocomelon.execution.accounting import empty_account

MARKET = MarketId("", "SOL")


def feature_snapshot(
    *,
    market: MarketId = MARKET,
    as_of_ms: int = 1_000,
) -> FeatureSnapshot:
    return FeatureSnapshot(
        market=market,
        as_of_ms=as_of_ms,
        source_received_at_ms=as_of_ms,
        schema_version=1,
        day_return=Decimal("0.01"),
        funding=Decimal("0.0001"),
        open_interest=Decimal("100"),
        day_notional_volume=Decimal("1000000"),
        oi_change_fraction=None,
        funding_change=None,
        mark_oracle_dislocation_bps=Decimal("2"),
        return_5m=Decimal("0.002"),
        return_15m=Decimal("0.004"),
        return_1h=Decimal("0.01"),
        return_4h=Decimal("0.03"),
        realized_vol_15m=Decimal("0.02"),
        range_expansion_15m=Decimal("1.2"),
        relative_volume_15m=Decimal("1.5"),
        spread_bps=Decimal("3"),
        bid_depth_25bps=Decimal("10000"),
        ask_depth_25bps=Decimal("9000"),
        book_imbalance=Decimal("0.05"),
        book_age_ms=25,
        trend_regime=TrendRegime.UP,
        volatility_regime=VolatilityRegime.NORMAL,
        provenance=("hyperliquid-mainnet-info",),
    )


def strategy_decision(
    feature: FeatureSnapshot,
    *,
    timestamp_ms: int = 1_000,
    feature_snapshot_id: str | None = None,
) -> StrategyDecision:
    return StrategyDecision(
        market=feature.market,
        direction=Direction.LONG,
        score=Decimal("74"),
        timestamp_ms=timestamp_ms,
        feature_snapshot_id=feature_snapshot_id or feature.snapshot_id,
        lead_strategy="trend",
        invalidation_price=Decimal("95"),
        signal_ids=("signal-b", "signal-a"),
        reason_codes=("TREND_UP", "LIQUID"),
    )


def test_decision_evaluation_fact_preserves_strategy_and_regime_dimensions() -> None:
    feature = feature_snapshot()
    decision = strategy_decision(feature)

    fact = decision_evaluation_fact(decision, feature, replay_run_id="run-1")

    assert fact.strategy_decision_id == decision.decision_id
    assert fact.feature_snapshot_id == feature.snapshot_id
    assert fact.market == MARKET
    assert fact.direction is Direction.LONG
    assert fact.score == Decimal("74")
    assert fact.lead_strategy == "trend"
    assert fact.signal_ids == ("signal-a", "signal-b")
    assert fact.reason_codes == ("LIQUID", "TREND_UP")
    assert fact.trend_regime is TrendRegime.UP
    assert fact.volatility_regime is VolatilityRegime.NORMAL


def test_decision_evaluation_fact_rejects_feature_identity_mismatch() -> None:
    feature = feature_snapshot()
    decision = strategy_decision(feature, feature_snapshot_id="wrong-feature")

    with pytest.raises(ValueError, match="feature"):
        decision_evaluation_fact(decision, feature, replay_run_id="run-1")


def test_decision_evaluation_fact_rejects_market_mismatch() -> None:
    feature = feature_snapshot()
    decision = strategy_decision(feature)
    other = feature_snapshot(market=MarketId("", "ETH"))

    with pytest.raises(ValueError, match="market"):
        decision_evaluation_fact(decision, other, replay_run_id="run-1")


def test_decision_evaluation_fact_rejects_future_feature() -> None:
    feature = feature_snapshot(as_of_ms=2_000)
    decision = strategy_decision(feature, timestamp_ms=1_000)

    with pytest.raises(ValueError, match="timestamp"):
        decision_evaluation_fact(decision, feature, replay_run_id="run-1")


def test_account_equity_fact_preserves_phase7_account_values() -> None:
    account = empty_account(Decimal("10000"), 1_000)

    fact = account_equity_fact(account, replay_run_id="run-1", kind=EquityFactKind.MARK)

    assert fact.replay_run_id == "run-1"
    assert fact.account_state_id == account.state_id
    assert fact.timestamp_ms == 1_000
    assert fact.kind is EquityFactKind.MARK
    assert fact.equity == Decimal("10000")
    assert fact.cash == Decimal("10000")
    assert fact.unrealized_pnl == Decimal("0")
    assert fact.realized_gross_pnl == Decimal("0")
    assert fact.cumulative_fees == Decimal("0")
    assert fact.cumulative_funding == Decimal("0")
    assert fact.gross_open_notional == Decimal("0")
    assert fact.open_position_count == 0
