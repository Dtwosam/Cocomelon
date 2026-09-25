from __future__ import annotations

import json
from decimal import Decimal

from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.learning_grouped_mean_cli import main
from cocomelon.research.learning_challenger_run import (
    build_learning_challenger_run_manifest,
    write_learning_challenger_run_manifest,
)
from cocomelon.research.learning_dataset import build_learning_dataset_snapshot
from cocomelon.research.learning_dataset_bundle import (
    load_verified_learning_dataset_bundle,
    write_learning_dataset_bundle,
)
from cocomelon.research.learning_grouped_mean import GROUPED_MEAN_MODEL_FAMILY
from cocomelon.research.learning_training_bundle import write_learning_training_bundle
from cocomelon.research.learning_training_rows import build_learning_training_set
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
        source_record_id=f"paper-cli-{index}",
        source_evidence_class="paper",
        candidate_id="candidate-grouped-cli",
        candidate_spec_id=None,
        campaign_id=None,
        market=MarketId("", "HYPE"),
        direction=Direction.LONG,
        opened_at_ms=opened,
        closed_at_ms=closed,
        feature_snapshot_id=f"feature-cli-{index}",
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


def _inputs(tmp_path, *, model_family: str = GROUPED_MEAN_MODEL_FAMILY):
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
    dataset_dir = tmp_path / "dataset"
    write_learning_dataset_bundle(snapshot, output_dir=dataset_dir)
    source_bundle = load_verified_learning_dataset_bundle(output_dir=dataset_dir)
    manifest = build_learning_challenger_run_manifest(
        source_bundle,
        input_kinds=(LearningEvidenceKind.PAPER_EXECUTION,),
        feature_registry=("market", "direction"),
        model_family=model_family,
        model_config={
            "min_train_rows": 5,
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
    manifest_path = write_learning_challenger_run_manifest(
        tmp_path / "challenger-run.json",
        manifest,
    )
    training_set = build_learning_training_set(source_bundle, manifest)
    training_dir = tmp_path / "training"
    write_learning_training_bundle(training_set, output_dir=training_dir)
    return training_dir, manifest_path


def test_grouped_mean_cli_writes_research_only_evaluation(tmp_path, capsys) -> None:
    training_dir, manifest_path = _inputs(tmp_path)
    output = tmp_path / "evaluation.json"

    code = main(
        (
            "--training-bundle-dir",
            str(training_dir),
            "--run-manifest",
            str(manifest_path),
            "--output",
            str(output),
        )
    )

    assert code == 0
    emitted = json.loads(capsys.readouterr().out)
    report = json.loads(output.read_text(encoding="utf-8"))
    assert emitted["evaluation_id"] == report["evaluation_id"]
    assert emitted["train_row_count"] == 6
    assert emitted["validation_row_count"] == 4
    assert emitted["validation_trade_count"] == 4
    assert emitted["validation_mean_target"] == "0.02"
    assert emitted["qualifies_development"] is True
    assert report["research_only"] is True
    assert report["promotion_eligible"] is False
    assert report["execution_ready"] is False


def test_grouped_mean_cli_rejects_different_model_family(tmp_path, capsys) -> None:
    training_dir, manifest_path = _inputs(
        tmp_path,
        model_family="fixed_shallow_tree",
    )

    code = main(
        (
            "--training-bundle-dir",
            str(training_dir),
            "--run-manifest",
            str(manifest_path),
            "--output",
            str(tmp_path / "evaluation.json"),
        )
    )

    assert code == 2
    emitted = json.loads(capsys.readouterr().err)
    assert "MODEL_FAMILY_MISMATCH" in emitted["error"]
