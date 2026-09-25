from __future__ import annotations

from decimal import Decimal

import pytest

from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.research.learning_challenger_run import (
    LearningChallengerRunManifestError,
    build_learning_challenger_run_manifest,
    load_learning_challenger_run_manifest,
    verify_learning_challenger_run_manifest,
    write_learning_challenger_run_manifest,
)
from cocomelon.research.learning_dataset import build_learning_dataset_snapshot
from cocomelon.research.learning_dataset_bundle import (
    load_verified_learning_dataset_bundle,
    write_learning_dataset_bundle,
)
from cocomelon.research.outcome_learning import (
    LearningEvidenceKind,
    LearningEvidenceLedger,
    LearningEvidenceRecord,
)


def _paper_record() -> LearningEvidenceRecord:
    return LearningEvidenceRecord(
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


def _verified_bundle(tmp_path):
    ledger = LearningEvidenceLedger(tmp_path / "ledger")
    ledger.record(_paper_record())
    snapshot = build_learning_dataset_snapshot(ledger, as_of_ms=20_000)
    output_dir = tmp_path / "bundle"
    write_learning_dataset_bundle(snapshot, output_dir=output_dir)
    return load_verified_learning_dataset_bundle(output_dir=output_dir)


def _manifest(tmp_path, *, threshold: str = "0.001"):
    bundle = _verified_bundle(tmp_path)
    return build_learning_challenger_run_manifest(
        bundle,
        input_kinds=(LearningEvidenceKind.PAPER_EXECUTION,),
        feature_registry=("context_state_1h", "direction"),
        model_family="fixed_shallow_tree",
        model_config={
            "max_leaf_nodes": 7,
            "min_samples_leaf": 100,
            "max_iter": 100,
        },
        decision_policy={
            "threshold": threshold,
            "no_trade_below_threshold": True,
            "one_position_per_market": True,
        },
        implementation_commit_sha="a" * 40,
    )


def test_challenger_run_binds_verified_dataset_and_recipe(tmp_path) -> None:
    manifest = _manifest(tmp_path)

    assert len(manifest.run_id) == 64
    assert len(manifest.dataset_lineage_id) == 64
    assert len(manifest.feature_registry_id) == 64
    assert len(manifest.model_config_id) == 64
    assert len(manifest.decision_policy_id) == 64
    assert manifest.input_kinds == (LearningEvidenceKind.PAPER_EXECUTION.value,)
    payload = manifest.to_dict()
    assert payload["input_record_count"] == 1
    assert payload["research_only"] is True
    assert payload["promotion_eligible"] is False
    assert payload["execution_ready"] is False


def test_challenger_run_identity_changes_with_decision_policy(tmp_path) -> None:
    first = _manifest(tmp_path / "first", threshold="0.001")
    second = _manifest(tmp_path / "second", threshold="0.002")

    assert first.dataset_id == second.dataset_id
    assert first.input_record_ids == second.input_record_ids
    assert first.decision_policy_id != second.decision_policy_id
    assert first.run_id != second.run_id


def test_challenger_run_rejects_empty_selected_partition(tmp_path) -> None:
    bundle = _verified_bundle(tmp_path)

    with pytest.raises(ValueError, match="contain no eligible records"):
        build_learning_challenger_run_manifest(
            bundle,
            input_kinds=(LearningEvidenceKind.LIVE_EXECUTION,),
            feature_registry=("context_state_1h",),
            model_family="fixed_shallow_tree",
            model_config={"max_leaf_nodes": 7},
            decision_policy={"threshold": "0.001"},
            implementation_commit_sha="a" * 40,
        )


def test_challenger_run_rejects_unbound_implementation_revision(tmp_path) -> None:
    bundle = _verified_bundle(tmp_path)

    with pytest.raises(ValueError, match="implementation_commit_sha"):
        build_learning_challenger_run_manifest(
            bundle,
            input_kinds=(LearningEvidenceKind.PAPER_EXECUTION,),
            feature_registry=("context_state_1h",),
            model_family="fixed_shallow_tree",
            model_config={"max_leaf_nodes": 7},
            decision_policy={"threshold": "0.001"},
            implementation_commit_sha="not-a-commit",
        )



def test_challenger_run_manifest_round_trips_and_verifies_lineage(tmp_path) -> None:
    bundle = _verified_bundle(tmp_path)
    manifest = build_learning_challenger_run_manifest(
        bundle,
        input_kinds=(LearningEvidenceKind.PAPER_EXECUTION,),
        feature_registry=("context_state_1h", "direction"),
        model_family="fixed_shallow_tree",
        model_config={"max_leaf_nodes": 7},
        decision_policy={"threshold": "0.001"},
        implementation_commit_sha="a" * 40,
    )
    path = write_learning_challenger_run_manifest(
        tmp_path / "challenger-run.json",
        manifest,
    )

    assert load_learning_challenger_run_manifest(path) == manifest
    assert verify_learning_challenger_run_manifest(path, bundle=bundle) == manifest


def test_challenger_run_manifest_rejects_tampering(tmp_path) -> None:
    manifest = _manifest(tmp_path)
    path = write_learning_challenger_run_manifest(
        tmp_path / "challenger-run.json",
        manifest,
    )
    payload = path.read_text(encoding="utf-8").replace(
        '"threshold":"0.001"',
        '"threshold":"0.009"',
    )
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(
        LearningChallengerRunManifestError,
        match="IDENTITY_MISMATCH",
    ):
        load_learning_challenger_run_manifest(path)


def test_challenger_run_manifest_refuses_conflicting_overwrite(tmp_path) -> None:
    first = _manifest(tmp_path / "first", threshold="0.001")
    second = _manifest(tmp_path / "second", threshold="0.002")
    path = write_learning_challenger_run_manifest(
        tmp_path / "challenger-run.json",
        first,
    )

    with pytest.raises(
        LearningChallengerRunManifestError,
        match="MANIFEST_CONFLICT",
    ):
        write_learning_challenger_run_manifest(path, second)


def test_challenger_run_rejects_mixed_economic_target_families(tmp_path) -> None:
    bundle = _verified_bundle(tmp_path)

    with pytest.raises(ValueError, match="exactly one evidence kind"):
        build_learning_challenger_run_manifest(
            bundle,
            input_kinds=(
                LearningEvidenceKind.PAPER_EXECUTION,
                LearningEvidenceKind.LIVE_EXECUTION,
            ),
            feature_registry=("direction",),
            model_family="fixed_shallow_tree",
            model_config={"max_leaf_nodes": 7},
            decision_policy={"threshold": "0.001"},
            implementation_commit_sha="a" * 40,
        )
