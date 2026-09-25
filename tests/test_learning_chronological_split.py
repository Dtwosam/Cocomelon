from __future__ import annotations

import hashlib
from decimal import Decimal

import pytest

from cocomelon.research.learning_chronological_split import (
    LearningTemporalSplitError,
    LearningWalkForwardConfig,
    build_learning_walk_forward_plan,
)
from cocomelon.research.learning_training_rows import (
    LearningTrainingRow,
    LearningTrainingSet,
)


def _record_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _row(
    index: int,
    *,
    close_offset: int = 2,
) -> LearningTrainingRow:
    opened_at_ms = index * 10
    return LearningTrainingRow(
        source_record_id=_record_id(f"record-{index}"),
        evidence_kind="paper_execution",
        source_evidence_class="microstructure",
        candidate_id="candidate-1",
        candidate_spec_id=None,
        campaign_id=None,
        market="HYPE",
        direction="long",
        opened_at_ms=opened_at_ms,
        closed_at_ms=opened_at_ms + close_offset,
        feature_snapshot_id=f"feature-{index}",
        feature_registry=("market", "direction"),
        feature_values=("HYPE", "long"),
        target_name="realized_net_r",
        target_value=Decimal(index) / Decimal("100"),
    )


def _training_set(
    *,
    rows: tuple[LearningTrainingRow, ...] | None = None,
) -> LearningTrainingSet:
    resolved = rows if rows is not None else tuple(_row(index) for index in range(8))
    return LearningTrainingSet(
        run_id="a" * 64,
        dataset_id="b" * 64,
        dataset_lineage_id="c" * 64,
        evidence_kind="paper_execution",
        target_name="realized_net_r",
        feature_registry=("market", "direction"),
        rows=tuple(sorted(resolved, key=lambda row: row.source_record_id)),
    )


def test_walk_forward_plan_is_chronological_and_deterministic() -> None:
    training_set = _training_set()
    config = LearningWalkForwardConfig(
        min_train_anchors=3,
        validation_anchors=2,
        test_anchors=2,
        step_anchors=1,
    )

    plan = build_learning_walk_forward_plan(training_set, config=config)

    assert len(plan.folds) == 2
    first = plan.folds[0]
    assert first.validation_start_ms == 30
    assert first.test_start_ms == 50
    assert {row.opened_at_ms for row in first.train} == {0, 10, 20}
    assert {row.opened_at_ms for row in first.validation} == {30, 40}
    assert {row.opened_at_ms for row in first.test} == {50, 60}
    assert all(row.closed_at_ms < first.validation_start_ms for row in first.train)
    assert all(
        row.closed_at_ms < first.test_start_ms
        for row in first.validation
    )
    assert len(plan.plan_id) == 64
    assert plan.plan_id == build_learning_walk_forward_plan(
        training_set,
        config=config,
    ).plan_id


def test_walk_forward_plan_respects_embargo_anchors() -> None:
    training_set = _training_set(
        rows=tuple(_row(index) for index in range(10))
    )
    config = LearningWalkForwardConfig(
        min_train_anchors=3,
        validation_anchors=2,
        test_anchors=2,
        step_anchors=1,
        embargo_anchors=1,
    )

    plan = build_learning_walk_forward_plan(training_set, config=config)

    first = plan.folds[0]
    assert first.validation_start_ms == 40
    assert first.test_start_ms == 70
    assert set(first.embargo_record_ids) == {
        _record_id("record-3"),
        _record_id("record-6"),
    }


def test_walk_forward_plan_rejects_training_outcome_crossing_validation() -> None:
    rows = tuple(
        _row(index, close_offset=15 if index == 2 else 2)
        for index in range(8)
    )
    training_set = _training_set(rows=rows)
    config = LearningWalkForwardConfig(
        min_train_anchors=3,
        validation_anchors=2,
        test_anchors=2,
        step_anchors=1,
    )

    with pytest.raises(
        LearningTemporalSplitError,
        match="TRAIN_OUTCOME_CROSSES_VALIDATION",
    ):
        build_learning_walk_forward_plan(training_set, config=config)


def test_walk_forward_plan_rejects_validation_outcome_crossing_test() -> None:
    rows = tuple(
        _row(index, close_offset=15 if index == 4 else 2)
        for index in range(8)
    )
    training_set = _training_set(rows=rows)
    config = LearningWalkForwardConfig(
        min_train_anchors=3,
        validation_anchors=2,
        test_anchors=2,
        step_anchors=1,
    )

    with pytest.raises(
        LearningTemporalSplitError,
        match="VALIDATION_OUTCOME_CROSSES_TEST",
    ):
        build_learning_walk_forward_plan(training_set, config=config)
