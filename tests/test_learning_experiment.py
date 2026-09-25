from __future__ import annotations

import json
from decimal import Decimal

import pytest

from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.learning_experiment_cli import main
from cocomelon.research.learning_challenger_run import (
    build_learning_challenger_run_manifest,
    write_learning_challenger_run_manifest,
)
from cocomelon.research.learning_dataset import build_learning_dataset_snapshot
from cocomelon.research.learning_dataset_bundle import (
    load_verified_learning_dataset_bundle,
    write_learning_dataset_bundle,
)
from cocomelon.research.learning_experiment import (
    LearningExperimentError,
    load_verified_learning_experiment,
    materialize_learning_experiment,
)
from cocomelon.research.learning_grouped_mean import GROUPED_MEAN_MODEL_FAMILY
from cocomelon.research.outcome_learning import (
    LearningEvidenceKind,
    LearningEvidenceLedger,
    LearningEvidenceRecord,
)


def _record(index: int, *, net_r: str) -> LearningEvidenceRecord:
    opened = index * 10_000
    closed = opened + 1_000
    return LearningEvidenceRecord(
        kind=LearningEvidenceKind.PAPER_EXECUTION,
        source_record_id=f"paper-experiment-{index}",
        source_evidence_class="paper",
        candidate_id="candidate-experiment",
        candidate_spec_id=None,
        campaign_id=None,
        market=MarketId("", "HYPE"),
        direction=Direction.LONG,
        opened_at_ms=opened,
        closed_at_ms=closed,
        feature_snapshot_id=f"feature-experiment-{index}",
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


def _inputs(tmp_path):
    records = tuple(
        _record(index, net_r=("0.10" if index <= 6 else "0.02"))
        for index in range(1, 11)
    )
    ledger = LearningEvidenceLedger(tmp_path / "ledger")
    for record in records:
        ledger.record(record)
    snapshot = build_learning_dataset_snapshot(
        ledger,
        as_of_ms=max(record.research_eligible_at_ms for record in records),
    )
    dataset_dir = tmp_path / "dataset-source"
    write_learning_dataset_bundle(snapshot, output_dir=dataset_dir)
    bundle = load_verified_learning_dataset_bundle(output_dir=dataset_dir)
    run_manifest = build_learning_challenger_run_manifest(
        bundle,
        input_kinds=(LearningEvidenceKind.PAPER_EXECUTION,),
        feature_registry=("market", "direction"),
        model_family=GROUPED_MEAN_MODEL_FAMILY,
        model_config={
            "min_train_rows": 6,
            "validation_rows": 4,
            "min_group_train_rows": 5,
        },
        decision_policy={
            "prediction_threshold": "0.01",
            "stability_blocks": 2,
            "min_block_trades": 2,
            "min_validation_trades": 4,
            "min_validation_mean_target": "0",
        },
        implementation_commit_sha="a" * 40,
    )
    run_path = write_learning_challenger_run_manifest(
        tmp_path / "challenger-run.json",
        run_manifest,
    )
    return dataset_dir, run_path


def test_learning_experiment_is_self_contained_and_reverifiable(tmp_path) -> None:
    dataset_dir, run_path = _inputs(tmp_path)
    output_dir = tmp_path / "experiment"

    manifest = materialize_learning_experiment(
        dataset_bundle_dir=dataset_dir,
        run_manifest_path=run_path,
        output_dir=output_dir,
    )
    verified = load_verified_learning_experiment(output_dir)

    assert verified == manifest
    assert manifest.model_family == GROUPED_MEAN_MODEL_FAMILY
    assert manifest.feature_snapshot_count == 0
    assert manifest.feature_snapshot_state_digest is None
    assert manifest.research_only is True
    assert manifest.promotion_eligible is False
    assert manifest.execution_ready is False
    assert len(manifest.experiment_id) == 64
    assert (output_dir / "dataset" / "manifest.json").is_file()
    assert (output_dir / "dataset" / "records.jsonl").is_file()
    assert (output_dir / "run-manifest.json").is_file()
    assert (output_dir / "training" / "manifest.json").is_file()
    assert (output_dir / "training" / "rows.jsonl").is_file()
    assert (output_dir / "evaluation.json").is_file()
    assert (output_dir / "experiment.json").is_file()


def test_learning_experiment_rejects_tampered_evaluation(tmp_path) -> None:
    dataset_dir, run_path = _inputs(tmp_path)
    output_dir = tmp_path / "experiment"
    materialize_learning_experiment(
        dataset_bundle_dir=dataset_dir,
        run_manifest_path=run_path,
        output_dir=output_dir,
    )
    evaluation_path = output_dir / "evaluation.json"
    evaluation_path.write_text(
        evaluation_path.read_text(encoding="utf-8").replace(
            '"qualifies_development":true',
            '"qualifies_development":false',
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        LearningExperimentError,
        match="EVALUATION_IDENTITY_MISMATCH",
    ):
        load_verified_learning_experiment(output_dir)


def test_learning_experiment_refuses_existing_output_root(tmp_path) -> None:
    dataset_dir, run_path = _inputs(tmp_path)
    output_dir = tmp_path / "experiment"
    output_dir.mkdir()

    with pytest.raises(LearningExperimentError, match="must not already exist"):
        materialize_learning_experiment(
            dataset_bundle_dir=dataset_dir,
            run_manifest_path=run_path,
            output_dir=output_dir,
        )


def test_learning_experiment_cli_materializes_verified_artifact(
    tmp_path,
    capsys,
) -> None:
    dataset_dir, run_path = _inputs(tmp_path)
    output_dir = tmp_path / "experiment"

    code = main(
        (
            "--dataset-bundle-dir",
            str(dataset_dir),
            "--run-manifest",
            str(run_path),
            "--output-dir",
            str(output_dir),
        )
    )

    assert code == 0
    emitted = json.loads(capsys.readouterr().out)
    verified = load_verified_learning_experiment(output_dir)
    assert emitted["experiment_id"] == verified.experiment_id
    assert emitted["evaluation_id"] == verified.evaluation_id
    assert emitted["model_family"] == GROUPED_MEAN_MODEL_FAMILY
    assert emitted["research_only"] is True
    assert emitted["promotion_eligible"] is False
    assert emitted["execution_ready"] is False
