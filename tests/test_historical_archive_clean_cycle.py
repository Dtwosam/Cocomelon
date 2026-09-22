from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from cocomelon.research.historical_archive_clean_cycle import (
    build_archive_clean_operational_cycle_receipt,
    write_archive_clean_operational_cycle_receipt,
)
from cocomelon.research.historical_archive_clean_observer import (
    ArchiveCleanObserverCycleResult,
)


def _checkpoint() -> SimpleNamespace:
    return SimpleNamespace(
        checkpoint_id="2" * 64,
        settled_outcome_count=5,
        pending_observations=(
            SimpleNamespace(pending_signal_ids=("a" * 64, "b" * 64)),
        ),
    )


def _result() -> ArchiveCleanObserverCycleResult:
    return ArchiveCleanObserverCycleResult(
        status="recorded",
        cycle_started_ms=100,
        anchor_end_ms=99,
        observation_id="3" * 64,
        settled_outcome_ids=("4" * 64,),
        missing_settlement_signal_ids=("5" * 64,),
        capture_coverage="0.9",
        expected_elapsed_anchor_count=10,
        captured_elapsed_anchor_count=9,
    )


def test_cycle_receipt_binds_checkpoint_and_emitted_file_digests(
    tmp_path: Path,
) -> None:
    evidence_root = tmp_path / "evidence"
    source_root = tmp_path / "sources"
    (evidence_root / "anchors").mkdir(parents=True)
    (source_root / "feature").mkdir(parents=True)
    (evidence_root / "anchors" / "one.json").write_text(
        '{"anchor":1}\n',
        encoding="utf-8",
    )
    (source_root / "feature" / "one.json").write_text(
        '{"source":1}\n',
        encoding="utf-8",
    )

    receipt = build_archive_clean_operational_cycle_receipt(
        runtime_id="6" * 64,
        pin_id="7" * 64,
        campaign_id="8" * 64,
        validation_spec_id="9" * 64,
        candidate_id="c" * 64,
        restored_checkpoint_id="1" * 64,
        checkpoint=_checkpoint(),  # type: ignore[arg-type]
        result=_result(),
        completed_at_ms=110,
        cycle_evidence_root=evidence_root,
        source_root=source_root,
    )

    assert receipt.current_checkpoint_id == "2" * 64
    assert receipt.pending_signal_count == 2
    assert receipt.cycle_evidence_file_count == 1
    assert receipt.source_file_count == 1
    assert len(receipt.cycle_evidence_digest) == 64
    assert len(receipt.source_digest) == 64
    assert len(receipt.receipt_id) == 64

    path = write_archive_clean_operational_cycle_receipt(
        evidence_root,
        receipt,
    )
    assert write_archive_clean_operational_cycle_receipt(
        evidence_root,
        receipt,
    ) == path


def test_cycle_receipt_digest_changes_when_evidence_bytes_change(
    tmp_path: Path,
) -> None:
    evidence_root = tmp_path / "evidence"
    source_root = tmp_path / "sources"
    evidence_root.mkdir()
    source_root.mkdir()
    evidence_file = evidence_root / "anchor.json"
    evidence_file.write_text('{"anchor":1}\n', encoding="utf-8")

    first = build_archive_clean_operational_cycle_receipt(
        runtime_id="6" * 64,
        pin_id="7" * 64,
        campaign_id="8" * 64,
        validation_spec_id="9" * 64,
        candidate_id="c" * 64,
        restored_checkpoint_id="1" * 64,
        checkpoint=_checkpoint(),  # type: ignore[arg-type]
        result=_result(),
        completed_at_ms=110,
        cycle_evidence_root=evidence_root,
        source_root=source_root,
    )
    evidence_file.write_text('{"anchor":2}\n', encoding="utf-8")
    second = build_archive_clean_operational_cycle_receipt(
        runtime_id="6" * 64,
        pin_id="7" * 64,
        campaign_id="8" * 64,
        validation_spec_id="9" * 64,
        candidate_id="c" * 64,
        restored_checkpoint_id="1" * 64,
        checkpoint=_checkpoint(),  # type: ignore[arg-type]
        result=_result(),
        completed_at_ms=110,
        cycle_evidence_root=evidence_root,
        source_root=source_root,
    )

    assert first.cycle_evidence_digest != second.cycle_evidence_digest
    assert first.receipt_id != second.receipt_id
