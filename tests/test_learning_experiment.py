from __future__ import annotations

import json
from decimal import Decimal

import pytest

from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.research.learning_experiment import run_learning_experiment
from cocomelon.research.learning_grouped_mean import GROUPED_MEAN_MODEL_FAMILY
from cocomelon.research.outcome_learning import (
    LearningEvidenceKind,
    LearningEvidenceLedger,
    LearningEvidenceRecord,
)


def _record(index: int) -> LearningEvidenceRecord:
    opened = index * 10_000
    closed = opened + 1_000
    return LearningEvidenceRecord(
        kind=LearningEvidenceKind.PAPER_EXECUTION,
        source_record_id=f"paper-experiment-{index}",
        source_evidence_class="microstructure",
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
        net_r=Decimal("0.05"),
    )


def _ledger(tmp_path):
    root = tmp_path / "learning"
    ledger = LearningEvidenceLedger(root)
    for index in range(1, 11):
        ledger.record(_record(index))
    return root


def _run(tmp_path, *, output_name: str = "experiment"):
    learning_root = _ledger(tmp_path)
    feature_store_dir = tmp_path / "features"
    output_root = tmp_path / output_name
    result = run_learning_experiment(
        learning_root=learning_root,
        feature_store_dir=feature_store_dir,
        output_root=output_root,
        as_of_ms=101_000,
        evidence_kind=LearningEvidenceKind.PAPER_EXECUTION,
        feature_registry=("market", "direction"),
        model_family=GROUPED_MEAN_MODEL_FAMILY,
        model_config={
            "min_train_rows": 4,
            "validation_rows": 4,
            "min_group_train_rows": 2,
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
    return result, output_root


def test_learning_experiment_materializes_fully_bound_artifact_chain(tmp_path) -> None:
    result, output_root = _run(tmp_path)

    summary = json.loads(
        (output_root / "experiment.json").read_text(encoding="utf-8")
    )
    dataset_manifest = json.loads(
        (output_root / "dataset" / "manifest.json").read_text(encoding="utf-8")
    )
    run_manifest = json.loads(
        (output_root / "challenger-run.json").read_text(encoding="utf-8")
    )
    training_manifest = json.loads(
        (output_root / "training" / "manifest.json").read_text(encoding="utf-8")
    )
    evaluation = json.loads(
        (output_root / "evaluation.json").read_text(encoding="utf-8")
    )

    assert summary["experiment_id"] == result.experiment_id
    assert summary["dataset_id"] == dataset_manifest["dataset_id"]
    assert summary["run_id"] == run_manifest["run_id"]
    assert summary["training_set_id"] == training_manifest["training_set_id"]
    assert summary["evaluation_id"] == evaluation["evaluation_id"]
    assert summary["model_family"] == GROUPED_MEAN_MODEL_FAMILY
    assert summary["qualifies_development"] is True
    assert summary["research_only"] is True
    assert summary["promotion_eligible"] is False
    assert summary["execution_ready"] is False
    assert result.qualifies_development is True


def test_learning_experiment_refuses_nonempty_output_root(tmp_path) -> None:
    learning_root = _ledger(tmp_path)
    output_root = tmp_path / "experiment"
    output_root.mkdir()
    (output_root / "existing").write_text("do not overwrite", encoding="utf-8")

    with pytest.raises(
        RuntimeError,
        match="output directory must be empty",
    ):
        run_learning_experiment(
            learning_root=learning_root,
            feature_store_dir=tmp_path / "features",
            output_root=output_root,
            as_of_ms=101_000,
            evidence_kind=LearningEvidenceKind.PAPER_EXECUTION,
            feature_registry=("market", "direction"),
            model_family=GROUPED_MEAN_MODEL_FAMILY,
            model_config={
                "min_train_rows": 4,
                "validation_rows": 4,
                "min_group_train_rows": 2,
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
