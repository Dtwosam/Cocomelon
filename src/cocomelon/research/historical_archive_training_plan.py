from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from cocomelon.hyperliquid.client import INTERVAL_MS
from cocomelon.research.historical_archive_candidate_freeze import (
    HistoricalArchiveCandidateFreeze,
    verify_archive_candidate_freeze,
)
from cocomelon.research.historical_archive_experiment import (
    verify_prepared_archive_historical_sources,
)
from cocomelon.research.historical_archive_presets import (
    EVIDENCE_CLASS,
    HistoricalArchiveExperimentPreset,
    verify_archive_preset_run_receipt,
)
from cocomelon.research.historical_dataset import (
    HistoricalTrainingRow,
    build_training_rows_from_source_root,
    canonical_training_rows,
    training_rows_logical_sha256,
)

TRAINING_PLAN_POLICY = "chronological-final-fit-calibration-v1"
TRAINING_PLAN_SCHEMA_VERSION = 1


class HistoricalArchiveTrainingPlanError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise HistoricalArchiveTrainingPlanError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _sequence(value: object, field: str) -> tuple[object, ...]:
    if not isinstance(value, list):
        raise HistoricalArchiveTrainingPlanError(f"{field} must be an array")
    return tuple(value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalArchiveTrainingPlanError(
            f"{field} must be a non-empty string"
        )
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise HistoricalArchiveTrainingPlanError(f"{field} must be an integer")
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise HistoricalArchiveTrainingPlanError(f"{field} must be boolean")
    return value


def _require_sha256(value: str, field: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} must be lowercase SHA-256")


@dataclass(frozen=True, slots=True)
class HistoricalArchiveCandidateTrainingPlan:
    preset_name: str
    preset_id: str
    evidence_class: str
    candidate_id: str
    bundle_id: str
    model_family: str
    calibration_variant: str
    qualified_variant_sha256: str
    dataset_id: str
    dataset_logical_sha256: str
    dataset_row_count: int
    anchor_interval: str
    total_anchor_count: int
    fit_anchor_count: int
    fit_row_count: int
    fit_start_ms: int
    fit_end_ms: int
    embargo_anchor_count: int
    embargo_start_ms: int
    embargo_end_ms: int
    calibration_anchor_count: int
    calibration_row_count: int
    calibration_start_ms: int
    calibration_end_ms: int
    maximum_horizon_ms: int
    comparison_config_sha256: str
    comparison_config: dict[str, object]
    selection_algorithm: str
    validation_not_before_ms: int
    training_policy: str = TRAINING_PLAN_POLICY
    prospective_only: bool = True
    promotion_eligible: bool = False
    execution_ready: bool = False
    schema_version: int = TRAINING_PLAN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in (
            "preset_name",
            "preset_id",
            "candidate_id",
            "bundle_id",
            "model_family",
            "calibration_variant",
            "qualified_variant_sha256",
            "dataset_id",
            "dataset_logical_sha256",
            "anchor_interval",
            "comparison_config_sha256",
            "selection_algorithm",
        ):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} must not be empty")
        for field in (
            "candidate_id",
            "bundle_id",
            "qualified_variant_sha256",
            "dataset_id",
            "dataset_logical_sha256",
            "comparison_config_sha256",
        ):
            _require_sha256(getattr(self, field), field)
        if self.evidence_class != EVIDENCE_CLASS:
            raise ValueError("training plan evidence must remain touched")
        if self.anchor_interval not in INTERVAL_MS:
            raise ValueError("unsupported anchor_interval")
        if self.dataset_row_count <= 0:
            raise ValueError("dataset_row_count must be positive")
        for field in (
            "total_anchor_count",
            "fit_anchor_count",
            "fit_row_count",
            "embargo_anchor_count",
            "calibration_anchor_count",
            "calibration_row_count",
            "maximum_horizon_ms",
        ):
            if getattr(self, field) <= 0:
                raise ValueError(f"{field} must be positive")
        if (
            self.fit_anchor_count
            + self.embargo_anchor_count
            + self.calibration_anchor_count
            != self.total_anchor_count
        ):
            raise ValueError("fit/embargo/calibration anchors must cover dataset")
        if not (
            self.fit_start_ms <= self.fit_end_ms
            < self.embargo_start_ms
            <= self.embargo_end_ms
            < self.calibration_start_ms
            <= self.calibration_end_ms
        ):
            raise ValueError("training plan partitions must be chronological")
        if (
            self.embargo_anchor_count * INTERVAL_MS[self.anchor_interval]
            < self.maximum_horizon_ms
        ):
            raise ValueError("training plan embargo must cover maximum horizon")
        if not isinstance(self.comparison_config, dict) or not self.comparison_config:
            raise ValueError("comparison_config must not be empty")
        expected_config_sha256 = hashlib.sha256(
            _canonical_json(self.comparison_config).encode("utf-8")
        ).hexdigest()
        if expected_config_sha256 != self.comparison_config_sha256:
            raise ValueError("comparison_config_sha256 must match comparison_config")
        if self.training_policy != TRAINING_PLAN_POLICY:
            raise ValueError("unsupported training plan policy")
        if not self.prospective_only:
            raise ValueError("training plan must remain prospective-only")
        if self.promotion_eligible:
            raise ValueError("touched training plan cannot be promotion eligible")
        if self.execution_ready:
            raise ValueError("training plan is not a trained execution artifact")
        if self.schema_version != TRAINING_PLAN_SCHEMA_VERSION:
            raise ValueError("unsupported training plan schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "preset_name": self.preset_name,
            "preset_id": self.preset_id,
            "evidence_class": self.evidence_class,
            "candidate_id": self.candidate_id,
            "bundle_id": self.bundle_id,
            "model_family": self.model_family,
            "calibration_variant": self.calibration_variant,
            "qualified_variant_sha256": self.qualified_variant_sha256,
            "dataset_id": self.dataset_id,
            "dataset_logical_sha256": self.dataset_logical_sha256,
            "dataset_row_count": self.dataset_row_count,
            "anchor_interval": self.anchor_interval,
            "total_anchor_count": self.total_anchor_count,
            "fit_anchor_count": self.fit_anchor_count,
            "fit_row_count": self.fit_row_count,
            "fit_start_ms": self.fit_start_ms,
            "fit_end_ms": self.fit_end_ms,
            "embargo_anchor_count": self.embargo_anchor_count,
            "embargo_start_ms": self.embargo_start_ms,
            "embargo_end_ms": self.embargo_end_ms,
            "calibration_anchor_count": self.calibration_anchor_count,
            "calibration_row_count": self.calibration_row_count,
            "calibration_start_ms": self.calibration_start_ms,
            "calibration_end_ms": self.calibration_end_ms,
            "maximum_horizon_ms": self.maximum_horizon_ms,
            "comparison_config_sha256": self.comparison_config_sha256,
            "comparison_config": self.comparison_config,
            "selection_algorithm": self.selection_algorithm,
            "validation_not_before_ms": self.validation_not_before_ms,
            "training_policy": self.training_policy,
            "prospective_only": self.prospective_only,
            "promotion_eligible": self.promotion_eligible,
            "execution_ready": self.execution_ready,
            "schema_version": self.schema_version,
        }

    @property
    def plan_id(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "plan_id": self.plan_id}


def _dataset_manifest(output_root: Path) -> dict[str, object]:
    path = output_root / "dataset" / "manifest.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HistoricalArchiveTrainingPlanError(
            "ARCHIVE_TRAINING_DATASET_MANIFEST_INVALID"
        ) from exc
    return _mapping(raw, "historical dataset manifest")


def _selection_algorithm(freeze: HistoricalArchiveCandidateFreeze) -> str:
    algorithms = {
        "stable_horizon_ridge": "stable_horizon_ridge_final_calibration_v1",
        "occupancy_stable_ridge": "occupancy_stable_ridge_final_calibration_v1",
        "portfolio_capacity_stable_ridge": (
            "portfolio_capacity_stable_ridge_final_calibration_v1"
        ),
        "stable_tree": "stable_tree_final_calibration_v1",
    }
    try:
        return algorithms[freeze.model_family]
    except KeyError as exc:
        raise HistoricalArchiveTrainingPlanError(
            "ARCHIVE_TRAINING_MODEL_FAMILY_UNSUPPORTED"
        ) from exc


def _partition_rows(
    rows: tuple[HistoricalTrainingRow, ...],
    *,
    validation_anchors: int,
    embargo_anchors: int,
    min_train_anchors: int,
) -> tuple[
    tuple[HistoricalTrainingRow, ...],
    tuple[HistoricalTrainingRow, ...],
    tuple[HistoricalTrainingRow, ...],
    tuple[int, ...],
    tuple[int, ...],
    tuple[int, ...],
]:
    anchors = tuple(sorted({row.anchor_end_ms for row in rows}))
    required = min_train_anchors + embargo_anchors + validation_anchors
    if len(anchors) < required:
        raise HistoricalArchiveTrainingPlanError(
            "ARCHIVE_TRAINING_DATASET_TOO_SHORT"
        )
    fit_count = len(anchors) - embargo_anchors - validation_anchors
    fit_anchors = anchors[:fit_count]
    embargo = anchors[fit_count : fit_count + embargo_anchors]
    calibration = anchors[fit_count + embargo_anchors :]
    if (
        len(fit_anchors) < min_train_anchors
        or len(embargo) != embargo_anchors
        or len(calibration) != validation_anchors
    ):
        raise HistoricalArchiveTrainingPlanError(
            "ARCHIVE_TRAINING_PARTITION_INVALID"
        )

    fit_set = set(fit_anchors)
    embargo_set = set(embargo)
    calibration_set = set(calibration)
    fit_rows = tuple(row for row in rows if row.anchor_end_ms in fit_set)
    embargo_rows = tuple(row for row in rows if row.anchor_end_ms in embargo_set)
    calibration_rows = tuple(
        row for row in rows if row.anchor_end_ms in calibration_set
    )
    return (
        fit_rows,
        embargo_rows,
        calibration_rows,
        fit_anchors,
        embargo,
        calibration,
    )


def build_archive_candidate_training_plan(
    preset: HistoricalArchiveExperimentPreset,
    *,
    archive_root: Path,
    source_root: Path,
    output_root: Path,
) -> HistoricalArchiveCandidateTrainingPlan:
    freeze = verify_archive_candidate_freeze(
        output_root / "candidate-freeze.json",
        preset=preset,
        archive_root=archive_root,
        source_root=source_root,
        output_root=output_root,
    )
    verify_prepared_archive_historical_sources(
        archive_root=archive_root,
        source_root=source_root,
        markets=preset.markets,
        intervals=preset.intervals,
        start_ms=preset.start_ms,
        end_ms=preset.end_ms,
        overlap_candles=preset.overlap_candles,
    )
    run_receipt = verify_archive_preset_run_receipt(
        output_root / "preset-run.json",
        preset=preset,
    )
    manifest = _dataset_manifest(output_root)

    dataset_id = _string(manifest.get("dataset_id"), "dataset_id")
    dataset_logical_sha256 = _string(
        manifest.get("logical_sha256"),
        "logical_sha256",
    )
    dataset_row_count = _integer(manifest.get("row_count"), "row_count")
    anchor_interval = _string(
        manifest.get("anchor_interval"),
        "anchor_interval",
    )
    markets = tuple(
        _string(item, "dataset market")
        for item in _sequence(manifest.get("markets"), "markets")
    )
    horizons_ms = tuple(
        _integer(item, "dataset horizon_ms")
        for item in _sequence(manifest.get("horizons_ms"), "horizons_ms")
    )
    if dataset_id != run_receipt.dataset_id:
        raise HistoricalArchiveTrainingPlanError(
            "ARCHIVE_TRAINING_DATASET_ID_MISMATCH"
        )
    if markets != tuple(sorted(market.canonical for market in preset.markets)):
        raise HistoricalArchiveTrainingPlanError(
            "ARCHIVE_TRAINING_DATASET_MARKETS_MISMATCH"
        )
    if horizons_ms != tuple(sorted(preset.horizons_ms)):
        raise HistoricalArchiveTrainingPlanError(
            "ARCHIVE_TRAINING_DATASET_HORIZONS_MISMATCH"
        )
    if anchor_interval != "5m":
        raise HistoricalArchiveTrainingPlanError(
            "ARCHIVE_TRAINING_ANCHOR_INTERVAL_MISMATCH"
        )

    rows = canonical_training_rows(
        build_training_rows_from_source_root(
            source_root,
            markets=preset.markets,
            horizons_ms=preset.horizons_ms,
            anchor_interval=anchor_interval,
        )
    )
    if len(rows) != dataset_row_count:
        raise HistoricalArchiveTrainingPlanError(
            "ARCHIVE_TRAINING_DATASET_ROW_COUNT_MISMATCH"
        )
    if training_rows_logical_sha256(rows) != dataset_logical_sha256:
        raise HistoricalArchiveTrainingPlanError(
            "ARCHIVE_TRAINING_DATASET_LOGICAL_SHA256_MISMATCH"
        )

    config = preset.comparison_config
    maximum_horizon_ms = max(preset.horizons_ms)
    if config.embargo_anchors * INTERVAL_MS[anchor_interval] < maximum_horizon_ms:
        raise HistoricalArchiveTrainingPlanError(
            "ARCHIVE_TRAINING_EMBARGO_TOO_SHORT"
        )
    (
        fit_rows,
        _embargo_rows,
        calibration_rows,
        fit_anchors,
        embargo_anchors,
        calibration_anchors,
    ) = _partition_rows(
        rows,
        validation_anchors=config.validation_anchors,
        embargo_anchors=config.embargo_anchors,
        min_train_anchors=config.min_train_anchors,
    )

    comparison_config = config.to_dict()
    comparison_config_sha256 = hashlib.sha256(
        _canonical_json(comparison_config).encode("utf-8")
    ).hexdigest()
    return HistoricalArchiveCandidateTrainingPlan(
        preset_name=preset.name,
        preset_id=preset.preset_id,
        evidence_class=preset.evidence_class,
        candidate_id=freeze.candidate_id,
        bundle_id=freeze.bundle_id,
        model_family=freeze.model_family,
        calibration_variant=freeze.calibration_variant,
        qualified_variant_sha256=freeze.qualified_variant_sha256,
        dataset_id=dataset_id,
        dataset_logical_sha256=dataset_logical_sha256,
        dataset_row_count=dataset_row_count,
        anchor_interval=anchor_interval,
        total_anchor_count=len(fit_anchors)
        + len(embargo_anchors)
        + len(calibration_anchors),
        fit_anchor_count=len(fit_anchors),
        fit_row_count=len(fit_rows),
        fit_start_ms=fit_anchors[0],
        fit_end_ms=fit_anchors[-1],
        embargo_anchor_count=len(embargo_anchors),
        embargo_start_ms=embargo_anchors[0],
        embargo_end_ms=embargo_anchors[-1],
        calibration_anchor_count=len(calibration_anchors),
        calibration_row_count=len(calibration_rows),
        calibration_start_ms=calibration_anchors[0],
        calibration_end_ms=calibration_anchors[-1],
        maximum_horizon_ms=maximum_horizon_ms,
        comparison_config_sha256=comparison_config_sha256,
        comparison_config=comparison_config,
        selection_algorithm=_selection_algorithm(freeze),
        validation_not_before_ms=freeze.validation_not_before_ms,
    )


def write_archive_candidate_training_plan(
    output_root: Path,
    plan: HistoricalArchiveCandidateTrainingPlan,
) -> Path:
    path = output_root / "candidate-training-plan.json"
    payload = (_canonical_json(plan.to_dict()) + "\n").encode("utf-8")
    if path.exists():
        if path.read_bytes() != payload:
            raise HistoricalArchiveTrainingPlanError(
                "ARCHIVE_TRAINING_PLAN_CONFLICT"
            )
        return path

    temporary = output_root / ".candidate-training-plan.json.tmp"
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


def verify_archive_candidate_training_plan(
    path: Path,
    *,
    preset: HistoricalArchiveExperimentPreset,
    archive_root: Path,
    source_root: Path,
    output_root: Path,
) -> HistoricalArchiveCandidateTrainingPlan:
    try:
        raw = _mapping(
            json.loads(path.read_text(encoding="utf-8")),
            "archive candidate training plan",
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise HistoricalArchiveTrainingPlanError(
            "ARCHIVE_TRAINING_PLAN_INVALID"
        ) from exc

    expected = build_archive_candidate_training_plan(
        preset,
        archive_root=archive_root,
        source_root=source_root,
        output_root=output_root,
    )
    expected_payload = expected.to_dict()
    if raw != expected_payload:
        raise HistoricalArchiveTrainingPlanError(
            "ARCHIVE_TRAINING_PLAN_EVIDENCE_MISMATCH"
        )
    canonical = _canonical_json(expected_payload) + "\n"
    if path.read_text(encoding="utf-8") != canonical:
        raise HistoricalArchiveTrainingPlanError(
            "ARCHIVE_TRAINING_PLAN_NON_CANONICAL"
        )
    return expected
