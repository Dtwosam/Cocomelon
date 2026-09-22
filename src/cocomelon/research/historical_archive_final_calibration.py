from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Any

from cocomelon.research.historical_archive_presets import (
    EVIDENCE_CLASS,
    HistoricalArchiveExperimentPreset,
)
from cocomelon.research.historical_archive_training_plan import (
    materialize_archive_candidate_training_rows,
    verify_archive_candidate_training_plan,
)
from cocomelon.research.historical_ridge_occupancy import (
    select_final_occupancy_stable_ridge,
)
from cocomelon.research.historical_ridge_portfolio_capacity import (
    select_final_portfolio_capacity_stable_ridge,
)
from cocomelon.research.historical_ridge_stability import (
    select_final_stable_horizon_ridge,
)
from cocomelon.research.historical_tree import calibrate_final_stable_tree

FINAL_CALIBRATION_SCHEMA_VERSION = 1


class HistoricalArchiveFinalCalibrationError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _require_sha256(value: str, field: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} must be lowercase SHA-256")


@dataclass(frozen=True, slots=True)
class HistoricalFinalCalibrationCandidate:
    alpha: Decimal | None
    horizon_thresholds: tuple[tuple[int, Decimal | None], ...]
    trade_count: int
    long_count: int
    short_count: int
    total_realized_net_return: Decimal
    mean_realized_net_return: Decimal | None
    qualifies: bool
    selected: bool

    def __post_init__(self) -> None:
        if self.alpha is not None and (
            not self.alpha.is_finite() or self.alpha <= 0
        ):
            raise ValueError("alpha must be positive and finite")
        horizons = tuple(item[0] for item in self.horizon_thresholds)
        if not horizons or horizons != tuple(sorted(set(horizons))):
            raise ValueError("horizon_thresholds must be sorted and unique")
        for horizon_ms, threshold in self.horizon_thresholds:
            if horizon_ms <= 0:
                raise ValueError("horizon_ms must be positive")
            if threshold is not None and (
                not threshold.is_finite() or threshold < 0
            ):
                raise ValueError("threshold must be non-negative and finite")
        for field in ("trade_count", "long_count", "short_count"):
            if getattr(self, field) < 0:
                raise ValueError(f"{field} must be non-negative")
        if self.long_count + self.short_count != self.trade_count:
            raise ValueError("long_count + short_count must equal trade_count")
        if not self.total_realized_net_return.is_finite():
            raise ValueError("total_realized_net_return must be finite")
        if self.mean_realized_net_return is None:
            if self.trade_count != 0:
                raise ValueError("mean return required when trades exist")
        elif not self.mean_realized_net_return.is_finite():
            raise ValueError("mean_realized_net_return must be finite")
        if self.selected and not self.qualifies:
            raise ValueError("selected calibration candidate must qualify")

    def identity_payload(self) -> dict[str, object]:
        return {
            "alpha": None if self.alpha is None else str(self.alpha),
            "horizon_thresholds": tuple(
                {
                    "horizon_ms": horizon_ms,
                    "threshold": None if threshold is None else str(threshold),
                }
                for horizon_ms, threshold in self.horizon_thresholds
            ),
            "trade_count": self.trade_count,
            "long_count": self.long_count,
            "short_count": self.short_count,
            "total_realized_net_return": str(
                self.total_realized_net_return
            ),
            "mean_realized_net_return": (
                None
                if self.mean_realized_net_return is None
                else str(self.mean_realized_net_return)
            ),
            "qualifies": self.qualifies,
            "selected": self.selected,
        }

    @property
    def candidate_sha256(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "candidate_sha256": self.candidate_sha256,
        }


@dataclass(frozen=True, slots=True)
class HistoricalArchiveFinalCalibration:
    preset_name: str
    preset_id: str
    evidence_class: str
    candidate_id: str
    training_plan_id: str
    bundle_id: str
    dataset_id: str
    model_family: str
    calibration_variant: str
    selection_algorithm: str
    fit_anchor_count: int
    calibration_anchor_count: int
    minimum_required_trades: int
    minimum_required_mean_net_return: Decimal
    candidates: tuple[HistoricalFinalCalibrationCandidate, ...]
    selected_candidate_sha256: str
    selected_alpha: Decimal | None
    selected_horizon_thresholds: tuple[tuple[int, Decimal | None], ...]
    calibration_trade_count: int
    calibration_long_count: int
    calibration_short_count: int
    calibration_total_realized_net_return: Decimal
    calibration_mean_realized_net_return: Decimal
    validation_not_before_ms: int
    prospective_only: bool = True
    promotion_eligible: bool = False
    trained_model_persisted: bool = False
    execution_ready: bool = False
    schema_version: int = FINAL_CALIBRATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in (
            "preset_name",
            "preset_id",
            "candidate_id",
            "training_plan_id",
            "bundle_id",
            "dataset_id",
            "model_family",
            "calibration_variant",
            "selection_algorithm",
            "selected_candidate_sha256",
        ):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} must not be empty")
        for field in (
            "candidate_id",
            "training_plan_id",
            "bundle_id",
            "dataset_id",
            "selected_candidate_sha256",
        ):
            _require_sha256(getattr(self, field), field)
        if self.evidence_class != EVIDENCE_CLASS:
            raise ValueError("final calibration evidence must remain touched")
        if self.fit_anchor_count <= 0 or self.calibration_anchor_count <= 0:
            raise ValueError("fit/calibration anchor counts must be positive")
        if self.minimum_required_trades <= 0:
            raise ValueError("minimum_required_trades must be positive")
        if not self.minimum_required_mean_net_return.is_finite():
            raise ValueError("minimum_required_mean_net_return must be finite")
        if not self.candidates:
            raise ValueError("candidates must not be empty")
        selected = tuple(item for item in self.candidates if item.selected)
        if len(selected) != 1:
            raise ValueError("exactly one final calibration candidate must be selected")
        if selected[0].candidate_sha256 != self.selected_candidate_sha256:
            raise ValueError("selected_candidate_sha256 must match selected candidate")
        if selected[0].alpha != self.selected_alpha:
            raise ValueError("selected_alpha must match selected candidate")
        if selected[0].horizon_thresholds != self.selected_horizon_thresholds:
            raise ValueError("selected thresholds must match selected candidate")
        if self.calibration_trade_count != selected[0].trade_count:
            raise ValueError("calibration_trade_count must match selected candidate")
        if self.calibration_long_count != selected[0].long_count:
            raise ValueError("calibration_long_count must match selected candidate")
        if self.calibration_short_count != selected[0].short_count:
            raise ValueError("calibration_short_count must match selected candidate")
        if (
            self.calibration_total_realized_net_return
            != selected[0].total_realized_net_return
        ):
            raise ValueError("calibration total return must match selected candidate")
        if selected[0].mean_realized_net_return is None:
            raise ValueError("selected candidate must have calibration mean")
        if (
            self.calibration_mean_realized_net_return
            != selected[0].mean_realized_net_return
        ):
            raise ValueError("calibration mean must match selected candidate")
        if (
            self.calibration_trade_count < self.minimum_required_trades
            or self.calibration_mean_realized_net_return
            <= self.minimum_required_mean_net_return
        ):
            raise ValueError("selected calibration must remain above frozen floor")
        if not any(
            threshold is not None
            for _horizon, threshold in self.selected_horizon_thresholds
        ):
            raise ValueError("selected calibration must trade at least one horizon")
        if not self.prospective_only:
            raise ValueError("final calibration must remain prospective-only")
        if self.promotion_eligible:
            raise ValueError("touched final calibration cannot be promotion eligible")
        if self.trained_model_persisted:
            raise ValueError("final calibration receipt does not persist a model")
        if self.execution_ready:
            raise ValueError("final calibration receipt is not execution ready")
        if self.schema_version != FINAL_CALIBRATION_SCHEMA_VERSION:
            raise ValueError("unsupported final calibration schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "preset_name": self.preset_name,
            "preset_id": self.preset_id,
            "evidence_class": self.evidence_class,
            "candidate_id": self.candidate_id,
            "training_plan_id": self.training_plan_id,
            "bundle_id": self.bundle_id,
            "dataset_id": self.dataset_id,
            "model_family": self.model_family,
            "calibration_variant": self.calibration_variant,
            "selection_algorithm": self.selection_algorithm,
            "fit_anchor_count": self.fit_anchor_count,
            "calibration_anchor_count": self.calibration_anchor_count,
            "minimum_required_trades": self.minimum_required_trades,
            "minimum_required_mean_net_return": str(
                self.minimum_required_mean_net_return
            ),
            "candidates": tuple(item.to_dict() for item in self.candidates),
            "selected_candidate_sha256": self.selected_candidate_sha256,
            "selected_alpha": (
                None if self.selected_alpha is None else str(self.selected_alpha)
            ),
            "selected_horizon_thresholds": tuple(
                {
                    "horizon_ms": horizon_ms,
                    "threshold": None if threshold is None else str(threshold),
                }
                for horizon_ms, threshold in self.selected_horizon_thresholds
            ),
            "calibration_trade_count": self.calibration_trade_count,
            "calibration_long_count": self.calibration_long_count,
            "calibration_short_count": self.calibration_short_count,
            "calibration_total_realized_net_return": str(
                self.calibration_total_realized_net_return
            ),
            "calibration_mean_realized_net_return": str(
                self.calibration_mean_realized_net_return
            ),
            "validation_not_before_ms": self.validation_not_before_ms,
            "prospective_only": self.prospective_only,
            "promotion_eligible": self.promotion_eligible,
            "trained_model_persisted": self.trained_model_persisted,
            "execution_ready": self.execution_ready,
            "schema_version": self.schema_version,
        }

    @property
    def calibration_id(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "calibration_id": self.calibration_id}


def _thresholds(horizons: Sequence[Any]) -> tuple[tuple[int, Decimal | None], ...]:
    return tuple(
        (
            int(item.horizon_ms),
            item.calibration.selected_threshold,
        )
        for item in horizons
    )


def _candidate(
    *,
    alpha: Decimal | None,
    horizons: Sequence[Any],
    evaluation: Any,
    minimum_required_trades: int,
    minimum_required_mean_net_return: Decimal,
    selected: bool,
) -> HistoricalFinalCalibrationCandidate:
    thresholds = _thresholds(horizons)
    mean = evaluation.mean_realized_net_return
    qualifies = (
        evaluation.trade_count >= minimum_required_trades
        and mean is not None
        and mean > minimum_required_mean_net_return
        and any(threshold is not None for _horizon, threshold in thresholds)
    )
    return HistoricalFinalCalibrationCandidate(
        alpha=alpha,
        horizon_thresholds=thresholds,
        trade_count=int(evaluation.trade_count),
        long_count=int(evaluation.long_count),
        short_count=int(evaluation.short_count),
        total_realized_net_return=evaluation.total_realized_net_return,
        mean_realized_net_return=mean,
        qualifies=qualifies,
        selected=selected,
    )


def _ridge_result(
    selected: Any | None,
    raw_candidates: Sequence[Any],
    *,
    minimum_required_trades: int,
    minimum_required_mean_net_return: Decimal,
) -> tuple[
    HistoricalFinalCalibrationCandidate,
    tuple[HistoricalFinalCalibrationCandidate, ...],
]:
    if selected is None:
        raise HistoricalArchiveFinalCalibrationError(
            "ARCHIVE_FINAL_CALIBRATION_NO_ELIGIBLE_RECIPE"
        )
    candidates = tuple(
        _candidate(
            alpha=item.alpha,
            horizons=item.horizons,
            evaluation=item.evaluation,
            minimum_required_trades=minimum_required_trades,
            minimum_required_mean_net_return=minimum_required_mean_net_return,
            selected=item.alpha == selected.alpha,
        )
        for item in raw_candidates
    )
    selected_items = tuple(item for item in candidates if item.selected)
    if len(selected_items) != 1 or not selected_items[0].qualifies:
        raise HistoricalArchiveFinalCalibrationError(
            "ARCHIVE_FINAL_CALIBRATION_SELECTION_INVALID"
        )
    return selected_items[0], candidates


def _tree_result(
    validation: Any,
    *,
    minimum_required_trades: int,
    minimum_required_mean_net_return: Decimal,
) -> tuple[
    HistoricalFinalCalibrationCandidate,
    tuple[HistoricalFinalCalibrationCandidate, ...],
]:
    item = _candidate(
        alpha=None,
        horizons=validation.horizons,
        evaluation=validation.evaluation,
        minimum_required_trades=minimum_required_trades,
        minimum_required_mean_net_return=minimum_required_mean_net_return,
        selected=False,
    )
    if not item.qualifies:
        raise HistoricalArchiveFinalCalibrationError(
            "ARCHIVE_FINAL_CALIBRATION_NO_ELIGIBLE_RECIPE"
        )
    selected_item = replace(item, selected=True)
    return selected_item, (selected_item,)


def build_archive_final_calibration(
    preset: HistoricalArchiveExperimentPreset,
    *,
    archive_root: Path,
    source_root: Path,
    output_root: Path,
) -> HistoricalArchiveFinalCalibration:
    plan = verify_archive_candidate_training_plan(
        output_root / "candidate-training-plan.json",
        preset=preset,
        archive_root=archive_root,
        source_root=source_root,
        output_root=output_root,
    )
    fit_rows, _embargo_rows, calibration_rows = (
        materialize_archive_candidate_training_rows(
            preset,
            source_root=source_root,
            plan=plan,
        )
    )
    config = preset.comparison_config
    allow_coin_calibration = plan.calibration_variant == "market"

    if plan.model_family == "stable_horizon_ridge":
        stable_selected_raw, stable_raw_candidates = (
            select_final_stable_horizon_ridge(
            fit_rows,
            calibration_rows,
            costs=config.costs,
            candidate_alphas=config.candidate_ridge_alphas,
            candidate_thresholds=config.candidate_thresholds,
            min_market_samples=config.ridge_min_market_samples,
            min_sample_count=config.min_sample_count,
            min_validation_trades=config.min_validation_trades,
            stability_blocks=config.stability_blocks,
            min_block_trades=config.min_validation_block_trades,
            allow_coin_calibration=allow_coin_calibration,
            min_validation_mean_net_return=(
                config.min_validation_mean_net_return
            ),
        )
        )
        selected, candidates = _ridge_result(
            stable_selected_raw,
            stable_raw_candidates,
            minimum_required_trades=config.min_validation_trades,
            minimum_required_mean_net_return=(
                config.min_validation_mean_net_return
            ),
        )
    elif plan.model_family == "occupancy_stable_ridge":
        occupancy_selected_raw, occupancy_raw_candidates = (
            select_final_occupancy_stable_ridge(
            fit_rows,
            calibration_rows,
            costs=config.costs,
            candidate_alphas=config.candidate_ridge_alphas,
            candidate_thresholds=config.candidate_thresholds,
            min_market_samples=config.ridge_min_market_samples,
            min_sample_count=config.min_sample_count,
            min_validation_trades=config.min_validation_trades,
            stability_blocks=config.stability_blocks,
            min_block_trades=config.min_validation_block_trades,
            allow_coin_calibration=allow_coin_calibration,
            min_validation_mean_net_return=(
                config.min_validation_mean_net_return
            ),
        )
        )
        selected, candidates = _ridge_result(
            occupancy_selected_raw,
            occupancy_raw_candidates,
            minimum_required_trades=config.min_validation_trades,
            minimum_required_mean_net_return=(
                config.min_validation_mean_net_return
            ),
        )
    elif plan.model_family == "portfolio_capacity_stable_ridge":
        portfolio_selected_raw, portfolio_raw_candidates = (
            select_final_portfolio_capacity_stable_ridge(
                fit_rows,
                calibration_rows,
                costs=config.costs,
                candidate_alphas=config.candidate_ridge_alphas,
                candidate_thresholds=config.candidate_thresholds,
                min_market_samples=config.ridge_min_market_samples,
                min_sample_count=config.min_sample_count,
                min_validation_trades=config.min_validation_trades,
                stability_blocks=config.stability_blocks,
                min_block_trades=config.min_validation_block_trades,
                allow_coin_calibration=allow_coin_calibration,
                max_concurrent_positions=(
                    config.portfolio_max_concurrent_positions
                ),
                min_validation_mean_net_return=(
                    config.min_validation_mean_net_return
                ),
            )
        )
        selected, candidates = _ridge_result(
            portfolio_selected_raw,
            portfolio_raw_candidates,
            minimum_required_trades=config.min_validation_trades,
            minimum_required_mean_net_return=(
                config.min_validation_mean_net_return
            ),
        )
    elif plan.model_family == "stable_tree":
        validation = calibrate_final_stable_tree(
            fit_rows,
            calibration_rows,
            config=config.tree_config,
            costs=config.costs,
            candidate_thresholds=config.candidate_thresholds,
            min_market_samples=config.tree_min_market_samples,
            min_sample_count=config.min_sample_count,
            min_validation_trades=config.min_validation_trades,
            stability_blocks=config.stability_blocks,
            min_block_trades=config.min_validation_block_trades,
            allow_coin_calibration=allow_coin_calibration,
            min_validation_mean_net_return=(
                config.min_validation_mean_net_return
            ),
        )
        selected, candidates = _tree_result(
            validation,
            minimum_required_trades=config.min_validation_trades,
            minimum_required_mean_net_return=(
                config.min_validation_mean_net_return
            ),
        )
    else:
        raise HistoricalArchiveFinalCalibrationError(
            "ARCHIVE_FINAL_CALIBRATION_MODEL_FAMILY_UNSUPPORTED"
        )

    if selected.mean_realized_net_return is None:
        raise HistoricalArchiveFinalCalibrationError(
            "ARCHIVE_FINAL_CALIBRATION_SELECTED_MEAN_REQUIRED"
        )
    return HistoricalArchiveFinalCalibration(
        preset_name=preset.name,
        preset_id=preset.preset_id,
        evidence_class=preset.evidence_class,
        candidate_id=plan.candidate_id,
        training_plan_id=plan.plan_id,
        bundle_id=plan.bundle_id,
        dataset_id=plan.dataset_id,
        model_family=plan.model_family,
        calibration_variant=plan.calibration_variant,
        selection_algorithm=plan.selection_algorithm,
        fit_anchor_count=plan.fit_anchor_count,
        calibration_anchor_count=plan.calibration_anchor_count,
        minimum_required_trades=config.min_validation_trades,
        minimum_required_mean_net_return=config.min_validation_mean_net_return,
        candidates=candidates,
        selected_candidate_sha256=selected.candidate_sha256,
        selected_alpha=selected.alpha,
        selected_horizon_thresholds=selected.horizon_thresholds,
        calibration_trade_count=selected.trade_count,
        calibration_long_count=selected.long_count,
        calibration_short_count=selected.short_count,
        calibration_total_realized_net_return=(
            selected.total_realized_net_return
        ),
        calibration_mean_realized_net_return=(
            selected.mean_realized_net_return
        ),
        validation_not_before_ms=plan.validation_not_before_ms,
    )


def write_archive_final_calibration(
    output_root: Path,
    calibration: HistoricalArchiveFinalCalibration,
) -> Path:
    path = output_root / "candidate-final-calibration.json"
    payload = (_canonical_json(calibration.to_dict()) + "\n").encode("utf-8")
    if path.exists():
        if path.read_bytes() != payload:
            raise HistoricalArchiveFinalCalibrationError(
                "ARCHIVE_FINAL_CALIBRATION_CONFLICT"
            )
        return path

    temporary = output_root / ".candidate-final-calibration.json.tmp"
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return path


def verify_archive_final_calibration(
    path: Path,
    *,
    preset: HistoricalArchiveExperimentPreset,
    archive_root: Path,
    source_root: Path,
    output_root: Path,
) -> HistoricalArchiveFinalCalibration:
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HistoricalArchiveFinalCalibrationError(
            "ARCHIVE_FINAL_CALIBRATION_INVALID"
        ) from exc
    expected = build_archive_final_calibration(
        preset,
        archive_root=archive_root,
        source_root=source_root,
        output_root=output_root,
    )
    canonical = _canonical_json(expected.to_dict()) + "\n"
    if path.read_text(encoding="utf-8") != canonical:
        raise HistoricalArchiveFinalCalibrationError(
            "ARCHIVE_FINAL_CALIBRATION_EVIDENCE_MISMATCH"
        )
    return expected
