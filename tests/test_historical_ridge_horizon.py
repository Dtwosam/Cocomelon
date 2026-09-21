from __future__ import annotations

from decimal import Decimal

import pytest

pytest.importorskip("numpy")

from cocomelon.domain.features import TrendRegime
from cocomelon.domain.market import MarketId
from cocomelon.research.historical_baselines import ExecutionCostAssumptions
from cocomelon.research.historical_features import HistoricalFeatureRow, HistoricalTrainingRow
from cocomelon.research.historical_learning import DirectionalOutcome
from cocomelon.research.historical_ridge import run_walk_forward_ridge
from cocomelon.research.historical_ridge_horizon import (
    run_walk_forward_horizon_calibrated_ridge,
)

MARKET = MarketId(dex="", coin="ETH")
FIVE = 300_000
HOUR = 3_600_000


def _feature(anchor_end_ms: int) -> HistoricalFeatureRow:
    return HistoricalFeatureRow(
        market=MARKET,
        anchor_end_ms=anchor_end_ms,
        anchor_close_px=Decimal("100"),
        return_5m=Decimal("0.02"),
        return_15m=Decimal("0.02"),
        return_1h=Decimal("0.02"),
        return_4h=Decimal("0.02"),
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
    horizon_ms: int,
    long_return: str,
) -> HistoricalTrainingRow:
    anchor_end_ms = anchor_index * FIVE
    feature = _feature(anchor_end_ms)
    long_value = Decimal(long_return)
    return HistoricalTrainingRow(
        feature=feature,
        outcome=DirectionalOutcome(
            market=MARKET,
            interval="5m",
            anchor_end_ms=anchor_end_ms,
            target_end_ms=anchor_end_ms + horizon_ms,
            horizon_ms=horizon_ms,
            entry_px=Decimal("100"),
            exit_px=Decimal("100") * (Decimal("1") + long_value),
            long_gross_return=long_value,
            short_gross_return=-long_value,
            provenance=("hyperliquid-mainnet-info",),
        ),
    )


def _two_horizon_rows() -> tuple[HistoricalTrainingRow, ...]:
    rows: list[HistoricalTrainingRow] = []
    for index in range(1, 9):
        if index <= 4:
            five_return = "0.02"
            hour_return = "0.02"
        elif index <= 6:
            five_return = "0.03"
            hour_return = "-0.01"
        else:
            five_return = "0.03"
            hour_return = "-0.10"
        rows.extend(
            (
                _row(anchor_index=index, horizon_ms=FIVE, long_return=five_return),
                _row(anchor_index=index, horizon_ms=HOUR, long_return=hour_return),
            )
        )
    return tuple(rows)


def _kwargs() -> dict[str, object]:
    return {
        "costs": ExecutionCostAssumptions(
            round_trip_fee_fraction=Decimal("0"),
            round_trip_slippage_fraction=Decimal("0"),
            funding_reserve_fraction_per_hour=Decimal("0"),
        ),
        "candidate_alphas": (Decimal("0.1"),),
        "candidate_thresholds": (Decimal("0"),),
        "min_train_anchors": 4,
        "validation_anchors": 2,
        "test_anchors": 2,
        "step_anchors": 2,
        "embargo_anchors": 0,
        "min_market_samples": 99,
        "min_sample_count": 1,
        "min_validation_trades": 1,
    }


def test_horizon_calibration_abstains_only_the_losing_validation_horizon() -> None:
    report = run_walk_forward_horizon_calibrated_ridge(
        _two_horizon_rows(),
        **_kwargs(),
    )

    fold = report.folds[0]
    thresholds = dict(fold.shared_horizon_thresholds)

    assert thresholds[FIVE] == Decimal("0")
    assert thresholds[HOUR] is None
    assert fold.shared_test.trade_count == 2
    assert fold.shared_test.long_count == 2
    assert fold.shared_test.total_realized_net_return == Decimal("0.06")
    horizon_breakdowns = {
        item.value: item.evaluation
        for item in fold.shared_test_breakdowns
        if item.dimension == "horizon_ms"
    }
    assert horizon_breakdowns[str(FIVE)].trade_count == 2
    assert horizon_breakdowns[str(HOUR)].trade_count == 0


def test_horizon_calibration_avoids_loss_that_pooled_validation_accepts() -> None:
    rows = _two_horizon_rows()

    pooled = run_walk_forward_ridge(rows, **_kwargs())
    horizon = run_walk_forward_horizon_calibrated_ridge(rows, **_kwargs())

    pooled_fold = pooled.folds[0]
    horizon_fold = horizon.folds[0]

    assert pooled_fold.shared_threshold == Decimal("0")
    assert pooled_fold.shared_test.trade_count == 4
    assert pooled_fold.shared_test.total_realized_net_return == Decimal("-0.14")

    assert horizon_fold.shared_test.trade_count == 2
    assert horizon_fold.shared_test.total_realized_net_return == Decimal("0.06")


def test_horizon_alpha_and_threshold_selection_ignore_future_test_outcomes() -> None:
    rows = list(_two_horizon_rows())
    changed: list[HistoricalTrainingRow] = []
    for row in rows:
        if row.anchor_end_ms <= 6 * FIVE:
            changed.append(row)
            continue
        changed.append(
            _row(
                anchor_index=row.anchor_end_ms // FIVE,
                horizon_ms=row.horizon_ms,
                long_return="0.50" if row.horizon_ms == HOUR else "-0.50",
            )
        )

    first = run_walk_forward_horizon_calibrated_ridge(rows, **_kwargs()).folds[0]
    second = run_walk_forward_horizon_calibrated_ridge(changed, **_kwargs()).folds[0]

    assert first.shared_alpha == second.shared_alpha
    assert first.market_alpha == second.market_alpha
    assert first.shared_horizon_thresholds == second.shared_horizon_thresholds
    assert first.market_horizon_thresholds == second.market_horizon_thresholds
