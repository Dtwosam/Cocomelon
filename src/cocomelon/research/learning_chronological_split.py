from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from cocomelon.research.learning_training_rows import (
    LearningTrainingRow,
    LearningTrainingSet,
)

SPLIT_SCHEMA_VERSION = 1


class LearningTemporalSplitError(RuntimeError):
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


@dataclass(frozen=True, slots=True)
class LearningWalkForwardConfig:
    min_train_anchors: int
    validation_anchors: int
    test_anchors: int
    step_anchors: int
    embargo_anchors: int = 0
    schema_version: int = SPLIT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in (
            "min_train_anchors",
            "validation_anchors",
            "test_anchors",
            "step_anchors",
        ):
            if getattr(self, field) <= 0:
                raise ValueError(f"{field} must be positive")
        if self.embargo_anchors < 0:
            raise ValueError("embargo_anchors must be non-negative")
        if self.schema_version != SPLIT_SCHEMA_VERSION:
            raise ValueError("unsupported learning split schema")

    def to_dict(self) -> dict[str, object]:
        return {
            "min_train_anchors": self.min_train_anchors,
            "validation_anchors": self.validation_anchors,
            "test_anchors": self.test_anchors,
            "step_anchors": self.step_anchors,
            "embargo_anchors": self.embargo_anchors,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class LearningTemporalFold:
    fold_index: int
    validation_start_ms: int
    test_start_ms: int
    train: tuple[LearningTrainingRow, ...]
    validation: tuple[LearningTrainingRow, ...]
    test: tuple[LearningTrainingRow, ...]
    embargo_record_ids: tuple[str, ...]
    schema_version: int = SPLIT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.fold_index <= 0:
            raise ValueError("fold_index must be positive")
        if self.validation_start_ms < 0:
            raise ValueError("validation_start_ms must be non-negative")
        if self.test_start_ms <= self.validation_start_ms:
            raise ValueError("test_start_ms must follow validation_start_ms")
        if not self.train or not self.validation or not self.test:
            raise ValueError("learning temporal fold partitions must not be empty")
        if self.schema_version != SPLIT_SCHEMA_VERSION:
            raise ValueError("unsupported learning split schema")

        train_ids = {row.source_record_id for row in self.train}
        validation_ids = {row.source_record_id for row in self.validation}
        test_ids = {row.source_record_id for row in self.test}
        embargo_ids = set(self.embargo_record_ids)
        if train_ids & validation_ids or train_ids & test_ids or validation_ids & test_ids:
            raise ValueError("learning temporal fold partitions must be disjoint")
        if embargo_ids & (train_ids | validation_ids | test_ids):
            raise ValueError("embargo rows must be disjoint from evaluated partitions")

        if max(row.opened_at_ms for row in self.train) >= self.validation_start_ms:
            raise ValueError("training features must precede validation")
        if any(row.closed_at_ms >= self.validation_start_ms for row in self.train):
            raise ValueError("training outcomes must settle before validation")
        if min(row.opened_at_ms for row in self.validation) < self.validation_start_ms:
            raise ValueError("validation features must not predate validation")
        if max(row.opened_at_ms for row in self.validation) >= self.test_start_ms:
            raise ValueError("validation features must precede test")
        if any(row.closed_at_ms >= self.test_start_ms for row in self.validation):
            raise ValueError("validation outcomes must settle before test")
        if min(row.opened_at_ms for row in self.test) < self.test_start_ms:
            raise ValueError("test features must not predate test")

    def identity_payload(self) -> dict[str, object]:
        return {
            "fold_index": self.fold_index,
            "validation_start_ms": self.validation_start_ms,
            "test_start_ms": self.test_start_ms,
            "train_record_ids": tuple(row.source_record_id for row in self.train),
            "validation_record_ids": tuple(
                row.source_record_id for row in self.validation
            ),
            "test_record_ids": tuple(row.source_record_id for row in self.test),
            "embargo_record_ids": self.embargo_record_ids,
            "schema_version": self.schema_version,
        }

    @property
    def fold_id(self) -> str:
        return _sha256_json(self.identity_payload())


@dataclass(frozen=True, slots=True)
class LearningWalkForwardPlan:
    training_set_id: str
    run_id: str
    config: LearningWalkForwardConfig
    folds: tuple[LearningTemporalFold, ...]
    schema_version: int = SPLIT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for value, field in (
            (self.training_set_id, "training_set_id"),
            (self.run_id, "run_id"),
        ):
            if len(value) != 64:
                raise ValueError(f"{field} must be a SHA-256 identity")
        if not self.folds:
            raise ValueError("walk-forward plan must contain at least one fold")
        expected = tuple(range(1, len(self.folds) + 1))
        if tuple(fold.fold_index for fold in self.folds) != expected:
            raise ValueError("walk-forward fold indexes must be contiguous")
        if self.schema_version != SPLIT_SCHEMA_VERSION:
            raise ValueError("unsupported learning split schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "training_set_id": self.training_set_id,
            "run_id": self.run_id,
            "config": self.config.to_dict(),
            "fold_ids": tuple(fold.fold_id for fold in self.folds),
            "schema_version": self.schema_version,
        }

    @property
    def plan_id(self) -> str:
        return _sha256_json(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "fold_count": len(self.folds),
            "folds": tuple(fold.identity_payload() for fold in self.folds),
            "plan_id": self.plan_id,
        }


def _row_order(row: LearningTrainingRow) -> tuple[int, int, str]:
    return (row.opened_at_ms, row.closed_at_ms, row.source_record_id)


def build_learning_walk_forward_plan(
    training_set: LearningTrainingSet,
    *,
    config: LearningWalkForwardConfig,
) -> LearningWalkForwardPlan:
    ordered = tuple(sorted(training_set.rows, key=_row_order))
    anchors = tuple(sorted({row.opened_at_ms for row in ordered}))
    folds: list[LearningTemporalFold] = []
    train_count = config.min_train_anchors

    while True:
        validation_start = train_count + config.embargo_anchors
        validation_end = validation_start + config.validation_anchors
        test_start = validation_end + config.embargo_anchors
        test_end = test_start + config.test_anchors
        if test_end > len(anchors):
            break

        train_anchor_set = set(anchors[:train_count])
        first_embargo_set = set(anchors[train_count:validation_start])
        validation_anchor_set = set(anchors[validation_start:validation_end])
        second_embargo_set = set(anchors[validation_end:test_start])
        test_anchor_set = set(anchors[test_start:test_end])
        validation_start_ms = anchors[validation_start]
        test_start_ms = anchors[test_start]

        train_candidates = tuple(
            row for row in ordered if row.opened_at_ms in train_anchor_set
        )
        validation_candidates = tuple(
            row for row in ordered if row.opened_at_ms in validation_anchor_set
        )
        test = tuple(row for row in ordered if row.opened_at_ms in test_anchor_set)
        embargo_rows = tuple(
            row
            for row in ordered
            if row.opened_at_ms in first_embargo_set
            or row.opened_at_ms in second_embargo_set
        )

        train = tuple(
            row
            for row in train_candidates
            if row.closed_at_ms < validation_start_ms
        )
        validation = tuple(
            row
            for row in validation_candidates
            if row.closed_at_ms < test_start_ms
        )
        if len(train) != len(train_candidates):
            raise LearningTemporalSplitError(
                "LEARNING_SPLIT_TRAIN_OUTCOME_CROSSES_VALIDATION_BOUNDARY"
            )
        if len(validation) != len(validation_candidates):
            raise LearningTemporalSplitError(
                "LEARNING_SPLIT_VALIDATION_OUTCOME_CROSSES_TEST_BOUNDARY"
            )
        if not train or not validation or not test:
            raise LearningTemporalSplitError(
                "LEARNING_SPLIT_EMPTY_PARTITION"
            )

        folds.append(
            LearningTemporalFold(
                fold_index=len(folds) + 1,
                validation_start_ms=validation_start_ms,
                test_start_ms=test_start_ms,
                train=train,
                validation=validation,
                test=test,
                embargo_record_ids=tuple(
                    sorted(row.source_record_id for row in embargo_rows)
                ),
            )
        )
        train_count += config.step_anchors

    if not folds:
        raise LearningTemporalSplitError(
            "LEARNING_SPLIT_CONFIGURATION_PRODUCED_NO_FOLDS"
        )
    return LearningWalkForwardPlan(
        training_set_id=training_set.training_set_id,
        run_id=training_set.run_id,
        config=config,
        folds=tuple(folds),
    )
