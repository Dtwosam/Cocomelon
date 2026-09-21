from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from cocomelon.domain.features import TrendRegime
from cocomelon.domain.market import MarketId
from cocomelon.research.historical_baselines import (
    DecisionPolicy,
    ExecutionCostAssumptions,
    PredictedTrainingRow,
)
from cocomelon.research.historical_features import HistoricalFeatureRow, HistoricalTrainingRow
from cocomelon.research.historical_learning import DirectionalOutcome
from cocomelon.research.historical_portfolio_capacity import (
    HistoricalPortfolioCapacityError,
    evaluate_predicted_portfolio_capacity_policy,
    portfolio_capacity_trade_breakdowns,
)
from cocomelon.research.historical_ridge import RidgeDirectionalEstimate

BTC = MarketId(dex="", coin="BTC")
ETH = MarketId(dex="", coin="ETH")
SOL = MarketId(dex="", coin="SOL")
HYPE = MarketId(dex="", coin="HYPE")
FIFTEEN = 900_000
HOUR = 3_600_000


def _feature(*, market: MarketId, anchor_end_ms: int) -> HistoricalFeatureRow:
    return HistoricalFeatureRow(
        market=market,
        anchor_end_ms=anchor_end_ms,
        anchor_close_px=Decimal("100"),
        return_5m=None,
        return_15m=Decimal("0.01"),
        return_1h=Decimal("0.02"),
        return_4h=Decimal("0.03"),
        realized_vol_15m=Decimal("0.005"),
        range_expansion_15m=Decimal("1.1"),
        relative_volume_15m=Decimal("1.2"),
        funding_rate=Decimal("0.0001"),
        funding_change=Decimal("0.00001"),
        funding_premium=Decimal("0.0002"),
        funding_premium_change=Decimal("0.00001"),
        funding_age_ms=0,
        candle_15m_age_ms=0,
        trend_regime=TrendRegime.UP,
        availability_basis="exchange_timestamp",
        source_retrieved_at_ms=99_000_000,
        retrieved_after_anchor=True,
        available_features=(),
        unavailable_features=(),
        provenance=("hyperliquid-mainnet-info",),
        source_manifest_ids=("source-a",),
    )


def _predicted(
    *,
    market: MarketId,
    anchor_end_ms: int,
    horizon_ms: int,
    expected_long: str,
    long_return: str,
) -> PredictedTrainingRow:
    feature = _feature(market=market, anchor_end_ms=anchor_end_ms)
    realized = Decimal(long_return)
    row = HistoricalTrainingRow(
        feature=feature,
        outcome=DirectionalOutcome(
            market=market,
            interval="15m",
            anchor_end_ms=anchor_end_ms,
            target_end_ms=anchor_end_ms + horizon_ms,
            horizon_ms=horizon_ms,
            entry_px=Decimal("100"),
            exit_px=Decimal("100") * (Decimal("1") + realized),
            long_gross_return=realized,
            short_gross_return=-realized,
            provenance=("hyperliquid-mainnet-info",),
        ),
    )
    expected = Decimal(expected_long)
    return PredictedTrainingRow(
        row=row,
        estimate=RidgeDirectionalEstimate(
            sample_count=100,
            expected_long_return=expected,
            expected_short_return=-expected,
            horizon_ms=horizon_ms,
            estimate_source="shared_ridge",
        ),
    )


def _costs() -> ExecutionCostAssumptions:
    return ExecutionCostAssumptions(
        round_trip_fee_fraction=Decimal("0.001"),
        round_trip_slippage_fraction=Decimal("0"),
        funding_reserve_fraction_per_hour=Decimal("0"),
    )


def _policy() -> DecisionPolicy:
    return DecisionPolicy(
        min_expected_net_edge=Decimal("0"),
        min_sample_count=1,
    )


def test_portfolio_capacity_keeps_only_strongest_two_simultaneous_markets() -> None:
    rows = (
        _predicted(
            market=BTC,
            anchor_end_ms=0,
            horizon_ms=HOUR,
            expected_long="0.04",
            long_return="0.02",
        ),
        _predicted(
            market=ETH,
            anchor_end_ms=0,
            horizon_ms=HOUR,
            expected_long="0.03",
            long_return="0.015",
        ),
        _predicted(
            market=SOL,
            anchor_end_ms=0,
            horizon_ms=HOUR,
            expected_long="0.02",
            long_return="0.01",
        ),
    )

    result = evaluate_predicted_portfolio_capacity_policy(
        rows,
        policy=_policy(),
        costs=_costs(),
        max_concurrent_positions=2,
    )

    assert result.opportunity_count == 3
    assert result.trade_count == 2
    assert result.capacity_skip_count == 1
    assert result.occupied_skip_count == 0
    assert {trade.market for trade in result.trades} == {"BTC", "ETH"}


def test_portfolio_capacity_persists_across_anchors_until_positions_exit() -> None:
    rows = (
        _predicted(
            market=BTC,
            anchor_end_ms=0,
            horizon_ms=HOUR,
            expected_long="0.04",
            long_return="0.02",
        ),
        _predicted(
            market=ETH,
            anchor_end_ms=0,
            horizon_ms=HOUR,
            expected_long="0.03",
            long_return="0.015",
        ),
        _predicted(
            market=SOL,
            anchor_end_ms=FIFTEEN,
            horizon_ms=FIFTEEN,
            expected_long="0.05",
            long_return="0.02",
        ),
        _predicted(
            market=BTC,
            anchor_end_ms=FIFTEEN,
            horizon_ms=FIFTEEN,
            expected_long="0.06",
            long_return="0.02",
        ),
    )

    result = evaluate_predicted_portfolio_capacity_policy(
        rows,
        policy=_policy(),
        costs=_costs(),
        max_concurrent_positions=2,
    )

    assert result.trade_count == 2
    assert result.occupied_skip_count == 1
    assert result.capacity_skip_count == 1


def test_portfolio_capacity_releases_slots_exactly_at_target_exit() -> None:
    rows = (
        _predicted(
            market=BTC,
            anchor_end_ms=0,
            horizon_ms=HOUR,
            expected_long="0.04",
            long_return="0.02",
        ),
        _predicted(
            market=ETH,
            anchor_end_ms=0,
            horizon_ms=HOUR,
            expected_long="0.03",
            long_return="0.015",
        ),
        _predicted(
            market=SOL,
            anchor_end_ms=HOUR,
            horizon_ms=FIFTEEN,
            expected_long="0.05",
            long_return="0.02",
        ),
    )

    result = evaluate_predicted_portfolio_capacity_policy(
        rows,
        policy=_policy(),
        costs=_costs(),
        max_concurrent_positions=2,
    )

    assert result.trade_count == 3
    assert result.capacity_skip_count == 0
    assert [trade.anchor_end_ms for trade in result.trades] == [0, 0, HOUR]


def test_portfolio_capacity_breaks_equal_cross_market_edge_by_market_name() -> None:
    rows = (
        _predicted(
            market=SOL,
            anchor_end_ms=0,
            horizon_ms=FIFTEEN,
            expected_long="0.03",
            long_return="0.01",
        ),
        _predicted(
            market=BTC,
            anchor_end_ms=0,
            horizon_ms=FIFTEEN,
            expected_long="0.03",
            long_return="0.01",
        ),
    )

    result = evaluate_predicted_portfolio_capacity_policy(
        rows,
        policy=_policy(),
        costs=_costs(),
        max_concurrent_positions=1,
    )

    assert result.trade_count == 1
    assert result.capacity_skip_count == 1
    assert result.trades[0].market == "BTC"


def test_portfolio_capacity_rejects_duplicate_market_anchor_horizon() -> None:
    duplicate = _predicted(
        market=BTC,
        anchor_end_ms=0,
        horizon_ms=FIFTEEN,
        expected_long="0.02",
        long_return="0.01",
    )

    with pytest.raises(
        HistoricalPortfolioCapacityError,
        match="DUPLICATE_MARKET_ANCHOR_HORIZON",
    ):
        evaluate_predicted_portfolio_capacity_policy(
            (duplicate, duplicate),
            policy=_policy(),
            costs=_costs(),
            max_concurrent_positions=2,
        )


def test_default_crypto_risk_limits_imply_two_full_risk_slots() -> None:
    from cocomelon.config import Settings

    settings = Settings()
    assert settings.correlation_bucket_risk_limit == Decimal("0.005")
    assert settings.risk_per_trade == Decimal("0.0025")
    assert (
        settings.correlation_bucket_risk_limit / settings.risk_per_trade
        == Decimal("2")
    )



def test_portfolio_capacity_breakdowns_include_fixed_1h_market_context() -> None:
    predicted = _predicted(
        market=BTC,
        anchor_end_ms=0,
        horizon_ms=FIFTEEN,
        expected_long="0.02",
        long_return="0.01",
    )
    feature = replace(
        predicted.row.feature,
        basket_median_return_1h=Decimal("-0.01"),
        basket_breadth_positive_1h=Decimal("0.25"),
        relative_return_zscore_1h_vs_basket=Decimal("-1.2"),
        schema_version=3,
    )
    contextual = replace(
        predicted,
        row=replace(predicted.row, feature=feature),
    )
    result = evaluate_predicted_portfolio_capacity_policy(
        (contextual,),
        policy=_policy(),
        costs=_costs(),
        max_concurrent_positions=2,
    )

    breakdowns = {
        (item.dimension, item.value): item.summary
        for item in portfolio_capacity_trade_breakdowns(result)
    }
    for key in (
        ("basket_direction_1h", "down"),
        ("basket_breadth_1h", "bearish"),
        ("relative_strength_1h", "lagging_1sd"),
    ):
        assert breakdowns[key].trade_count == 1
