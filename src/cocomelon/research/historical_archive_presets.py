from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from cocomelon.domain.market import MarketId
from cocomelon.research.historical_archive_experiment import (
    ArchiveHistoricalExperimentResult,
    HistoricalArchiveExperimentClient,
    run_archive_historical_experiment,
)
from cocomelon.research.historical_archive_acquisition import plan_archive_shards
from cocomelon.research.historical_baselines import ExecutionCostAssumptions
from cocomelon.research.historical_model_comparison import (
    HistoricalModelComparisonConfig,
)

PRESET_NAME = "archive-jul-sep-2026-v1"
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
    schema_version: int = 1

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
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")

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


JUL_SEP_2026_V1 = HistoricalArchiveExperimentPreset(
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
    ),
    overlap_candles=96,
    max_funding_items=500,
)

PRESETS = {
    JUL_SEP_2026_V1.name: JUL_SEP_2026_V1,
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
    return run_archive_historical_experiment(
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
