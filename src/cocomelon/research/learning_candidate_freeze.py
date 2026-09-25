from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from cocomelon.research.historical_discovery_freeze import (
    MIN_PROSPECTIVE_EMBARGO_MS,
)
from cocomelon.research.learning_experiment import verify_learning_experiment

LEARNING_CANDIDATE_FREEZE_SCHEMA_VERSION = 1
LEARNING_CANDIDATE_KIND = "learning_challenger"
LEARNING_CANDIDATE_SELECTION_POLICY = "development-qualified-learning-experiment-v1"


class LearningCandidateFreezeError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise LearningCandidateFreezeError(f"{field} must be a JSON object")
    return cast(dict[str, object], value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LearningCandidateFreezeError(f"{field} must be a non-empty string")
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LearningCandidateFreezeError(f"{field} must be a non-negative integer")
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise LearningCandidateFreezeError(f"{field} must be boolean")
    return value


def _require_sha256(value: str, field: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} must be a lowercase SHA-256 identity")


@dataclass(frozen=True, slots=True)
class LearningCandidateFreeze:
    experiment_id: str
    experiment_manifest_sha256: str
    dataset_id: str
    dataset_lineage_id: str
    run_id: str
    training_set_id: str
    training_bundle_id: str
    evaluation_id: str
    model_family: str
    experiment_as_of_ms: int
    frozen_at_ms: int
    validation_not_before_ms: int
    selection_policy: str = LEARNING_CANDIDATE_SELECTION_POLICY
    candidate_kind: str = LEARNING_CANDIDATE_KIND
    prospective_only: bool = True
    research_only: bool = True
    promotion_eligible: bool = False
    execution_ready: bool = False
    schema_version: int = LEARNING_CANDIDATE_FREEZE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in (
            "experiment_id",
            "experiment_manifest_sha256",
            "dataset_id",
            "dataset_lineage_id",
            "run_id",
            "training_set_id",
            "training_bundle_id",
            "evaluation_id",
        ):
            _require_sha256(getattr(self, field), field)
        if not self.model_family.strip():
            raise ValueError("model_family must not be empty")
        if self.experiment_as_of_ms < 0:
            raise ValueError("experiment_as_of_ms must be non-negative")
        if self.frozen_at_ms < self.experiment_as_of_ms:
            raise ValueError("frozen_at_ms must not precede experiment as_of_ms")
        if self.validation_not_before_ms != (
            self.frozen_at_ms + MIN_PROSPECTIVE_EMBARGO_MS
        ):
            raise ValueError("validation_not_before_ms must equal freeze + embargo")
        if self.selection_policy != LEARNING_CANDIDATE_SELECTION_POLICY:
            raise ValueError("unsupported learning candidate selection policy")
        if self.candidate_kind != LEARNING_CANDIDATE_KIND:
            raise ValueError("unsupported learning candidate kind")
        if not self.prospective_only:
            raise ValueError("learning candidate freeze must remain prospective-only")
        if not self.research_only:
            raise ValueError("learning candidate freeze must remain research-only")
        if self.promotion_eligible:
            raise ValueError("learning candidate freeze cannot authorize promotion")
        if self.execution_ready:
            raise ValueError("learning candidate freeze cannot authorize execution")
        if self.schema_version != LEARNING_CANDIDATE_FREEZE_SCHEMA_VERSION:
            raise ValueError("unsupported learning candidate freeze schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "experiment_id": self.experiment_id,
            "experiment_manifest_sha256": self.experiment_manifest_sha256,
            "dataset_id": self.dataset_id,
            "dataset_lineage_id": self.dataset_lineage_id,
            "run_id": self.run_id,
            "training_set_id": self.training_set_id,
            "training_bundle_id": self.training_bundle_id,
            "evaluation_id": self.evaluation_id,
            "model_family": self.model_family,
            "experiment_as_of_ms": self.experiment_as_of_ms,
            "frozen_at_ms": self.frozen_at_ms,
            "validation_not_before_ms": self.validation_not_before_ms,
            "selection_policy": self.selection_policy,
            "candidate_kind": self.candidate_kind,
            "prospective_only": self.prospective_only,
            "research_only": self.research_only,
            "promotion_eligible": self.promotion_eligible,
            "execution_ready": self.execution_ready,
            "schema_version": self.schema_version,
        }

    @property
    def candidate_id(self) -> str:
        return _sha256_bytes(
            _canonical_json(self.identity_payload()).encode("utf-8")
        )

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "candidate_id": self.candidate_id}


def build_learning_candidate_freeze(
    *,
    experiment_root: Path,
    frozen_at_ms: int,
) -> LearningCandidateFreeze:
    if frozen_at_ms < 0:
        raise ValueError("frozen_at_ms must be non-negative")

    manifest_path = experiment_root / "experiment.json"
    try:
        before = manifest_path.read_bytes()
    except OSError as exc:
        raise LearningCandidateFreezeError(
            "LEARNING_CANDIDATE_EXPERIMENT_MANIFEST_MISSING"
        ) from exc

    verified = verify_learning_experiment(output_root=experiment_root)
    if not verified.qualifies_development:
        raise LearningCandidateFreezeError(
            "LEARNING_EXPERIMENT_NOT_DEVELOPMENT_QUALIFIED"
        )

    try:
        after = manifest_path.read_bytes()
        raw = _mapping(
            json.loads(after),
            "learning experiment manifest",
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise LearningCandidateFreezeError(
            "LEARNING_CANDIDATE_EXPERIMENT_MANIFEST_INVALID"
        ) from exc
    if before != after:
        raise LearningCandidateFreezeError(
            "LEARNING_CANDIDATE_EXPERIMENT_CHANGED_DURING_FREEZE"
        )
    if _string(raw.get("experiment_id"), "experiment_id") != verified.experiment_id:
        raise LearningCandidateFreezeError(
            "LEARNING_CANDIDATE_EXPERIMENT_ID_MISMATCH"
        )
    experiment_as_of_ms = _integer(raw.get("as_of_ms"), "as_of_ms")
    if frozen_at_ms < experiment_as_of_ms:
        raise LearningCandidateFreezeError(
            "LEARNING_CANDIDATE_FREEZE_PRECEDES_EXPERIMENT"
        )

    return LearningCandidateFreeze(
        experiment_id=verified.experiment_id,
        experiment_manifest_sha256=_sha256_bytes(after),
        dataset_id=verified.dataset_id,
        dataset_lineage_id=verified.dataset_lineage_id,
        run_id=verified.run_id,
        training_set_id=verified.training_set_id,
        training_bundle_id=verified.training_bundle_id,
        evaluation_id=verified.evaluation_id,
        model_family=verified.model_family,
        experiment_as_of_ms=experiment_as_of_ms,
        frozen_at_ms=frozen_at_ms,
        validation_not_before_ms=frozen_at_ms + MIN_PROSPECTIVE_EMBARGO_MS,
    )


def write_learning_candidate_freeze(
    output_root: Path,
    freeze: LearningCandidateFreeze,
) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / "candidate-freeze.json"
    payload = (_canonical_json(freeze.to_dict()) + "\n").encode("utf-8")
    if path.exists():
        if path.read_bytes() != payload:
            raise LearningCandidateFreezeError(
                "LEARNING_CANDIDATE_FREEZE_CONFLICT"
            )
        return path

    temporary = output_root / ".candidate-freeze.json.tmp"
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


def _freeze_from_payload(raw: dict[str, object]) -> LearningCandidateFreeze:
    try:
        freeze = LearningCandidateFreeze(
            experiment_id=_string(raw.get("experiment_id"), "experiment_id"),
            experiment_manifest_sha256=_string(
                raw.get("experiment_manifest_sha256"),
                "experiment_manifest_sha256",
            ),
            dataset_id=_string(raw.get("dataset_id"), "dataset_id"),
            dataset_lineage_id=_string(
                raw.get("dataset_lineage_id"),
                "dataset_lineage_id",
            ),
            run_id=_string(raw.get("run_id"), "run_id"),
            training_set_id=_string(
                raw.get("training_set_id"),
                "training_set_id",
            ),
            training_bundle_id=_string(
                raw.get("training_bundle_id"),
                "training_bundle_id",
            ),
            evaluation_id=_string(raw.get("evaluation_id"), "evaluation_id"),
            model_family=_string(raw.get("model_family"), "model_family"),
            experiment_as_of_ms=_integer(
                raw.get("experiment_as_of_ms"),
                "experiment_as_of_ms",
            ),
            frozen_at_ms=_integer(raw.get("frozen_at_ms"), "frozen_at_ms"),
            validation_not_before_ms=_integer(
                raw.get("validation_not_before_ms"),
                "validation_not_before_ms",
            ),
            selection_policy=_string(
                raw.get("selection_policy"),
                "selection_policy",
            ),
            candidate_kind=_string(raw.get("candidate_kind"), "candidate_kind"),
            prospective_only=_boolean(
                raw.get("prospective_only"),
                "prospective_only",
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
    except ValueError as exc:
        raise LearningCandidateFreezeError(
            "LEARNING_CANDIDATE_FREEZE_INVALID"
        ) from exc
    candidate_id = _string(raw.get("candidate_id"), "candidate_id")
    if candidate_id != freeze.candidate_id:
        raise LearningCandidateFreezeError(
            "LEARNING_CANDIDATE_FREEZE_ID_MISMATCH"
        )
    return freeze


def verify_learning_candidate_freeze(
    path: Path,
    *,
    experiment_root: Path,
) -> LearningCandidateFreeze:
    try:
        stored_bytes = path.read_bytes()
        raw = _mapping(
            json.loads(stored_bytes),
            "learning candidate freeze",
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise LearningCandidateFreezeError(
            "LEARNING_CANDIDATE_FREEZE_INVALID"
        ) from exc

    freeze = _freeze_from_payload(raw)
    canonical = (_canonical_json(freeze.to_dict()) + "\n").encode("utf-8")
    if stored_bytes != canonical:
        raise LearningCandidateFreezeError(
            "LEARNING_CANDIDATE_FREEZE_NON_CANONICAL"
        )

    expected = build_learning_candidate_freeze(
        experiment_root=experiment_root,
        frozen_at_ms=freeze.frozen_at_ms,
    )
    if expected != freeze:
        raise LearningCandidateFreezeError(
            "LEARNING_CANDIDATE_FREEZE_EVIDENCE_MISMATCH"
        )
    return freeze
