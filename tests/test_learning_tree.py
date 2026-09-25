from __future__ import annotations

import hashlib
from decimal import Decimal

import pytest

pytest.importorskip("sklearn")

from cocomelon.research.learning_challenger_run import LearningChallengerRunManifest
from cocomelon.research.learning_training_bundle import VerifiedLearningTrainingBundle
from cocomelon.research.learning_training_rows import (
    LearningTrainingRow,
    LearningTrainingSet,
)
from cocomelon.research.learning_tree import (
    TREE_MODEL_FAMILY,
    LearningTreeError,
    evaluate_learning_tree,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _row(
    index: int,
    *,
    feature_value: str,
    target_value: str,
    opened_at_ms: int | None = None,
    closed_at_ms: int | None = None,
) -> LearningTrainingRow:
    opened = index * 10_000 if opened_at_ms is None else opened_at_ms
    closed = opened + 1_000 if closed_at_ms is None else closed_at_ms
    return LearningTrainingRow(
        source_record_id=_sha(f"record-{index}"),
        evidence_kind="paper_execution",
        source_evidence_class="paper",
        candidate_id="candidate-tree",
        candidate_spec_id=None,
        campaign_id=None,
        market="HYPE",
        direction="long",
        opened_at_ms=opened,
        closed_at_ms=closed,
        feature_snapshot_id=_sha(f"feature-{index}")[:24],
        feature_registry=("return_5m",),
        feature_values=(feature_value,),
        target_name="realized_net_r",
        target_value=Decimal(target_value),
    )


def _manifest(
    rows: tuple[LearningTrainingRow, ...],
    *,
    model_family: str = TREE_MODEL_FAMILY,
    min_train_rows: int = 40,
    validation_rows: int = 8,
) -> LearningChallengerRunManifest:
    return LearningChallengerRunManifest(
        dataset_id="1" * 64,
        dataset_lineage_id="2" * 64,
        dataset_manifest_sha256="3" * 64,
        dataset_records_sha256="4" * 64,
        input_kinds=("paper_execution",),
        input_record_ids=tuple(sorted(row.source_record_id for row in rows)),
        feature_registry=("return_5m",),
        model_family=model_family,
        model_config={
            "min_train_rows": min_train_rows,
            "validation_rows": validation_rows,
            "max_leaf_nodes": 7,
            "min_samples_leaf": 2,
            "learning_rate": "0.1",
            "max_iter": 100,
            "l2_regularization": "0.1",
        },
        decision_policy={
            "prediction_threshold": "0",
            "stability_blocks": 2,
            "min_block_trades": 2,
            "min_validation_trades": 4,
            "min_validation_mean_target": "0",
        },
        implementation_commit_sha="a" * 40,
    )


def _bundle(
    rows: tuple[LearningTrainingRow, ...],
    manifest: LearningChallengerRunManifest,
) -> VerifiedLearningTrainingBundle:
    training_set = LearningTrainingSet(
        run_id=manifest.run_id,
        dataset_id=manifest.dataset_id,
        dataset_lineage_id=manifest.dataset_lineage_id,
        evidence_kind="paper_execution",
        target_name="realized_net_r",
        feature_registry=("return_5m",),
        rows=tuple(sorted(rows, key=lambda row: row.source_record_id)),
    )
    return VerifiedLearningTrainingBundle(
        training_set=training_set,
        manifest_sha256="5" * 64,
        rows_sha256="6" * 64,
    )


def test_tree_learns_fixed_nonlinear_filter_on_chronological_holdout() -> None:
    train_rows = tuple(
        _row(
            index,
            feature_value=str(
                Decimal((index % 20) - 10) / Decimal("10")
            ),
            target_value=(
                "0.05"
                if abs(Decimal((index % 20) - 10) / Decimal("10"))
                >= Decimal("0.6")
                else "-0.05"
            ),
        )
        for index in range(1, 61)
    )
    validation_values = (
        ("0.9", "0.04"),
        ("0.1", "-0.04"),
        ("-0.9", "0.04"),
        ("-0.1", "-0.04"),
        ("0.8", "0.04"),
        ("0.0", "-0.04"),
        ("-0.8", "0.04"),
        ("0.2", "-0.04"),
    )
    validation_rows = tuple(
        _row(
            60 + offset,
            feature_value=feature,
            target_value=target,
        )
        for offset, (feature, target) in enumerate(validation_values, start=1)
    )
    rows = train_rows + validation_rows
    manifest = _manifest(rows)
    bundle = _bundle(rows, manifest)

    result = evaluate_learning_tree(bundle, manifest)

    assert result.train_row_count == 60
    assert result.validation_row_count == 8
    assert result.overlap_excluded_count == 0
    assert result.overall.trade_count == 4
    assert result.overall.no_trade_count == 4
    assert result.overall.mean_target == Decimal("0.04")
    assert tuple(block.summary.trade_count for block in result.blocks) == (2, 2)
    assert result.qualifies_development is True
    assert result.research_only is True
    assert result.promotion_eligible is False
    assert result.execution_ready is False
    assert len(result.prediction_sha256) == 64
    assert len(result.evaluation_id) == 64


def test_tree_excludes_outcome_not_settled_before_validation_start() -> None:
    rows = tuple(
        [
            _row(index, feature_value="0.9", target_value="0.05")
            for index in range(1, 41)
        ]
        + [
            _row(
                41,
                feature_value="0.9",
                target_value="0.05",
                opened_at_ms=410_000,
                closed_at_ms=435_000,
            ),
            _row(42, feature_value="0.9", target_value="0.04"),
            _row(43, feature_value="-0.9", target_value="0.04"),
        ]
    )
    manifest = _manifest(
        rows,
        min_train_rows=40,
        validation_rows=2,
    )
    bundle = _bundle(rows, manifest)

    result = evaluate_learning_tree(bundle, manifest)

    assert result.validation_start_opened_at_ms == 420_000
    assert result.train_row_count == 40
    assert result.overlap_excluded_count == 1


def test_tree_rejects_non_tree_model_family() -> None:
    rows = tuple(
        _row(index, feature_value="0.9", target_value="0.05")
        for index in range(1, 49)
    )
    manifest = _manifest(rows, model_family="categorical_group_mean_v1")
    bundle = _bundle(rows, manifest)

    with pytest.raises(LearningTreeError, match="MODEL_FAMILY_MISMATCH"):
        evaluate_learning_tree(bundle, manifest)
