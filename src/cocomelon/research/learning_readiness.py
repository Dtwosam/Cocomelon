from __future__ import annotations

from dataclasses import dataclass

from cocomelon.research.learning_feature_snapshots import LearningFeatureSnapshotStore
from cocomelon.research.learning_training_rows import (
    SUPPORTED_FEATURES,
    resolve_learning_feature_values,
)
from cocomelon.research.outcome_learning import (
    LearningEvidenceKind,
    LearningEvidenceLedger,
)


@dataclass(frozen=True, slots=True)
class LearningReadinessBlockedRecord:
    record_id: str
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "record_id": self.record_id,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class LearningReadinessReport:
    as_of_ms: int
    evidence_kind: LearningEvidenceKind
    feature_registry: tuple[str, ...]
    ledger_state_digest: str
    feature_store_state_digest: str | None
    eligible_record_ids: tuple[str, ...]
    quarantined_record_ids: tuple[str, ...]
    feature_complete_record_ids: tuple[str, ...]
    blocked_records: tuple[LearningReadinessBlockedRecord, ...]
    research_only: bool = True
    promotion_eligible: bool = False
    execution_ready: bool = False

    @property
    def structurally_ready(self) -> bool:
        return (
            bool(self.eligible_record_ids)
            and not self.blocked_records
            and self.feature_complete_record_ids == self.eligible_record_ids
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "as_of_ms": self.as_of_ms,
            "evidence_kind": self.evidence_kind.value,
            "feature_registry": self.feature_registry,
            "ledger_state_digest": self.ledger_state_digest,
            "feature_store_state_digest": self.feature_store_state_digest,
            "eligible_record_ids": self.eligible_record_ids,
            "eligible_record_count": len(self.eligible_record_ids),
            "quarantined_record_ids": self.quarantined_record_ids,
            "quarantined_record_count": len(self.quarantined_record_ids),
            "feature_complete_record_ids": self.feature_complete_record_ids,
            "feature_complete_record_count": len(self.feature_complete_record_ids),
            "blocked_records": tuple(item.to_dict() for item in self.blocked_records),
            "blocked_record_count": len(self.blocked_records),
            "structurally_ready": self.structurally_ready,
            "research_only": self.research_only,
            "promotion_eligible": self.promotion_eligible,
            "execution_ready": self.execution_ready,
        }


def _validate_feature_registry(feature_registry: tuple[str, ...]) -> None:
    if not feature_registry:
        raise ValueError("feature registry must not be empty")
    if len(set(feature_registry)) != len(feature_registry):
        raise ValueError("feature registry must be unique")
    for feature in feature_registry:
        if not feature.strip():
            raise ValueError("feature registry values must not be empty")
        if feature not in SUPPORTED_FEATURES:
            raise ValueError(f"unsupported learning training feature: {feature}")


def evaluate_learning_readiness(
    ledger: LearningEvidenceLedger,
    *,
    as_of_ms: int,
    evidence_kind: LearningEvidenceKind,
    feature_registry: tuple[str, ...],
    feature_store: LearningFeatureSnapshotStore | None = None,
) -> LearningReadinessReport:
    if as_of_ms < 0:
        raise ValueError("as_of_ms must be non-negative")
    _validate_feature_registry(feature_registry)

    eligible = tuple(
        record
        for record in ledger.eligible_records(as_of_ms=as_of_ms)
        if record.kind is evidence_kind
    )
    quarantined = tuple(
        record
        for record in ledger.quarantined_records(as_of_ms=as_of_ms)
        if record.kind is evidence_kind
    )

    complete: list[str] = []
    blocked: list[LearningReadinessBlockedRecord] = []
    for record in eligible:
        try:
            resolve_learning_feature_values(
                record,
                feature_registry,
                feature_store=feature_store,
            )
        except ValueError as exc:
            blocked.append(
                LearningReadinessBlockedRecord(
                    record_id=record.record_id,
                    reason=str(exc),
                )
            )
        else:
            complete.append(record.record_id)

    return LearningReadinessReport(
        as_of_ms=as_of_ms,
        evidence_kind=evidence_kind,
        feature_registry=feature_registry,
        ledger_state_digest=ledger.state_digest,
        feature_store_state_digest=(
            None if feature_store is None else feature_store.state_digest
        ),
        eligible_record_ids=tuple(sorted(record.record_id for record in eligible)),
        quarantined_record_ids=tuple(
            sorted(record.record_id for record in quarantined)
        ),
        feature_complete_record_ids=tuple(sorted(complete)),
        blocked_records=tuple(sorted(blocked, key=lambda item: item.record_id)),
    )
