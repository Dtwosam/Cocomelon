from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from cocomelon.domain.market import MarketId
from cocomelon.research.historical_archive_acquisition import plan_archive_shards
from cocomelon.research.historical_archive_experiment import (
    ArchiveHistoricalExperimentResult,
    HistoricalArchiveExperimentClient,
    run_archive_historical_experiment,
)
from cocomelon.research.historical_baselines import ExecutionCostAssumptions
from cocomelon.research.historical_model_comparison import (
    HistoricalModelComparisonConfig,
)
from cocomelon.research.historical_tree import TreeModelConfig

PRESET_NAME = "archive-jul-sep-2026-v2"
EVIDENCE_CLASS = "touched_development"


def _utc_ms(value: str) -> int:
    return int(datetime.fromisoformat(value).astimezone(UTC).timestamp() * 1000)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


@dataclass(frozen=True, slots=True)
class HistoricalArchiveExperimentPreset:
    name: str
    start_ms: int
    end_ms: int
    markets: tuple[MarketId, ...]
    intervals: tuple[str, ...]
    horizons_ms: tuple[int, ...]
    comparison_config: HistoricalModelComparisonConfig
    overlap_candles: int
    max_funding_items: int
    evidence_class: str = EVIDENCE_CLASS
    schema_version: int = 2

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("name must not be empty")
        if self.start_ms < 0 or self.end_ms < self.start_ms:
            raise ValueError("invalid preset range")
        if not self.markets:
            raise ValueError("markets must not be empty")
        if not self.intervals:
            raise ValueError("intervals must not be empty")
        if not self.horizons_ms or any(value <= 0 for value in self.horizons_ms):
            raise ValueError("horizons_ms must contain positive values")
        if self.overlap_candles <= 0 or self.overlap_candles > 5_000:
            raise ValueError("overlap_candles must be between 1 and 5000")
        if self.max_funding_items <= 1:
            raise ValueError("max_funding_items must be greater than one")
        if self.evidence_class != EVIDENCE_CLASS:
            raise ValueError("archive presets must remain touched_development")
        if self.schema_version != 2:
            raise ValueError("unsupported archive preset schema")

    @property
    def archive_shard_count(self) -> int:
        return len(plan_archive_shards(start_ms=self.start_ms, end_ms=self.end_ms))

    def identity_payload(self) -> dict[str, object]:
        return {
            "name": self.name,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "markets": tuple(market.canonical for market in self.markets),
            "intervals": self.intervals,
            "horizons_ms": self.horizons_ms,
            "comparison_config": self.comparison_config.to_dict(),
            "overlap_candles": self.overlap_candles,
            "max_funding_items": self.max_funding_items,
            "archive_shard_count": self.archive_shard_count,
            "evidence_class": self.evidence_class,
            "schema_version": self.schema_version,
        }

    @property
    def preset_id(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()[:24]

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "preset_id": self.preset_id}


@dataclass(frozen=True, slots=True)
class HistoricalArchivePresetRunReceipt:
    preset_name: str
    preset_id: str
    preset_identity_sha256: str
    evidence_class: str
    archive_manifest_id: str
    archive_ingest_manifest_id: str
    coverage_report_id: str
    overlap_report_id: str
    dataset_id: str
    comparison_report_id: str
    comparison_version: str
    archive_shard_count: int
    archive_total_byte_count: int
    overlap_compared_count: int
    dataset_row_count: int
    fold_count: int
    schema_version: int = 1

    def __post_init__(self) -> None:
        for field in (
            "preset_name",
            "preset_id",
            "archive_manifest_id",
            "archive_ingest_manifest_id",
            "coverage_report_id",
            "overlap_report_id",
            "dataset_id",
            "comparison_report_id",
            "comparison_version",
        ):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} must not be empty")
        if len(self.preset_identity_sha256) != 64:
            raise ValueError("preset_identity_sha256 must be SHA-256")
        if self.evidence_class != EVIDENCE_CLASS:
            raise ValueError("preset run evidence must remain touched_development")
        for field in (
            "archive_shard_count",
            "overlap_compared_count",
            "dataset_row_count",
            "fold_count",
        ):
            if getattr(self, field) <= 0:
                raise ValueError(f"{field} must be positive")
        if self.archive_total_byte_count < 0:
            raise ValueError("archive_total_byte_count must be non-negative")
        if self.schema_version != 1:
            raise ValueError("unsupported preset run receipt schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "preset_name": self.preset_name,
            "preset_id": self.preset_id,
            "preset_identity_sha256": self.preset_identity_sha256,
            "evidence_class": self.evidence_class,
            "archive_manifest_id": self.archive_manifest_id,
            "archive_ingest_manifest_id": self.archive_ingest_manifest_id,
            "coverage_report_id": self.coverage_report_id,
            "overlap_report_id": self.overlap_report_id,
            "dataset_id": self.dataset_id,
            "comparison_report_id": self.comparison_report_id,
            "comparison_version": self.comparison_version,
            "archive_shard_count": self.archive_shard_count,
            "archive_total_byte_count": self.archive_total_byte_count,
            "overlap_compared_count": self.overlap_compared_count,
            "dataset_row_count": self.dataset_row_count,
            "fold_count": self.fold_count,
            "schema_version": self.schema_version,
        }

    @property
    def receipt_id(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "receipt_id": self.receipt_id}


def _summary_string(
    result: ArchiveHistoricalExperimentResult,
    field: str,
) -> str:
    value = result.source_summary.get(field)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"ARCHIVE_PRESET_{field.upper()}_MISSING")
    return value


def build_archive_preset_run_receipt(
    preset: HistoricalArchiveExperimentPreset,
    result: ArchiveHistoricalExperimentResult,
) -> HistoricalArchivePresetRunReceipt:
    if (
        result.archive.requested_start_ms != preset.start_ms
        or result.archive.requested_end_ms != preset.end_ms
    ):
        raise RuntimeError("ARCHIVE_PRESET_RANGE_MISMATCH")
    if result.archive.shard_count != preset.archive_shard_count:
        raise RuntimeError("ARCHIVE_PRESET_SHARD_COUNT_MISMATCH")
    if result.comparison.evidence_class != preset.evidence_class:
        raise RuntimeError("ARCHIVE_PRESET_EVIDENCE_CLASS_MISMATCH")
    if result.comparison.config.to_dict() != preset.comparison_config.to_dict():
        raise RuntimeError("ARCHIVE_PRESET_COMPARISON_CONFIG_MISMATCH")
    expected_markets = tuple(
        sorted(market.canonical for market in preset.markets)
    )
    if tuple(sorted(result.comparison.markets)) != expected_markets:
        raise RuntimeError("ARCHIVE_PRESET_MARKET_SET_MISMATCH")
    if tuple(sorted(result.comparison.horizons_ms)) != tuple(
        sorted(preset.horizons_ms)
    ):
        raise RuntimeError("ARCHIVE_PRESET_HORIZON_SET_MISMATCH")
    if (
        result.overlap.overlap_candles != preset.overlap_candles
        or not result.overlap.exact
    ):
        raise RuntimeError("ARCHIVE_PRESET_OVERLAP_MISMATCH")

    preset_identity_sha256 = hashlib.sha256(
        _canonical_json(preset.identity_payload()).encode("utf-8")
    ).hexdigest()
    return HistoricalArchivePresetRunReceipt(
        preset_name=preset.name,
        preset_id=preset.preset_id,
        preset_identity_sha256=preset_identity_sha256,
        evidence_class=preset.evidence_class,
        archive_manifest_id=result.archive.manifest_id,
        archive_ingest_manifest_id=_summary_string(
            result,
            "archive_manifest_id",
        ),
        coverage_report_id=_summary_string(result, "coverage_report_id"),
        overlap_report_id=result.overlap.report_id,
        dataset_id=result.dataset_id,
        comparison_report_id=result.report_id,
        comparison_version=result.comparison.comparison_version,
        archive_shard_count=result.archive.shard_count,
        archive_total_byte_count=result.archive.total_byte_count,
        overlap_compared_count=result.overlap.compared_count,
        dataset_row_count=result.comparison.dataset_row_count,
        fold_count=len(result.comparison.baseline_folds),
    )


def write_archive_preset_run_receipt(
    output_root: Path,
    receipt: HistoricalArchivePresetRunReceipt,
) -> Path:
    path = output_root / "preset-run.json"
    payload = _canonical_json(receipt.to_dict()) + "\n"
    output_root.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_text(encoding="utf-8") != payload:
            raise RuntimeError("ARCHIVE_PRESET_RUN_RECEIPT_CONFLICT")
        return path

    temporary = output_root / ".preset-run.json.tmp"
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)
    return path


JUL_SEP_2026_V2 = HistoricalArchiveExperimentPreset(
    name=PRESET_NAME,
    start_ms=_utc_ms("2026-07-01T00:00:00+00:00"),
    end_ms=_utc_ms("2026-09-20T23:55:00+00:00"),
    markets=(
        MarketId(dex="", coin="BTC"),
        MarketId(dex="", coin="ETH"),
        MarketId(dex="", coin="HYPE"),
        MarketId(dex="", coin="SOL"),
    ),
    intervals=("5m", "15m"),
    horizons_ms=(900_000, 3_600_000, 14_400_000),
    comparison_config=HistoricalModelComparisonConfig(
        costs=ExecutionCostAssumptions(
            round_trip_fee_fraction=Decimal("0.0007"),
            round_trip_slippage_fraction=Decimal("0.0005"),
            funding_reserve_fraction_per_hour=Decimal("0.0001"),
        ),
        candidate_thresholds=(
            Decimal("0"),
            Decimal("0.0005"),
            Decimal("0.001"),
            Decimal("0.002"),
            Decimal("0.004"),
        ),
        candidate_ridge_alphas=(
            Decimal("0.01"),
            Decimal("0.1"),
            Decimal("1"),
            Decimal("10"),
        ),
        min_train_anchors=8_000,
        validation_anchors=2_000,
        test_anchors=2_000,
        step_anchors=2_000,
        embargo_anchors=48,
        baseline_min_state_samples=50,
        baseline_min_coin_samples=100,
        ridge_min_market_samples=100,
        min_sample_count=50,
        min_validation_trades=20,
        min_validation_mean_net_return=Decimal("0"),
        stability_blocks=4,
        min_validation_block_trades=5,
        tree_min_market_samples=100,
        portfolio_max_concurrent_positions=2,
        tree_config=TreeModelConfig(
            max_leaf_nodes=7,
            min_samples_leaf=100,
            learning_rate=Decimal("0.05"),
            max_iter=100,
            l2_regularization=Decimal("1"),
        ),
    ),
    overlap_candles=96,
    max_funding_items=500,
)

PRESETS = {
    JUL_SEP_2026_V2.name: JUL_SEP_2026_V2,
}


def get_archive_experiment_preset(name: str) -> HistoricalArchiveExperimentPreset:
    try:
        return PRESETS[name]
    except KeyError as exc:
        raise ValueError(f"unknown archive experiment preset: {name}") from exc


def run_archive_experiment_preset(
    client: HistoricalArchiveExperimentClient,
    *,
    preset: HistoricalArchiveExperimentPreset,
    archive_root: Path,
    source_root: Path,
    output_root: Path,
    clock_ms: Callable[[], int],
) -> ArchiveHistoricalExperimentResult:
    result = run_archive_historical_experiment(
        client,
        archive_root=archive_root,
        source_root=source_root,
        output_root=output_root,
        markets=preset.markets,
        intervals=preset.intervals,
        horizons_ms=preset.horizons_ms,
        start_ms=preset.start_ms,
        end_ms=preset.end_ms,
        clock_ms=clock_ms,
        config=preset.comparison_config,
        max_funding_items=preset.max_funding_items,
        overlap_candles=preset.overlap_candles,
    )
    receipt = build_archive_preset_run_receipt(preset, result)
    write_archive_preset_run_receipt(output_root, receipt)
    return result
