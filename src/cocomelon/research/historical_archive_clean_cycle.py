from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from cocomelon.research.historical_archive_clean_checkpoint import (
    ArchiveCleanOperationalCheckpoint,
)
from cocomelon.research.historical_archive_clean_observer import (
    ArchiveCleanObserverCycleResult,
)

CYCLE_RECEIPT_SCHEMA_VERSION = 1


class HistoricalArchiveCleanCycleError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _require_sha256(value: str, field: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} must be lowercase SHA-256")


def _file_manifest(
    root: Path,
    *,
    exclude_names: frozenset[str] = frozenset(),
) -> tuple[dict[str, object], ...]:
    if not root.exists():
        return ()
    if not root.is_dir():
        raise HistoricalArchiveCleanCycleError("CYCLE_ROOT_NOT_DIRECTORY")
    values: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name in exclude_names:
            continue
        relative = path.relative_to(root).as_posix()
        data = path.read_bytes()
        values.append(
            {
                "relative_path": relative,
                "sha256": hashlib.sha256(data).hexdigest(),
                "byte_count": len(data),
            }
        )
    return tuple(values)


def _manifest_digest(values: tuple[dict[str, object], ...]) -> str:
    return hashlib.sha256(
        _canonical_json(values).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class ArchiveCleanOperationalCycleReceipt:
    runtime_id: str
    pin_id: str
    campaign_id: str
    validation_spec_id: str
    candidate_id: str
    restored_checkpoint_id: str
    current_checkpoint_id: str
    cycle_started_ms: int
    completed_at_ms: int
    status: str
    anchor_end_ms: int | None
    observation_id: str | None
    settled_outcome_ids: tuple[str, ...]
    missing_settlement_signal_ids: tuple[str, ...]
    capture_coverage: str | None
    expected_elapsed_anchor_count: int
    captured_elapsed_anchor_count: int
    cumulative_settled_outcome_count: int
    pending_signal_count: int
    cycle_evidence_digest: str
    cycle_evidence_file_count: int
    source_digest: str
    source_file_count: int
    paper_only: bool = True
    prospective_only: bool = True
    promotion_eligible: bool = False
    execution_ready: bool = False
    schema_version: int = CYCLE_RECEIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in (
            "runtime_id",
            "pin_id",
            "campaign_id",
            "validation_spec_id",
            "candidate_id",
            "restored_checkpoint_id",
            "current_checkpoint_id",
            "cycle_evidence_digest",
            "source_digest",
        ):
            _require_sha256(getattr(self, field), field)
        if self.cycle_started_ms < 0:
            raise ValueError("cycle_started_ms must be non-negative")
        if self.completed_at_ms < self.cycle_started_ms:
            raise ValueError("completed_at_ms cannot precede cycle start")
        if not self.status.strip():
            raise ValueError("status must not be empty")
        if self.anchor_end_ms is not None and self.anchor_end_ms < 0:
            raise ValueError("anchor_end_ms must be non-negative")
        if self.observation_id is not None:
            _require_sha256(self.observation_id, "observation_id")
        if (
            tuple(sorted(set(self.settled_outcome_ids)))
            != self.settled_outcome_ids
        ):
            raise ValueError("settled_outcome_ids must be sorted unique")
        if (
            tuple(sorted(set(self.missing_settlement_signal_ids)))
            != self.missing_settlement_signal_ids
        ):
            raise ValueError("missing settlement IDs must be sorted unique")
        for value in (
            *self.settled_outcome_ids,
            *self.missing_settlement_signal_ids,
        ):
            _require_sha256(value, "signal/outcome ID")
        if self.expected_elapsed_anchor_count < 0:
            raise ValueError("expected_elapsed_anchor_count must be non-negative")
        if (
            self.captured_elapsed_anchor_count < 0
            or self.captured_elapsed_anchor_count
            > self.expected_elapsed_anchor_count
        ):
            raise ValueError("captured anchor count is invalid")
        if self.cumulative_settled_outcome_count < 0:
            raise ValueError("cumulative settled count must be non-negative")
        if self.pending_signal_count < 0:
            raise ValueError("pending_signal_count must be non-negative")
        if self.cycle_evidence_file_count < 0 or self.source_file_count < 0:
            raise ValueError("file counts must be non-negative")
        if not self.paper_only or not self.prospective_only:
            raise ValueError("operational cycle must remain paper/prospective only")
        if self.promotion_eligible or self.execution_ready:
            raise ValueError("operational cycle must remain non-promotable")
        if self.schema_version != CYCLE_RECEIPT_SCHEMA_VERSION:
            raise ValueError("unsupported operational cycle receipt schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "runtime_id": self.runtime_id,
            "pin_id": self.pin_id,
            "campaign_id": self.campaign_id,
            "validation_spec_id": self.validation_spec_id,
            "candidate_id": self.candidate_id,
            "restored_checkpoint_id": self.restored_checkpoint_id,
            "current_checkpoint_id": self.current_checkpoint_id,
            "cycle_started_ms": self.cycle_started_ms,
            "completed_at_ms": self.completed_at_ms,
            "status": self.status,
            "anchor_end_ms": self.anchor_end_ms,
            "observation_id": self.observation_id,
            "settled_outcome_ids": self.settled_outcome_ids,
            "missing_settlement_signal_ids": (
                self.missing_settlement_signal_ids
            ),
            "capture_coverage": self.capture_coverage,
            "expected_elapsed_anchor_count": self.expected_elapsed_anchor_count,
            "captured_elapsed_anchor_count": self.captured_elapsed_anchor_count,
            "cumulative_settled_outcome_count": (
                self.cumulative_settled_outcome_count
            ),
            "pending_signal_count": self.pending_signal_count,
            "cycle_evidence_digest": self.cycle_evidence_digest,
            "cycle_evidence_file_count": self.cycle_evidence_file_count,
            "source_digest": self.source_digest,
            "source_file_count": self.source_file_count,
            "paper_only": self.paper_only,
            "prospective_only": self.prospective_only,
            "promotion_eligible": self.promotion_eligible,
            "execution_ready": self.execution_ready,
            "schema_version": self.schema_version,
        }

    @property
    def receipt_id(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "receipt_id": self.receipt_id}


def build_archive_clean_operational_cycle_receipt(
    *,
    runtime_id: str,
    pin_id: str,
    campaign_id: str,
    validation_spec_id: str,
    candidate_id: str,
    restored_checkpoint_id: str,
    checkpoint: ArchiveCleanOperationalCheckpoint,
    result: ArchiveCleanObserverCycleResult,
    completed_at_ms: int,
    cycle_evidence_root: Path,
    source_root: Path,
) -> ArchiveCleanOperationalCycleReceipt:
    evidence_files = _file_manifest(
        cycle_evidence_root,
        exclude_names=frozenset({"cycle.json"}),
    )
    source_files = _file_manifest(source_root)
    pending_signal_count = sum(
        len(item.pending_signal_ids)
        for item in checkpoint.pending_observations
    )
    return ArchiveCleanOperationalCycleReceipt(
        runtime_id=runtime_id,
        pin_id=pin_id,
        campaign_id=campaign_id,
        validation_spec_id=validation_spec_id,
        candidate_id=candidate_id,
        restored_checkpoint_id=restored_checkpoint_id,
        current_checkpoint_id=checkpoint.checkpoint_id,
        cycle_started_ms=result.cycle_started_ms,
        completed_at_ms=completed_at_ms,
        status=result.status,
        anchor_end_ms=result.anchor_end_ms,
        observation_id=result.observation_id,
        settled_outcome_ids=tuple(sorted(result.settled_outcome_ids)),
        missing_settlement_signal_ids=tuple(
            sorted(result.missing_settlement_signal_ids)
        ),
        capture_coverage=result.capture_coverage,
        expected_elapsed_anchor_count=result.expected_elapsed_anchor_count,
        captured_elapsed_anchor_count=result.captured_elapsed_anchor_count,
        cumulative_settled_outcome_count=checkpoint.settled_outcome_count,
        pending_signal_count=pending_signal_count,
        cycle_evidence_digest=_manifest_digest(evidence_files),
        cycle_evidence_file_count=len(evidence_files),
        source_digest=_manifest_digest(source_files),
        source_file_count=len(source_files),
    )


def write_archive_clean_operational_cycle_receipt(
    cycle_evidence_root: Path,
    receipt: ArchiveCleanOperationalCycleReceipt,
) -> Path:
    path = cycle_evidence_root / "cycle.json"
    payload = (_canonical_json(receipt.to_dict()) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise HistoricalArchiveCleanCycleError(
                "ARCHIVE_CLEAN_CYCLE_RECEIPT_CONFLICT"
            )
        return path
    temporary = path.with_name(".cycle.json.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return path
