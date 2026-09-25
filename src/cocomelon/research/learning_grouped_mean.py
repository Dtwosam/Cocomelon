from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import cast

from cocomelon.research.learning_challenger_run import LearningChallengerRunManifest
from cocomelon.research.learning_training_bundle import VerifiedLearningTrainingBundle
from cocomelon.research.learning_training_rows import LearningTrainingRow

GROUPED_MEAN_MODEL_FAMILY = "categorical_group_mean_v1"
EVALUATION_SCHEMA_VERSION = 1


class LearningGroupedMeanError(RuntimeError):
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


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise LearningGroupedMeanError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise LearningGroupedMeanError(f"{field} must be an integer")
    return value


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise LearningGroupedMeanError(f"{field} must be a decimal string")
    try:
        resolved = Decimal(value)
    except ArithmeticError as exc:
        raise LearningGroupedMeanError(f"{field} must be a decimal string") from exc
    if not resolved.is_finite():
        raise LearningGroupedMeanError(f"{field} must be finite")
    return resolved


@dataclass(frozen=True, slots=True)
class LearningGroupedMeanConfig:
    min_train_rows: int
    validation_rows: int
    min_group_train_rows: int

    def __post_init__(self) -> None:
        if self.min_train_rows <= 0:
            raise ValueError("min_train_rows must be positive")
        if self.validation_rows <= 0:
            raise ValueError("validation_rows must be positive")
        if self.min_group_train_rows <= 0:
            raise ValueError("min_group_train_rows must be positive")

    def to_dict(self) -> dict[str, object]:
        return {
            "min_train_rows": self.min_train_rows,
            "validation_rows": self.validation_rows,
            "min_group_train_rows": self.min_group_train_rows,
        }


@dataclass(frozen=True, slots=True)
class LearningGroupedMeanDecisionPolicy:
    prediction_threshold: Decimal
    stability_blocks: int
    min_block_trades: int
    min_validation_trades: int
    min_validation_mean_target: Decimal

    def __post_init__(self) -> None:
        for field in (
            "prediction_threshold",
            "min_validation_mean_target",
        ):
            value = cast(Decimal, getattr(self, field))
            if not value.is_finite():
                raise ValueError(f"{field} must be finite")
        if self.stability_blocks <= 0:
            raise ValueError("stability_blocks must be positive")
        if self.min_block_trades <= 0:
            raise ValueError("min_block_trades must be positive")
        if self.min_validation_trades <= 0:
            raise ValueError("min_validation_trades must be positive")

    def to_dict(self) -> dict[str, object]:
        return {
            "prediction_threshold": str(self.prediction_threshold),
            "stability_blocks": self.stability_blocks,
            "min_block_trades": self.min_block_trades,
            "min_validation_trades": self.min_validation_trades,
            "min_validation_mean_target": str(self.min_validation_mean_target),
        }


@dataclass(frozen=True, slots=True)
class LearningGroupedMeanSummary:
    row_count: int
    trade_count: int
    no_trade_count: int
    total_target: Decimal
    mean_target: Decimal | None

    def __post_init__(self) -> None:
        if min(self.row_count, self.trade_count, self.no_trade_count) < 0:
            raise ValueError("evaluation counts must be non-negative")
        if self.trade_count + self.no_trade_count != self.row_count:
            raise ValueError("trade/no-trade counts must cover evaluation rows")
        if self.trade_count == 0 and self.mean_target is not None:
            raise ValueError("mean_target must be None when there are no trades")
        if self.trade_count > 0 and self.mean_target is None:
            raise ValueError("mean_target is required when trades exist")

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
class LearningGroupedMeanBlock:
    block_index: int
    start_opened_at_ms: int
    end_opened_at_ms: int
    summary: LearningGroupedMeanSummary

    def to_dict(self) -> dict[str, object]:
        return {
            "block_index": self.block_index,
            "start_opened_at_ms": self.start_opened_at_ms,
            "end_opened_at_ms": self.end_opened_at_ms,
            "summary": self.summary.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class LearningGroupedMeanEvaluation:
    run_id: str
    training_bundle_id: str
    training_set_id: str
    dataset_lineage_id: str
    model_family: str
    model_config: LearningGroupedMeanConfig
    decision_policy: LearningGroupedMeanDecisionPolicy
    train_row_count: int
    validation_row_count: int
    overlap_excluded_count: int
    validation_start_opened_at_ms: int
    validation_end_opened_at_ms: int
    group_count: int
    overall: LearningGroupedMeanSummary
    blocks: tuple[LearningGroupedMeanBlock, ...]
    qualifies_development: bool
    research_only: bool = True
    promotion_eligible: bool = False
    execution_ready: bool = False
    schema_version: int = EVALUATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.model_family != GROUPED_MEAN_MODEL_FAMILY:
            raise ValueError("unsupported grouped mean model family")
        if min(
            self.train_row_count,
            self.validation_row_count,
            self.overlap_excluded_count,
            self.group_count,
        ) < 0:
            raise ValueError("evaluation counts must be non-negative")
        if self.validation_row_count <= 0:
            raise ValueError("validation_row_count must be positive")
        if len(self.blocks) != self.decision_policy.stability_blocks:
            raise ValueError("block count must match decision policy")
        if not self.research_only:
            raise ValueError("learning evaluation must remain research-only")
        if self.promotion_eligible or self.execution_ready:
            raise ValueError("learning evaluation cannot authorize promotion/execution")
        if self.schema_version != EVALUATION_SCHEMA_VERSION:
            raise ValueError("unsupported learning evaluation schema")

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
            "train_row_count": self.train_row_count,
            "validation_row_count": self.validation_row_count,
            "overlap_excluded_count": self.overlap_excluded_count,
            "validation_start_opened_at_ms": self.validation_start_opened_at_ms,
            "validation_end_opened_at_ms": self.validation_end_opened_at_ms,
            "group_count": self.group_count,
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
) -> tuple[LearningGroupedMeanConfig, LearningGroupedMeanDecisionPolicy]:
    if manifest.model_family != GROUPED_MEAN_MODEL_FAMILY:
        raise LearningGroupedMeanError(
            "LEARNING_GROUPED_MEAN_MODEL_FAMILY_MISMATCH"
        )
    model_config = _mapping(manifest.model_config, "model_config")
    expected_model_fields = {
        "min_train_rows",
        "validation_rows",
        "min_group_train_rows",
    }
    if set(model_config) != expected_model_fields:
        raise LearningGroupedMeanError(
            "LEARNING_GROUPED_MEAN_MODEL_CONFIG_FIELDS_MISMATCH"
        )
    decision_policy = _mapping(manifest.decision_policy, "decision_policy")
    expected_policy_fields = {
        "prediction_threshold",
        "stability_blocks",
        "min_block_trades",
        "min_validation_trades",
        "min_validation_mean_target",
    }
    if set(decision_policy) != expected_policy_fields:
        raise LearningGroupedMeanError(
            "LEARNING_GROUPED_MEAN_DECISION_POLICY_FIELDS_MISMATCH"
        )
    try:
        config = LearningGroupedMeanConfig(
            min_train_rows=_integer(
                model_config.get("min_train_rows"),
                "min_train_rows",
            ),
            validation_rows=_integer(
                model_config.get("validation_rows"),
                "validation_rows",
            ),
            min_group_train_rows=_integer(
                model_config.get("min_group_train_rows"),
                "min_group_train_rows",
            ),
        )
        policy = LearningGroupedMeanDecisionPolicy(
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
        raise LearningGroupedMeanError(
            "LEARNING_GROUPED_MEAN_CONFIG_INVALID"
        ) from exc
    return config, policy


def _validate_bundle_binding(
    bundle: VerifiedLearningTrainingBundle,
    manifest: LearningChallengerRunManifest,
) -> None:
    training_set = bundle.training_set
    if training_set.run_id != manifest.run_id:
        raise LearningGroupedMeanError("LEARNING_GROUPED_MEAN_RUN_ID_MISMATCH")
    if training_set.dataset_id != manifest.dataset_id:
        raise LearningGroupedMeanError("LEARNING_GROUPED_MEAN_DATASET_ID_MISMATCH")
    if training_set.dataset_lineage_id != manifest.dataset_lineage_id:
        raise LearningGroupedMeanError(
            "LEARNING_GROUPED_MEAN_DATASET_LINEAGE_MISMATCH"
        )
    if training_set.feature_registry != manifest.feature_registry:
        raise LearningGroupedMeanError(
            "LEARNING_GROUPED_MEAN_FEATURE_REGISTRY_MISMATCH"
        )
    if training_set.evidence_kind != manifest.input_kinds[0]:
        raise LearningGroupedMeanError(
            "LEARNING_GROUPED_MEAN_EVIDENCE_KIND_MISMATCH"
        )
    source_record_ids = tuple(row.source_record_id for row in training_set.rows)
    if source_record_ids != manifest.input_record_ids:
        raise LearningGroupedMeanError(
            "LEARNING_GROUPED_MEAN_INPUT_RECORDS_MISMATCH"
        )


def _mean(values: tuple[Decimal, ...]) -> Decimal:
    if not values:
        raise ValueError("mean requires values")
    return sum(values, Decimal("0")) / Decimal(len(values))


def _summary(
    rows: tuple[LearningTrainingRow, ...],
    *,
    predictions: dict[str, Decimal | None],
    threshold: Decimal,
) -> LearningGroupedMeanSummary:
    accepted = tuple(
        row
        for row in rows
        if predictions[row.source_record_id] is not None
        and cast(Decimal, predictions[row.source_record_id]) >= threshold
    )
    total = sum((row.target_value for row in accepted), Decimal("0"))
    return LearningGroupedMeanSummary(
        row_count=len(rows),
        trade_count=len(accepted),
        no_trade_count=len(rows) - len(accepted),
        total_target=total,
        mean_target=None if not accepted else total / Decimal(len(accepted)),
    )


def _blocks(
    rows: tuple[LearningTrainingRow, ...],
    *,
    predictions: dict[str, Decimal | None],
    policy: LearningGroupedMeanDecisionPolicy,
) -> tuple[LearningGroupedMeanBlock, ...]:
    if len(rows) < policy.stability_blocks:
        raise LearningGroupedMeanError(
            "LEARNING_GROUPED_MEAN_VALIDATION_TOO_SHORT_FOR_BLOCKS"
        )
    quotient, remainder = divmod(len(rows), policy.stability_blocks)
    output: list[LearningGroupedMeanBlock] = []
    offset = 0
    for block_index in range(policy.stability_blocks):
        size = quotient + (1 if block_index < remainder else 0)
        block_rows = rows[offset : offset + size]
        offset += size
        output.append(
            LearningGroupedMeanBlock(
                block_index=block_index,
                start_opened_at_ms=block_rows[0].opened_at_ms,
                end_opened_at_ms=block_rows[-1].opened_at_ms,
                summary=_summary(
                    block_rows,
                    predictions=predictions,
                    threshold=policy.prediction_threshold,
                ),
            )
        )
    return tuple(output)


def evaluate_learning_grouped_mean(
    bundle: VerifiedLearningTrainingBundle,
    manifest: LearningChallengerRunManifest,
) -> LearningGroupedMeanEvaluation:
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
        raise LearningGroupedMeanError(
            "LEARNING_GROUPED_MEAN_INSUFFICIENT_ROWS"
        )
    validation = ordered[-config.validation_rows :]
    validation_start = validation[0].opened_at_ms
    prefix = ordered[: -config.validation_rows]
    train = tuple(row for row in prefix if row.closed_at_ms < validation_start)
    overlap_excluded_count = len(prefix) - len(train)
    if len(train) < config.min_train_rows:
        raise LearningGroupedMeanError(
            "LEARNING_GROUPED_MEAN_INSUFFICIENT_SETTLED_TRAIN_ROWS"
        )

    grouped_targets: dict[tuple[str, ...], list[Decimal]] = {}
    for row in train:
        grouped_targets.setdefault(row.feature_values, []).append(row.target_value)
    group_means = {
        key: _mean(tuple(values))
        for key, values in grouped_targets.items()
        if len(values) >= config.min_group_train_rows
    }
    predictions = {
        row.source_record_id: group_means.get(row.feature_values)
        for row in validation
    }
    overall = _summary(
        validation,
        predictions=predictions,
        threshold=policy.prediction_threshold,
    )
    blocks = _blocks(
        validation,
        predictions=predictions,
        policy=policy,
    )
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
    return LearningGroupedMeanEvaluation(
        run_id=manifest.run_id,
        training_bundle_id=bundle.bundle_id,
        training_set_id=bundle.training_set.training_set_id,
        dataset_lineage_id=bundle.training_set.dataset_lineage_id,
        model_family=manifest.model_family,
        model_config=config,
        decision_policy=policy,
        train_row_count=len(train),
        validation_row_count=len(validation),
        overlap_excluded_count=overlap_excluded_count,
        validation_start_opened_at_ms=validation[0].opened_at_ms,
        validation_end_opened_at_ms=validation[-1].opened_at_ms,
        group_count=len(group_means),
        overall=overall,
        blocks=blocks,
        qualifies_development=overall_qualifies and blocks_qualify,
    )
