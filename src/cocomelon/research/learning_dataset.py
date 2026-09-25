from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from cocomelon.research.outcome_learning import (
    LEARNING_SCHEMA_VERSION,
    LearningEvidenceKind,
    LearningEvidenceLedger,
    LearningEvidenceRecord,
)

DATASET_SCHEMA_VERSION = 1


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


@dataclass(frozen=True, slots=True)
class LearningDatasetManifest:
    as_of_ms: int
    ledger_state_digest: str
    eligible_record_ids: tuple[str, ...]
    quarantined_record_ids: tuple[str, ...]
    prospective_record_ids: tuple[str, ...]
    paper_execution_record_ids: tuple[str, ...]
    live_execution_record_ids: tuple[str, ...]
    candidate_ids: tuple[str, ...]
    schema_version: int = DATASET_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.as_of_ms < 0:
            raise ValueError("as_of_ms must be non-negative")
        if len(self.ledger_state_digest) != 64:
            raise ValueError("ledger_state_digest must be a SHA-256 identity")
        if self.schema_version != DATASET_SCHEMA_VERSION:
            raise ValueError("unsupported learning dataset schema")

        eligible = tuple(sorted(set(self.eligible_record_ids)))
        quarantined = tuple(sorted(set(self.quarantined_record_ids)))
        prospective = tuple(sorted(set(self.prospective_record_ids)))
        paper = tuple(sorted(set(self.paper_execution_record_ids)))
        live = tuple(sorted(set(self.live_execution_record_ids)))
        candidates = tuple(sorted(set(self.candidate_ids)))
        for values, field in (
            (eligible, "eligible_record_ids"),
            (quarantined, "quarantined_record_ids"),
            (prospective, "prospective_record_ids"),
            (paper, "paper_execution_record_ids"),
            (live, "live_execution_record_ids"),
            (candidates, "candidate_ids"),
        ):
            if any(not item.strip() for item in values):
                raise ValueError(f"{field} values must not be empty")

        partition = set(prospective) | set(paper) | set(live)
        if partition != set(eligible):
            raise ValueError("eligible kind partitions must exactly cover eligible records")
        if set(prospective) & set(paper):
            raise ValueError("prospective and paper execution records must be disjoint")
        if set(prospective) & set(live):
            raise ValueError("prospective and live execution records must be disjoint")
        if set(paper) & set(live):
            raise ValueError("paper and live execution records must be disjoint")
        if set(eligible) & set(quarantined):
            raise ValueError("eligible and quarantined record ids must be disjoint")

        object.__setattr__(self, "eligible_record_ids", eligible)
        object.__setattr__(self, "quarantined_record_ids", quarantined)
        object.__setattr__(self, "prospective_record_ids", prospective)
        object.__setattr__(self, "paper_execution_record_ids", paper)
        object.__setattr__(self, "live_execution_record_ids", live)
        object.__setattr__(self, "candidate_ids", candidates)

    def identity_payload(self) -> dict[str, object]:
        return {
            "as_of_ms": self.as_of_ms,
            "ledger_state_digest": self.ledger_state_digest,
            "eligible_record_ids": self.eligible_record_ids,
            "quarantined_record_ids": self.quarantined_record_ids,
            "prospective_record_ids": self.prospective_record_ids,
            "paper_execution_record_ids": self.paper_execution_record_ids,
            "live_execution_record_ids": self.live_execution_record_ids,
            "candidate_ids": self.candidate_ids,
            "learning_schema_version": LEARNING_SCHEMA_VERSION,
            "schema_version": self.schema_version,
        }

    @property
    def dataset_id(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "dataset_id": self.dataset_id,
            "eligible_record_count": len(self.eligible_record_ids),
            "quarantined_record_count": len(self.quarantined_record_ids),
            "prospective_record_count": len(self.prospective_record_ids),
            "paper_execution_record_count": len(self.paper_execution_record_ids),
            "live_execution_record_count": len(self.live_execution_record_ids),
        }


@dataclass(frozen=True, slots=True)
class LearningDatasetSnapshot:
    manifest: LearningDatasetManifest
    prospective_records: tuple[LearningEvidenceRecord, ...]
    paper_execution_records: tuple[LearningEvidenceRecord, ...]
    live_execution_records: tuple[LearningEvidenceRecord, ...]

    def __post_init__(self) -> None:
        actual_prospective = tuple(
            sorted(item.record_id for item in self.prospective_records)
        )
        actual_paper = tuple(
            sorted(item.record_id for item in self.paper_execution_records)
        )
        actual_live = tuple(
            sorted(item.record_id for item in self.live_execution_records)
        )
        if actual_prospective != self.manifest.prospective_record_ids:
            raise ValueError("prospective records do not match dataset manifest")
        if actual_paper != self.manifest.paper_execution_record_ids:
            raise ValueError("paper execution records do not match dataset manifest")
        if actual_live != self.manifest.live_execution_record_ids:
            raise ValueError("live execution records do not match dataset manifest")

        for item in self.prospective_records:
            if item.kind is not LearningEvidenceKind.PROSPECTIVE_PAPER:
                raise ValueError("prospective dataset contains non-prospective record")
        for item in self.paper_execution_records:
            if item.kind is not LearningEvidenceKind.PAPER_EXECUTION:
                raise ValueError("paper execution dataset contains wrong record kind")
        for item in self.live_execution_records:
            if item.kind is not LearningEvidenceKind.LIVE_EXECUTION:
                raise ValueError("live execution dataset contains wrong record kind")

    @property
    def eligible_records(self) -> tuple[LearningEvidenceRecord, ...]:
        return tuple(
            sorted(
                (
                    *self.prospective_records,
                    *self.paper_execution_records,
                    *self.live_execution_records,
                ),
                key=lambda item: (
                    item.closed_at_ms,
                    item.opened_at_ms,
                    item.market.canonical,
                    item.record_id,
                ),
            )
        )


def build_learning_dataset_snapshot(
    ledger: LearningEvidenceLedger,
    *,
    as_of_ms: int,
) -> LearningDatasetSnapshot:
    if as_of_ms < 0:
        raise ValueError("as_of_ms must be non-negative")

    all_records = ledger.iter_records()
    eligible = tuple(
        item for item in all_records if item.research_eligible_at_ms <= as_of_ms
    )
    quarantined = tuple(
        item for item in all_records if item.research_eligible_at_ms > as_of_ms
    )
    prospective = tuple(
        item for item in eligible if item.kind is LearningEvidenceKind.PROSPECTIVE_PAPER
    )
    paper = tuple(
        item for item in eligible if item.kind is LearningEvidenceKind.PAPER_EXECUTION
    )
    live = tuple(
        item for item in eligible if item.kind is LearningEvidenceKind.LIVE_EXECUTION
    )

    manifest = LearningDatasetManifest(
        as_of_ms=as_of_ms,
        ledger_state_digest=ledger.state_digest,
        eligible_record_ids=tuple(item.record_id for item in eligible),
        quarantined_record_ids=tuple(item.record_id for item in quarantined),
        prospective_record_ids=tuple(item.record_id for item in prospective),
        paper_execution_record_ids=tuple(item.record_id for item in paper),
        live_execution_record_ids=tuple(item.record_id for item in live),
        candidate_ids=tuple(item.candidate_id for item in eligible),
    )
    return LearningDatasetSnapshot(
        manifest=manifest,
        prospective_records=prospective,
        paper_execution_records=paper,
        live_execution_records=live,
    )
