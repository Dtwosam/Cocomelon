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
from cocomelon.research.historical_ridge_stability import (
    run_walk_forward_stable_horizon_ridge,
)

MARKET = MarketId(dex="", coin="ETH")
FIVE = 300_000


def _row(anchor_index: int, long_return: str) -> HistoricalTrainingRow:
    anchor_end_ms = anchor_index * FIVE
    feature = HistoricalFeatureRow(
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
    value = Decimal(long_return)
    return HistoricalTrainingRow(
        feature=feature,
        outcome=DirectionalOutcome(
            market=MARKET,
            interval="5m",
            anchor_end_ms=anchor_end_ms,
            target_end_ms=anchor_end_ms + FIVE,
            horizon_ms=FIVE,
            entry_px=Decimal("100"),
            exit_px=Decimal("100") * (Decimal("1") + value),
            long_gross_return=value,
            short_gross_return=-value,
            provenance=("hyperliquid-mainnet-info",),
        ),
    )


def _costs() -> ExecutionCostAssumptions:
    return ExecutionCostAssumptions(
        round_trip_fee_fraction=Decimal("0"),
        round_trip_slippage_fraction=Decimal("0"),
        funding_reserve_fraction_per_hour=Decimal("0"),
    )


def _stable_kwargs() -> dict[str, object]:
    return {
        "costs": _costs(),
        "candidate_alphas": (Decimal("0.1"),),
        "candidate_thresholds": (Decimal("0"),),
        "min_train_anchors": 4,
        "validation_anchors": 4,
        "test_anchors": 2,
        "step_anchors": 2,
        "embargo_anchors": 0,
        "min_market_samples": 99,
        "min_sample_count": 1,
        "min_validation_trades": 4,
        "validation_segments": 2,
        "min_segment_validation_trades": 2,
    }


def test_stability_gate_rejects_positive_pooled_edge_with_negative_second_half() -> None:
    rows = tuple(
        _row(
            index,
            (
                "0.02"
                if index <= 4
                else "0.04"
                if index <= 6
                else "-0.01"
                if index <= 8
                else "-0.05"
            ),
        )
        for index in range(1, 11)
    )

    pooled = run_walk_forward_ridge(
        rows,
        costs=_costs(),
        candidate_alphas=(Decimal("0.1"),),
        candidate_thresholds=(Decimal("0"),),
        min_train_anchors=4,
        validation_anchors=4,
        test_anchors=2,
        step_anchors=2,
        embargo_anchors=0,
        min_market_samples=99,
        min_sample_count=1,
        min_validation_trades=4,
    )
    stable = run_walk_forward_stable_horizon_ridge(rows, **_stable_kwargs())

    assert pooled.folds[0].shared_threshold == Decimal("0")
    assert pooled.folds[0].shared_test.trade_count == 2
    assert pooled.folds[0].shared_test.total_realized_net_return == Decimal("-0.10")

    stable_fold = stable.folds[0]
    assert stable_fold.shared_alpha is None
    assert stable_fold.shared_test.trade_count == 0
    assert stable_fold.shared_test.total_realized_net_return == Decimal("0")


def test_stability_gate_accepts_edge_positive_in_both_validation_halves() -> None:
    rows = tuple(
        _row(
            index,
            "0.02" if index <= 4 else "0.03",
        )
        for index in range(1, 11)
    )

    report = run_walk_forward_stable_horizon_ridge(rows, **_stable_kwargs())
    fold = report.folds[0]

    assert fold.shared_alpha == Decimal("0.1")
    assert dict(fold.shared_horizon_thresholds)[FIVE] == Decimal("0")
    assert fold.shared_test.trade_count == 2
    assert fold.shared_test.total_realized_net_return == Decimal("0.06")

    selected = fold.shared_validation[0].horizons[0]
    candidate = selected.candidates[0]
    assert [item.trade_count for item in candidate.segments] == [2, 2]
    assert all(
        item.mean_realized_net_return == Decimal("0.03")
        for item in candidate.segments
    )


def test_stability_selection_is_independent_of_future_test_outcomes() -> None:
    prefix = tuple(
        _row(index, "0.02" if index <= 4 else "0.03")
        for index in range(1, 9)
    )
    positive = (*prefix, _row(9, "0.05"), _row(10, "0.05"))
    negative = (*prefix, _row(9, "-0.05"), _row(10, "-0.05"))

    first = run_walk_forward_stable_horizon_ridge(
        positive,
        **_stable_kwargs(),
    ).folds[0]
    second = run_walk_forward_stable_horizon_ridge(
        negative,
        **_stable_kwargs(),
    ).folds[0]

    assert first.shared_alpha == second.shared_alpha
    assert first.market_alpha == second.market_alpha
    assert first.shared_horizon_thresholds == second.shared_horizon_thresholds
    assert first.market_horizon_thresholds == second.market_horizon_thresholds
    assert first.shared_test.total_realized_net_return == Decimal("0.10")
    assert second.shared_test.total_realized_net_return == Decimal("-0.10")
