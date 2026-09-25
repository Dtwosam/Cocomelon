from __future__ import annotations

import json
from decimal import Decimal

import pytest

from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.research.learning_dataset import build_learning_dataset_snapshot
from cocomelon.research.learning_dataset_bundle import (
    verify_learning_dataset_bundle,
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


def test_bundle_materializes_and_verifies_eligible_records(tmp_path) -> None:
    ledger = LearningEvidenceLedger(tmp_path / "ledger")
    record = _paper_record()
    ledger.record(record)
    snapshot = build_learning_dataset_snapshot(ledger, as_of_ms=20_000)

    payload = write_learning_dataset_bundle(
        snapshot,
        output_dir=tmp_path / "bundle",
    )
    verified = verify_learning_dataset_bundle(output_dir=tmp_path / "bundle")

    assert payload["dataset_id"] == snapshot.manifest.dataset_id
    assert payload["eligible_record_count"] == 1
    assert verified["verified"] is True
    assert verified["dataset_id"] == snapshot.manifest.dataset_id
    lines = (tmp_path / "bundle" / "records.jsonl").read_text().splitlines()
    assert json.loads(lines[0])["record_id"] == record.record_id


def test_bundle_rejects_nonempty_output_directory(tmp_path) -> None:
    ledger = LearningEvidenceLedger(tmp_path / "ledger")
    snapshot = build_learning_dataset_snapshot(ledger, as_of_ms=0)
    output_dir = tmp_path / "bundle"
    output_dir.mkdir()
    (output_dir / "existing").write_text("do not overwrite")

    with pytest.raises(ValueError, match="must be empty"):
        write_learning_dataset_bundle(snapshot, output_dir=output_dir)


def test_bundle_verification_rejects_tampered_records(tmp_path) -> None:
    ledger = LearningEvidenceLedger(tmp_path / "ledger")
    ledger.record(_paper_record())
    snapshot = build_learning_dataset_snapshot(ledger, as_of_ms=20_000)
    output_dir = tmp_path / "bundle"
    write_learning_dataset_bundle(snapshot, output_dir=output_dir)

    records_path = output_dir / "records.jsonl"
    records_path.write_text(records_path.read_text().replace('"net_r":"0.36"', '"net_r":"9"'))

    with pytest.raises(ValueError, match="records digest mismatch"):
        verify_learning_dataset_bundle(output_dir=output_dir)
