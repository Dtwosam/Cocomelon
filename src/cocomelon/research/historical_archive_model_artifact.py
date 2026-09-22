from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from cocomelon.domain.features import TrendRegime
from cocomelon.research.historical_archive_final_calibration import (
    verify_archive_final_calibration,
)
from cocomelon.research.historical_archive_presets import (
    EVIDENCE_CLASS,
    HistoricalArchiveExperimentPreset,
)
from cocomelon.research.historical_archive_training_plan import (
    materialize_archive_candidate_training_rows,
    verify_archive_candidate_training_plan,
)
from cocomelon.research.historical_features import HistoricalFeatureRow
from cocomelon.research.historical_ridge import (
    NUMERIC_FEATURES,
    RidgeDirectionalModel,
    fit_ridge_directional_model,
)
from cocomelon.research.historical_tree import (
    TreeDirectionalModel,
    fit_tree_directional_model,
)

MODEL_ARTIFACT_SCHEMA_VERSION = 1
RIDGE_MODEL_FORMAT = "ridge-directional-json-v1"
TREE_MODEL_FORMAT = "hist-gradient-boosting-json-v1"
TREND_REGIMES = tuple(TrendRegime)
RIDGE_FAMILIES = {
    "stable_horizon_ridge",
    "occupancy_stable_ridge",
    "portfolio_capacity_stable_ridge",
}


class HistoricalArchiveModelArtifactError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _require_sha256(value: str, field: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} must be lowercase SHA-256")


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise HistoricalArchiveModelArtifactError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _sequence(value: object, field: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise HistoricalArchiveModelArtifactError(f"{field} must be an array")
    return tuple(value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalArchiveModelArtifactError(
            f"{field} must be a non-empty string"
        )
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise HistoricalArchiveModelArtifactError(f"{field} must be an integer")
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise HistoricalArchiveModelArtifactError(f"{field} must be boolean")
    return value


def _optional_integer(value: object, field: str) -> int | None:
    if value is None:
        return None
    return _integer(value, field)


def _optional_decimal(value: object, field: str) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise HistoricalArchiveModelArtifactError(f"{field} must be decimal string")
    resolved = Decimal(value)
    if not resolved.is_finite():
        raise HistoricalArchiveModelArtifactError(f"{field} must be finite")
    return resolved


def _tuple_sequences(value: object) -> object:
    if isinstance(value, list):
        return tuple(_tuple_sequences(item) for item in value)
    if isinstance(value, dict):
        return {
            key: _tuple_sequences(item)
            for key, item in value.items()
        }
    return value


def _finite_float(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HistoricalArchiveModelArtifactError(f"{field} must be numeric")
    resolved = float(value)
    if not math.isfinite(resolved):
        raise HistoricalArchiveModelArtifactError(f"{field} must be finite")
    return resolved


@dataclass(frozen=True, slots=True)
class HistoricalArchiveCandidateModelArtifact:
    preset_name: str
    preset_id: str
    evidence_class: str
    candidate_id: str
    training_plan_id: str
    calibration_id: str
    bundle_id: str
    dataset_id: str
    model_family: str
    calibration_variant: str
    model_format: str
    model_payload: dict[str, object]
    model_payload_sha256: str
    selected_candidate_sha256: str
    selected_alpha: Decimal | None
    selected_horizon_thresholds: tuple[tuple[int, Decimal | None], ...]
    allow_coin_calibration: bool
    min_sample_count: int
    min_market_samples: int
    execution_policy: str
    max_concurrent_positions: int | None
    costs: dict[str, str]
    numpy_version: str
    scikit_learn_version: str
    validation_not_before_ms: int
    prospective_only: bool = True
    promotion_eligible: bool = False
    trained_model_persisted: bool = True
    execution_ready: bool = False
    schema_version: int = MODEL_ARTIFACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in (
            "preset_name",
            "preset_id",
            "candidate_id",
            "training_plan_id",
            "calibration_id",
            "bundle_id",
            "dataset_id",
            "model_family",
            "calibration_variant",
            "model_format",
            "model_payload_sha256",
            "selected_candidate_sha256",
            "execution_policy",
            "numpy_version",
            "scikit_learn_version",
        ):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} must not be empty")
        for field in (
            "candidate_id",
            "training_plan_id",
            "calibration_id",
            "bundle_id",
            "dataset_id",
            "model_payload_sha256",
            "selected_candidate_sha256",
        ):
            _require_sha256(getattr(self, field), field)
        if self.evidence_class != EVIDENCE_CLASS:
            raise ValueError("candidate model artifact evidence must remain touched")
        expected_format = (
            TREE_MODEL_FORMAT
            if self.model_family == "stable_tree"
            else RIDGE_MODEL_FORMAT
        )
        if self.model_format != expected_format:
            raise ValueError("model_format must match model_family")
        if _sha256_json(self.model_payload) != self.model_payload_sha256:
            raise ValueError("model_payload_sha256 must match model_payload")
        payload_format = self.model_payload.get("format")
        if payload_format != self.model_format:
            raise ValueError("embedded model format must match model_format")
        payload_min_market_samples = self.model_payload.get("min_market_samples")
        if (
            isinstance(payload_min_market_samples, bool)
            or not isinstance(payload_min_market_samples, int)
            or payload_min_market_samples != self.min_market_samples
        ):
            raise ValueError(
                "embedded min_market_samples must match artifact metadata"
            )
        if self.model_family in RIDGE_FAMILIES:
            if self.selected_alpha is None:
                raise ValueError("ridge model artifact requires selected_alpha")
            if self.model_payload.get("alpha") != str(self.selected_alpha):
                raise ValueError("embedded ridge alpha must match selected_alpha")
        elif self.model_family == "stable_tree":
            if self.selected_alpha is not None:
                raise ValueError("tree model artifact must not have selected_alpha")
        else:
            raise ValueError("unsupported model_family")
        if not self.selected_horizon_thresholds:
            raise ValueError("selected_horizon_thresholds must not be empty")
        horizons = tuple(item[0] for item in self.selected_horizon_thresholds)
        if horizons != tuple(sorted(set(horizons))):
            raise ValueError("selected horizon thresholds must be sorted unique")
        if not any(
            threshold is not None
            for _horizon_ms, threshold in self.selected_horizon_thresholds
        ):
            raise ValueError("candidate model artifact must trade at least one horizon")
        raw_model_horizons = self.model_payload.get("horizons")
        if not isinstance(raw_model_horizons, (tuple, list)):
            raise ValueError("embedded model horizons must be a sequence")
        model_horizons: list[int] = []
        for item in raw_model_horizons:
            if not isinstance(item, dict):
                raise ValueError("embedded model horizon must be an object")
            value = item.get("horizon_ms")
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError("embedded model horizon_ms must be positive")
            model_horizons.append(value)
        if tuple(model_horizons) != horizons:
            raise ValueError(
                "embedded model horizons must match selected horizon thresholds"
            )
        if self.min_sample_count <= 0 or self.min_market_samples <= 0:
            raise ValueError("sample floors must be positive")
        expected_policy = {
            "stable_horizon_ridge": "independent_horizon",
            "occupancy_stable_ridge": "single_position_occupancy",
            "portfolio_capacity_stable_ridge": "portfolio_capacity",
            "stable_tree": "independent_horizon",
        }[self.model_family]
        if self.execution_policy != expected_policy:
            raise ValueError("execution_policy must match model_family")
        if self.model_family == "portfolio_capacity_stable_ridge":
            if self.max_concurrent_positions is None or self.max_concurrent_positions <= 0:
                raise ValueError("portfolio capacity artifact requires positive capacity")
        elif self.max_concurrent_positions is not None:
            raise ValueError("max_concurrent_positions only applies to capacity family")
        required_costs = {
            "round_trip_fee_fraction",
            "round_trip_slippage_fraction",
            "funding_reserve_fraction_per_hour",
        }
        if set(self.costs) != required_costs:
            raise ValueError("costs must contain the frozen execution cost fields")
        for value in self.costs.values():
            resolved = Decimal(value)
            if not resolved.is_finite() or resolved < 0:
                raise ValueError("cost values must be non-negative finite decimals")
        if self.validation_not_before_ms <= 0:
            raise ValueError("validation_not_before_ms must be positive")
        if not self.prospective_only:
            raise ValueError("candidate model artifact must remain prospective-only")
        if self.promotion_eligible:
            raise ValueError("touched candidate model cannot be promotion eligible")
        if not self.trained_model_persisted:
            raise ValueError("candidate model artifact must persist trained model state")
        if self.execution_ready:
            raise ValueError("candidate model artifact is not execution ready")
        if self.schema_version != MODEL_ARTIFACT_SCHEMA_VERSION:
            raise ValueError("unsupported candidate model artifact schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "preset_name": self.preset_name,
            "preset_id": self.preset_id,
            "evidence_class": self.evidence_class,
            "candidate_id": self.candidate_id,
            "training_plan_id": self.training_plan_id,
            "calibration_id": self.calibration_id,
            "bundle_id": self.bundle_id,
            "dataset_id": self.dataset_id,
            "model_family": self.model_family,
            "calibration_variant": self.calibration_variant,
            "model_format": self.model_format,
            "model_payload": self.model_payload,
            "model_payload_sha256": self.model_payload_sha256,
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
            "allow_coin_calibration": self.allow_coin_calibration,
            "min_sample_count": self.min_sample_count,
            "min_market_samples": self.min_market_samples,
            "execution_policy": self.execution_policy,
            "max_concurrent_positions": self.max_concurrent_positions,
            "costs": self.costs,
            "numpy_version": self.numpy_version,
            "scikit_learn_version": self.scikit_learn_version,
            "validation_not_before_ms": self.validation_not_before_ms,
            "prospective_only": self.prospective_only,
            "promotion_eligible": self.promotion_eligible,
            "trained_model_persisted": self.trained_model_persisted,
            "execution_ready": self.execution_ready,
            "schema_version": self.schema_version,
        }

    @property
    def artifact_id(self) -> str:
        return _sha256_json(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "artifact_id": self.artifact_id}


def _ridge_payload(model: RidgeDirectionalModel) -> dict[str, object]:
    horizons: list[dict[str, object]] = []
    for horizon_ms in sorted(model.horizons):
        fitted = model.horizons[horizon_ms]
        horizons.append(
            {
                "horizon_ms": fitted.horizon_ms,
                "sample_count": fitted.sample_count,
                "means": fitted.transform.means,
                "scales": fitted.transform.scales,
                "market_names": fitted.market_names,
                "shared_coefficients": fitted.shared_coefficients,
                "market_coefficients": fitted.market_coefficients,
            }
        )
    return {
        "format": RIDGE_MODEL_FORMAT,
        "alpha": str(model.alpha),
        "min_market_samples": model.min_market_samples,
        "numeric_features": NUMERIC_FEATURES,
        "trend_regimes": tuple(item.value for item in TREND_REGIMES),
        "horizons": tuple(horizons),
    }


def _tree_nodes(estimator: Any) -> tuple[tuple[dict[str, object], ...], ...]:
    predictors = getattr(estimator, "_predictors", None)
    if not isinstance(predictors, list) or not predictors:
        raise HistoricalArchiveModelArtifactError("TREE_PREDICTORS_MISSING")
    if getattr(estimator, "n_trees_per_iteration_", None) != 1:
        raise HistoricalArchiveModelArtifactError("TREE_MULTI_OUTPUT_UNSUPPORTED")

    trees: list[tuple[dict[str, object], ...]] = []
    for iteration in predictors:
        if not isinstance(iteration, list) or len(iteration) != 1:
            raise HistoricalArchiveModelArtifactError("TREE_ITERATION_INVALID")
        predictor = iteration[0]
        raw_nodes = getattr(predictor, "nodes", None)
        if raw_nodes is None:
            raise HistoricalArchiveModelArtifactError("TREE_NODES_MISSING")
        nodes: list[dict[str, object]] = []
        for raw in raw_nodes:
            if bool(raw["is_categorical"]):
                raise HistoricalArchiveModelArtifactError(
                    "TREE_CATEGORICAL_SPLIT_UNSUPPORTED"
                )
            value = float(raw["value"])
            threshold = float(raw["num_threshold"])
            if not math.isfinite(value) or not math.isfinite(threshold):
                raise HistoricalArchiveModelArtifactError("TREE_NODE_NON_FINITE")
            nodes.append(
                {
                    "value": value,
                    "feature_idx": int(raw["feature_idx"]),
                    "threshold": threshold,
                    "missing_go_to_left": bool(raw["missing_go_to_left"]),
                    "left": int(raw["left"]),
                    "right": int(raw["right"]),
                    "is_leaf": bool(raw["is_leaf"]),
                }
            )
        trees.append(tuple(nodes))
    return tuple(trees)


def _tree_estimator_payload(estimator: Any) -> dict[str, object]:
    baseline = getattr(estimator, "_baseline_prediction", None)
    if baseline is None:
        raise HistoricalArchiveModelArtifactError("TREE_BASELINE_MISSING")
    flattened = baseline.ravel().tolist()
    if len(flattened) != 1:
        raise HistoricalArchiveModelArtifactError("TREE_BASELINE_INVALID")
    baseline_value = float(flattened[0])
    if not math.isfinite(baseline_value):
        raise HistoricalArchiveModelArtifactError("TREE_BASELINE_NON_FINITE")
    return {
        "baseline": baseline_value,
        "trees": _tree_nodes(estimator),
    }


def _tree_payload(model: TreeDirectionalModel) -> dict[str, object]:
    horizons: list[dict[str, object]] = []
    for horizon_ms in sorted(model.horizons):
        fitted = model.horizons[horizon_ms]
        horizons.append(
            {
                "horizon_ms": fitted.horizon_ms,
                "sample_count": fitted.sample_count,
                "numeric_features": fitted.encoder.numeric_features,
                "market_names": fitted.encoder.market_names,
                "shared_estimator": _tree_estimator_payload(
                    fitted.shared_estimator
                ),
                "market_estimator": _tree_estimator_payload(
                    fitted.market_estimator
                ),
            }
        )
    return {
        "format": TREE_MODEL_FORMAT,
        "config": model.config.to_dict(),
        "min_market_samples": model.min_market_samples,
        "trend_regimes": tuple(item.value for item in TREND_REGIMES),
        "horizons": tuple(horizons),
    }


def _cost_payload(preset: HistoricalArchiveExperimentPreset) -> dict[str, str]:
    costs = preset.comparison_config.costs
    return {
        "round_trip_fee_fraction": str(costs.round_trip_fee_fraction),
        "round_trip_slippage_fraction": str(costs.round_trip_slippage_fraction),
        "funding_reserve_fraction_per_hour": str(
            costs.funding_reserve_fraction_per_hour
        ),
    }


def _versions() -> tuple[str, str]:
    return (
        importlib.metadata.version("numpy"),
        importlib.metadata.version("scikit-learn"),
    )


def build_archive_candidate_model_artifact(
    preset: HistoricalArchiveExperimentPreset,
    *,
    archive_root: Path,
    source_root: Path,
    output_root: Path,
) -> HistoricalArchiveCandidateModelArtifact:
    calibration = verify_archive_final_calibration(
        output_root / "candidate-final-calibration.json",
        preset=preset,
        archive_root=archive_root,
        source_root=source_root,
        output_root=output_root,
    )
    plan = verify_archive_candidate_training_plan(
        output_root / "candidate-training-plan.json",
        preset=preset,
        archive_root=archive_root,
        source_root=source_root,
        output_root=output_root,
    )
    if (
        calibration.candidate_id != plan.candidate_id
        or calibration.training_plan_id != plan.plan_id
        or calibration.bundle_id != plan.bundle_id
        or calibration.dataset_id != plan.dataset_id
        or calibration.model_family != plan.model_family
        or calibration.calibration_variant != plan.calibration_variant
        or calibration.validation_not_before_ms != plan.validation_not_before_ms
    ):
        raise HistoricalArchiveModelArtifactError(
            "ARCHIVE_MODEL_ARTIFACT_LINEAGE_MISMATCH"
        )

    fit_rows, _embargo_rows, _calibration_rows = (
        materialize_archive_candidate_training_rows(
            preset,
            source_root=source_root,
            plan=plan,
        )
    )
    config = preset.comparison_config
    if calibration.model_family == "stable_tree":
        tree_model = fit_tree_directional_model(
            fit_rows,
            config=config.tree_config,
            min_market_samples=config.tree_min_market_samples,
        )
        model_payload = _tree_payload(tree_model)
        min_market_samples = config.tree_min_market_samples
        model_format = TREE_MODEL_FORMAT
    else:
        alpha = calibration.selected_alpha
        if alpha is None:
            raise HistoricalArchiveModelArtifactError(
                "ARCHIVE_MODEL_ARTIFACT_RIDGE_ALPHA_REQUIRED"
            )
        ridge_model = fit_ridge_directional_model(
            fit_rows,
            alpha=alpha,
            min_market_samples=config.ridge_min_market_samples,
        )
        model_payload = _ridge_payload(ridge_model)
        min_market_samples = config.ridge_min_market_samples
        model_format = RIDGE_MODEL_FORMAT

    numpy_version, sklearn_version = _versions()
    policy = {
        "stable_horizon_ridge": "independent_horizon",
        "occupancy_stable_ridge": "single_position_occupancy",
        "portfolio_capacity_stable_ridge": "portfolio_capacity",
        "stable_tree": "independent_horizon",
    }[calibration.model_family]
    capacity = (
        config.portfolio_max_concurrent_positions
        if calibration.model_family == "portfolio_capacity_stable_ridge"
        else None
    )
    return HistoricalArchiveCandidateModelArtifact(
        preset_name=preset.name,
        preset_id=preset.preset_id,
        evidence_class=preset.evidence_class,
        candidate_id=calibration.candidate_id,
        training_plan_id=calibration.training_plan_id,
        calibration_id=calibration.calibration_id,
        bundle_id=calibration.bundle_id,
        dataset_id=calibration.dataset_id,
        model_family=calibration.model_family,
        calibration_variant=calibration.calibration_variant,
        model_format=model_format,
        model_payload=model_payload,
        model_payload_sha256=_sha256_json(model_payload),
        selected_candidate_sha256=calibration.selected_candidate_sha256,
        selected_alpha=calibration.selected_alpha,
        selected_horizon_thresholds=calibration.selected_horizon_thresholds,
        allow_coin_calibration=calibration.calibration_variant == "market",
        min_sample_count=config.min_sample_count,
        min_market_samples=min_market_samples,
        execution_policy=policy,
        max_concurrent_positions=capacity,
        costs=_cost_payload(preset),
        numpy_version=numpy_version,
        scikit_learn_version=sklearn_version,
        validation_not_before_ms=calibration.validation_not_before_ms,
    )


def write_archive_candidate_model_artifact(
    output_root: Path,
    artifact: HistoricalArchiveCandidateModelArtifact,
) -> Path:
    path = output_root / "candidate-model.json"
    payload = (_canonical_json(artifact.to_dict()) + "\n").encode("utf-8")
    if path.exists():
        if path.read_bytes() != payload:
            raise HistoricalArchiveModelArtifactError(
                "ARCHIVE_MODEL_ARTIFACT_CONFLICT"
            )
        return path
    temporary = output_root / ".candidate-model.json.tmp"
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


def load_archive_candidate_model_artifact(
    path: Path,
) -> HistoricalArchiveCandidateModelArtifact:
    try:
        raw = _mapping(
            json.loads(path.read_text(encoding="utf-8")),
            "candidate model artifact",
        )
        thresholds = tuple(
            (
                _integer(
                    _mapping(item, "selected horizon threshold").get(
                        "horizon_ms"
                    ),
                    "selected horizon threshold horizon_ms",
                ),
                _optional_decimal(
                    _mapping(item, "selected horizon threshold").get(
                        "threshold"
                    ),
                    "selected horizon threshold threshold",
                ),
            )
            for item in _sequence(
                raw.get("selected_horizon_thresholds"),
                "selected_horizon_thresholds",
            )
        )
        raw_costs = _mapping(raw.get("costs"), "costs")
        costs = {
            key: _string(raw_costs.get(key), f"costs.{key}")
            for key in (
                "round_trip_fee_fraction",
                "round_trip_slippage_fraction",
                "funding_reserve_fraction_per_hour",
            )
        }
        artifact = HistoricalArchiveCandidateModelArtifact(
            preset_name=_string(raw.get("preset_name"), "preset_name"),
            preset_id=_string(raw.get("preset_id"), "preset_id"),
            evidence_class=_string(
                raw.get("evidence_class"),
                "evidence_class",
            ),
            candidate_id=_string(raw.get("candidate_id"), "candidate_id"),
            training_plan_id=_string(
                raw.get("training_plan_id"),
                "training_plan_id",
            ),
            calibration_id=_string(
                raw.get("calibration_id"),
                "calibration_id",
            ),
            bundle_id=_string(raw.get("bundle_id"), "bundle_id"),
            dataset_id=_string(raw.get("dataset_id"), "dataset_id"),
            model_family=_string(raw.get("model_family"), "model_family"),
            calibration_variant=_string(
                raw.get("calibration_variant"),
                "calibration_variant",
            ),
            model_format=_string(raw.get("model_format"), "model_format"),
            model_payload=cast(
                dict[str, object],
                _tuple_sequences(
                    _mapping(
                        raw.get("model_payload"),
                        "model_payload",
                    )
                ),
            ),
            model_payload_sha256=_string(
                raw.get("model_payload_sha256"),
                "model_payload_sha256",
            ),
            selected_candidate_sha256=_string(
                raw.get("selected_candidate_sha256"),
                "selected_candidate_sha256",
            ),
            selected_alpha=_optional_decimal(
                raw.get("selected_alpha"),
                "selected_alpha",
            ),
            selected_horizon_thresholds=thresholds,
            allow_coin_calibration=_boolean(
                raw.get("allow_coin_calibration"),
                "allow_coin_calibration",
            ),
            min_sample_count=_integer(
                raw.get("min_sample_count"),
                "min_sample_count",
            ),
            min_market_samples=_integer(
                raw.get("min_market_samples"),
                "min_market_samples",
            ),
            execution_policy=_string(
                raw.get("execution_policy"),
                "execution_policy",
            ),
            max_concurrent_positions=_optional_integer(
                raw.get("max_concurrent_positions"),
                "max_concurrent_positions",
            ),
            costs=costs,
            numpy_version=_string(
                raw.get("numpy_version"),
                "numpy_version",
            ),
            scikit_learn_version=_string(
                raw.get("scikit_learn_version"),
                "scikit_learn_version",
            ),
            validation_not_before_ms=_integer(
                raw.get("validation_not_before_ms"),
                "validation_not_before_ms",
            ),
            prospective_only=_boolean(
                raw.get("prospective_only"),
                "prospective_only",
            ),
            promotion_eligible=_boolean(
                raw.get("promotion_eligible"),
                "promotion_eligible",
            ),
            trained_model_persisted=_boolean(
                raw.get("trained_model_persisted"),
                "trained_model_persisted",
            ),
            execution_ready=_boolean(
                raw.get("execution_ready"),
                "execution_ready",
            ),
            schema_version=_integer(
                raw.get("schema_version"),
                "schema_version",
            ),
        )
    except (
        OSError,
        json.JSONDecodeError,
        ValueError,
        ArithmeticError,
    ) as exc:
        raise HistoricalArchiveModelArtifactError(
            "ARCHIVE_MODEL_ARTIFACT_INVALID"
        ) from exc

    if _string(raw.get("artifact_id"), "artifact_id") != artifact.artifact_id:
        raise HistoricalArchiveModelArtifactError(
            "ARCHIVE_MODEL_ARTIFACT_ID_MISMATCH"
        )
    canonical = _canonical_json(artifact.to_dict()) + "\n"
    if path.read_text(encoding="utf-8") != canonical:
        raise HistoricalArchiveModelArtifactError(
            "ARCHIVE_MODEL_ARTIFACT_NON_CANONICAL"
        )
    return artifact


def verify_archive_candidate_model_artifact(
    path: Path,
    *,
    preset: HistoricalArchiveExperimentPreset,
    archive_root: Path,
    source_root: Path,
    output_root: Path,
) -> HistoricalArchiveCandidateModelArtifact:
    try:
        loaded = load_archive_candidate_model_artifact(path)
    except HistoricalArchiveModelArtifactError as exc:
        raise HistoricalArchiveModelArtifactError(
            "ARCHIVE_MODEL_ARTIFACT_EVIDENCE_MISMATCH"
        ) from exc
    expected = build_archive_candidate_model_artifact(
        preset,
        archive_root=archive_root,
        source_root=source_root,
        output_root=output_root,
    )
    if loaded != expected:
        raise HistoricalArchiveModelArtifactError(
            "ARCHIVE_MODEL_ARTIFACT_EVIDENCE_MISMATCH"
        )
    return expected


def _ridge_vector(
    feature: HistoricalFeatureRow,
    horizon: dict[str, object],
    *,
    include_market: bool,
) -> tuple[float, ...]:
    means = tuple(
        _finite_float(value, "ridge mean")
        for value in _sequence(horizon.get("means"), "ridge means")
    )
    scales = tuple(
        _finite_float(value, "ridge scale")
        for value in _sequence(horizon.get("scales"), "ridge scales")
    )
    if len(means) != len(NUMERIC_FEATURES) or len(scales) != len(NUMERIC_FEATURES):
        raise HistoricalArchiveModelArtifactError("RIDGE_TRANSFORM_WIDTH_MISMATCH")
    values: list[float] = [1.0]
    missing: list[float] = []
    for index, name in enumerate(NUMERIC_FEATURES):
        raw = getattr(feature, name)
        if raw is None:
            values.append(0.0)
            missing.append(1.0)
        else:
            resolved = float(raw)
            if not math.isfinite(resolved):
                raise HistoricalArchiveModelArtifactError(
                    "RIDGE_FEATURE_NON_FINITE"
                )
            values.append((resolved - means[index]) / scales[index])
            missing.append(0.0)
    values.extend(missing)
    values.extend(
        1.0 if feature.trend_regime is regime else 0.0
        for regime in TREND_REGIMES
    )
    if include_market:
        market_names = tuple(
            _string(item, "ridge market")
            for item in _sequence(horizon.get("market_names"), "ridge markets")
        )
        values.extend(
            1.0 if feature.market.canonical == market else 0.0
            for market in market_names
        )
    return tuple(values)


def _tree_vector(
    feature: HistoricalFeatureRow,
    horizon: dict[str, object],
    *,
    include_market: bool,
) -> tuple[float, ...]:
    numeric_features = tuple(
        _string(item, "tree numeric feature")
        for item in _sequence(
            horizon.get("numeric_features"),
            "tree numeric features",
        )
    )
    values: list[float] = []
    for name in numeric_features:
        raw = getattr(feature, name)
        if raw is None:
            values.append(math.nan)
        else:
            resolved = float(raw)
            if not math.isfinite(resolved):
                raise HistoricalArchiveModelArtifactError(
                    "TREE_FEATURE_NON_FINITE"
                )
            values.append(resolved)
    values.extend(
        1.0 if feature.trend_regime is regime else 0.0
        for regime in TREND_REGIMES
    )
    if include_market:
        market_names = tuple(
            _string(item, "tree market")
            for item in _sequence(horizon.get("market_names"), "tree markets")
        )
        values.extend(
            1.0 if feature.market.canonical == market else 0.0
            for market in market_names
        )
    return tuple(values)


def _tree_estimator_predict(
    estimator: dict[str, object],
    vector: tuple[float, ...],
) -> float:
    value = _finite_float(estimator.get("baseline"), "tree baseline")
    raw_trees = _sequence(estimator.get("trees"), "tree estimators")
    for raw_tree in raw_trees:
        nodes = tuple(
            _mapping(item, "tree node")
            for item in _sequence(raw_tree, "tree nodes")
        )
        if not nodes:
            raise HistoricalArchiveModelArtifactError("TREE_NODES_EMPTY")
        index = 0
        steps = 0
        while True:
            if index < 0 or index >= len(nodes):
                raise HistoricalArchiveModelArtifactError(
                    "TREE_NODE_INDEX_OUT_OF_RANGE"
                )
            node = nodes[index]
            if _boolean(node.get("is_leaf"), "tree node is_leaf"):
                value += _finite_float(node.get("value"), "tree leaf value")
                break
            feature_idx = _integer(node.get("feature_idx"), "tree feature_idx")
            if feature_idx < 0 or feature_idx >= len(vector):
                raise HistoricalArchiveModelArtifactError(
                    "TREE_FEATURE_INDEX_OUT_OF_RANGE"
                )
            observed = vector[feature_idx]
            go_left = (
                _boolean(
                    node.get("missing_go_to_left"),
                    "tree missing_go_to_left",
                )
                if math.isnan(observed)
                else observed <= _finite_float(
                    node.get("threshold"),
                    "tree threshold",
                )
            )
            index = _integer(
                node.get("left" if go_left else "right"),
                "tree child index",
            )
            steps += 1
            if steps > len(nodes):
                raise HistoricalArchiveModelArtifactError("TREE_CYCLE_DETECTED")
    if not math.isfinite(value):
        raise HistoricalArchiveModelArtifactError("TREE_PREDICTION_NON_FINITE")
    return value


def predict_archive_candidate_model(
    artifact: HistoricalArchiveCandidateModelArtifact,
    feature: HistoricalFeatureRow,
    *,
    horizon_ms: int,
) -> Decimal:
    raw_horizons = _sequence(
        artifact.model_payload.get("horizons"),
        "model horizons",
    )
    horizon = next(
        (
            _mapping(item, "model horizon")
            for item in raw_horizons
            if _integer(
                _mapping(item, "model horizon").get("horizon_ms"),
                "horizon_ms",
            )
            == horizon_ms
        ),
        None,
    )
    if horizon is None:
        raise HistoricalArchiveModelArtifactError(
            "ARCHIVE_MODEL_ARTIFACT_HORIZON_MISSING"
        )

    market_names = tuple(
        _string(item, "model market")
        for item in _sequence(horizon.get("market_names"), "model markets")
    )
    use_market = (
        artifact.allow_coin_calibration
        and feature.market.canonical in market_names
    )
    if artifact.model_format == RIDGE_MODEL_FORMAT:
        vector = _ridge_vector(feature, horizon, include_market=use_market)
        field = "market_coefficients" if use_market else "shared_coefficients"
        coefficients = tuple(
            _finite_float(item, field)
            for item in _sequence(horizon.get(field), field)
        )
        if len(coefficients) != len(vector):
            raise HistoricalArchiveModelArtifactError(
                "RIDGE_COEFFICIENT_WIDTH_MISMATCH"
            )
        predicted = sum(
            coefficient * value
            for coefficient, value in zip(coefficients, vector, strict=True)
        )
    elif artifact.model_format == TREE_MODEL_FORMAT:
        vector = _tree_vector(feature, horizon, include_market=use_market)
        field = "market_estimator" if use_market else "shared_estimator"
        predicted = _tree_estimator_predict(
            _mapping(horizon.get(field), field),
            vector,
        )
    else:
        raise HistoricalArchiveModelArtifactError(
            "ARCHIVE_MODEL_ARTIFACT_FORMAT_UNSUPPORTED"
        )

    if not math.isfinite(predicted):
        raise HistoricalArchiveModelArtifactError(
            "ARCHIVE_MODEL_ARTIFACT_PREDICTION_NON_FINITE"
        )
    return Decimal(str(predicted))
