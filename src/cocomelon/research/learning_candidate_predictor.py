from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from cocomelon.research.learning_candidate_package import (
    LearningCandidatePackage,
    verify_learning_candidate_package,
)
from cocomelon.research.learning_challenger_run import (
    LearningChallengerRunManifest,
    load_learning_challenger_run_manifest,
)
from cocomelon.research.learning_clean_validation_spec import (
    LearningCleanValidationSpec,
    verify_learning_clean_validation_spec,
)
from cocomelon.research.learning_grouped_mean import (
    GROUPED_MEAN_MODEL_FAMILY,
    _config_from_manifest as _grouped_config_from_manifest,
)
from cocomelon.research.learning_training_bundle import (
    VerifiedLearningTrainingBundle,
    verify_learning_training_bundle,
)
from cocomelon.research.learning_training_rows import LearningTrainingRow
from cocomelon.research.learning_tree import (
    TREE_MODEL_FAMILY,
    LearningTreeEncoder,
    _config_from_manifest as _tree_config_from_manifest,
    _encoder as _tree_encoder,
    _fit_estimator as _fit_tree_estimator,
)

LEARNING_CANDIDATE_PREDICTION_SCHEMA_VERSION = 1


class LearningCandidatePredictorError(RuntimeError):
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


def _mapping(value: object, field_name: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise LearningCandidatePredictorError(
            f"{field_name} must be a JSON object"
        )
    return cast(dict[str, object], value)


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise LearningCandidatePredictorError(f"{field_name} must be an integer")
    return value


def _string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LearningCandidatePredictorError(
            f"{field_name} must be a non-empty string"
        )
    return value


def _ordered_rows(
    bundle: VerifiedLearningTrainingBundle,
) -> tuple[LearningTrainingRow, ...]:
    return tuple(
        sorted(
            bundle.training_set.rows,
            key=lambda row: (
                row.opened_at_ms,
                row.closed_at_ms,
                row.source_record_id,
            ),
        )
    )


def _training_partition(
    bundle: VerifiedLearningTrainingBundle,
    *,
    validation_rows: int,
    min_train_rows: int,
) -> tuple[tuple[LearningTrainingRow, ...], int]:
    ordered = _ordered_rows(bundle)
    if len(ordered) <= validation_rows:
        raise LearningCandidatePredictorError(
            "LEARNING_CANDIDATE_PREDICTOR_INSUFFICIENT_ROWS"
        )
    validation = ordered[-validation_rows:]
    validation_start = validation[0].opened_at_ms
    prefix = ordered[:-validation_rows]
    train = tuple(row for row in prefix if row.closed_at_ms < validation_start)
    if len(train) < min_train_rows:
        raise LearningCandidatePredictorError(
            "LEARNING_CANDIDATE_PREDICTOR_INSUFFICIENT_SETTLED_TRAIN_ROWS"
        )
    return train, validation_start


def _verify_runtime_partition(
    *,
    experiment_root: Path,
    package: LearningCandidatePackage,
    train_row_count: int,
    validation_rows: int,
    validation_start_ms: int,
) -> None:
    try:
        raw = _mapping(
            json.loads((experiment_root / "evaluation.json").read_text(encoding="utf-8")),
            "learning experiment evaluation",
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise LearningCandidatePredictorError(
            "LEARNING_CANDIDATE_PREDICTOR_EVALUATION_INVALID"
        ) from exc
    if _string(raw.get("run_id"), "evaluation run_id") != package.run_id:
        raise LearningCandidatePredictorError(
            "LEARNING_CANDIDATE_PREDICTOR_RUN_MISMATCH"
        )
    if (
        _string(raw.get("training_bundle_id"), "evaluation training_bundle_id")
        != package.training_bundle_id
    ):
        raise LearningCandidatePredictorError(
            "LEARNING_CANDIDATE_PREDICTOR_BUNDLE_MISMATCH"
        )
    if _string(raw.get("model_family"), "evaluation model_family") != package.model_family:
        raise LearningCandidatePredictorError(
            "LEARNING_CANDIDATE_PREDICTOR_MODEL_MISMATCH"
        )
    if _integer(raw.get("train_row_count"), "evaluation train_row_count") != train_row_count:
        raise LearningCandidatePredictorError(
            "LEARNING_CANDIDATE_PREDICTOR_TRAIN_PARTITION_MISMATCH"
        )
    if _integer(raw.get("validation_row_count"), "evaluation validation_row_count") != validation_rows:
        raise LearningCandidatePredictorError(
            "LEARNING_CANDIDATE_PREDICTOR_VALIDATION_PARTITION_MISMATCH"
        )
    if (
        _integer(
            raw.get("validation_start_opened_at_ms"),
            "evaluation validation_start_opened_at_ms",
        )
        != validation_start_ms
    ):
        raise LearningCandidatePredictorError(
            "LEARNING_CANDIDATE_PREDICTOR_VALIDATION_BOUNDARY_MISMATCH"
        )


@dataclass(frozen=True, slots=True)
class LearningCandidatePrediction:
    candidate_id: str
    validation_spec_id: str
    candidate_package_id: str
    experiment_id: str
    model_family: str
    observed_at_ms: int
    feature_registry: tuple[str, ...]
    feature_values: tuple[str, ...]
    predicted_net_r: Decimal | None
    prediction_threshold: Decimal
    trade_eligible: bool
    reason_code: str
    paper_only: bool = True
    research_only: bool = True
    promotion_eligible: bool = False
    execution_ready: bool = False
    schema_version: int = LEARNING_CANDIDATE_PREDICTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field_name in (
            "candidate_id",
            "validation_spec_id",
            "candidate_package_id",
            "experiment_id",
        ):
            value = getattr(self, field_name)
            if len(value) != 64:
                raise ValueError(f"{field_name} must be SHA-256")
        if not self.model_family.strip():
            raise ValueError("model_family must not be empty")
        if self.observed_at_ms < 0:
            raise ValueError("observed_at_ms must be non-negative")
        if not self.feature_registry:
            raise ValueError("feature_registry must not be empty")
        if len(self.feature_registry) != len(self.feature_values):
            raise ValueError("feature values must align with registry")
        if any(not value.strip() for value in self.feature_values):
            raise ValueError("feature values must not be empty")
        if self.predicted_net_r is not None and not self.predicted_net_r.is_finite():
            raise ValueError("predicted_net_r must be finite")
        if not self.prediction_threshold.is_finite():
            raise ValueError("prediction_threshold must be finite")
        expected_eligible = (
            self.predicted_net_r is not None
            and self.predicted_net_r >= self.prediction_threshold
        )
        if self.trade_eligible != expected_eligible:
            raise ValueError("trade_eligible does not match frozen threshold")
        expected_reason = (
            "prediction_not_available"
            if self.predicted_net_r is None
            else (
                "prediction_meets_threshold"
                if self.trade_eligible
                else "prediction_below_threshold"
            )
        )
        if self.reason_code != expected_reason:
            raise ValueError("prediction reason code is inconsistent")
        if not self.paper_only or not self.research_only:
            raise ValueError("learning candidate prediction must remain paper research")
        if self.promotion_eligible or self.execution_ready:
            raise ValueError("prediction cannot authorize promotion or execution")
        if self.schema_version != LEARNING_CANDIDATE_PREDICTION_SCHEMA_VERSION:
            raise ValueError("unsupported learning candidate prediction schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "validation_spec_id": self.validation_spec_id,
            "candidate_package_id": self.candidate_package_id,
            "experiment_id": self.experiment_id,
            "model_family": self.model_family,
            "observed_at_ms": self.observed_at_ms,
            "feature_registry": self.feature_registry,
            "feature_values": self.feature_values,
            "predicted_net_r": (
                None if self.predicted_net_r is None else str(self.predicted_net_r)
            ),
            "prediction_threshold": str(self.prediction_threshold),
            "trade_eligible": self.trade_eligible,
            "reason_code": self.reason_code,
            "paper_only": self.paper_only,
            "research_only": self.research_only,
            "promotion_eligible": self.promotion_eligible,
            "execution_ready": self.execution_ready,
            "schema_version": self.schema_version,
        }

    @property
    def prediction_id(self) -> str:
        return _sha256_json(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "prediction_id": self.prediction_id}


@dataclass(slots=True)
class LearningCandidatePredictor:
    package: LearningCandidatePackage
    spec: LearningCleanValidationSpec
    manifest: LearningChallengerRunManifest
    prediction_threshold: Decimal
    grouped_means: dict[tuple[str, ...], Decimal] | None = field(
        default=None,
        repr=False,
    )
    tree_encoder: LearningTreeEncoder | None = field(default=None, repr=False)
    tree_estimator: Any | None = field(default=None, repr=False)

    @property
    def feature_registry(self) -> tuple[str, ...]:
        return self.manifest.feature_registry

    def score(
        self,
        *,
        feature_values: tuple[str, ...],
        observed_at_ms: int,
    ) -> LearningCandidatePrediction:
        if observed_at_ms < self.spec.validation_start_ms:
            raise LearningCandidatePredictorError(
                "LEARNING_CANDIDATE_PREDICTION_BEFORE_VALIDATION_START"
            )
        if len(feature_values) != len(self.feature_registry):
            raise LearningCandidatePredictorError(
                "LEARNING_CANDIDATE_FEATURE_VALUES_MISMATCH"
            )
        if any(not value.strip() for value in feature_values):
            raise LearningCandidatePredictorError(
                "LEARNING_CANDIDATE_FEATURE_VALUE_EMPTY"
            )

        prediction: Decimal | None
        if self.package.model_family == GROUPED_MEAN_MODEL_FAMILY:
            if self.grouped_means is None:
                raise LearningCandidatePredictorError(
                    "LEARNING_CANDIDATE_GROUPED_MODEL_MISSING"
                )
            prediction = self.grouped_means.get(feature_values)
        elif self.package.model_family == TREE_MODEL_FAMILY:
            if self.tree_encoder is None or self.tree_estimator is None:
                raise LearningCandidatePredictorError(
                    "LEARNING_CANDIDATE_TREE_MODEL_MISSING"
                )
            vector = self.tree_encoder.vector_values(feature_values)
            raw = self.tree_estimator.predict([vector])
            if len(raw) != 1:
                raise LearningCandidatePredictorError(
                    "LEARNING_CANDIDATE_TREE_PREDICTION_SHAPE_INVALID"
                )
            resolved = float(raw[0])
            if not math.isfinite(resolved):
                raise LearningCandidatePredictorError(
                    "LEARNING_CANDIDATE_TREE_PREDICTION_NOT_FINITE"
                )
            prediction = Decimal(str(resolved))
        else:
            raise LearningCandidatePredictorError(
                "LEARNING_CANDIDATE_MODEL_FAMILY_UNSUPPORTED"
            )

        eligible = (
            prediction is not None
            and prediction >= self.prediction_threshold
        )
        reason = (
            "prediction_not_available"
            if prediction is None
            else (
                "prediction_meets_threshold"
                if eligible
                else "prediction_below_threshold"
            )
        )
        return LearningCandidatePrediction(
            candidate_id=self.package.candidate_id,
            validation_spec_id=self.spec.spec_id,
            candidate_package_id=self.package.package_id,
            experiment_id=self.package.experiment_id,
            model_family=self.package.model_family,
            observed_at_ms=observed_at_ms,
            feature_registry=self.feature_registry,
            feature_values=feature_values,
            predicted_net_r=prediction,
            prediction_threshold=self.prediction_threshold,
            trade_eligible=eligible,
            reason_code=reason,
        )


def build_learning_candidate_predictor(
    *,
    package_root: Path,
    validation_spec_path: Path,
) -> LearningCandidatePredictor:
    package = verify_learning_candidate_package(package_root)
    spec = verify_learning_clean_validation_spec(
        validation_spec_path,
        package_root=package_root,
    )
    experiment_root = package_root / "experiment"
    manifest = load_learning_challenger_run_manifest(
        experiment_root / "challenger-run.json"
    )
    bundle = verify_learning_training_bundle(
        output_dir=experiment_root / "training",
        manifest=manifest,
    )
    if manifest.run_id != package.run_id:
        raise LearningCandidatePredictorError(
            "LEARNING_CANDIDATE_MANIFEST_RUN_MISMATCH"
        )
    if manifest.model_family != package.model_family:
        raise LearningCandidatePredictorError(
            "LEARNING_CANDIDATE_MANIFEST_MODEL_MISMATCH"
        )

    if package.model_family == GROUPED_MEAN_MODEL_FAMILY:
        config, policy = _grouped_config_from_manifest(manifest)
        train, validation_start = _training_partition(
            bundle,
            validation_rows=config.validation_rows,
            min_train_rows=config.min_train_rows,
        )
        grouped_targets: dict[tuple[str, ...], list[Decimal]] = {}
        for row in train:
            grouped_targets.setdefault(row.feature_values, []).append(row.target_value)
        group_means = {
            values_key: sum(values, Decimal("0")) / Decimal(len(values))
            for values_key, values in grouped_targets.items()
            if len(values) >= config.min_group_train_rows
        }
        _verify_runtime_partition(
            experiment_root=experiment_root,
            package=package,
            train_row_count=len(train),
            validation_rows=config.validation_rows,
            validation_start_ms=validation_start,
        )
        return LearningCandidatePredictor(
            package=package,
            spec=spec,
            manifest=manifest,
            prediction_threshold=policy.prediction_threshold,
            grouped_means=group_means,
        )

    if package.model_family == TREE_MODEL_FAMILY:
        config, policy = _tree_config_from_manifest(manifest)
        train, validation_start = _training_partition(
            bundle,
            validation_rows=config.validation_rows,
            min_train_rows=config.min_train_rows,
        )
        encoder = _tree_encoder(train, bundle.training_set.feature_registry)
        estimator = _fit_tree_estimator(train, encoder, config)
        _verify_runtime_partition(
            experiment_root=experiment_root,
            package=package,
            train_row_count=len(train),
            validation_rows=config.validation_rows,
            validation_start_ms=validation_start,
        )
        return LearningCandidatePredictor(
            package=package,
            spec=spec,
            manifest=manifest,
            prediction_threshold=policy.prediction_threshold,
            tree_encoder=encoder,
            tree_estimator=estimator,
        )

    raise LearningCandidatePredictorError(
        "LEARNING_CANDIDATE_MODEL_FAMILY_UNSUPPORTED"
    )
