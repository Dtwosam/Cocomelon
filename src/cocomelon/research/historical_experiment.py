from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from cocomelon.domain.market import MarketId
from cocomelon.research.historical_baselines import (
    ExecutionCostAssumptions,
    PolicyEvaluation,
    WalkForwardFoldResult,
    run_walk_forward_baseline,
)
from cocomelon.research.historical_dataset import (
    HistoricalDatasetManifest,
    build_training_rows_from_source_root,
    export_training_dataset,
)
from cocomelon.research.historical_features import HistoricalTrainingRow

EXPERIMENT_VERSION = "historical-conditional-baseline-v1"
EVIDENCE_CLASS = "touched_development"


class HistoricalExperimentError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with temporary.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()


@dataclass(frozen=True, slots=True)
class HistoricalExperimentConfig:
    costs: ExecutionCostAssumptions
    candidate_thresholds: tuple[Decimal, ...]
    min_train_anchors: int
    validation_anchors: int
    test_anchors: int
    step_anchors: int
    embargo_anchors: int
    min_state_samples: int
    min_coin_samples: int
    min_sample_count: int
    min_validation_trades: int

    def __post_init__(self) -> None:
        thresholds = tuple(sorted(set(self.candidate_thresholds)))
        if not thresholds:
            raise ValueError("candidate_thresholds must not be empty")
        if any(not value.is_finite() or value < 0 for value in thresholds):
            raise ValueError("candidate_thresholds must be non-negative finite Decimals")
        object.__setattr__(self, "candidate_thresholds", thresholds)

        for field in (
            "min_train_anchors",
            "validation_anchors",
            "test_anchors",
            "step_anchors",
            "min_state_samples",
            "min_coin_samples",
            "min_sample_count",
            "min_validation_trades",
        ):
            if getattr(self, field) <= 0:
                raise ValueError(f"{field} must be positive")
        if self.embargo_anchors < 0:
            raise ValueError("embargo_anchors must be non-negative")

    def to_dict(self) -> dict[str, object]:
        return {
            "costs": {
                "round_trip_fee_fraction": str(self.costs.round_trip_fee_fraction),
                "round_trip_slippage_fraction": str(
                    self.costs.round_trip_slippage_fraction
                ),
                "funding_reserve_fraction_per_hour": str(
                    self.costs.funding_reserve_fraction_per_hour
                ),
            },
            "candidate_thresholds": tuple(str(value) for value in self.candidate_thresholds),
            "min_train_anchors": self.min_train_anchors,
            "validation_anchors": self.validation_anchors,
            "test_anchors": self.test_anchors,
            "step_anchors": self.step_anchors,
            "embargo_anchors": self.embargo_anchors,
            "min_state_samples": self.min_state_samples,
            "min_coin_samples": self.min_coin_samples,
            "min_sample_count": self.min_sample_count,
            "min_validation_trades": self.min_validation_trades,
        }


def _evaluation_payload(value: PolicyEvaluation) -> dict[str, object]:
    return {
        "row_count": value.row_count,
        "trade_count": value.trade_count,
        "long_count": value.long_count,
        "short_count": value.short_count,
        "no_trade_count": value.no_trade_count,
        "total_realized_net_return": str(value.total_realized_net_return),
        "mean_realized_net_return": (
            None
            if value.mean_realized_net_return is None
            else str(value.mean_realized_net_return)
        ),
    }


def _fold_payload(value: WalkForwardFoldResult) -> dict[str, object]:
    return {
        "fold_index": value.fold_index,
        "train_anchor_count": value.train_anchor_count,
        "validation_anchor_count": value.validation_anchor_count,
        "test_anchor_count": value.test_anchor_count,
        "shared_threshold": str(value.shared_threshold),
        "coin_threshold": str(value.coin_threshold),
        "shared_test": _evaluation_payload(value.shared_test),
        "coin_test": _evaluation_payload(value.coin_test),
    }


@dataclass(frozen=True, slots=True)
class HistoricalExperimentReport:
    dataset_id: str
    dataset_logical_sha256: str
    dataset_row_count: int
    markets: tuple[str, ...]
    horizons_ms: tuple[int, ...]
    source_manifest_ids: tuple[str, ...]
    config: HistoricalExperimentConfig
    folds: tuple[WalkForwardFoldResult, ...]
    evidence_class: str = EVIDENCE_CLASS
    experiment_version: str = EXPERIMENT_VERSION
    schema_version: int = 1

    def __post_init__(self) -> None:
        for field in ("dataset_id", "dataset_logical_sha256"):
            value = getattr(self, field)
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise ValueError(f"{field} must be a lowercase SHA-256 digest")
        if self.dataset_row_count <= 0:
            raise ValueError("dataset_row_count must be positive")
        if not self.markets or any(not value.strip() for value in self.markets):
            raise ValueError("markets must contain non-empty values")
        if not self.horizons_ms or any(value <= 0 for value in self.horizons_ms):
            raise ValueError("horizons_ms must contain positive values")
        if not self.source_manifest_ids or any(
            not value.strip() for value in self.source_manifest_ids
        ):
            raise ValueError("source_manifest_ids must contain non-empty values")
        if not self.folds:
            raise ValueError("folds must not be empty")
        if self.evidence_class != EVIDENCE_CLASS:
            raise ValueError("historical experiment evidence must remain touched_development")
        if not self.experiment_version.strip():
            raise ValueError("experiment_version must not be empty")
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")
        object.__setattr__(self, "markets", tuple(sorted(set(self.markets))))
        object.__setattr__(self, "horizons_ms", tuple(sorted(set(self.horizons_ms))))
        object.__setattr__(
            self,
            "source_manifest_ids",
            tuple(sorted(set(self.source_manifest_ids))),
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            "dataset_id": self.dataset_id,
            "dataset_logical_sha256": self.dataset_logical_sha256,
            "dataset_row_count": self.dataset_row_count,
            "markets": self.markets,
            "horizons_ms": self.horizons_ms,
            "source_manifest_ids": self.source_manifest_ids,
            "config": self.config.to_dict(),
            "folds": tuple(_fold_payload(value) for value in self.folds),
            "evidence_class": self.evidence_class,
            "experiment_version": self.experiment_version,
            "schema_version": self.schema_version,
        }

    @property
    def report_id(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "report_id": self.report_id}


def _validate_dataset_identity(
    rows: Sequence[HistoricalTrainingRow],
    manifest: HistoricalDatasetManifest,
) -> None:
    if len(rows) != manifest.row_count:
        raise HistoricalExperimentError("training row count does not match dataset manifest")

    markets = tuple(sorted({row.market.canonical for row in rows}))
    if markets != manifest.markets:
        raise HistoricalExperimentError("training markets do not match dataset manifest")

    horizons = tuple(sorted({row.horizon_ms for row in rows}))
    if horizons != manifest.horizons_ms:
        raise HistoricalExperimentError("training horizons do not match dataset manifest")

    source_manifest_ids = tuple(
        sorted(
            {
                source_id
                for row in rows
                for source_id in row.feature.source_manifest_ids
            }
        )
    )
    if source_manifest_ids != manifest.source_manifest_ids:
        raise HistoricalExperimentError(
            "training source manifests do not match dataset manifest"
        )


def build_historical_experiment_report(
    rows: Sequence[HistoricalTrainingRow],
    *,
    dataset_manifest: HistoricalDatasetManifest,
    config: HistoricalExperimentConfig,
) -> HistoricalExperimentReport:
    if not rows:
        raise HistoricalExperimentError("training rows must not be empty")
    _validate_dataset_identity(rows, dataset_manifest)
    walk_forward = run_walk_forward_baseline(
        rows,
        costs=config.costs,
        candidate_thresholds=config.candidate_thresholds,
        min_train_anchors=config.min_train_anchors,
        validation_anchors=config.validation_anchors,
        test_anchors=config.test_anchors,
        step_anchors=config.step_anchors,
        embargo_anchors=config.embargo_anchors,
        min_state_samples=config.min_state_samples,
        min_coin_samples=config.min_coin_samples,
        min_sample_count=config.min_sample_count,
        min_validation_trades=config.min_validation_trades,
    )
    return HistoricalExperimentReport(
        dataset_id=dataset_manifest.dataset_id,
        dataset_logical_sha256=dataset_manifest.logical_sha256,
        dataset_row_count=dataset_manifest.row_count,
        markets=dataset_manifest.markets,
        horizons_ms=dataset_manifest.horizons_ms,
        source_manifest_ids=dataset_manifest.source_manifest_ids,
        config=config,
        folds=walk_forward.folds,
    )


def write_historical_experiment_report(
    path: Path,
    report: HistoricalExperimentReport,
) -> None:
    _atomic_write(
        path,
        (_canonical_json(report.to_dict()) + "\n").encode("utf-8"),
    )


def run_historical_experiment_from_sources(
    *,
    source_root: Path,
    output_root: Path,
    markets: Sequence[MarketId],
    horizons_ms: Sequence[int],
    config: HistoricalExperimentConfig,
) -> HistoricalExperimentReport:
    rows = build_training_rows_from_source_root(
        source_root,
        markets=markets,
        horizons_ms=horizons_ms,
    )
    dataset_manifest = export_training_dataset(rows, output_root / "dataset")
    report = build_historical_experiment_report(
        rows,
        dataset_manifest=dataset_manifest,
        config=config,
    )
    write_historical_experiment_report(output_root / "experiment.json", report)
    return report
