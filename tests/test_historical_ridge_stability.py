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
from cocomelon.research.historical_ridge_stability import (
    calibrate_stable_no_trade_threshold,
    run_walk_forward_stable_horizon_ridge,
)

MARKET = MarketId(dex="", coin="ETH")
FIVE = 300_000


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


def _feature(anchor_end_ms: int, momentum: str = "0.02") -> HistoricalFeatureRow:
    return HistoricalFeatureRow(
        market=MARKET,
        anchor_end_ms=anchor_end_ms,
        anchor_close_px=Decimal("100"),
        return_5m=Decimal(momentum),
        return_15m=Decimal(momentum),
        return_1h=Decimal(momentum),
        return_4h=Decimal(momentum),
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


def _row(
    *,
    anchor_index: int,
    long_return: str,
    momentum: str = "0.02",
) -> HistoricalTrainingRow:
    anchor_end_ms = anchor_index * FIVE
    feature = _feature(anchor_end_ms, momentum=momentum)
    long_value = Decimal(long_return)
    return HistoricalTrainingRow(
        feature=feature,
        outcome=DirectionalOutcome(
            market=MARKET,
            interval="5m",
            anchor_end_ms=anchor_end_ms,
            target_end_ms=anchor_end_ms + FIVE,
            horizon_ms=FIVE,
            entry_px=Decimal("100"),
            exit_px=Decimal("100") * (Decimal("1") + long_value),
            long_gross_return=long_value,
            short_gross_return=-long_value,
            provenance=("hyperliquid-mainnet-info",),
        ),
    )


def _costs() -> ExecutionCostAssumptions:
    return ExecutionCostAssumptions(
        round_trip_fee_fraction=Decimal("0"),
        round_trip_slippage_fraction=Decimal("0"),
        funding_reserve_fraction_per_hour=Decimal("0"),
    )


def test_stability_gate_rejects_positive_aggregate_with_one_losing_block() -> None:
    returns = ("0.03", "0.03", "0.03", "0.03", "-0.02", "-0.02", "0.03", "0.03")
    rows = tuple(
        _row(anchor_index=index, long_return=value)
        for index, value in enumerate(returns, start=1)
    )

    calibration = calibrate_stable_no_trade_threshold(
        FixedLongModel(),
        rows,
        costs=_costs(),
        candidate_thresholds=(Decimal("0"),),
        min_sample_count=1,
        min_validation_trades=4,
        stability_blocks=4,
        min_block_trades=2,
        allow_coin_calibration=False,
    )

    candidate = calibration.candidates[0]
    assert candidate.overall.mean_realized_net_return == Decimal("0.0175")
    assert candidate.blocks[2].mean_realized_net_return == Decimal("-0.02")
    assert candidate.qualifies is False
    assert calibration.selected_threshold is None


def test_stability_gate_selects_threshold_only_when_every_block_is_positive() -> None:
    rows = tuple(
        _row(anchor_index=index, long_return="0.02")
        for index in range(1, 9)
    )

    calibration = calibrate_stable_no_trade_threshold(
        FixedLongModel(),
        rows,
        costs=_costs(),
        candidate_thresholds=(Decimal("0"), Decimal("0.01")),
        min_sample_count=1,
        min_validation_trades=4,
        stability_blocks=4,
        min_block_trades=2,
        allow_coin_calibration=False,
    )

    assert calibration.selected_threshold == Decimal("0")
    selected = next(
        item
        for item in calibration.candidates
        if item.threshold == calibration.selected_threshold
    )
    assert selected.qualifies is True
    assert selected.worst_block_mean == Decimal("0.02")


def _walk_forward_rows(test_return: str) -> tuple[HistoricalTrainingRow, ...]:
    rows: list[HistoricalTrainingRow] = []
    for index in range(1, 13):
        if index <= 4:
            long_return = "0.02"
        elif index <= 8:
            long_return = "0.02"
        else:
            long_return = test_return
        rows.append(
            _row(
                anchor_index=index,
                long_return=long_return,
                momentum=str(Decimal(index) / Decimal("100")),
            )
        )
    return tuple(rows)


def _walk_forward_kwargs() -> dict[str, object]:
    return {
        "costs": _costs(),
        "candidate_alphas": (Decimal("0.01"), Decimal("0.1")),
        "candidate_thresholds": (Decimal("0"), Decimal("0.001")),
        "min_train_anchors": 4,
        "validation_anchors": 4,
        "test_anchors": 4,
        "step_anchors": 4,
        "embargo_anchors": 0,
        "min_market_samples": 99,
        "min_sample_count": 1,
        "min_validation_trades": 2,
        "stability_blocks": 2,
        "min_block_trades": 1,
    }


def test_stable_walk_forward_selection_ignores_future_test_outcomes() -> None:
    positive = run_walk_forward_stable_horizon_ridge(
        _walk_forward_rows("0.03"),
        **_walk_forward_kwargs(),
    ).folds[0]
    negative = run_walk_forward_stable_horizon_ridge(
        _walk_forward_rows("-0.03"),
        **_walk_forward_kwargs(),
    ).folds[0]

    assert positive.shared_alpha == negative.shared_alpha
    assert positive.market_alpha == negative.market_alpha
    assert positive.shared_horizon_thresholds == negative.shared_horizon_thresholds
    assert positive.market_horizon_thresholds == negative.market_horizon_thresholds
    assert positive.shared_test.mean_realized_net_return > 0
    assert negative.shared_test.mean_realized_net_return < 0
