from __future__ import annotations

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
from cocomelon.research.historical_occupancy import (
    HistoricalOccupancyError,
    evaluate_predicted_occupancy_policy,
)
from cocomelon.research.historical_ridge import RidgeDirectionalEstimate

BTC = MarketId(dex="", coin="BTC")
ETH = MarketId(dex="", coin="ETH")
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


def test_occupancy_selects_strongest_edge_and_skips_until_exit() -> None:
    rows = (
        _predicted(
            market=BTC,
            anchor_end_ms=0,
            horizon_ms=FIFTEEN,
            expected_long="0.02",
            long_return="0.01",
        ),
        _predicted(
            market=BTC,
            anchor_end_ms=0,
            horizon_ms=HOUR,
            expected_long="0.04",
            long_return="0.03",
        ),
        _predicted(
            market=BTC,
            anchor_end_ms=FIFTEEN,
            horizon_ms=FIFTEEN,
            expected_long="0.05",
            long_return="0.02",
        ),
        _predicted(
            market=BTC,
            anchor_end_ms=HOUR,
            horizon_ms=FIFTEEN,
            expected_long="0.03",
            long_return="0.02",
        ),
    )

    result = evaluate_predicted_occupancy_policy(
        rows,
        policy=_policy(),
        costs=_costs(),
    )

    assert result.opportunity_count == 3
    assert result.trade_count == 2
    assert result.occupied_skip_count == 1
    assert [trade.horizon_ms for trade in result.trades] == [HOUR, FIFTEEN]
    assert [trade.anchor_end_ms for trade in result.trades] == [0, HOUR]


def test_occupancy_allows_different_markets_to_trade_concurrently() -> None:
    rows = (
        _predicted(
            market=BTC,
            anchor_end_ms=0,
            horizon_ms=HOUR,
            expected_long="0.03",
            long_return="0.02",
        ),
        _predicted(
            market=ETH,
            anchor_end_ms=0,
            horizon_ms=HOUR,
            expected_long="0.025",
            long_return="0.015",
        ),
        _predicted(
            market=BTC,
            anchor_end_ms=FIFTEEN,
            horizon_ms=FIFTEEN,
            expected_long="0.04",
            long_return="0.02",
        ),
        _predicted(
            market=ETH,
            anchor_end_ms=FIFTEEN,
            horizon_ms=FIFTEEN,
            expected_long="0.04",
            long_return="0.02",
        ),
    )

    result = evaluate_predicted_occupancy_policy(
        rows,
        policy=_policy(),
        costs=_costs(),
    )

    assert result.trade_count == 2
    assert result.occupied_skip_count == 2
    assert {trade.market for trade in result.trades} == {"BTC", "ETH"}


def test_occupancy_breaks_equal_edge_ties_with_shorter_horizon() -> None:
    rows = (
        _predicted(
            market=BTC,
            anchor_end_ms=0,
            horizon_ms=HOUR,
            expected_long="0.03",
            long_return="0.02",
        ),
        _predicted(
            market=BTC,
            anchor_end_ms=0,
            horizon_ms=FIFTEEN,
            expected_long="0.03",
            long_return="0.01",
        ),
    )

    result = evaluate_predicted_occupancy_policy(
        rows,
        policy=_policy(),
        costs=_costs(),
    )

    assert result.trade_count == 1
    assert result.trades[0].horizon_ms == FIFTEEN


def test_occupancy_subtracts_costs_from_executed_trade_return() -> None:
    rows = (
        _predicted(
            market=BTC,
            anchor_end_ms=0,
            horizon_ms=FIFTEEN,
            expected_long="0.02",
            long_return="0.01",
        ),
    )

    result = evaluate_predicted_occupancy_policy(
        rows,
        policy=_policy(),
        costs=_costs(),
    )

    assert result.total_realized_net_return == Decimal("0.009")
    assert result.mean_realized_net_return == Decimal("0.009")


def test_occupancy_rejects_duplicate_market_anchor_horizon() -> None:
    duplicate = _predicted(
        market=BTC,
        anchor_end_ms=0,
        horizon_ms=FIFTEEN,
        expected_long="0.02",
        long_return="0.01",
    )

    with pytest.raises(
        HistoricalOccupancyError,
        match="DUPLICATE_MARKET_ANCHOR_HORIZON",
    ):
        evaluate_predicted_occupancy_policy(
            (duplicate, duplicate),
            policy=_policy(),
            costs=_costs(),
        )
