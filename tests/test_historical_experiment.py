from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from cocomelon.domain.features import TrendRegime
from cocomelon.domain.market import MarketId
from cocomelon.research.historical_baselines import ExecutionCostAssumptions
from cocomelon.research.historical_dataset import HistoricalDatasetManifest
from cocomelon.research.historical_experiment import (
    HistoricalExperimentConfig,
    build_historical_experiment_report,
    write_historical_experiment_report,
)
from cocomelon.research.historical_features import HistoricalFeatureRow, HistoricalTrainingRow
from cocomelon.research.historical_learning import DirectionalOutcome

MARKET = MarketId(dex="", coin="ETH")
FIVE = 300_000


def _row(anchor_end_ms: int, long_return: str, short_return: str) -> HistoricalTrainingRow:
    feature = HistoricalFeatureRow(
        market=MARKET,
        anchor_end_ms=anchor_end_ms,
        anchor_close_px=Decimal("100"),
        return_5m=Decimal("0.01"),
        return_15m=Decimal("0.01"),
        return_1h=Decimal("0.02"),
        return_4h=Decimal("0.03"),
        realized_vol_15m=Decimal("0.005"),
        range_expansion_15m=Decimal("1.2"),
        relative_volume_15m=Decimal("1.5"),
        funding_rate=Decimal("0.0001"),
        funding_change=None,
        funding_premium=None,
        funding_premium_change=None,
        funding_age_ms=0,
        candle_15m_age_ms=0,
        trend_regime=TrendRegime.UP,
        availability_basis="exchange_timestamp",
        source_retrieved_at_ms=99_000_000,
        retrieved_after_anchor=True,
        available_features=("funding_rate", "return_5m"),
        unavailable_features=("book_imbalance", "open_interest", "spread_bps"),
        provenance=("hyperliquid-mainnet-info",),
        source_manifest_ids=("source-manifest-a",),
    )
    outcome = DirectionalOutcome(
        market=MARKET,
        interval="5m",
        anchor_end_ms=anchor_end_ms,
        target_end_ms=anchor_end_ms + FIVE,
        horizon_ms=FIVE,
        entry_px=Decimal("100"),
        exit_px=Decimal("100") * (Decimal("1") + Decimal(long_return)),
        long_gross_return=Decimal(long_return),
        short_gross_return=Decimal(short_return),
        provenance=("hyperliquid-mainnet-info",),
    )
    return HistoricalTrainingRow(feature=feature, outcome=outcome)


def _dataset_manifest(row_count: int) -> HistoricalDatasetManifest:
    return HistoricalDatasetManifest(
        output_relative_path="training.parquet",
        output_sha256="a" * 64,
        output_byte_count=100,
        row_count=row_count,
        logical_sha256="b" * 64,
        markets=("ETH",),
        horizons_ms=(FIVE,),
        source_manifest_ids=("source-manifest-a",),
        writer_library_version="test-pyarrow",
    )


def _config() -> HistoricalExperimentConfig:
    return HistoricalExperimentConfig(
        costs=ExecutionCostAssumptions(
            round_trip_fee_fraction=Decimal("0.001"),
            round_trip_slippage_fraction=Decimal("0.001"),
            funding_reserve_fraction_per_hour=Decimal("0.0001"),
        ),
        candidate_thresholds=(Decimal("0"), Decimal("0.005"), Decimal("0.01")),
        min_train_anchors=4,
        validation_anchors=2,
        test_anchors=2,
        step_anchors=2,
        embargo_anchors=0,
        min_state_samples=2,
        min_coin_samples=99,
        min_sample_count=2,
        min_validation_trades=1,
    )


def test_experiment_report_is_deterministic_and_permanently_touched() -> None:
    rows = tuple(
        _row(
            anchor_end_ms=index * FIVE,
            long_return="0.03" if index <= 8 else "-0.02",
            short_return="-0.03" if index <= 8 else "0.02",
        )
        for index in range(1, 13)
    )
    manifest = _dataset_manifest(len(rows))

    first = build_historical_experiment_report(rows, dataset_manifest=manifest, config=_config())
    second = build_historical_experiment_report(rows, dataset_manifest=manifest, config=_config())

    assert first == second
    assert first.report_id == second.report_id
    assert len(first.report_id) == 64
    assert first.evidence_class == "touched_development"
    assert first.dataset_id == manifest.dataset_id
    assert first.dataset_logical_sha256 == manifest.logical_sha256
    assert first.source_manifest_ids == ("source-manifest-a",)
    assert len(first.folds) == 3
    assert first.folds[-1].shared_threshold is None
    assert first.folds[-1].shared_test.trade_count == 0
    assert first.folds[-1].shared_test.mean_realized_net_return is None


def test_experiment_report_serializes_costs_thresholds_and_fold_results(tmp_path: Path) -> None:
    rows = tuple(
        _row(anchor_end_ms=index * FIVE, long_return="0.03", short_return="-0.03")
        for index in range(1, 9)
    )
    report = build_historical_experiment_report(
        rows,
        dataset_manifest=_dataset_manifest(len(rows)),
        config=_config(),
    )

    path = tmp_path / "experiment.json"
    write_historical_experiment_report(path, report)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["report_id"] == report.report_id
    assert payload["evidence_class"] == "touched_development"
    assert payload["config"]["costs"]["round_trip_fee_fraction"] == "0.001"
    assert payload["config"]["candidate_thresholds"] == ["0", "0.005", "0.01"]
    assert payload["config"]["min_validation_mean_net_return"] == "0"
    assert payload["folds"][0]["shared_threshold"] in {"0", "0.005", "0.01"}
    assert payload["folds"][0]["shared_test"]["trade_count"] == 2
    assert payload["folds"][0]["shared_validation_candidates"]
    assert payload["folds"][0]["coin_validation_candidates"]
    assert payload["folds"][0]["shared_test_breakdowns"]
    assert payload["folds"][0]["coin_test_breakdowns"]
