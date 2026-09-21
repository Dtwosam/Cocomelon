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
    PolicyBreakdownEntry,
    PolicyEvaluation,
    ThresholdCandidateResult,
    WalkForwardFoldResult,
    run_walk_forward_baseline,
)
from cocomelon.research.historical_dataset import (
    HistoricalDatasetManifest,
    build_training_rows_from_source_root,
    export_training_dataset,
)
from cocomelon.research.historical_features import HistoricalTrainingRow
from cocomelon.research.historical_ridge import (
    RidgeAlphaValidation,
    RidgeWalkForwardFold,
    run_walk_forward_ridge,
)
from cocomelon.research.historical_ridge_horizon import (
    RidgeHorizonAlphaValidation,
    RidgeHorizonWalkForwardFold,
    run_walk_forward_horizon_calibrated_ridge,
)

EVIDENCE_CLASS = "touched_development"
COMPARISON_VERSION = "historical-baseline-vs-ridge-v2"


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
    finally:
        if temporary.exists():
            temporary.unlink()


def _evaluation(value: PolicyEvaluation) -> dict[str, object]:
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


def _threshold(value: ThresholdCandidateResult) -> dict[str, object]:
    return {
        "threshold": str(value.threshold),
        "trade_count": value.trade_count,
        "total_realized_net_return": str(value.total_realized_net_return),
        "mean_realized_net_return": (
            None
            if value.mean_realized_net_return is None
            else str(value.mean_realized_net_return)
        ),
    }


def _breakdown(value: PolicyBreakdownEntry) -> dict[str, object]:
    return {
        "dimension": value.dimension,
        "value": value.value,
        "evaluation": _evaluation(value.evaluation),
    }


def _baseline_fold(value: WalkForwardFoldResult) -> dict[str, object]:
    return {
        "fold_index": value.fold_index,
        "train_anchor_count": value.train_anchor_count,
        "validation_anchor_count": value.validation_anchor_count,
        "test_anchor_count": value.test_anchor_count,
        "shared_threshold": (
            None if value.shared_threshold is None else str(value.shared_threshold)
        ),
        "coin_threshold": (
            None if value.coin_threshold is None else str(value.coin_threshold)
        ),
        "shared_test": _evaluation(value.shared_test),
        "coin_test": _evaluation(value.coin_test),
        "shared_validation_candidates": tuple(
            _threshold(item) for item in value.shared_validation_candidates
        ),
        "coin_validation_candidates": tuple(
            _threshold(item) for item in value.coin_validation_candidates
        ),
        "shared_test_breakdowns": tuple(
            _breakdown(item) for item in value.shared_test_breakdowns
        ),
        "coin_test_breakdowns": tuple(
            _breakdown(item) for item in value.coin_test_breakdowns
        ),
    }


def _ridge_validation(value: RidgeAlphaValidation) -> dict[str, object]:
    return {
        "alpha": str(value.alpha),
        "selected_threshold": (
            None
            if value.calibration.selected_threshold is None
            else str(value.calibration.selected_threshold)
        ),
        "threshold_candidates": tuple(
            _threshold(item) for item in value.calibration.candidates
        ),
    }


def _ridge_fold(value: RidgeWalkForwardFold) -> dict[str, object]:
    return {
        "fold_index": value.fold_index,
        "train_anchor_count": value.train_anchor_count,
        "validation_anchor_count": value.validation_anchor_count,
        "test_anchor_count": value.test_anchor_count,
        "shared_alpha": None if value.shared_alpha is None else str(value.shared_alpha),
        "market_alpha": None if value.market_alpha is None else str(value.market_alpha),
        "shared_threshold": (
            None if value.shared_threshold is None else str(value.shared_threshold)
        ),
        "market_threshold": (
            None if value.market_threshold is None else str(value.market_threshold)
        ),
        "shared_test": _evaluation(value.shared_test),
        "market_test": _evaluation(value.market_test),
        "shared_validation": tuple(_ridge_validation(item) for item in value.shared_validation),
        "market_validation": tuple(_ridge_validation(item) for item in value.market_validation),
        "shared_test_breakdowns": tuple(
            _breakdown(item) for item in value.shared_test_breakdowns
        ),
        "market_test_breakdowns": tuple(
            _breakdown(item) for item in value.market_test_breakdowns
        ),
    }


def _horizon_validation(
    value: RidgeHorizonAlphaValidation,
) -> dict[str, object]:
    return {
        "alpha": str(value.alpha),
        "validation": _evaluation(value.evaluation),
        "horizons": tuple(
            {
                "horizon_ms": item.horizon_ms,
                "selected_threshold": (
                    None
                    if item.calibration.selected_threshold is None
                    else str(item.calibration.selected_threshold)
                ),
                "threshold_candidates": tuple(
                    _threshold(candidate)
                    for candidate in item.calibration.candidates
                ),
            }
            for item in value.horizons
        ),
    }


def _horizon_ridge_fold(
    value: RidgeHorizonWalkForwardFold,
) -> dict[str, object]:
    return {
        "fold_index": value.fold_index,
        "train_anchor_count": value.train_anchor_count,
        "validation_anchor_count": value.validation_anchor_count,
        "test_anchor_count": value.test_anchor_count,
        "shared_alpha": (
            None if value.shared_alpha is None else str(value.shared_alpha)
        ),
        "market_alpha": (
            None if value.market_alpha is None else str(value.market_alpha)
        ),
        "shared_horizon_thresholds": tuple(
            {
                "horizon_ms": horizon_ms,
                "threshold": None if threshold is None else str(threshold),
            }
            for horizon_ms, threshold in value.shared_horizon_thresholds
        ),
        "market_horizon_thresholds": tuple(
            {
                "horizon_ms": horizon_ms,
                "threshold": None if threshold is None else str(threshold),
            }
            for horizon_ms, threshold in value.market_horizon_thresholds
        ),
        "shared_test": _evaluation(value.shared_test),
        "market_test": _evaluation(value.market_test),
        "shared_validation": tuple(
            _horizon_validation(item) for item in value.shared_validation
        ),
        "market_validation": tuple(
            _horizon_validation(item) for item in value.market_validation
        ),
        "shared_test_breakdowns": tuple(
            _breakdown(item) for item in value.shared_test_breakdowns
        ),
        "market_test_breakdowns": tuple(
            _breakdown(item) for item in value.market_test_breakdowns
        ),
    }


@dataclass(frozen=True, slots=True)
class HistoricalModelComparisonConfig:
    costs: ExecutionCostAssumptions
    candidate_thresholds: tuple[Decimal, ...]
    candidate_ridge_alphas: tuple[Decimal, ...]
    min_train_anchors: int
    validation_anchors: int
    test_anchors: int
    step_anchors: int
    embargo_anchors: int
    baseline_min_state_samples: int
    baseline_min_coin_samples: int
    ridge_min_market_samples: int
    min_sample_count: int
    min_validation_trades: int
    min_validation_mean_net_return: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        thresholds = tuple(sorted(set(self.candidate_thresholds)))
        alphas = tuple(sorted(set(self.candidate_ridge_alphas)))
        if not thresholds:
            raise ValueError("candidate_thresholds must not be empty")
        if not alphas:
            raise ValueError("candidate_ridge_alphas must not be empty")
        if any(not value.is_finite() or value < 0 for value in thresholds):
            raise ValueError("candidate_thresholds must be non-negative finite Decimals")
        if any(not value.is_finite() or value <= 0 for value in alphas):
            raise ValueError("candidate_ridge_alphas must be positive finite Decimals")
        if not self.min_validation_mean_net_return.is_finite():
            raise ValueError("min_validation_mean_net_return must be finite")
        object.__setattr__(self, "candidate_thresholds", thresholds)
        object.__setattr__(self, "candidate_ridge_alphas", alphas)
        for field in (
            "min_train_anchors",
            "validation_anchors",
            "test_anchors",
            "step_anchors",
            "baseline_min_state_samples",
            "baseline_min_coin_samples",
            "ridge_min_market_samples",
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
            "candidate_thresholds": tuple(str(item) for item in self.candidate_thresholds),
            "candidate_ridge_alphas": tuple(
                str(item) for item in self.candidate_ridge_alphas
            ),
            "min_train_anchors": self.min_train_anchors,
            "validation_anchors": self.validation_anchors,
            "test_anchors": self.test_anchors,
            "step_anchors": self.step_anchors,
            "embargo_anchors": self.embargo_anchors,
            "baseline_min_state_samples": self.baseline_min_state_samples,
            "baseline_min_coin_samples": self.baseline_min_coin_samples,
            "ridge_min_market_samples": self.ridge_min_market_samples,
            "min_sample_count": self.min_sample_count,
            "min_validation_trades": self.min_validation_trades,
            "min_validation_mean_net_return": str(
                self.min_validation_mean_net_return
            ),
        }


@dataclass(frozen=True, slots=True)
class HistoricalModelComparisonReport:
    dataset_id: str
    dataset_logical_sha256: str
    dataset_row_count: int
    markets: tuple[str, ...]
    horizons_ms: tuple[int, ...]
    source_manifest_ids: tuple[str, ...]
    config: HistoricalModelComparisonConfig
    baseline_folds: tuple[WalkForwardFoldResult, ...]
    ridge_folds: tuple[RidgeWalkForwardFold, ...]
    horizon_ridge_folds: tuple[RidgeHorizonWalkForwardFold, ...]
    evidence_class: str = EVIDENCE_CLASS
    comparison_version: str = COMPARISON_VERSION
    schema_version: int = 2

    def __post_init__(self) -> None:
        fold_count = len(self.baseline_folds)
        if fold_count != len(self.ridge_folds):
            raise ValueError("baseline and ridge fold counts must match")
        if fold_count != len(self.horizon_ridge_folds):
            raise ValueError("all model fold counts must match")
        for baseline, ridge, horizon_ridge in zip(
            self.baseline_folds,
            self.ridge_folds,
            self.horizon_ridge_folds,
            strict=True,
        ):
            baseline_shape = (
                baseline.fold_index,
                baseline.train_anchor_count,
                baseline.validation_anchor_count,
                baseline.test_anchor_count,
            )
            ridge_shape = (
                ridge.fold_index,
                ridge.train_anchor_count,
                ridge.validation_anchor_count,
                ridge.test_anchor_count,
            )
            horizon_shape = (
                horizon_ridge.fold_index,
                horizon_ridge.train_anchor_count,
                horizon_ridge.validation_anchor_count,
                horizon_ridge.test_anchor_count,
            )
            if baseline_shape != ridge_shape or baseline_shape != horizon_shape:
                raise ValueError("all model folds must use identical chronology")
        if self.evidence_class != EVIDENCE_CLASS:
            raise ValueError("comparison evidence must remain touched_development")

    def identity_payload(self) -> dict[str, object]:
        return {
            "dataset_id": self.dataset_id,
            "dataset_logical_sha256": self.dataset_logical_sha256,
            "dataset_row_count": self.dataset_row_count,
            "markets": self.markets,
            "horizons_ms": self.horizons_ms,
            "source_manifest_ids": self.source_manifest_ids,
            "config": self.config.to_dict(),
            "baseline_folds": tuple(_baseline_fold(item) for item in self.baseline_folds),
            "ridge_folds": tuple(_ridge_fold(item) for item in self.ridge_folds),
            "horizon_ridge_folds": tuple(
                _horizon_ridge_fold(item)
                for item in self.horizon_ridge_folds
            ),
            "evidence_class": self.evidence_class,
            "comparison_version": self.comparison_version,
            "schema_version": self.schema_version,
        }

    @property
    def report_id(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "report_id": self.report_id}


def build_historical_model_comparison_report(
    rows: Sequence[HistoricalTrainingRow],
    *,
    dataset_manifest: HistoricalDatasetManifest,
    config: HistoricalModelComparisonConfig,
) -> HistoricalModelComparisonReport:
    baseline = run_walk_forward_baseline(
        rows,
        costs=config.costs,
        candidate_thresholds=config.candidate_thresholds,
        min_train_anchors=config.min_train_anchors,
        validation_anchors=config.validation_anchors,
        test_anchors=config.test_anchors,
        step_anchors=config.step_anchors,
        embargo_anchors=config.embargo_anchors,
        min_state_samples=config.baseline_min_state_samples,
        min_coin_samples=config.baseline_min_coin_samples,
        min_sample_count=config.min_sample_count,
        min_validation_trades=config.min_validation_trades,
        min_validation_mean_net_return=config.min_validation_mean_net_return,
    )
    ridge = run_walk_forward_ridge(
        rows,
        costs=config.costs,
        candidate_alphas=config.candidate_ridge_alphas,
        candidate_thresholds=config.candidate_thresholds,
        min_train_anchors=config.min_train_anchors,
        validation_anchors=config.validation_anchors,
        test_anchors=config.test_anchors,
        step_anchors=config.step_anchors,
        embargo_anchors=config.embargo_anchors,
        min_market_samples=config.ridge_min_market_samples,
        min_sample_count=config.min_sample_count,
        min_validation_trades=config.min_validation_trades,
        min_validation_mean_net_return=config.min_validation_mean_net_return,
    )
    horizon_ridge = run_walk_forward_horizon_calibrated_ridge(
        rows,
        costs=config.costs,
        candidate_alphas=config.candidate_ridge_alphas,
        candidate_thresholds=config.candidate_thresholds,
        min_train_anchors=config.min_train_anchors,
        validation_anchors=config.validation_anchors,
        test_anchors=config.test_anchors,
        step_anchors=config.step_anchors,
        embargo_anchors=config.embargo_anchors,
        min_market_samples=config.ridge_min_market_samples,
        min_sample_count=config.min_sample_count,
        min_validation_trades=config.min_validation_trades,
        min_validation_mean_net_return=config.min_validation_mean_net_return,
    )
    return HistoricalModelComparisonReport(
        dataset_id=dataset_manifest.dataset_id,
        dataset_logical_sha256=dataset_manifest.logical_sha256,
        dataset_row_count=dataset_manifest.row_count,
        markets=dataset_manifest.markets,
        horizons_ms=dataset_manifest.horizons_ms,
        source_manifest_ids=dataset_manifest.source_manifest_ids,
        config=config,
        baseline_folds=baseline.folds,
        ridge_folds=ridge.folds,
        horizon_ridge_folds=horizon_ridge.folds,
    )


def run_historical_model_comparison_from_sources(
    *,
    source_root: Path,
    output_root: Path,
    markets: Sequence[MarketId],
    horizons_ms: Sequence[int],
    config: HistoricalModelComparisonConfig,
) -> HistoricalModelComparisonReport:
    rows = build_training_rows_from_source_root(
        source_root,
        markets=markets,
        horizons_ms=horizons_ms,
    )
    manifest = export_training_dataset(rows, output_root / "dataset")
    report = build_historical_model_comparison_report(
        rows,
        dataset_manifest=manifest,
        config=config,
    )
    _atomic_write(
        output_root / "comparison.json",
        (_canonical_json(report.to_dict()) + "\n").encode("utf-8"),
    )
    return report
