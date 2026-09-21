from __future__ import annotations

from decimal import Decimal

import pytest

pytest.importorskip("numpy")

from cocomelon.domain.features import TrendRegime
from cocomelon.domain.market import MarketId
from cocomelon.research.historical_baselines import ExecutionCostAssumptions
from cocomelon.research.historical_dataset import HistoricalDatasetManifest
from cocomelon.research.historical_features import HistoricalFeatureRow, HistoricalTrainingRow
from cocomelon.research.historical_learning import DirectionalOutcome
from cocomelon.research.historical_model_comparison import (
    HistoricalModelComparisonConfig,
    build_historical_model_comparison_report,
)

MARKET = MarketId(dex="", coin="ETH")
FIVE = 300_000


def _row(index: int) -> HistoricalTrainingRow:
    momentum = Decimal(index - 7) / Decimal("100")
    feature = HistoricalFeatureRow(
        market=MARKET,
        anchor_end_ms=index * FIVE,
        anchor_close_px=Decimal("100"),
        return_5m=momentum,
        return_15m=momentum / Decimal("2"),
        return_1h=momentum,
        return_4h=momentum * Decimal("2"),
        realized_vol_15m=Decimal("0.005"),
        range_expansion_15m=Decimal("1.1"),
        relative_volume_15m=Decimal("1.2"),
        funding_rate=Decimal("0.0001"),
        funding_change=Decimal("0.00001"),
        funding_premium=Decimal("0.0002"),
        funding_premium_change=Decimal("0.00001"),
        funding_age_ms=0,
        candle_15m_age_ms=0,
        trend_regime=TrendRegime.UP if momentum >= 0 else TrendRegime.DOWN,
        availability_basis="exchange_timestamp",
        source_retrieved_at_ms=99_000_000,
        retrieved_after_anchor=True,
        available_features=(),
        unavailable_features=(),
        provenance=("hyperliquid-mainnet-info",),
        source_manifest_ids=("source-a",),
    )
    long_return = momentum / Decimal("2")
    outcome = DirectionalOutcome(
        market=MARKET,
        interval="5m",
        anchor_end_ms=index * FIVE,
        target_end_ms=(index + 1) * FIVE,
        horizon_ms=FIVE,
        entry_px=Decimal("100"),
        exit_px=Decimal("100") * (Decimal("1") + long_return),
        long_gross_return=long_return,
        short_gross_return=-long_return,
        provenance=("hyperliquid-mainnet-info",),
    )
    return HistoricalTrainingRow(feature=feature, outcome=outcome)


def _manifest(row_count: int) -> HistoricalDatasetManifest:
    return HistoricalDatasetManifest(
        output_relative_path="training.parquet",
        output_sha256="a" * 64,
        output_byte_count=100,
        row_count=row_count,
        logical_sha256="b" * 64,
        markets=("ETH",),
        horizons_ms=(FIVE,),
        source_manifest_ids=("source-a",),
        writer_library_version="test",
    )


def test_comparison_uses_identical_folds_and_touched_dataset_identity() -> None:
    rows = tuple(_row(index) for index in range(1, 13))
    config = HistoricalModelComparisonConfig(
        costs=ExecutionCostAssumptions(
            round_trip_fee_fraction=Decimal("0"),
            round_trip_slippage_fraction=Decimal("0"),
            funding_reserve_fraction_per_hour=Decimal("0"),
        ),
        candidate_thresholds=(Decimal("0"), Decimal("0.001")),
        candidate_ridge_alphas=(Decimal("0.01"), Decimal("0.1")),
        min_train_anchors=4,
        validation_anchors=2,
        test_anchors=2,
        step_anchors=2,
        embargo_anchors=0,
        baseline_min_state_samples=2,
        baseline_min_coin_samples=99,
        ridge_min_market_samples=99,
        min_sample_count=2,
        min_validation_trades=1,
    )
    manifest = _manifest(len(rows))

    report = build_historical_model_comparison_report(
        rows,
        dataset_manifest=manifest,
        config=config,
    )

    assert report.evidence_class == "touched_development"
    assert report.dataset_id == manifest.dataset_id
    assert report.dataset_logical_sha256 == manifest.logical_sha256
    assert len(report.baseline_folds) == len(report.ridge_folds) == 3
    assert len(report.horizon_ridge_folds) == 3
    assert len(report.stable_ridge_folds) == 3
    for baseline, ridge, horizon_ridge, stable_ridge in zip(
        report.baseline_folds,
        report.ridge_folds,
        report.horizon_ridge_folds,
        report.stable_ridge_folds,
        strict=True,
    ):
        assert (
            baseline.train_anchor_count,
            baseline.validation_anchor_count,
            baseline.test_anchor_count,
        ) == (
            ridge.train_anchor_count,
            ridge.validation_anchor_count,
            ridge.test_anchor_count,
        ) == (
            horizon_ridge.train_anchor_count,
            horizon_ridge.validation_anchor_count,
            horizon_ridge.test_anchor_count,
        ) == (
            stable_ridge.train_anchor_count,
            stable_ridge.validation_anchor_count,
            stable_ridge.test_anchor_count,
        )
    assert {
        candidate.alpha
        for candidate in report.ridge_folds[0].shared_validation
    } == {Decimal("0.01"), Decimal("0.1")}
    assert len(report.report_id) == 64


def test_comparison_report_is_deterministic() -> None:
    rows = tuple(_row(index) for index in range(1, 9))
    config = HistoricalModelComparisonConfig(
        costs=ExecutionCostAssumptions(
            round_trip_fee_fraction=Decimal("0"),
            round_trip_slippage_fraction=Decimal("0"),
            funding_reserve_fraction_per_hour=Decimal("0"),
        ),
        candidate_thresholds=(Decimal("0"),),
        candidate_ridge_alphas=(Decimal("0.1"),),
        min_train_anchors=4,
        validation_anchors=2,
        test_anchors=2,
        step_anchors=2,
        embargo_anchors=0,
        baseline_min_state_samples=1,
        baseline_min_coin_samples=99,
        ridge_min_market_samples=99,
        min_sample_count=1,
        min_validation_trades=1,
    )
    manifest = _manifest(len(rows))

    first = build_historical_model_comparison_report(
        rows,
        dataset_manifest=manifest,
        config=config,
    )
    second = build_historical_model_comparison_report(
        rows,
        dataset_manifest=manifest,
        config=config,
    )

    assert first == second
    assert first.report_id == second.report_id
