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
from cocomelon.research.learning_training_input import (
    LearningTrainingInputError,
    build_learning_training_table,
)
from cocomelon.research.outcome_learning import (
    LearningEvidenceKind,
    LearningEvidenceLedger,
    LearningEvidenceRecord,
)


def _prospective_record() -> LearningEvidenceRecord:
    return LearningEvidenceRecord(
        kind=LearningEvidenceKind.PROSPECTIVE_PAPER,
        source_record_id="prospective-1",
        source_evidence_class="prospective_clean",
        candidate_id="candidate-prospective",
        candidate_spec_id="b" * 64,
        campaign_id="campaign-v2",
        market=MarketId("", "HYPE"),
        direction=Direction.LONG,
        opened_at_ms=10_000,
        closed_at_ms=20_000,
        feature_snapshot_id="feature-prospective",
        research_eligible_at_ms=20_000,
        context_state_1h="bearish_near_basket",
        gross_return_fraction=Decimal("0.012"),
        modeled_cost_fraction=Decimal("0.002"),
        net_return_fraction=Decimal("0.010"),
    )


def _paper_record() -> LearningEvidenceRecord:
    return LearningEvidenceRecord(
        kind=LearningEvidenceKind.PAPER_EXECUTION,
        source_record_id="paper-1",
        source_evidence_class="paper",
        candidate_id="candidate-paper",
        candidate_spec_id=None,
        campaign_id=None,
        market=MarketId("", "HYPE"),
        direction=Direction.SHORT,
        opened_at_ms=30_000,
        closed_at_ms=40_000,
        feature_snapshot_id="feature-paper",
        research_eligible_at_ms=40_000,
        gross_realized_pnl=Decimal("12"),
        entry_fees=Decimal("0.5"),
        exit_fees=Decimal("0.5"),
        funding_cash_pnl=Decimal("0"),
        entry_slippage_fraction=Decimal("0.001"),
        exit_slippage_fraction=Decimal("0.001"),
        net_pnl=Decimal("11"),
        net_r=Decimal("0.44"),
    )


def _bundle(tmp_path, records, *, as_of_ms: int):
    ledger = LearningEvidenceLedger(tmp_path / "ledger")
    for record in records:
        ledger.record(record)
    snapshot = build_learning_dataset_snapshot(ledger, as_of_ms=as_of_ms)
    output_dir = tmp_path / "bundle"
    write_learning_dataset_bundle(snapshot, output_dir=output_dir)
    return load_verified_learning_dataset_bundle(output_dir=output_dir)


def _manifest(bundle, *, kinds, features):
    return build_learning_challenger_run_manifest(
        bundle,
        input_kinds=kinds,
        feature_registry=features,
        model_family="fixed_shallow_tree",
        model_config={"max_leaf_nodes": 7, "min_samples_leaf": 20},
        decision_policy={
            "threshold": "0.001",
            "no_trade_below_threshold": True,
        },
        implementation_commit_sha="a" * 40,
    )


def test_prospective_training_table_uses_modeled_net_return_target(tmp_path) -> None:
    bundle = _bundle(
        tmp_path,
        (_prospective_record(),),
        as_of_ms=20_000,
    )
    manifest = _manifest(
        bundle,
        kinds=(LearningEvidenceKind.PROSPECTIVE_PAPER,),
        features=("market", "direction", "context_state_1h"),
    )

    table = build_learning_training_table(bundle, manifest)

    assert table.target_name == "net_return_fraction"
    assert table.evidence_kind == "prospective_paper"
    assert table.feature_registry == ("market", "direction", "context_state_1h")
    assert table.rows[0].target_value == Decimal("0.010")
    assert table.rows[0].features == {
        "market": "HYPE",
        "direction": "LONG",
        "context_state_1h": "bearish_near_basket",
    }
    assert len(table.table_id) == 64
    assert len(table.rows_sha256) == 64


def test_execution_training_table_uses_realized_net_r_target(tmp_path) -> None:
    bundle = _bundle(tmp_path, (_paper_record(),), as_of_ms=40_000)
    manifest = _manifest(
        bundle,
        kinds=(LearningEvidenceKind.PAPER_EXECUTION,),
        features=("market", "direction", "source_evidence_class"),
    )

    table = build_learning_training_table(bundle, manifest)

    assert table.target_name == "net_r"
    assert table.evidence_kind == "paper_execution"
    assert table.rows[0].target_value == Decimal("0.44")
    assert table.rows[0].features == {
        "market": "HYPE",
        "direction": "SHORT",
        "source_evidence_class": "paper",
    }


def test_training_table_rejects_mixed_evidence_kinds(tmp_path) -> None:
    bundle = _bundle(
        tmp_path,
        (_prospective_record(), _paper_record()),
        as_of_ms=40_000,
    )
    manifest = _manifest(
        bundle,
        kinds=(
            LearningEvidenceKind.PROSPECTIVE_PAPER,
            LearningEvidenceKind.PAPER_EXECUTION,
        ),
        features=("market", "direction"),
    )

    with pytest.raises(
        LearningTrainingInputError,
        match="REQUIRES_ONE_EVIDENCE_KIND",
    ):
        build_learning_training_table(bundle, manifest)


def test_training_table_rejects_run_from_different_bundle_lineage(tmp_path) -> None:
    first = _bundle(
        tmp_path / "first",
        (_paper_record(),),
        as_of_ms=40_000,
    )
    second = _bundle(
        tmp_path / "second",
        (_paper_record(),),
        as_of_ms=50_000,
    )
    manifest = _manifest(
        first,
        kinds=(LearningEvidenceKind.PAPER_EXECUTION,),
        features=("market", "direction"),
    )

    with pytest.raises(
        LearningTrainingInputError,
        match="RUN_LINEAGE_MISMATCH",
    ):
        build_learning_training_table(second, manifest)


def test_training_table_rejects_unavailable_feature_registry(tmp_path) -> None:
    bundle = _bundle(tmp_path, (_paper_record(),), as_of_ms=40_000)
    manifest = _manifest(
        bundle,
        kinds=(LearningEvidenceKind.PAPER_EXECUTION,),
        features=("market", "future_price"),
    )

    with pytest.raises(
        LearningTrainingInputError,
        match="FEATURE_REGISTRY_UNSUPPORTED",
    ):
        build_learning_training_table(bundle, manifest)
