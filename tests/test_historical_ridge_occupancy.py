from __future__ import annotations

from decimal import Decimal

import pytest

pytest.importorskip("numpy")

from cocomelon.domain.features import TrendRegime
from cocomelon.domain.market import MarketId
from cocomelon.research.historical_baselines import ExecutionCostAssumptions
from cocomelon.research.historical_features import HistoricalFeatureRow, HistoricalTrainingRow
from cocomelon.research.historical_learning import DirectionalOutcome
from cocomelon.research.historical_ridge import RidgeDirectionalEstimate
from cocomelon.research.historical_ridge_occupancy import (
    calibrate_occupancy_stable_threshold,
)

BTC = MarketId(dex="", coin="BTC")
FIFTEEN = 900_000
FOUR_HOURS = 14_400_000


class FixedLongModel:
    def predict(
        self,
        feature: HistoricalFeatureRow,
        *,
        horizon_ms: int,
        allow_coin_calibration: bool = True,
    ) -> RidgeDirectionalEstimate:
        del feature, allow_coin_calibration
        return RidgeDirectionalEstimate(
            sample_count=100,
            expected_long_return=Decimal("0.02"),
            expected_short_return=Decimal("-0.02"),
            horizon_ms=horizon_ms,
            estimate_source="shared_ridge",
        )


def _row(anchor_index: int, *, long_return: str = "0.01") -> HistoricalTrainingRow:
    anchor_end_ms = anchor_index * FIFTEEN
    feature = HistoricalFeatureRow(
        market=BTC,
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
    realized = Decimal(long_return)
    return HistoricalTrainingRow(
        feature=feature,
        outcome=DirectionalOutcome(
            market=BTC,
            interval="15m",
            anchor_end_ms=anchor_end_ms,
            target_end_ms=anchor_end_ms + FOUR_HOURS,
            horizon_ms=FOUR_HOURS,
            entry_px=Decimal("100"),
            exit_px=Decimal("100") * (Decimal("1") + realized),
            long_gross_return=realized,
            short_gross_return=-realized,
            provenance=("hyperliquid-mainnet-info",),
        ),
    )


def _costs() -> ExecutionCostAssumptions:
    return ExecutionCostAssumptions(
        round_trip_fee_fraction=Decimal("0"),
        round_trip_slippage_fraction=Decimal("0"),
        funding_reserve_fraction_per_hour=Decimal("0"),
    )


def test_occupancy_stability_carries_position_across_validation_blocks() -> None:
    rows = tuple(_row(index) for index in range(8))

    calibration = calibrate_occupancy_stable_threshold(
        FixedLongModel(),
        rows,
        costs=_costs(),
        candidate_thresholds=(Decimal("0"),),
        min_sample_count=1,
        min_validation_trades=1,
        stability_blocks=2,
        min_block_trades=1,
        allow_coin_calibration=False,
    )

    candidate = calibration.candidates[0]
    assert candidate.overall.trade_count == 1
    assert candidate.overall.occupied_skip_count == 7
    assert [block.trade_count for block in candidate.blocks] == [1, 0]
    assert candidate.qualifies is False
    assert calibration.selected_threshold is None


def test_occupancy_stability_can_qualify_non_overlapping_repeated_trades() -> None:
    rows = tuple(_row(index * 16) for index in range(4))

    calibration = calibrate_occupancy_stable_threshold(
        FixedLongModel(),
        rows,
        costs=_costs(),
        candidate_thresholds=(Decimal("0"),),
        min_sample_count=1,
        min_validation_trades=4,
        stability_blocks=2,
        min_block_trades=2,
        allow_coin_calibration=False,
    )

    candidate = calibration.candidates[0]
    assert candidate.overall.trade_count == 4
    assert candidate.overall.occupied_skip_count == 0
    assert [block.trade_count for block in candidate.blocks] == [2, 2]
    assert candidate.qualifies is True
    assert calibration.selected_threshold == Decimal("0")
