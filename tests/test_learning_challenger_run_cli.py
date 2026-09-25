from __future__ import annotations

import json
from decimal import Decimal

from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.learning_challenger_run_cli import main
from cocomelon.research.learning_dataset import build_learning_dataset_snapshot
from cocomelon.research.learning_dataset_bundle import write_learning_dataset_bundle
from cocomelon.research.outcome_learning import (
    LearningEvidenceKind,
    LearningEvidenceLedger,
    LearningEvidenceRecord,
)


def _bundle(tmp_path):
    ledger = LearningEvidenceLedger(tmp_path / "ledger")
    ledger.record(
        LearningEvidenceRecord(
            kind=LearningEvidenceKind.PAPER_EXECUTION,
            source_record_id="paper-1",
            source_evidence_class="microstructure",
            candidate_id="candidate-1",
            candidate_spec_id=None,
            campaign_id=None,
            market=MarketId("", "HYPE"),
            direction=Direction.LONG,
            opened_at_ms=10_000,
            closed_at_ms=20_000,
            feature_snapshot_id="feature-1",
            research_eligible_at_ms=20_000,
            gross_realized_pnl=Decimal("10"),
            entry_fees=Decimal("0.5"),
            exit_fees=Decimal("0.5"),
            funding_cash_pnl=Decimal("0"),
            entry_slippage_fraction=Decimal("0.001"),
            exit_slippage_fraction=Decimal("0.001"),
            net_pnl=Decimal("9"),
            net_r=Decimal("0.36"),
        )
    )
    snapshot = build_learning_dataset_snapshot(ledger, as_of_ms=20_000)
    bundle_dir = tmp_path / "bundle"
    write_learning_dataset_bundle(snapshot, output_dir=bundle_dir)
    return bundle_dir


def test_learning_challenger_run_cli_materializes_manifest(tmp_path, capsys) -> None:
    bundle_dir = _bundle(tmp_path)
    model_config = tmp_path / "model.json"
    policy = tmp_path / "policy.json"
    output = tmp_path / "run.json"
    model_config.write_text('{"max_leaf_nodes":7}\n', encoding="utf-8")
    policy.write_text('{"threshold":"0.001"}\n', encoding="utf-8")

    code = main(
        (
            "--bundle-dir",
            str(bundle_dir),
            "--output",
            str(output),
            "--input-kind",
            "paper_execution",
            "--feature",
            "context_state_1h",
            "--feature",
            "direction",
            "--model-family",
            "fixed_shallow_tree",
            "--model-config",
            str(model_config),
            "--decision-policy",
            str(policy),
            "--implementation-commit-sha",
            "a" * 40,
        )
    )

    assert code == 0
    emitted = json.loads(capsys.readouterr().out)
    stored = json.loads(output.read_text(encoding="utf-8"))
    assert emitted["run_id"] == stored["run_id"]
    assert emitted["dataset_lineage_id"] == stored["dataset_lineage_id"]
    assert emitted["input_record_count"] == 1
    assert emitted["research_only"] is True
    assert emitted["promotion_eligible"] is False
    assert emitted["execution_ready"] is False


def test_learning_challenger_run_cli_fails_closed_on_bad_config(tmp_path, capsys) -> None:
    bundle_dir = _bundle(tmp_path)
    model_config = tmp_path / "model.json"
    policy = tmp_path / "policy.json"
    model_config.write_text("[]\n", encoding="utf-8")
    policy.write_text('{"threshold":"0.001"}\n', encoding="utf-8")

    code = main(
        (
            "--bundle-dir",
            str(bundle_dir),
            "--output",
            str(tmp_path / "run.json"),
            "--input-kind",
            "paper_execution",
            "--feature",
            "direction",
            "--model-family",
            "fixed_shallow_tree",
            "--model-config",
            str(model_config),
            "--decision-policy",
            str(policy),
            "--implementation-commit-sha",
            "a" * 40,
        )
    )

    assert code == 2
    emitted = json.loads(capsys.readouterr().err)
    assert emitted["error_type"] == "ValueError"
    assert "model_config must be a JSON object" in emitted["error"]
