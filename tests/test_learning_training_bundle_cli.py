from __future__ import annotations

import json
from decimal import Decimal

from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.learning_training_bundle_cli import main
from cocomelon.research.learning_challenger_run import (
    build_learning_challenger_run_manifest,
    write_learning_challenger_run_manifest,
)
from cocomelon.research.learning_dataset import build_learning_dataset_snapshot
from cocomelon.research.learning_dataset_bundle import (
    load_verified_learning_dataset_bundle,
    write_learning_dataset_bundle,
)
from cocomelon.research.learning_training_input import (
    load_verified_learning_training_bundle,
)
from cocomelon.research.outcome_learning import (
    LearningEvidenceKind,
    LearningEvidenceLedger,
    LearningEvidenceRecord,
)


def _paper_record() -> LearningEvidenceRecord:
    return LearningEvidenceRecord(
        kind=LearningEvidenceKind.PAPER_EXECUTION,
        source_record_id="paper-cli-1",
        source_evidence_class="paper",
        candidate_id="candidate-cli",
        candidate_spec_id=None,
        campaign_id=None,
        market=MarketId("", "HYPE"),
        direction=Direction.LONG,
        opened_at_ms=10_000,
        closed_at_ms=20_000,
        feature_snapshot_id="feature-cli",
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


def _inputs(tmp_path):
    ledger = LearningEvidenceLedger(tmp_path / "ledger")
    ledger.record(_paper_record())
    snapshot = build_learning_dataset_snapshot(ledger, as_of_ms=20_000)
    source_bundle_dir = tmp_path / "source-bundle"
    write_learning_dataset_bundle(snapshot, output_dir=source_bundle_dir)
    bundle = load_verified_learning_dataset_bundle(output_dir=source_bundle_dir)
    manifest = build_learning_challenger_run_manifest(
        bundle,
        input_kinds=(LearningEvidenceKind.PAPER_EXECUTION,),
        feature_registry=("market", "direction"),
        model_family="fixed_shallow_tree",
        model_config={"max_leaf_nodes": 7},
        decision_policy={"threshold": "0.001"},
        implementation_commit_sha="a" * 40,
    )
    run_manifest_path = tmp_path / "challenger-run.json"
    write_learning_challenger_run_manifest(run_manifest_path, manifest)
    return source_bundle_dir, run_manifest_path


def test_learning_training_bundle_cli_materializes_verified_bundle(
    tmp_path,
    capsys,
) -> None:
    source_bundle_dir, run_manifest_path = _inputs(tmp_path)
    output_dir = tmp_path / "training-bundle"

    code = main(
        (
            "--source-bundle-dir",
            str(source_bundle_dir),
            "--run-manifest",
            str(run_manifest_path),
            "--output-dir",
            str(output_dir),
        )
    )

    assert code == 0
    emitted = json.loads(capsys.readouterr().out)
    loaded = load_verified_learning_training_bundle(output_dir=output_dir)
    assert emitted["command"] == "learning-training-bundle"
    assert emitted["run_id"] == loaded.table.run_id
    assert emitted["table_id"] == loaded.table.table_id
    assert emitted["row_count"] == 1
    assert emitted["target_name"] == "net_r"
    assert (output_dir / "manifest.json").is_file()
    assert (output_dir / "rows.jsonl").is_file()


def test_learning_training_bundle_cli_fails_closed_on_tampered_source(
    tmp_path,
    capsys,
) -> None:
    source_bundle_dir, run_manifest_path = _inputs(tmp_path)
    records_path = source_bundle_dir / "records.jsonl"
    records_path.write_text(
        records_path.read_text(encoding="utf-8").replace(
            '"net_r":"0.36"',
            '"net_r":"9"',
        ),
        encoding="utf-8",
    )

    code = main(
        (
            "--source-bundle-dir",
            str(source_bundle_dir),
            "--run-manifest",
            str(run_manifest_path),
            "--output-dir",
            str(tmp_path / "training-bundle"),
        )
    )

    assert code == 2
    emitted = json.loads(capsys.readouterr().err)
    assert emitted["error_type"] == "ValueError"
    assert "records digest mismatch" in emitted["error"]
