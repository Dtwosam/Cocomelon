from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal

from cocomelon.research.learning_challenger_run import (
    LearningChallengerRunManifest,
    build_learning_challenger_run_manifest,
)
from cocomelon.research.learning_dataset_bundle import VerifiedLearningDatasetBundle
from cocomelon.research.outcome_learning import LearningEvidenceKind, LearningEvidenceRecord

TRAINING_INPUT_SCHEMA_VERSION = 1
SUPPORTED_FEATURES = (
    "market",
    "direction",
    "context_state_1h",
    "source_evidence_class",
)


class LearningTrainingInputError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _require_sha256(value: str, field: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} must be lowercase SHA-256")


@dataclass(frozen=True, slots=True)
class LearningTrainingRow:
    run_id: str
    record_id: str
    evidence_kind: str
    source_record_id: str
    candidate_id: str
    candidate_spec_id: str | None
    campaign_id: str | None
    feature_snapshot_id: str
    opened_at_ms: int
    closed_at_ms: int
    features: dict[str, str | None]
    target_name: str
    target_value: Decimal
    schema_version: int = TRAINING_INPUT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.run_id, "run_id")
        _require_sha256(self.record_id, "record_id")
        if self.evidence_kind not in {kind.value for kind in LearningEvidenceKind}:
            raise ValueError("unsupported evidence_kind")
        for field in (
            "source_record_id",
            "candidate_id",
            "feature_snapshot_id",
            "target_name",
        ):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} must not be empty")
        if self.candidate_spec_id is not None and not self.candidate_spec_id.strip():
            raise ValueError("candidate_spec_id must not be empty when present")
        if self.campaign_id is not None and not self.campaign_id.strip():
            raise ValueError("campaign_id must not be empty when present")
        if self.opened_at_ms < 0 or self.closed_at_ms < self.opened_at_ms:
            raise ValueError("training row timestamps are invalid")
        if not self.features:
            raise ValueError("training row features must not be empty")
        if any(feature not in SUPPORTED_FEATURES for feature in self.features):
            raise ValueError("training row contains unsupported feature")
        if not self.target_value.is_finite():
            raise ValueError("training row target_value must be finite")
        if self.schema_version != TRAINING_INPUT_SCHEMA_VERSION:
            raise ValueError("unsupported learning training row schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "record_id": self.record_id,
            "evidence_kind": self.evidence_kind,
            "source_record_id": self.source_record_id,
            "candidate_id": self.candidate_id,
            "candidate_spec_id": self.candidate_spec_id,
            "campaign_id": self.campaign_id,
            "feature_snapshot_id": self.feature_snapshot_id,
            "opened_at_ms": self.opened_at_ms,
            "closed_at_ms": self.closed_at_ms,
            "features": self.features,
            "target_name": self.target_name,
            "target_value": str(self.target_value),
            "schema_version": self.schema_version,
        }

    @property
    def row_id(self) -> str:
        return _sha256_json(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "row_id": self.row_id}


@dataclass(frozen=True, slots=True)
class LearningTrainingTable:
    run_id: str
    dataset_lineage_id: str
    evidence_kind: str
    target_name: str
    feature_registry: tuple[str, ...]
    rows: tuple[LearningTrainingRow, ...]
    schema_version: int = TRAINING_INPUT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.run_id, "run_id")
        _require_sha256(self.dataset_lineage_id, "dataset_lineage_id")
        if self.evidence_kind not in {kind.value for kind in LearningEvidenceKind}:
            raise ValueError("unsupported evidence_kind")
        if not self.target_name.strip():
            raise ValueError("target_name must not be empty")
        if not self.feature_registry:
            raise ValueError("feature_registry must not be empty")
        if len(set(self.feature_registry)) != len(self.feature_registry):
            raise ValueError("feature_registry must be unique")
        if any(feature not in SUPPORTED_FEATURES for feature in self.feature_registry):
            raise ValueError("feature_registry contains unsupported learning feature")
        if not self.rows:
            raise ValueError("learning training table must contain rows")
        expected_order = tuple(
            sorted(
                self.rows,
                key=lambda item: (
                    item.closed_at_ms,
                    item.opened_at_ms,
                    item.record_id,
                ),
            )
        )
        if self.rows != expected_order:
            raise ValueError("learning training rows must be chronological")
        for row in self.rows:
            if row.run_id != self.run_id:
                raise ValueError("training row run_id does not match table")
            if row.evidence_kind != self.evidence_kind:
                raise ValueError("training row evidence kind does not match table")
            if row.target_name != self.target_name:
                raise ValueError("training row target does not match table")
            if tuple(row.features) != self.feature_registry:
                raise ValueError("training row feature order does not match registry")
        if self.schema_version != TRAINING_INPUT_SCHEMA_VERSION:
            raise ValueError("unsupported learning training table schema")

    @property
    def rows_sha256(self) -> str:
        return _sha256_json(tuple(row.to_dict() for row in self.rows))

    def identity_payload(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "dataset_lineage_id": self.dataset_lineage_id,
            "evidence_kind": self.evidence_kind,
            "target_name": self.target_name,
            "feature_registry": self.feature_registry,
            "row_count": len(self.rows),
            "row_ids": tuple(row.row_id for row in self.rows),
            "rows_sha256": self.rows_sha256,
            "schema_version": self.schema_version,
        }

    @property
    def table_id(self) -> str:
        return _sha256_json(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "table_id": self.table_id}


def _target(record: LearningEvidenceRecord) -> tuple[str, Decimal]:
    if record.kind is LearningEvidenceKind.PROSPECTIVE_PAPER:
        if record.net_return_fraction is None:
            raise LearningTrainingInputError("PROSPECTIVE_TARGET_MISSING")
        return "net_return_fraction", record.net_return_fraction
    if record.net_r is None:
        raise LearningTrainingInputError("EXECUTION_TARGET_MISSING")
    return "net_r", record.net_r


def _feature_value(record: LearningEvidenceRecord, feature: str) -> str | None:
    if feature == "market":
        return record.market.canonical
    if feature == "direction":
        return record.direction.value
    if feature == "context_state_1h":
        return record.context_state_1h
    if feature == "source_evidence_class":
        return record.source_evidence_class
    raise LearningTrainingInputError(f"UNSUPPORTED_FEATURE:{feature}")


def build_learning_training_table(
    bundle: VerifiedLearningDatasetBundle,
    manifest: LearningChallengerRunManifest,
) -> LearningTrainingTable:
    input_kinds = tuple(LearningEvidenceKind(kind) for kind in manifest.input_kinds)
    expected = build_learning_challenger_run_manifest(
        bundle,
        input_kinds=input_kinds,
        feature_registry=manifest.feature_registry,
        model_family=manifest.model_family,
        model_config=manifest.model_config,
        decision_policy=manifest.decision_policy,
        implementation_commit_sha=manifest.implementation_commit_sha,
    )
    if manifest != expected:
        raise LearningTrainingInputError("LEARNING_TRAINING_RUN_LINEAGE_MISMATCH")
    if len(input_kinds) != 1:
        raise LearningTrainingInputError("LEARNING_TRAINING_REQUIRES_ONE_EVIDENCE_KIND")
    if any(feature not in SUPPORTED_FEATURES for feature in manifest.feature_registry):
        raise LearningTrainingInputError("LEARNING_TRAINING_FEATURE_REGISTRY_UNSUPPORTED")

    records = {
        record.record_id: record
        for record in bundle.snapshot.eligible_records
    }
    selected: list[LearningEvidenceRecord] = []
    for record_id in manifest.input_record_ids:
        record = records.get(record_id)
        if record is None:
            raise LearningTrainingInputError("LEARNING_TRAINING_RECORD_MISSING")
        selected.append(record)

    kind = input_kinds[0]
    if any(record.kind is not kind for record in selected):
        raise LearningTrainingInputError("LEARNING_TRAINING_EVIDENCE_KIND_MISMATCH")

    rows: list[LearningTrainingRow] = []
    target_name: str | None = None
    for record in selected:
        row_target_name, target_value = _target(record)
        if target_name is None:
            target_name = row_target_name
        elif row_target_name != target_name:
            raise LearningTrainingInputError("LEARNING_TRAINING_TARGET_FAMILY_MISMATCH")
        rows.append(
            LearningTrainingRow(
                run_id=manifest.run_id,
                record_id=record.record_id,
                evidence_kind=record.kind.value,
                source_record_id=record.source_record_id,
                candidate_id=record.candidate_id,
                candidate_spec_id=record.candidate_spec_id,
                campaign_id=record.campaign_id,
                feature_snapshot_id=record.feature_snapshot_id,
                opened_at_ms=record.opened_at_ms,
                closed_at_ms=record.closed_at_ms,
                features={
                    feature: _feature_value(record, feature)
                    for feature in manifest.feature_registry
                },
                target_name=row_target_name,
                target_value=target_value,
            )
        )

    if target_name is None:
        raise LearningTrainingInputError("LEARNING_TRAINING_TARGET_MISSING")
    return LearningTrainingTable(
        run_id=manifest.run_id,
        dataset_lineage_id=bundle.lineage_id,
        evidence_kind=kind.value,
        target_name=target_name,
        feature_registry=manifest.feature_registry,
        rows=tuple(
            sorted(
                rows,
                key=lambda item: (
                    item.closed_at_ms,
                    item.opened_at_ms,
                    item.record_id,
                ),
            )
        ),
    )
