from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from cocomelon.research.historical_archive_clean_checkpoint import (
    build_archive_clean_initial_checkpoint,
)
from cocomelon.research.historical_archive_clean_cycle import (
    ArchiveCleanOperationalCycleReceipt,
    load_archive_clean_operational_cycle_receipt,
)
from cocomelon.research.historical_archive_validation_spec import (
    HistoricalArchiveCleanValidationSpec,
)

LINEAGE_SCHEMA_VERSION = 1
VALID_CYCLE_STATUSES = {
    "before_validation_window",
    "recorded",
    "already_recorded",
    "missed_anchor_window",
    "after_validation_window",
    "no_anchor_recorded",
}


class HistoricalArchiveCleanLineageError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _require_sha256(value: str, field: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} must be lowercase SHA-256")


@dataclass(frozen=True, slots=True)
class ArchiveCleanCycleLineageReport:
    runtime_id: str
    pin_id: str
    campaign_id: str
    validation_spec_id: str
    candidate_id: str
    initial_checkpoint_id: str
    latest_checkpoint_id: str
    receipt_count: int
    receipt_sequence_sha256: str
    first_cycle_started_ms: int
    last_cycle_completed_at_ms: int
    latest_expected_elapsed_anchor_count: int
    latest_captured_elapsed_anchor_count: int
    cumulative_settled_outcome_count: int
    unique_settled_outcome_count: int
    status: str = "append_only_valid"
    paper_only: bool = True
    prospective_only: bool = True
    promotion_eligible: bool = False
    execution_ready: bool = False
    schema_version: int = LINEAGE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in (
            "runtime_id",
            "pin_id",
            "campaign_id",
            "validation_spec_id",
            "candidate_id",
            "initial_checkpoint_id",
            "latest_checkpoint_id",
            "receipt_sequence_sha256",
        ):
            _require_sha256(getattr(self, field), field)
        if self.receipt_count <= 0:
            raise ValueError("receipt_count must be positive")
        if self.first_cycle_started_ms < 0:
            raise ValueError("first_cycle_started_ms must be non-negative")
        if self.last_cycle_completed_at_ms < self.first_cycle_started_ms:
            raise ValueError("last cycle cannot complete before first cycle starts")
        if self.latest_expected_elapsed_anchor_count < 0:
            raise ValueError("latest expected anchor count must be non-negative")
        if (
            self.latest_captured_elapsed_anchor_count < 0
            or self.latest_captured_elapsed_anchor_count
            > self.latest_expected_elapsed_anchor_count
        ):
            raise ValueError("latest captured anchor count is invalid")
        if self.cumulative_settled_outcome_count < 0:
            raise ValueError("cumulative settled outcome count must be non-negative")
        if self.unique_settled_outcome_count != self.cumulative_settled_outcome_count:
            raise ValueError("settled outcome identities must be globally unique")
        if self.status != "append_only_valid":
            raise ValueError("unsupported clean lineage status")
        if not self.paper_only or not self.prospective_only:
            raise ValueError("clean lineage must remain paper/prospective only")
        if self.promotion_eligible or self.execution_ready:
            raise ValueError("clean lineage cannot authorize promotion or execution")
        if self.schema_version != LINEAGE_SCHEMA_VERSION:
            raise ValueError("unsupported clean lineage schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "runtime_id": self.runtime_id,
            "pin_id": self.pin_id,
            "campaign_id": self.campaign_id,
            "validation_spec_id": self.validation_spec_id,
            "candidate_id": self.candidate_id,
            "initial_checkpoint_id": self.initial_checkpoint_id,
            "latest_checkpoint_id": self.latest_checkpoint_id,
            "receipt_count": self.receipt_count,
            "receipt_sequence_sha256": self.receipt_sequence_sha256,
            "first_cycle_started_ms": self.first_cycle_started_ms,
            "last_cycle_completed_at_ms": self.last_cycle_completed_at_ms,
            "latest_expected_elapsed_anchor_count": (
                self.latest_expected_elapsed_anchor_count
            ),
            "latest_captured_elapsed_anchor_count": (
                self.latest_captured_elapsed_anchor_count
            ),
            "cumulative_settled_outcome_count": (
                self.cumulative_settled_outcome_count
            ),
            "unique_settled_outcome_count": self.unique_settled_outcome_count,
            "status": self.status,
            "paper_only": self.paper_only,
            "prospective_only": self.prospective_only,
            "promotion_eligible": self.promotion_eligible,
            "execution_ready": self.execution_ready,
            "schema_version": self.schema_version,
        }

    @property
    def lineage_id(self) -> str:
        return _sha256(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "lineage_id": self.lineage_id}


def _ordered_receipts(
    receipts: Iterable[ArchiveCleanOperationalCycleReceipt],
) -> tuple[ArchiveCleanOperationalCycleReceipt, ...]:
    values = tuple(receipts)
    if not values:
        raise HistoricalArchiveCleanLineageError(
            "ARCHIVE_CLEAN_LINEAGE_RECEIPTS_REQUIRED"
        )
    receipt_ids = tuple(item.receipt_id for item in values)
    if len(set(receipt_ids)) != len(receipt_ids):
        raise HistoricalArchiveCleanLineageError(
            "ARCHIVE_CLEAN_LINEAGE_DUPLICATE_RECEIPT"
        )
    return tuple(
        sorted(
            values,
            key=lambda item: (
                item.cycle_started_ms,
                item.completed_at_ms,
                item.receipt_id,
            ),
        )
    )


def verify_archive_clean_cycle_lineage(
    spec: HistoricalArchiveCleanValidationSpec,
    *,
    runtime_id: str,
    pin_id: str,
    receipts: Iterable[ArchiveCleanOperationalCycleReceipt],
) -> ArchiveCleanCycleLineageReport:
    _require_sha256(runtime_id, "runtime_id")
    _require_sha256(pin_id, "pin_id")
    ordered = _ordered_receipts(receipts)
    initial = build_archive_clean_initial_checkpoint(
        spec,
        runtime_id=runtime_id,
        pin_id=pin_id,
    )
    expected_lineage = (
        runtime_id,
        pin_id,
        initial.campaign_id,
        spec.spec_id,
        spec.candidate_id,
    )
    previous_checkpoint_id = initial.checkpoint_id
    previous_completed_at_ms = -1
    previous_expected = 0
    previous_captured = 0
    previous_settled = 0
    settled_ids: set[str] = set()

    for index, receipt in enumerate(ordered):
        actual_lineage = (
            receipt.runtime_id,
            receipt.pin_id,
            receipt.campaign_id,
            receipt.validation_spec_id,
            receipt.candidate_id,
        )
        if actual_lineage != expected_lineage:
            raise HistoricalArchiveCleanLineageError(
                "ARCHIVE_CLEAN_LINEAGE_IDENTITY_MISMATCH"
            )
        if receipt.restored_checkpoint_id != previous_checkpoint_id:
            raise HistoricalArchiveCleanLineageError(
                "ARCHIVE_CLEAN_LINEAGE_CHECKPOINT_FORK"
            )
        if receipt.status not in VALID_CYCLE_STATUSES:
            raise HistoricalArchiveCleanLineageError(
                "ARCHIVE_CLEAN_LINEAGE_STATUS_INVALID"
            )
        if index and receipt.cycle_started_ms < previous_completed_at_ms:
            raise HistoricalArchiveCleanLineageError(
                "ARCHIVE_CLEAN_LINEAGE_CYCLE_OVERLAP"
            )
        if (
            receipt.expected_elapsed_anchor_count < previous_expected
            or receipt.expected_elapsed_anchor_count > spec.expected_anchor_count
        ):
            raise HistoricalArchiveCleanLineageError(
                "ARCHIVE_CLEAN_LINEAGE_EXPECTED_COUNT_REGRESSION"
            )
        if receipt.captured_elapsed_anchor_count < previous_captured:
            raise HistoricalArchiveCleanLineageError(
                "ARCHIVE_CLEAN_LINEAGE_CAPTURE_COUNT_REGRESSION"
            )
        captured_delta = (
            receipt.captured_elapsed_anchor_count - previous_captured
        )
        expected_capture_delta = 1 if receipt.status == "recorded" else 0
        if captured_delta != expected_capture_delta:
            raise HistoricalArchiveCleanLineageError(
                "ARCHIVE_CLEAN_LINEAGE_CAPTURE_DELTA_MISMATCH"
            )
        has_observation = receipt.observation_id is not None
        if has_observation != receipt.status in {"recorded", "already_recorded"}:
            raise HistoricalArchiveCleanLineageError(
                "ARCHIVE_CLEAN_LINEAGE_OBSERVATION_STATUS_MISMATCH"
            )
        if receipt.cumulative_settled_outcome_count < previous_settled:
            raise HistoricalArchiveCleanLineageError(
                "ARCHIVE_CLEAN_LINEAGE_SETTLED_COUNT_REGRESSION"
            )
        settled_delta = (
            receipt.cumulative_settled_outcome_count - previous_settled
        )
        if settled_delta != len(receipt.settled_outcome_ids):
            raise HistoricalArchiveCleanLineageError(
                "ARCHIVE_CLEAN_LINEAGE_SETTLED_DELTA_MISMATCH"
            )
        duplicates = settled_ids.intersection(receipt.settled_outcome_ids)
        if duplicates:
            raise HistoricalArchiveCleanLineageError(
                "ARCHIVE_CLEAN_LINEAGE_DUPLICATE_SETTLED_OUTCOME"
            )
        settled_ids.update(receipt.settled_outcome_ids)

        previous_checkpoint_id = receipt.current_checkpoint_id
        previous_completed_at_ms = receipt.completed_at_ms
        previous_expected = receipt.expected_elapsed_anchor_count
        previous_captured = receipt.captured_elapsed_anchor_count
        previous_settled = receipt.cumulative_settled_outcome_count

    sequence = tuple(item.receipt_id for item in ordered)
    return ArchiveCleanCycleLineageReport(
        runtime_id=runtime_id,
        pin_id=pin_id,
        campaign_id=initial.campaign_id,
        validation_spec_id=spec.spec_id,
        candidate_id=spec.candidate_id,
        initial_checkpoint_id=initial.checkpoint_id,
        latest_checkpoint_id=ordered[-1].current_checkpoint_id,
        receipt_count=len(ordered),
        receipt_sequence_sha256=_sha256(sequence),
        first_cycle_started_ms=ordered[0].cycle_started_ms,
        last_cycle_completed_at_ms=ordered[-1].completed_at_ms,
        latest_expected_elapsed_anchor_count=previous_expected,
        latest_captured_elapsed_anchor_count=previous_captured,
        cumulative_settled_outcome_count=previous_settled,
        unique_settled_outcome_count=len(settled_ids),
    )


def verify_archive_clean_cycle_lineage_paths(
    spec: HistoricalArchiveCleanValidationSpec,
    *,
    runtime_id: str,
    pin_id: str,
    receipt_paths: Iterable[Path],
) -> ArchiveCleanCycleLineageReport:
    receipts = tuple(
        load_archive_clean_operational_cycle_receipt(path)
        for path in receipt_paths
    )
    return verify_archive_clean_cycle_lineage(
        spec,
        runtime_id=runtime_id,
        pin_id=pin_id,
        receipts=receipts,
    )
