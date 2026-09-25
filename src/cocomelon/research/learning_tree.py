from __future__ import annotations

import hashlib
import importlib
import json
import math
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, cast

from cocomelon.research.learning_challenger_run import LearningChallengerRunManifest
from cocomelon.research.learning_training_bundle import VerifiedLearningTrainingBundle
from cocomelon.research.learning_training_rows import LearningTrainingRow

TREE_MODEL_FAMILY = "fixed_shallow_tree"
TREE_EVALUATION_SCHEMA_VERSION = 1
ZERO = Decimal("0")
CATEGORICAL_FEATURES = frozenset(
    {
        "market",
        "direction",
        "context_state_1h",
        "source_evidence_class",
        "candidate_id",
        "candidate_spec_id",
        "campaign_id",
        "trend_regime",
        "volatility_regime",
    }
)


class LearningTreeError(RuntimeError):
    pass


class LearningTreeDependencyError(RuntimeError):
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


def _hist_gradient_boosting_regressor() -> Any:
    try:
        ensemble = importlib.import_module("sklearn.ensemble")
    except ModuleNotFoundError as exc:
        raise LearningTreeDependencyError(
            "scikit-learn is required for learning tree research; "
            "install the research extra"
        ) from exc
    return ensemble.HistGradientBoostingRegressor


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise LearningTreeError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise LearningTreeError(f"{field} must be an integer")
    return value


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise LearningTreeError(f"{field} must be a decimal string")
    try:
        resolved = Decimal(value)
    except InvalidOperation as exc:
        raise LearningTreeError(f"{field} must be a decimal string") from exc
    if not resolved.is_finite():
        raise LearningTreeError(f"{field} must be finite")
    return resolved


def _numeric_value(value: str, feature: str) -> float:
    try:
        resolved = float(Decimal(value))
    except InvalidOperation as exc:
        raise LearningTreeError(
            f"numeric feature {feature} must be a decimal string"
        ) from exc
    if not math.isfinite(resolved):
        raise LearningTreeError(f"numeric feature {feature} must be finite")
    return resolved


@dataclass(frozen=True, slots=True)
class LearningTreeConfig:
    min_train_rows: int
    validation_rows: int
    max_leaf_nodes: int
    min_samples_leaf: int
    learning_rate: Decimal
    max_iter: int
    l2_regularization: Decimal

    def __post_init__(self) -> None:
        if self.min_train_rows <= 0:
            raise ValueError("min_train_rows must be positive")
        if self.validation_rows <= 0:
            raise ValueError("validation_rows must be positive")
        if self.max_leaf_nodes < 2:
            raise ValueError("max_leaf_nodes must be at least 2")
        if self.min_samples_leaf <= 0:
            raise ValueError("min_samples_leaf must be positive")
        if not self.learning_rate.is_finite() or self.learning_rate <= ZERO:
            raise ValueError("learning_rate must be positive and finite")
        if self.max_iter <= 0:
            raise ValueError("max_iter must be positive")
        if (
            not self.l2_regularization.is_finite()
            or self.l2_regularization < ZERO
        ):
            raise ValueError("l2_regularization must be non-negative and finite")

    def to_dict(self) -> dict[str, object]:
        return {
            "min_train_rows": self.min_train_rows,
            "validation_rows": self.validation_rows,
            "max_leaf_nodes": self.max_leaf_nodes,
            "min_samples_leaf": self.min_samples_leaf,
            "learning_rate": str(self.learning_rate),
            "max_iter": self.max_iter,
            "l2_regularization": str(self.l2_regularization),
            "early_stopping": False,
        }


@dataclass(frozen=True, slots=True)
class LearningTreeDecisionPolicy:
    prediction_threshold: Decimal
    stability_blocks: int
    min_block_trades: int
    min_validation_trades: int
    min_validation_mean_target: Decimal

    def __post_init__(self) -> None:
        if not self.prediction_threshold.is_finite():
            raise ValueError("prediction_threshold must be finite")
        if self.stability_blocks <= 0:
            raise ValueError("stability_blocks must be positive")
        if self.min_block_trades <= 0:
            raise ValueError("min_block_trades must be positive")
        if self.min_validation_trades <= 0:
            raise ValueError("min_validation_trades must be positive")
        if not self.min_validation_mean_target.is_finite():
            raise ValueError("min_validation_mean_target must be finite")

    def to_dict(self) -> dict[str, object]:
        return {
            "prediction_threshold": str(self.prediction_threshold),
            "stability_blocks": self.stability_blocks,
            "min_block_trades": self.min_block_trades,
            "min_validation_trades": self.min_validation_trades,
            "min_validation_mean_target": str(
                self.min_validation_mean_target
            ),
        }


@dataclass(frozen=True, slots=True)
class LearningTreeEncoder:
    feature_registry: tuple[str, ...]
    categories: tuple[tuple[str, tuple[str, ...]], ...]

    def __post_init__(self) -> None:
        category_names = tuple(name for name, _values in self.categories)
        expected = tuple(
            feature
            for feature in self.feature_registry
            if feature in CATEGORICAL_FEATURES
        )
        if category_names != expected:
            raise ValueError("tree categorical encodings must preserve feature order")
        for _name, values in self.categories:
            if tuple(sorted(set(values))) != values:
                raise ValueError("tree categorical values must be sorted and unique")

    @property
    def category_map(self) -> dict[str, tuple[str, ...]]:
        return dict(self.categories)

    def vector_values(
        self,
        feature_values: tuple[str, ...],
    ) -> tuple[float, ...]:
        if len(feature_values) != len(self.feature_registry):
            raise LearningTreeError(
                "tree feature values must align with frozen registry"
            )
        category_map = self.category_map
        output: list[float] = []
        for feature, value in zip(
            self.feature_registry,
            feature_values,
            strict=True,
        ):
            categories = category_map.get(feature)
            if categories is None:
                output.append(_numeric_value(value, feature))
                continue
            output.extend(1.0 if value == category else 0.0 for category in categories)
        return tuple(output)

    def vector(self, row: LearningTrainingRow) -> tuple[float, ...]:
        if row.feature_registry != self.feature_registry:
            raise LearningTreeError(
                "tree row feature registry does not match encoder"
            )
        return self.vector_values(row.feature_values)

    def to_dict(self) -> dict[str, object]:
        return {
            "feature_registry": self.feature_registry,
            "categories": self.categories,
        }


@dataclass(frozen=True, slots=True)
class LearningTreeSummary:
    row_count: int
    trade_count: int
    no_trade_count: int
    total_target: Decimal
    mean_target: Decimal | None

    def __post_init__(self) -> None:
        if min(self.row_count, self.trade_count, self.no_trade_count) < 0:
            raise ValueError("tree evaluation counts must be non-negative")
        if self.trade_count + self.no_trade_count != self.row_count:
            raise ValueError("tree trade/no-trade counts must cover rows")
        if self.trade_count == 0 and self.mean_target is not None:
            raise ValueError("mean_target must be None when no trades qualify")
        if self.trade_count > 0 and self.mean_target is None:
            raise ValueError("mean_target is required when trades qualify")

    def to_dict(self) -> dict[str, object]:
        return {
            "row_count": self.row_count,
            "trade_count": self.trade_count,
            "no_trade_count": self.no_trade_count,
            "total_target": str(self.total_target),
            "mean_target": (
                None if self.mean_target is None else str(self.mean_target)
            ),
        }


@dataclass(frozen=True, slots=True)
class LearningTreeBlock:
    block_index: int
    start_opened_at_ms: int
    end_opened_at_ms: int
    summary: LearningTreeSummary

    def to_dict(self) -> dict[str, object]:
        return {
            "block_index": self.block_index,
            "start_opened_at_ms": self.start_opened_at_ms,
            "end_opened_at_ms": self.end_opened_at_ms,
            "summary": self.summary.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class LearningTreeEvaluation:
    run_id: str
    training_bundle_id: str
    training_set_id: str
    dataset_lineage_id: str
    model_family: str
    model_config: LearningTreeConfig
    decision_policy: LearningTreeDecisionPolicy
    encoder: LearningTreeEncoder
    train_row_count: int
    validation_row_count: int
    overlap_excluded_count: int
    validation_start_opened_at_ms: int
    validation_end_opened_at_ms: int
    prediction_sha256: str
    overall: LearningTreeSummary
    blocks: tuple[LearningTreeBlock, ...]
    qualifies_development: bool
    research_only: bool = True
    promotion_eligible: bool = False
    execution_ready: bool = False
    schema_version: int = TREE_EVALUATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.model_family != TREE_MODEL_FAMILY:
            raise ValueError("unsupported learning tree model family")
        if min(
            self.train_row_count,
            self.validation_row_count,
            self.overlap_excluded_count,
        ) < 0:
            raise ValueError("tree evaluation counts must be non-negative")
        if self.validation_row_count <= 0:
            raise ValueError("validation_row_count must be positive")
        if len(self.prediction_sha256) != 64:
            raise ValueError("prediction_sha256 must be a SHA-256 identity")
        if len(self.blocks) != self.decision_policy.stability_blocks:
            raise ValueError("tree block count must match decision policy")
        if not self.research_only:
            raise ValueError("learning tree evaluation must remain research-only")
        if self.promotion_eligible or self.execution_ready:
            raise ValueError("learning tree cannot authorize promotion/execution")
        if self.schema_version != TREE_EVALUATION_SCHEMA_VERSION:
            raise ValueError("unsupported learning tree evaluation schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "training_bundle_id": self.training_bundle_id,
            "training_set_id": self.training_set_id,
            "dataset_lineage_id": self.dataset_lineage_id,
            "model_family": self.model_family,
            "model_config": self.model_config.to_dict(),
            "model_config_id": _sha256_json(self.model_config.to_dict()),
            "decision_policy": self.decision_policy.to_dict(),
            "decision_policy_id": _sha256_json(self.decision_policy.to_dict()),
            "encoder": self.encoder.to_dict(),
            "encoder_id": _sha256_json(self.encoder.to_dict()),
            "train_row_count": self.train_row_count,
            "validation_row_count": self.validation_row_count,
            "overlap_excluded_count": self.overlap_excluded_count,
            "validation_start_opened_at_ms": self.validation_start_opened_at_ms,
            "validation_end_opened_at_ms": self.validation_end_opened_at_ms,
            "prediction_sha256": self.prediction_sha256,
            "overall": self.overall.to_dict(),
            "blocks": tuple(block.to_dict() for block in self.blocks),
            "qualifies_development": self.qualifies_development,
            "research_only": self.research_only,
            "promotion_eligible": self.promotion_eligible,
            "execution_ready": self.execution_ready,
            "schema_version": self.schema_version,
        }

    @property
    def evaluation_id(self) -> str:
        return _sha256_json(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "evaluation_id": self.evaluation_id}


def _config_from_manifest(
    manifest: LearningChallengerRunManifest,
) -> tuple[LearningTreeConfig, LearningTreeDecisionPolicy]:
    if manifest.model_family != TREE_MODEL_FAMILY:
        raise LearningTreeError("LEARNING_TREE_MODEL_FAMILY_MISMATCH")
    model_config = _mapping(manifest.model_config, "model_config")
    expected_model_fields = {
        "min_train_rows",
        "validation_rows",
        "max_leaf_nodes",
        "min_samples_leaf",
        "learning_rate",
        "max_iter",
        "l2_regularization",
    }
    if set(model_config) != expected_model_fields:
        raise LearningTreeError("LEARNING_TREE_MODEL_CONFIG_FIELDS_MISMATCH")
    decision_policy = _mapping(manifest.decision_policy, "decision_policy")
    expected_policy_fields = {
        "prediction_threshold",
        "stability_blocks",
        "min_block_trades",
        "min_validation_trades",
        "min_validation_mean_target",
    }
    if set(decision_policy) != expected_policy_fields:
        raise LearningTreeError("LEARNING_TREE_DECISION_POLICY_FIELDS_MISMATCH")
    try:
        config = LearningTreeConfig(
            min_train_rows=_integer(
                model_config.get("min_train_rows"),
                "min_train_rows",
            ),
            validation_rows=_integer(
                model_config.get("validation_rows"),
                "validation_rows",
            ),
            max_leaf_nodes=_integer(
                model_config.get("max_leaf_nodes"),
                "max_leaf_nodes",
            ),
            min_samples_leaf=_integer(
                model_config.get("min_samples_leaf"),
                "min_samples_leaf",
            ),
            learning_rate=_decimal(
                model_config.get("learning_rate"),
                "learning_rate",
            ),
            max_iter=_integer(model_config.get("max_iter"), "max_iter"),
            l2_regularization=_decimal(
                model_config.get("l2_regularization"),
                "l2_regularization",
            ),
        )
        policy = LearningTreeDecisionPolicy(
            prediction_threshold=_decimal(
                decision_policy.get("prediction_threshold"),
                "prediction_threshold",
            ),
            stability_blocks=_integer(
                decision_policy.get("stability_blocks"),
                "stability_blocks",
            ),
            min_block_trades=_integer(
                decision_policy.get("min_block_trades"),
                "min_block_trades",
            ),
            min_validation_trades=_integer(
                decision_policy.get("min_validation_trades"),
                "min_validation_trades",
            ),
            min_validation_mean_target=_decimal(
                decision_policy.get("min_validation_mean_target"),
                "min_validation_mean_target",
            ),
        )
    except ValueError as exc:
        raise LearningTreeError("LEARNING_TREE_CONFIG_INVALID") from exc
    return config, policy


def _validate_bundle_binding(
    bundle: VerifiedLearningTrainingBundle,
    manifest: LearningChallengerRunManifest,
) -> None:
    training_set = bundle.training_set
    if training_set.run_id != manifest.run_id:
        raise LearningTreeError("LEARNING_TREE_RUN_ID_MISMATCH")
    if training_set.dataset_id != manifest.dataset_id:
        raise LearningTreeError("LEARNING_TREE_DATASET_ID_MISMATCH")
    if training_set.dataset_lineage_id != manifest.dataset_lineage_id:
        raise LearningTreeError("LEARNING_TREE_DATASET_LINEAGE_MISMATCH")
    if training_set.feature_registry != manifest.feature_registry:
        raise LearningTreeError("LEARNING_TREE_FEATURE_REGISTRY_MISMATCH")
    if training_set.evidence_kind != manifest.input_kinds[0]:
        raise LearningTreeError("LEARNING_TREE_EVIDENCE_KIND_MISMATCH")
    source_record_ids = tuple(row.source_record_id for row in training_set.rows)
    if source_record_ids != manifest.input_record_ids:
        raise LearningTreeError("LEARNING_TREE_INPUT_RECORDS_MISMATCH")


def _encoder(
    rows: tuple[LearningTrainingRow, ...],
    feature_registry: tuple[str, ...],
) -> LearningTreeEncoder:
    categories: list[tuple[str, tuple[str, ...]]] = []
    for index, feature in enumerate(feature_registry):
        if feature not in CATEGORICAL_FEATURES:
            continue
        values = tuple(sorted({row.feature_values[index] for row in rows}))
        categories.append((feature, values))
    return LearningTreeEncoder(
        feature_registry=feature_registry,
        categories=tuple(categories),
    )


def _fit_estimator(
    rows: tuple[LearningTrainingRow, ...],
    encoder: LearningTreeEncoder,
    config: LearningTreeConfig,
) -> Any:
    regressor = _hist_gradient_boosting_regressor()
    estimator = regressor(
        loss="squared_error",
        learning_rate=float(config.learning_rate),
        max_iter=config.max_iter,
        max_leaf_nodes=config.max_leaf_nodes,
        min_samples_leaf=config.min_samples_leaf,
        l2_regularization=float(config.l2_regularization),
        early_stopping=False,
    )
    estimator.fit(
        [encoder.vector(row) for row in rows],
        [float(row.target_value) for row in rows],
    )
    return estimator


def _predict(
    estimator: Any,
    encoder: LearningTreeEncoder,
    rows: tuple[LearningTrainingRow, ...],
) -> dict[str, Decimal]:
    raw = estimator.predict([encoder.vector(row) for row in rows])
    predictions: dict[str, Decimal] = {}
    for row, value in zip(rows, raw, strict=True):
        resolved = float(value)
        if not math.isfinite(resolved):
            raise LearningTreeError("tree prediction must be finite")
        predictions[row.source_record_id] = Decimal(str(resolved))
    return predictions


def _summary(
    rows: tuple[LearningTrainingRow, ...],
    predictions: dict[str, Decimal],
    *,
    threshold: Decimal,
) -> LearningTreeSummary:
    accepted = tuple(
        row
        for row in rows
        if predictions[row.source_record_id] >= threshold
    )
    total = sum((row.target_value for row in accepted), ZERO)
    return LearningTreeSummary(
        row_count=len(rows),
        trade_count=len(accepted),
        no_trade_count=len(rows) - len(accepted),
        total_target=total,
        mean_target=None if not accepted else total / Decimal(len(accepted)),
    )


def _blocks(
    rows: tuple[LearningTrainingRow, ...],
    predictions: dict[str, Decimal],
    policy: LearningTreeDecisionPolicy,
) -> tuple[LearningTreeBlock, ...]:
    if len(rows) < policy.stability_blocks:
        raise LearningTreeError("LEARNING_TREE_VALIDATION_TOO_SHORT_FOR_BLOCKS")
    quotient, remainder = divmod(len(rows), policy.stability_blocks)
    output: list[LearningTreeBlock] = []
    offset = 0
    for block_index in range(policy.stability_blocks):
        size = quotient + (1 if block_index < remainder else 0)
        block_rows = rows[offset : offset + size]
        offset += size
        output.append(
            LearningTreeBlock(
                block_index=block_index,
                start_opened_at_ms=block_rows[0].opened_at_ms,
                end_opened_at_ms=block_rows[-1].opened_at_ms,
                summary=_summary(
                    block_rows,
                    predictions,
                    threshold=policy.prediction_threshold,
                ),
            )
        )
    return tuple(output)


def evaluate_learning_tree(
    bundle: VerifiedLearningTrainingBundle,
    manifest: LearningChallengerRunManifest,
) -> LearningTreeEvaluation:
    _validate_bundle_binding(bundle, manifest)
    config, policy = _config_from_manifest(manifest)

    ordered = tuple(
        sorted(
            bundle.training_set.rows,
            key=lambda row: (
                row.opened_at_ms,
                row.closed_at_ms,
                row.source_record_id,
            ),
        )
    )
    if len(ordered) <= config.validation_rows:
        raise LearningTreeError("LEARNING_TREE_INSUFFICIENT_ROWS")
    validation = ordered[-config.validation_rows :]
    validation_start = validation[0].opened_at_ms
    prefix = ordered[: -config.validation_rows]
    train = tuple(row for row in prefix if row.closed_at_ms < validation_start)
    overlap_excluded_count = len(prefix) - len(train)
    if len(train) < config.min_train_rows:
        raise LearningTreeError("LEARNING_TREE_INSUFFICIENT_SETTLED_TRAIN_ROWS")

    encoder = _encoder(train, bundle.training_set.feature_registry)
    estimator = _fit_estimator(train, encoder, config)
    predictions = _predict(estimator, encoder, validation)
    prediction_sha256 = _sha256_json(
        tuple(
            {
                "source_record_id": row.source_record_id,
                "prediction": str(predictions[row.source_record_id]),
            }
            for row in validation
        )
    )
    overall = _summary(
        validation,
        predictions,
        threshold=policy.prediction_threshold,
    )
    blocks = _blocks(validation, predictions, policy)
    overall_qualifies = (
        overall.trade_count >= policy.min_validation_trades
        and overall.mean_target is not None
        and overall.mean_target > policy.min_validation_mean_target
    )
    blocks_qualify = all(
        block.summary.trade_count >= policy.min_block_trades
        and block.summary.mean_target is not None
        and block.summary.mean_target > policy.min_validation_mean_target
        for block in blocks
    )
    return LearningTreeEvaluation(
        run_id=manifest.run_id,
        training_bundle_id=bundle.bundle_id,
        training_set_id=bundle.training_set.training_set_id,
        dataset_lineage_id=bundle.training_set.dataset_lineage_id,
        model_family=manifest.model_family,
        model_config=config,
        decision_policy=policy,
        encoder=encoder,
        train_row_count=len(train),
        validation_row_count=len(validation),
        overlap_excluded_count=overlap_excluded_count,
        validation_start_opened_at_ms=validation[0].opened_at_ms,
        validation_end_opened_at_ms=validation[-1].opened_at_ms,
        prediction_sha256=prediction_sha256,
        overall=overall,
        blocks=blocks,
        qualifies_development=overall_qualifies and blocks_qualify,
    )



def write_learning_tree_evaluation(
    path: Path,
    evaluation: LearningTreeEvaluation,
) -> Path:
    payload = (_canonical_json(evaluation.to_dict()) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise LearningTreeError("LEARNING_TREE_EVALUATION_CONFLICT")
        return path
    temporary = path.with_name(f".{path.name}.tmp")
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
