from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from cocomelon.research.learning_dataset_bundle import VerifiedLearningDatasetBundle
from cocomelon.research.outcome_learning import LearningEvidenceKind

RUN_MANIFEST_SCHEMA_VERSION = 1


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


def _require_commit_sha(value: str) -> None:
    if len(value) != 40 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError("implementation_commit_sha must be lowercase 40-character git SHA")


@dataclass(frozen=True, slots=True)
class LearningChallengerRunManifest:
    dataset_id: str
    dataset_lineage_id: str
    dataset_manifest_sha256: str
    dataset_records_sha256: str
    input_kinds: tuple[str, ...]
    input_record_ids: tuple[str, ...]
    feature_registry: tuple[str, ...]
    model_family: str
    model_config: dict[str, object]
    decision_policy: dict[str, object]
    implementation_commit_sha: str
    research_only: bool = True
    promotion_eligible: bool = False
    execution_ready: bool = False
    schema_version: int = RUN_MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in (
            "dataset_id",
            "dataset_lineage_id",
            "dataset_manifest_sha256",
            "dataset_records_sha256",
        ):
            _require_sha256(getattr(self, field), field)
        _require_commit_sha(self.implementation_commit_sha)
        if not self.model_family.strip():
            raise ValueError("model_family must not be empty")
        if not self.input_kinds:
            raise ValueError("input_kinds must not be empty")
        if len(set(self.input_kinds)) != len(self.input_kinds):
            raise ValueError("input_kinds must be unique")
        valid_kinds = {kind.value for kind in LearningEvidenceKind}
        if any(kind not in valid_kinds for kind in self.input_kinds):
            raise ValueError("input_kinds contains unsupported evidence kind")
        if tuple(sorted(self.input_record_ids)) != self.input_record_ids:
            raise ValueError("input_record_ids must be sorted")
        if len(set(self.input_record_ids)) != len(self.input_record_ids):
            raise ValueError("input_record_ids must be unique")
        if not self.input_record_ids:
            raise ValueError("challenger run requires at least one input record")
        for record_id in self.input_record_ids:
            _require_sha256(record_id, "input_record_id")
        if not self.feature_registry:
            raise ValueError("feature_registry must not be empty")
        if len(set(self.feature_registry)) != len(self.feature_registry):
            raise ValueError("feature_registry must be unique")
        if any(not feature.strip() for feature in self.feature_registry):
            raise ValueError("feature_registry values must not be empty")
        if not self.model_config:
            raise ValueError("model_config must not be empty")
        if not self.decision_policy:
            raise ValueError("decision_policy must not be empty")
        if not self.research_only:
            raise ValueError("learning challenger run must remain research-only")
        if self.promotion_eligible or self.execution_ready:
            raise ValueError("learning challenger run cannot authorize promotion/execution")
        if self.schema_version != RUN_MANIFEST_SCHEMA_VERSION:
            raise ValueError("unsupported learning challenger run manifest schema")

    @property
    def feature_registry_id(self) -> str:
        return _sha256_json(self.feature_registry)

    @property
    def model_config_id(self) -> str:
        return _sha256_json(self.model_config)

    @property
    def decision_policy_id(self) -> str:
        return _sha256_json(self.decision_policy)

    def identity_payload(self) -> dict[str, object]:
        return {
            "dataset_id": self.dataset_id,
            "dataset_lineage_id": self.dataset_lineage_id,
            "dataset_manifest_sha256": self.dataset_manifest_sha256,
            "dataset_records_sha256": self.dataset_records_sha256,
            "input_kinds": self.input_kinds,
            "input_record_ids": self.input_record_ids,
            "input_record_count": len(self.input_record_ids),
            "feature_registry": self.feature_registry,
            "feature_registry_id": self.feature_registry_id,
            "model_family": self.model_family,
            "model_config": self.model_config,
            "model_config_id": self.model_config_id,
            "decision_policy": self.decision_policy,
            "decision_policy_id": self.decision_policy_id,
            "implementation_commit_sha": self.implementation_commit_sha,
            "research_only": self.research_only,
            "promotion_eligible": self.promotion_eligible,
            "execution_ready": self.execution_ready,
            "schema_version": self.schema_version,
        }

    @property
    def run_id(self) -> str:
        return _sha256_json(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "run_id": self.run_id}


def build_learning_challenger_run_manifest(
    bundle: VerifiedLearningDatasetBundle,
    *,
    input_kinds: tuple[LearningEvidenceKind, ...],
    feature_registry: tuple[str, ...],
    model_family: str,
    model_config: dict[str, object],
    decision_policy: dict[str, object],
    implementation_commit_sha: str,
) -> LearningChallengerRunManifest:
    if not input_kinds:
        raise ValueError("input_kinds must not be empty")
    if len(set(input_kinds)) != len(input_kinds):
        raise ValueError("input_kinds must be unique")

    records_by_kind = {
        LearningEvidenceKind.PROSPECTIVE_PAPER: bundle.snapshot.prospective_records,
        LearningEvidenceKind.PAPER_EXECUTION: bundle.snapshot.paper_execution_records,
        LearningEvidenceKind.LIVE_EXECUTION: bundle.snapshot.live_execution_records,
    }
    selected_records = tuple(
        record
        for kind in input_kinds
        for record in records_by_kind[kind]
    )
    if not selected_records:
        raise ValueError("selected evidence kinds contain no eligible records")

    return LearningChallengerRunManifest(
        dataset_id=bundle.snapshot.manifest.dataset_id,
        dataset_lineage_id=bundle.lineage_id,
        dataset_manifest_sha256=bundle.manifest_sha256,
        dataset_records_sha256=bundle.records_sha256,
        input_kinds=tuple(kind.value for kind in input_kinds),
        input_record_ids=tuple(sorted(record.record_id for record in selected_records)),
        feature_registry=feature_registry,
        model_family=model_family,
        model_config=model_config,
        decision_policy=decision_policy,
        implementation_commit_sha=implementation_commit_sha,
    )
