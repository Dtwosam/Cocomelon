from __future__ import annotations

from decimal import Decimal
import pytest

pytest.importorskip("pyarrow.parquet")

from cocomelon.domain.features import TrendRegime
from cocomelon.domain.market import MarketId
from cocomelon.research.historical_baselines import ExecutionCostAssumptions
from cocomelon.research.historical_context_opportunity import (
    build_context_opportunity_report,
)
from cocomelon.research.historical_dataset import HistoricalDatasetManifest
from cocomelon.research.historical_features import (
    HistoricalFeatureRow,
    HistoricalTrainingRow,
)
from cocomelon.research.historical_learning import DirectionalOutcome

MARKET = MarketId(dex="", coin="BTC")
HOUR = 3_600_000


def _row(anchor_index: int) -> HistoricalTrainingRow:
    anchor_end_ms = anchor_index * HOUR
    feature = HistoricalFeatureRow(
        market=MARKET,
        anchor_end_ms=anchor_end_ms,
        anchor_close_px=Decimal("100"),
        return_5m=None,
        return_15m=None,
        return_1h=Decimal("0.01"),
        return_4h=Decimal("0.02"),
        realized_vol_15m=None,
        range_expansion_15m=None,
        relative_volume_15m=None,
        funding_rate=Decimal("0.0001"),
        funding_change=Decimal("0"),
        funding_premium=Decimal("0.0002"),
        funding_premium_change=Decimal("0"),
        funding_age_ms=0,
        candle_15m_age_ms=None,
        trend_regime=TrendRegime.UP,
        availability_basis="exchange_timestamp",
        source_retrieved_at_ms=99_000_000,
        retrieved_after_anchor=True,
        available_features=(),
        unavailable_features=(),
        provenance=("hyperliquid-mainnet-info",),
        source_manifest_ids=("source-a",),
        basket_median_return_1h=Decimal("0.01"),
        basket_breadth_positive_1h=Decimal("0.75"),
        relative_return_zscore_1h_vs_basket=Decimal("1.2"),
        schema_version=3,
    )
    gross = Decimal("0.02")
    return HistoricalTrainingRow(
        feature=feature,
        outcome=DirectionalOutcome(
            market=MARKET,
            interval="1h",
            anchor_end_ms=anchor_end_ms,
            target_end_ms=anchor_end_ms + HOUR,
            horizon_ms=HOUR,
            entry_px=Decimal("100"),
            exit_px=Decimal("102"),
            long_gross_return=gross,
            short_gross_return=-gross,
            provenance=("hyperliquid-mainnet-info",),
        ),
    )


def _manifest(row_count: int) -> HistoricalDatasetManifest:
    return HistoricalDatasetManifest(
        output_relative_path="training.parquet",
        output_sha256="a" * 64,
        output_byte_count=100,
        row_count=row_count,
        logical_sha256="b" * 64,
        markets=("BTC",),
        horizons_ms=(HOUR,),
        source_manifest_ids=("source-a",),
        writer_library_version="test",
        anchor_interval="1h",
    )


def test_opportunity_report_binds_dataset_costs_and_stability_identity() -> None:
    rows = tuple(_row(index) for index in range(1, 9))
    costs = ExecutionCostAssumptions(
        round_trip_fee_fraction=Decimal("0.001"),
        round_trip_slippage_fraction=Decimal("0"),
        funding_reserve_fraction_per_hour=Decimal("0"),
    )
    manifest = _manifest(len(rows))

    first = build_context_opportunity_report(
        rows,
        dataset_manifest=manifest,
        costs=costs,
        stability_blocks=4,
        min_block_rows=2,
    )
    second = build_context_opportunity_report(
        tuple(reversed(rows)),
        dataset_manifest=manifest,
        costs=costs,
        stability_blocks=4,
        min_block_rows=2,
    )

    assert first.dataset_id == manifest.dataset_id
    assert first.dataset_logical_sha256 == manifest.logical_sha256
    assert first.anchor_interval == "1h"
    assert first.evidence_class == "touched_development"
    assert first.report_id == second.report_id
    assert len(first.report_id) == 64
    assert first.to_dict()["costs"]["round_trip_fee_fraction"] == "0.001"


def test_opportunity_report_identity_changes_when_stability_rule_changes() -> None:
    rows = tuple(_row(index) for index in range(1, 9))
    manifest = _manifest(len(rows))
    costs = ExecutionCostAssumptions(
        round_trip_fee_fraction=Decimal("0"),
        round_trip_slippage_fraction=Decimal("0"),
        funding_reserve_fraction_per_hour=Decimal("0"),
    )

    two_blocks = build_context_opportunity_report(
        rows,
        dataset_manifest=manifest,
        costs=costs,
        stability_blocks=2,
        min_block_rows=2,
    )
    four_blocks = build_context_opportunity_report(
        rows,
        dataset_manifest=manifest,
        costs=costs,
        stability_blocks=4,
        min_block_rows=2,
    )

    assert two_blocks.report_id != four_blocks.report_id
