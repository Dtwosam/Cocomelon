from __future__ import annotations

from decimal import Decimal

import pytest

from cocomelon.domain.features import FeatureSnapshot, TrendRegime, VolatilityRegime
from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.research.learning_feature_snapshots import LearningFeatureSnapshotStore
from cocomelon.research.learning_readiness import evaluate_learning_readiness
from cocomelon.research.outcome_learning import (
    LearningEvidenceKind,
    LearningEvidenceLedger,
    LearningEvidenceRecord,
)


def _record(
    *,
    source_record_id: str,
    feature_snapshot_id: str = "0123456789abcdef01234567",
    research_eligible_at_ms: int = 20_000,
) -> LearningEvidenceRecord:
    return LearningEvidenceRecord(
        kind=LearningEvidenceKind.PAPER_EXECUTION,
        source_record_id=source_record_id,
        source_evidence_class="microstructure",
        candidate_id="candidate-readiness",
        candidate_spec_id=None,
        campaign_id=None,
        market=MarketId("", "HYPE"),
        direction=Direction.LONG,
        opened_at_ms=10_000,
        closed_at_ms=20_000,
        feature_snapshot_id=feature_snapshot_id,
        research_eligible_at_ms=research_eligible_at_ms,
        gross_realized_pnl=Decimal("10"),
        entry_fees=Decimal("0.5"),
        exit_fees=Decimal("0.5"),
        funding_cash_pnl=Decimal("0"),
        entry_slippage_fraction=Decimal("0.001"),
        exit_slippage_fraction=Decimal("0.001"),
        net_pnl=Decimal("9"),
        net_r=Decimal("0.36"),
    )


def _snapshot(*, as_of_ms: int = 9_000) -> FeatureSnapshot:
    return FeatureSnapshot(
        market=MarketId("", "HYPE"),
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


def test_readiness_keeps_quarantined_records_out_of_structural_gate(tmp_path) -> None:
    ledger = LearningEvidenceLedger(tmp_path / "learning")
    eligible = _record(source_record_id="eligible")
    quarantined = _record(
        source_record_id="quarantined",
        research_eligible_at_ms=50_000,
    )
    ledger.record(eligible)
    ledger.record(quarantined)

    report = evaluate_learning_readiness(
        ledger,
        as_of_ms=30_000,
        evidence_kind=LearningEvidenceKind.PAPER_EXECUTION,
        feature_registry=("market", "direction"),
    )

    assert report.eligible_record_ids == (eligible.record_id,)
    assert report.quarantined_record_ids == (quarantined.record_id,)
    assert report.feature_complete_record_ids == (eligible.record_id,)
    assert report.blocked_records == ()
    assert report.structurally_ready is True
    assert report.research_only is True
    assert report.promotion_eligible is False
    assert report.execution_ready is False


def test_readiness_blocks_missing_snapshot_backed_features(tmp_path) -> None:
    ledger = LearningEvidenceLedger(tmp_path / "learning")
    record = _record(source_record_id="missing-snapshot")
    ledger.record(record)
    store = LearningFeatureSnapshotStore(tmp_path / "features")

    report = evaluate_learning_readiness(
        ledger,
        feature_store=store,
        as_of_ms=30_000,
        evidence_kind=LearningEvidenceKind.PAPER_EXECUTION,
        feature_registry=("return_5m",),
    )

    assert report.structurally_ready is False
    assert report.feature_complete_record_ids == ()
    assert len(report.blocked_records) == 1
    assert report.blocked_records[0].record_id == record.record_id
    assert "missing feature snapshot" in report.blocked_records[0].reason


def test_readiness_accepts_authenticated_point_in_time_snapshot(tmp_path) -> None:
    snapshot = _snapshot()
    ledger = LearningEvidenceLedger(tmp_path / "learning")
    record = _record(
        source_record_id="feature-complete",
        feature_snapshot_id=snapshot.snapshot_id,
    )
    ledger.record(record)
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    store.record(snapshot)

    report = evaluate_learning_readiness(
        ledger,
        feature_store=store,
        as_of_ms=30_000,
        evidence_kind=LearningEvidenceKind.PAPER_EXECUTION,
        feature_registry=("return_5m", "funding", "trend_regime"),
    )

    assert report.structurally_ready is True
    assert report.feature_complete_record_ids == (record.record_id,)
    assert report.feature_store_state_digest == store.state_digest
    assert report.blocked_records == ()


def test_readiness_blocks_snapshot_observed_after_trade_open(tmp_path) -> None:
    snapshot = _snapshot(as_of_ms=11_000)
    ledger = LearningEvidenceLedger(tmp_path / "learning")
    record = _record(
        source_record_id="late-feature",
        feature_snapshot_id=snapshot.snapshot_id,
    )
    ledger.record(record)
    store = LearningFeatureSnapshotStore(tmp_path / "features")
    store.record(snapshot)

    report = evaluate_learning_readiness(
        ledger,
        feature_store=store,
        as_of_ms=30_000,
        evidence_kind=LearningEvidenceKind.PAPER_EXECUTION,
        feature_registry=("return_5m",),
    )

    assert report.structurally_ready is False
    assert len(report.blocked_records) == 1
    assert "after trade open" in report.blocked_records[0].reason


def test_readiness_requires_at_least_one_eligible_record(tmp_path) -> None:
    ledger = LearningEvidenceLedger(tmp_path / "learning")
    quarantined = _record(
        source_record_id="future",
        research_eligible_at_ms=50_000,
    )
    ledger.record(quarantined)

    report = evaluate_learning_readiness(
        ledger,
        as_of_ms=30_000,
        evidence_kind=LearningEvidenceKind.PAPER_EXECUTION,
        feature_registry=("market",),
    )

    assert report.eligible_record_ids == ()
    assert report.quarantined_record_ids == (quarantined.record_id,)
    assert report.structurally_ready is False


def test_readiness_rejects_unsupported_feature_registry(tmp_path) -> None:
    ledger = LearningEvidenceLedger(tmp_path / "learning")
    ledger.record(_record(source_record_id="unsupported"))

    with pytest.raises(ValueError, match="unsupported learning training feature"):
        evaluate_learning_readiness(
            ledger,
            as_of_ms=30_000,
            evidence_kind=LearningEvidenceKind.PAPER_EXECUTION,
            feature_registry=("future_leak",),
        )
