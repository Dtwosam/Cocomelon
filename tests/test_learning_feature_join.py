from __future__ import annotations

from decimal import Decimal

import pytest

from cocomelon.domain.features import FeatureSnapshot, TrendRegime, VolatilityRegime
from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.research.learning_dataset import build_learning_dataset_snapshot
from cocomelon.research.learning_dataset_bundle import (
    load_verified_learning_dataset_bundle,
    write_learning_dataset_bundle,
)
from cocomelon.research.learning_feature_join import (
    NUMERIC_FEATURE_REGISTRY,
    LearningFeatureJoinError,
    build_learning_feature_join,
)
from cocomelon.research.learning_feature_snapshots import LearningFeatureSnapshotStore
from cocomelon.research.outcome_learning import (
    LearningEvidenceKind,
    LearningEvidenceLedger,
    LearningEvidenceRecord,
)


def _snapshot(
    *,
    market: str = "HYPE",
    as_of_ms: int = 19_000,
    source_received_at_ms: int = 18_900,
    return_5m: str = "0.01",
) -> FeatureSnapshot:
    return FeatureSnapshot(
        market=MarketId("", market),
        as_of_ms=as_of_ms,
        source_received_at_ms=source_received_at_ms,
        schema_version=1,
        day_return=Decimal("0.04"),
        funding=Decimal("0.0001"),
        open_interest=Decimal("1000000"),
        day_notional_volume=Decimal("5000000"),
        oi_change_fraction=Decimal("0.03"),
        funding_change=Decimal("0.00001"),
        mark_oracle_dislocation_bps=Decimal("1.5"),
        return_5m=Decimal(return_5m),
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


def _record(
    snapshot: FeatureSnapshot,
    *,
    market: str = "HYPE",
    opened_at_ms: int = 20_000,
) -> LearningEvidenceRecord:
    return LearningEvidenceRecord(
        kind=LearningEvidenceKind.PAPER_EXECUTION,
        source_record_id="paper-feature-1",
        source_evidence_class="paper",
        candidate_id="candidate-feature",
        candidate_spec_id=None,
        campaign_id=None,
        market=MarketId("", market),
        direction=Direction.LONG,
        opened_at_ms=opened_at_ms,
        closed_at_ms=30_000,
        feature_snapshot_id=snapshot.snapshot_id,
        research_eligible_at_ms=30_000,
        gross_realized_pnl=Decimal("10"),
        entry_fees=Decimal("0.5"),
        exit_fees=Decimal("0.5"),
        funding_cash_pnl=Decimal("0"),
        entry_slippage_fraction=Decimal("0.001"),
        exit_slippage_fraction=Decimal("0.001"),
        net_pnl=Decimal("9"),
        net_r=Decimal("0.36"),
    )


def _bundle(tmp_path, record: LearningEvidenceRecord):
    ledger = LearningEvidenceLedger(tmp_path / "ledger")
    ledger.record(record)
    snapshot = build_learning_dataset_snapshot(ledger, as_of_ms=30_000)
    output_dir = tmp_path / "dataset"
    write_learning_dataset_bundle(snapshot, output_dir=output_dir)
    return load_verified_learning_dataset_bundle(output_dir=output_dir)


def test_feature_join_binds_outcome_to_exact_pretrade_numeric_snapshot(tmp_path) -> None:
    feature = _snapshot()
    record = _record(feature)
    bundle = _bundle(tmp_path, record)
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    store.record(feature)

    joined = build_learning_feature_join(bundle, store)

    assert joined.dataset_id == bundle.snapshot.manifest.dataset_id
    assert joined.dataset_lineage_id == bundle.lineage_id
    assert joined.feature_registry == NUMERIC_FEATURE_REGISTRY
    assert len(joined.rows) == 1
    row = joined.rows[0]
    assert row.record_id == record.record_id
    assert row.feature_snapshot_id == feature.snapshot_id
    assert row.feature_as_of_ms == 19_000
    assert row.feature_source_received_at_ms == 18_900
    return_5m_index = NUMERIC_FEATURE_REGISTRY.index("return_5m")
    assert row.values[return_5m_index] == "0.01"
    assert len(joined.used_feature_records_sha256) == 64
    assert len(joined.join_id) == 64


def test_feature_join_rejects_missing_snapshot(tmp_path) -> None:
    feature = _snapshot()
    bundle = _bundle(tmp_path, _record(feature))
    store = LearningFeatureSnapshotStore(tmp_path / "features")

    with pytest.raises(
        LearningFeatureJoinError,
        match="SNAPSHOT_MISSING",
    ):
        build_learning_feature_join(bundle, store)


def test_feature_join_rejects_snapshot_after_trade_open(tmp_path) -> None:
    feature = _snapshot(
        as_of_ms=21_000,
        source_received_at_ms=20_900,
    )
    bundle = _bundle(
        tmp_path,
        _record(feature, opened_at_ms=20_000),
    )
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    store.record(feature)

    with pytest.raises(
        LearningFeatureJoinError,
        match="LOOKAHEAD_AS_OF",
    ):
        build_learning_feature_join(bundle, store)


def test_feature_join_rejects_market_mismatch(tmp_path) -> None:
    feature = _snapshot(market="BTC")
    bundle = _bundle(tmp_path, _record(feature, market="HYPE"))
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    store.record(feature)

    with pytest.raises(
        LearningFeatureJoinError,
        match="MARKET_MISMATCH",
    ):
        build_learning_feature_join(bundle, store)


def test_feature_join_identity_ignores_unrelated_store_growth(tmp_path) -> None:
    feature = _snapshot()
    bundle = _bundle(tmp_path, _record(feature))
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    store.record(feature)

    first = build_learning_feature_join(bundle, store)
    store.record(
        _snapshot(
            market="BTC",
            as_of_ms=25_000,
            source_received_at_ms=24_900,
            return_5m="-0.01",
        )
    )
    second = build_learning_feature_join(bundle, store)

    assert first == second
    assert first.join_id == second.join_id
