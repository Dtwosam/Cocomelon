from __future__ import annotations

from decimal import Decimal

import pytest

import cocomelon.research.learning_training_bundle as training_bundle
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
from cocomelon.research.learning_training_bundle import (
    LearningTrainingBundleError,
    load_verified_learning_training_bundle,
    verify_learning_training_bundle,
    write_learning_training_bundle,
)
from cocomelon.research.learning_training_rows import build_learning_training_set
from cocomelon.research.outcome_learning import (
    LearningEvidenceKind,
    LearningEvidenceLedger,
    LearningEvidenceRecord,
)


def _training_set(tmp_path):
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
            feature_snapshot_id="feature-paper",
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
    dataset_dir = tmp_path / "dataset"
    write_learning_dataset_bundle(snapshot, output_dir=dataset_dir)
    bundle = load_verified_learning_dataset_bundle(output_dir=dataset_dir)
    manifest = build_learning_challenger_run_manifest(
        bundle,
        input_kinds=(LearningEvidenceKind.PAPER_EXECUTION,),
        feature_registry=("market", "direction"),
        model_family="fixed_shallow_tree",
        model_config={"max_leaf_nodes": 7},
        decision_policy={"threshold": "0.001"},
        implementation_commit_sha="a" * 40,
    )
    return bundle, manifest, build_learning_training_set(bundle, manifest)


def test_training_bundle_round_trips_with_authenticated_rows(tmp_path) -> None:
    _bundle, manifest, training_set = _training_set(tmp_path)
    output_dir = tmp_path / "training"

    payload = write_learning_training_bundle(
        training_set,
        output_dir=output_dir,
    )
    verified = load_verified_learning_training_bundle(output_dir=output_dir)
    bound = verify_learning_training_bundle(
        output_dir=output_dir,
        manifest=manifest,
    )

    assert verified.training_set == training_set
    assert bound.training_set == training_set
    assert payload["training_set_id"] == training_set.training_set_id
    assert len(verified.manifest_sha256) == 64
    assert len(verified.rows_sha256) == 64
    assert len(verified.bundle_id) == 64


def test_training_bundle_rejects_tampered_rows(tmp_path) -> None:
    _bundle, _manifest, training_set = _training_set(tmp_path)
    output_dir = tmp_path / "training"
    write_learning_training_bundle(training_set, output_dir=output_dir)

    rows_path = output_dir / "rows.jsonl"
    rows_path.write_text(
        rows_path.read_text(encoding="utf-8").replace(
            '"target_value":"0.36"',
            '"target_value":"9"',
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        LearningTrainingBundleError,
        match="ROWS_DIGEST_MISMATCH",
    ):
        load_verified_learning_training_bundle(output_dir=output_dir)


def test_training_bundle_refuses_conflicting_output_directory(tmp_path) -> None:
    _bundle, _manifest, training_set = _training_set(tmp_path)
    output_dir = tmp_path / "training"
    output_dir.mkdir()
    (output_dir / "existing").write_text("do not overwrite", encoding="utf-8")

    with pytest.raises(LearningTrainingBundleError, match="must be empty"):
        write_learning_training_bundle(training_set, output_dir=output_dir)


def test_training_bundle_rejects_different_challenger_run(tmp_path) -> None:
    bundle, manifest, training_set = _training_set(tmp_path)
    output_dir = tmp_path / "training"
    write_learning_training_bundle(training_set, output_dir=output_dir)
    other_manifest = build_learning_challenger_run_manifest(
        bundle,
        input_kinds=(LearningEvidenceKind.PAPER_EXECUTION,),
        feature_registry=manifest.feature_registry,
        model_family=manifest.model_family,
        model_config=manifest.model_config,
        decision_policy={"threshold": "0.009"},
        implementation_commit_sha=manifest.implementation_commit_sha,
    )

    with pytest.raises(
        LearningTrainingBundleError,
        match="RUN_ID_MISMATCH",
    ):
        verify_learning_training_bundle(
            output_dir=output_dir,
            manifest=other_manifest,
        )



def test_training_bundle_atomic_write_cleans_temp_on_replace_failure(
    tmp_path,
    monkeypatch,
) -> None:
    _bundle, _manifest, training_set = _training_set(tmp_path)
    output_dir = tmp_path / "training"

    def fail_replace(_source, _target) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(training_bundle.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        write_learning_training_bundle(training_set, output_dir=output_dir)

    assert not (output_dir / ".rows.jsonl.tmp").exists()
    assert not (output_dir / "rows.jsonl").exists()
    assert not (output_dir / "manifest.json").exists()
