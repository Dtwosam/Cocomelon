from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from cocomelon.research.learning_dataset_bundle import VerifiedLearningDatasetBundle
from cocomelon.research.outcome_learning import LearningEvidenceKind

RUN_MANIFEST_SCHEMA_VERSION = 1


class LearningChallengerRunManifestError(RuntimeError):
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


def _require_commit_sha(value: str) -> None:
    if len(value) != 40 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError("implementation_commit_sha must be lowercase 40-character git SHA")


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise LearningChallengerRunManifestError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LearningChallengerRunManifestError(f"{field} must be a non-empty string")
    return value


def _strings(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise LearningChallengerRunManifestError(f"{field} must be a string array")
    return tuple(value)


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise LearningChallengerRunManifestError(f"{field} must be boolean")
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise LearningChallengerRunManifestError(f"{field} must be an integer")
    return value


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
        if len(self.input_kinds) != 1:
            raise ValueError("challenger run requires exactly one evidence kind")
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
    if len(input_kinds) != 1:
        raise ValueError("challenger run requires exactly one evidence kind")

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
        input_kinds=tuple(sorted(kind.value for kind in input_kinds)),
        input_record_ids=tuple(sorted(record.record_id for record in selected_records)),
        feature_registry=feature_registry,
        model_family=model_family,
        model_config=model_config,
        decision_policy=decision_policy,
        implementation_commit_sha=implementation_commit_sha,
    )



def write_learning_challenger_run_manifest(
    path: Path,
    manifest: LearningChallengerRunManifest,
) -> Path:
    payload = (_canonical_json(manifest.to_dict()) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise LearningChallengerRunManifestError(
                "LEARNING_CHALLENGER_RUN_MANIFEST_CONFLICT"
            )
        return path
    temporary = path.with_name(f".{path.name}.tmp")
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


def load_learning_challenger_run_manifest(
    path: Path,
) -> LearningChallengerRunManifest:
    try:
        raw = _mapping(
            json.loads(path.read_text(encoding="utf-8")),
            "learning challenger run manifest",
        )
        manifest = LearningChallengerRunManifest(
            dataset_id=_string(raw.get("dataset_id"), "dataset_id"),
            dataset_lineage_id=_string(
                raw.get("dataset_lineage_id"),
                "dataset_lineage_id",
            ),
            dataset_manifest_sha256=_string(
                raw.get("dataset_manifest_sha256"),
                "dataset_manifest_sha256",
            ),
            dataset_records_sha256=_string(
                raw.get("dataset_records_sha256"),
                "dataset_records_sha256",
            ),
            input_kinds=_strings(raw.get("input_kinds"), "input_kinds"),
            input_record_ids=_strings(
                raw.get("input_record_ids"),
                "input_record_ids",
            ),
            feature_registry=_strings(
                raw.get("feature_registry"),
                "feature_registry",
            ),
            model_family=_string(raw.get("model_family"), "model_family"),
            model_config=_mapping(raw.get("model_config"), "model_config"),
            decision_policy=_mapping(
                raw.get("decision_policy"),
                "decision_policy",
            ),
            implementation_commit_sha=_string(
                raw.get("implementation_commit_sha"),
                "implementation_commit_sha",
            ),
            research_only=_boolean(raw.get("research_only"), "research_only"),
            promotion_eligible=_boolean(
                raw.get("promotion_eligible"),
                "promotion_eligible",
            ),
            execution_ready=_boolean(
                raw.get("execution_ready"),
                "execution_ready",
            ),
            schema_version=_integer(raw.get("schema_version"), "schema_version"),
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise LearningChallengerRunManifestError(
            "LEARNING_CHALLENGER_RUN_MANIFEST_INVALID"
        ) from exc

    if _canonical_json(raw) != _canonical_json(manifest.to_dict()):
        raise LearningChallengerRunManifestError(
            "LEARNING_CHALLENGER_RUN_MANIFEST_IDENTITY_MISMATCH"
        )
    if path.read_text(encoding="utf-8") != _canonical_json(manifest.to_dict()) + "\n":
        raise LearningChallengerRunManifestError(
            "LEARNING_CHALLENGER_RUN_MANIFEST_NON_CANONICAL"
        )
    return manifest


def verify_learning_challenger_run_manifest(
    path: Path,
    *,
    bundle: VerifiedLearningDatasetBundle,
) -> LearningChallengerRunManifest:
    manifest = load_learning_challenger_run_manifest(path)
    expected = build_learning_challenger_run_manifest(
        bundle,
        input_kinds=tuple(LearningEvidenceKind(kind) for kind in manifest.input_kinds),
        feature_registry=manifest.feature_registry,
        model_family=manifest.model_family,
        model_config=manifest.model_config,
        decision_policy=manifest.decision_policy,
        implementation_commit_sha=manifest.implementation_commit_sha,
    )
    if manifest != expected:
        raise LearningChallengerRunManifestError(
            "LEARNING_CHALLENGER_RUN_DATASET_LINEAGE_MISMATCH"
        )
    return manifest
