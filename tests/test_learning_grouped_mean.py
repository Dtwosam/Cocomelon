from __future__ import annotations

from decimal import Decimal

import pytest

from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.research.learning_challenger_run import (
    build_learning_challenger_run_manifest,
)
from cocomelon.research.learning_dataset import build_learning_dataset_snapshot
from cocomelon.research.learning_dataset_bundle import (
    load_verified_learning_dataset_bundle,
    write_learning_dataset_bundle,
)
from cocomelon.research.learning_grouped_mean import (
    GROUPED_MEAN_MODEL_FAMILY,
    LearningGroupedMeanError,
    evaluate_learning_grouped_mean,
)
from cocomelon.research.learning_training_bundle import (
    load_verified_learning_training_bundle,
    write_learning_training_bundle,
)
from cocomelon.research.learning_training_rows import build_learning_training_set
from cocomelon.research.outcome_learning import (
    LearningEvidenceKind,
    LearningEvidenceLedger,
    LearningEvidenceRecord,
)


def _record(
    index: int,
    *,
    net_r: str,
    opened_at_ms: int | None = None,
    closed_at_ms: int | None = None,
    direction: Direction = Direction.LONG,
) -> LearningEvidenceRecord:
    opened = index * 10_000 if opened_at_ms is None else opened_at_ms
    closed = opened + 1_000 if closed_at_ms is None else closed_at_ms
    return LearningEvidenceRecord(
        kind=LearningEvidenceKind.PAPER_EXECUTION,
        source_record_id=f"paper-{index}",
        source_evidence_class="paper",
        candidate_id="candidate-grouped-mean",
        candidate_spec_id=None,
        campaign_id=None,
        market=MarketId("", "HYPE"),
        direction=direction,
        opened_at_ms=opened,
        closed_at_ms=closed,
        feature_snapshot_id=f"feature-{index}",
        research_eligible_at_ms=closed,
        gross_realized_pnl=Decimal("10"),
        entry_fees=Decimal("0.5"),
        exit_fees=Decimal("0.5"),
        funding_cash_pnl=Decimal("0"),
        entry_slippage_fraction=Decimal("0.001"),
        exit_slippage_fraction=Decimal("0.001"),
        net_pnl=Decimal("9"),
        net_r=Decimal(net_r),
    )


def _verified_inputs(
    tmp_path,
    records,
    *,
    validation_rows: int,
    min_train_rows: int,
    min_group_train_rows: int,
    prediction_threshold: str = "0.01",
    stability_blocks: int = 2,
    min_block_trades: int = 1,
    min_validation_trades: int = 1,
    min_validation_mean_target: str = "0",
    model_family: str = GROUPED_MEAN_MODEL_FAMILY,
):
    ledger = LearningEvidenceLedger(tmp_path / "ledger")
    for record in records:
        ledger.record(record)
    snapshot = build_learning_dataset_snapshot(
        ledger,
        as_of_ms=max(record.research_eligible_at_ms for record in records),
    )
    dataset_dir = tmp_path / "dataset"
    write_learning_dataset_bundle(snapshot, output_dir=dataset_dir)
    source_bundle = load_verified_learning_dataset_bundle(output_dir=dataset_dir)
    manifest = build_learning_challenger_run_manifest(
        source_bundle,
        input_kinds=(LearningEvidenceKind.PAPER_EXECUTION,),
        feature_registry=("market", "direction"),
        model_family=model_family,
        model_config={
            "min_train_rows": min_train_rows,
            "validation_rows": validation_rows,
            "min_group_train_rows": min_group_train_rows,
        },
        decision_policy={
            "prediction_threshold": prediction_threshold,
            "stability_blocks": stability_blocks,
            "min_block_trades": min_block_trades,
            "min_validation_trades": min_validation_trades,
            "min_validation_mean_target": min_validation_mean_target,
        },
        implementation_commit_sha="a" * 40,
    )
    training_set = build_learning_training_set(source_bundle, manifest)
    training_dir = tmp_path / "training"
    write_learning_training_bundle(training_set, output_dir=training_dir)
    training_bundle = load_verified_learning_training_bundle(output_dir=training_dir)
    return training_bundle, manifest


def test_grouped_mean_uses_chronological_holdout_and_stability_blocks(tmp_path) -> None:
    records = tuple(
        _record(
            index,
            net_r=("0.10" if index <= 6 else "0.02"),
        )
        for index in range(1, 11)
    )
    bundle, manifest = _verified_inputs(
        tmp_path,
        records,
        validation_rows=4,
        min_train_rows=5,
        min_group_train_rows=5,
        min_block_trades=2,
        min_validation_trades=4,
    )

    result = evaluate_learning_grouped_mean(bundle, manifest)

    assert result.train_row_count == 6
    assert result.validation_row_count == 4
    assert result.overlap_excluded_count == 0
    assert result.group_count == 1
    assert result.overall.trade_count == 4
    assert result.overall.mean_target == Decimal("0.02")
    assert tuple(block.summary.trade_count for block in result.blocks) == (2, 2)
    assert result.qualifies_development is True
    assert result.research_only is True
    assert result.promotion_eligible is False
    assert result.execution_ready is False
    assert len(result.evaluation_id) == 64


def test_grouped_mean_rejects_positive_overall_when_one_block_is_negative(tmp_path) -> None:
    validation = ("0.04", "0.04", "-0.01", "-0.01")
    records = tuple(
        _record(
            index,
            net_r=("0.10" if index <= 6 else validation[index - 7]),
        )
        for index in range(1, 11)
    )
    bundle, manifest = _verified_inputs(
        tmp_path,
        records,
        validation_rows=4,
        min_train_rows=5,
        min_group_train_rows=5,
        min_block_trades=2,
        min_validation_trades=4,
    )

    result = evaluate_learning_grouped_mean(bundle, manifest)

    assert result.overall.mean_target == Decimal("0.015")
    assert result.blocks[0].summary.mean_target == Decimal("0.04")
    assert result.blocks[1].summary.mean_target == Decimal("-0.01")
    assert result.qualifies_development is False


def test_grouped_mean_excludes_unsettled_prefix_outcome_at_validation_cutoff(
    tmp_path,
) -> None:
    records = (
        *tuple(_record(index, net_r="0.10") for index in range(1, 6)),
        _record(
            6,
            net_r="0.10",
            opened_at_ms=60_000,
            closed_at_ms=75_000,
        ),
        _record(7, net_r="0.02"),
        _record(8, net_r="0.02"),
    )
    bundle, manifest = _verified_inputs(
        tmp_path,
        records,
        validation_rows=2,
        min_train_rows=5,
        min_group_train_rows=5,
        stability_blocks=2,
        min_block_trades=1,
        min_validation_trades=2,
    )

    result = evaluate_learning_grouped_mean(bundle, manifest)

    assert result.validation_start_opened_at_ms == 70_000
    assert result.train_row_count == 5
    assert result.overlap_excluded_count == 1
    assert result.overall.trade_count == 2


def test_grouped_mean_abstains_when_group_support_is_too_small(tmp_path) -> None:
    records = tuple(_record(index, net_r="0.10") for index in range(1, 9))
    bundle, manifest = _verified_inputs(
        tmp_path,
        records,
        validation_rows=2,
        min_train_rows=5,
        min_group_train_rows=10,
        stability_blocks=2,
    )

    result = evaluate_learning_grouped_mean(bundle, manifest)

    assert result.group_count == 0
    assert result.overall.trade_count == 0
    assert result.overall.no_trade_count == 2
    assert result.overall.mean_target is None
    assert result.qualifies_development is False


def test_grouped_mean_rejects_different_model_family(tmp_path) -> None:
    records = tuple(_record(index, net_r="0.10") for index in range(1, 9))
    bundle, manifest = _verified_inputs(
        tmp_path,
        records,
        validation_rows=2,
        min_train_rows=5,
        min_group_train_rows=5,
        model_family="fixed_shallow_tree",
    )

    with pytest.raises(
        LearningGroupedMeanError,
        match="MODEL_FAMILY_MISMATCH",
    ):
        evaluate_learning_grouped_mean(bundle, manifest)
