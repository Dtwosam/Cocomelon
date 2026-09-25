from __future__ import annotations

from decimal import Decimal

import pytest

from cocomelon.domain.features import FeatureSnapshot, TrendRegime, VolatilityRegime
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
from cocomelon.research.learning_feature_snapshots import LearningFeatureSnapshotStore
from cocomelon.research.learning_training_rows import build_learning_training_set
from cocomelon.research.outcome_learning import (
    LearningEvidenceKind,
    LearningEvidenceLedger,
    LearningEvidenceRecord,
)


def _paper_record(
    *,
    source_record_id: str = "paper-1",
    feature_snapshot_id: str = "feature-paper",
) -> LearningEvidenceRecord:
    return LearningEvidenceRecord(
        kind=LearningEvidenceKind.PAPER_EXECUTION,
        source_record_id=source_record_id,
        source_evidence_class="microstructure",
        candidate_id="candidate-1",
        candidate_spec_id=None,
        campaign_id=None,
        market=MarketId("", "HYPE"),
        direction=Direction.LONG,
        opened_at_ms=10_000,
        closed_at_ms=20_000,
        feature_snapshot_id=feature_snapshot_id,
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


def _prospective_record() -> LearningEvidenceRecord:
    return LearningEvidenceRecord(
        kind=LearningEvidenceKind.PROSPECTIVE_PAPER,
        source_record_id="prospective-1",
        source_evidence_class="prospective_clean",
        candidate_id="candidate-2",
        candidate_spec_id="spec-1",
        campaign_id="campaign-1",
        market=MarketId("", "HYPE"),
        direction=Direction.SHORT,
        opened_at_ms=30_000,
        closed_at_ms=40_000,
        feature_snapshot_id="feature-prospective",
        research_eligible_at_ms=40_000,
        context_state_1h="bearish_near_basket",
        gross_return_fraction=Decimal("0.012"),
        modeled_cost_fraction=Decimal("0.002"),
        net_return_fraction=Decimal("0.010"),
    )


def _bundle(tmp_path, record: LearningEvidenceRecord):
    ledger = LearningEvidenceLedger(tmp_path / "ledger")
    ledger.record(record)
    snapshot = build_learning_dataset_snapshot(
        ledger,
        as_of_ms=record.research_eligible_at_ms,
    )
    output_dir = tmp_path / "bundle"
    write_learning_dataset_bundle(snapshot, output_dir=output_dir)
    return load_verified_learning_dataset_bundle(output_dir=output_dir)


def _manifest(bundle, *, kind: LearningEvidenceKind, features: tuple[str, ...]):
    return build_learning_challenger_run_manifest(
        bundle,
        input_kinds=(kind,),
        feature_registry=features,
        model_family="fixed_shallow_tree",
        model_config={"max_leaf_nodes": 7},
        decision_policy={"threshold": "0.001"},
        implementation_commit_sha="a" * 40,
    )


def test_paper_execution_training_set_uses_realized_net_r(tmp_path) -> None:
    bundle = _bundle(tmp_path, _paper_record())
    manifest = _manifest(
        bundle,
        kind=LearningEvidenceKind.PAPER_EXECUTION,
        features=("market", "direction"),
    )

    training = build_learning_training_set(bundle, manifest)

    assert training.evidence_kind == LearningEvidenceKind.PAPER_EXECUTION.value
    assert training.target_name == "realized_net_r"
    assert len(training.rows) == 1
    row = training.rows[0]
    assert row.feature_values == ("HYPE", "long")
    assert row.target_value == Decimal("0.36")
    assert row.source_record_id == manifest.input_record_ids[0]
    assert len(training.training_set_id) == 64


def test_prospective_training_set_keeps_modeled_return_family_separate(tmp_path) -> None:
    bundle = _bundle(tmp_path, _prospective_record())
    manifest = _manifest(
        bundle,
        kind=LearningEvidenceKind.PROSPECTIVE_PAPER,
        features=("direction", "context_state_1h", "campaign_id"),
    )

    training = build_learning_training_set(bundle, manifest)

    assert training.evidence_kind == LearningEvidenceKind.PROSPECTIVE_PAPER.value
    assert training.target_name == "modeled_net_return_fraction"
    row = training.rows[0]
    assert row.feature_values == ("short", "bearish_near_basket", "campaign-1")
    assert row.target_value == Decimal("0.010")


def test_training_set_rejects_missing_requested_feature(tmp_path) -> None:
    bundle = _bundle(tmp_path, _paper_record())
    manifest = _manifest(
        bundle,
        kind=LearningEvidenceKind.PAPER_EXECUTION,
        features=("context_state_1h",),
    )

    with pytest.raises(ValueError, match="has no context_state_1h"):
        build_learning_training_set(bundle, manifest)


def test_training_set_rejects_unbound_dataset_lineage(tmp_path) -> None:
    first = _bundle(tmp_path / "first", _paper_record(source_record_id="paper-1"))
    second = _bundle(tmp_path / "second", _paper_record(source_record_id="paper-2"))
    manifest = _manifest(
        first,
        kind=LearningEvidenceKind.PAPER_EXECUTION,
        features=("direction",),
    )

    with pytest.raises(ValueError, match="dataset_id does not match"):
        build_learning_training_set(second, manifest)



def _feature_snapshot(
    *,
    market: str = "HYPE",
    as_of_ms: int = 9_000,
) -> FeatureSnapshot:
    return FeatureSnapshot(
        market=MarketId("", market),
        as_of_ms=as_of_ms,
        source_received_at_ms=as_of_ms - 100,
        schema_version=1,
        day_return=Decimal("0.04"),
        funding=Decimal("0.0001"),
        open_interest=Decimal("1000000"),
        day_notional_volume=Decimal("5000000"),
        oi_change_fraction=Decimal("0.03"),
        funding_change=Decimal("0.00001"),
        mark_oracle_dislocation_bps=Decimal("1.5"),
        return_5m=Decimal("0.01"),
        return_15m=Decimal("0.02"),
        return_1h=Decimal("0.03"),
        return_4h=Decimal("0.05"),
        realized_vol_15m=Decimal("0.008"),
        range_expansion_15m=Decimal("1.2"),
        relative_volume_15m=Decimal("1.4"),
        spread_bps=Decimal("2"),
        bid_depth_25bps=Decimal("250000"),
        ask_depth_25bps=Decimal("230000"),
        book_imbalance=Decimal("0.04"),
        book_age_ms=50,
        trend_regime=TrendRegime.UP,
        volatility_regime=VolatilityRegime.NORMAL,
        provenance=("hyperliquid-mainnet-info",),
    )


def test_training_set_resolves_authenticated_numeric_snapshot_features(tmp_path) -> None:
    snapshot = _feature_snapshot()
    bundle = _bundle(
        tmp_path,
        _paper_record(feature_snapshot_id=snapshot.snapshot_id),
    )
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    store.record(snapshot)
    manifest = _manifest(
        bundle,
        kind=LearningEvidenceKind.PAPER_EXECUTION,
        features=(
            "return_5m",
            "funding",
            "spread_bps",
            "book_age_ms",
            "trend_regime",
        ),
    )

    training = build_learning_training_set(
        bundle,
        manifest,
        feature_store=store,
    )

    assert training.rows[0].feature_values == (
        "0.01",
        "0.0001",
        "2",
        "50",
        "up",
    )


def test_training_set_requires_store_for_snapshot_backed_features(tmp_path) -> None:
    snapshot = _feature_snapshot()
    bundle = _bundle(
        tmp_path,
        _paper_record(feature_snapshot_id=snapshot.snapshot_id),
    )
    manifest = _manifest(
        bundle,
        kind=LearningEvidenceKind.PAPER_EXECUTION,
        features=("return_5m",),
    )

    with pytest.raises(ValueError, match="snapshot store is required"):
        build_learning_training_set(bundle, manifest)


def test_training_set_rejects_snapshot_after_trade_open(tmp_path) -> None:
    snapshot = _feature_snapshot(as_of_ms=11_000)
    bundle = _bundle(
        tmp_path,
        _paper_record(feature_snapshot_id=snapshot.snapshot_id),
    )
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    store.record(snapshot)
    manifest = _manifest(
        bundle,
        kind=LearningEvidenceKind.PAPER_EXECUTION,
        features=("return_5m",),
    )

    with pytest.raises(ValueError, match="after trade open"):
        build_learning_training_set(
            bundle,
            manifest,
            feature_store=store,
        )


def test_training_set_rejects_snapshot_market_mismatch(tmp_path) -> None:
    snapshot = _feature_snapshot(market="BTC")
    bundle = _bundle(
        tmp_path,
        _paper_record(feature_snapshot_id=snapshot.snapshot_id),
    )
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    store.record(snapshot)
    manifest = _manifest(
        bundle,
        kind=LearningEvidenceKind.PAPER_EXECUTION,
        features=("return_5m",),
    )

    with pytest.raises(ValueError, match="market does not match"):
        build_learning_training_set(
            bundle,
            manifest,
            feature_store=store,
        )
