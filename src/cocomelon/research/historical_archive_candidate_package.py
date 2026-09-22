from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from cocomelon.research.historical_archive_clean_observer import (
    ArchiveCleanFrozenRuntime,
)
from cocomelon.research.historical_archive_model_artifact import (
    HistoricalArchiveCandidateModelArtifact,
    load_archive_candidate_model_artifact,
    verify_archive_candidate_model_artifact,
)
from cocomelon.research.historical_archive_presets import (
    HistoricalArchiveExperimentPreset,
)
from cocomelon.research.historical_archive_validation_spec import (
    HistoricalArchiveCleanValidationSpec,
    load_archive_clean_validation_spec,
    verify_archive_clean_validation_spec,
)

PACKAGE_SCHEMA_VERSION = 1
PACKAGE_KIND = "historical-archive-clean-candidate-package"


class HistoricalArchiveCandidatePackageError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _require_sha256(value: str, field: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} must be lowercase SHA-256")


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise HistoricalArchiveCandidatePackageError(
            f"{field} must be an object"
        )
    return cast(dict[str, object], value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalArchiveCandidatePackageError(
            f"{field} must be a non-empty string"
        )
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise HistoricalArchiveCandidatePackageError(
            f"{field} must be an integer"
        )
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise HistoricalArchiveCandidatePackageError(
            f"{field} must be boolean"
        )
    return value


@dataclass(frozen=True, slots=True)
class HistoricalArchiveCandidatePackage:
    preset_name: str
    preset_id: str
    source_evidence_class: str
    validation_evidence_class: str
    candidate_id: str
    training_plan_id: str
    calibration_id: str
    bundle_id: str
    dataset_id: str
    model_artifact_id: str
    model_payload_sha256: str
    validation_spec_id: str
    candidate_model_sha256: str
    validation_spec_sha256: str
    model_family: str
    calibration_variant: str
    validation_start_ms: int
    validation_end_ms: int
    finalization_not_before_ms: int
    package_kind: str = PACKAGE_KIND
    local_lineage_reverified: bool = True
    paper_only: bool = True
    prospective_only: bool = True
    promotion_eligible: bool = False
    execution_ready: bool = False
    schema_version: int = PACKAGE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in (
            "preset_name",
            "preset_id",
            "source_evidence_class",
            "validation_evidence_class",
            "candidate_id",
            "training_plan_id",
            "calibration_id",
            "bundle_id",
            "dataset_id",
            "model_artifact_id",
            "model_payload_sha256",
            "validation_spec_id",
            "candidate_model_sha256",
            "validation_spec_sha256",
            "model_family",
            "calibration_variant",
        ):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} must not be empty")
        for field in (
            "candidate_id",
            "training_plan_id",
            "calibration_id",
            "bundle_id",
            "dataset_id",
            "model_artifact_id",
            "model_payload_sha256",
            "validation_spec_id",
            "candidate_model_sha256",
            "validation_spec_sha256",
        ):
            _require_sha256(getattr(self, field), field)
        if self.validation_start_ms < 0:
            raise ValueError("validation_start_ms must be non-negative")
        if self.validation_end_ms <= self.validation_start_ms:
            raise ValueError("validation_end_ms must follow validation_start_ms")
        if self.finalization_not_before_ms < self.validation_end_ms:
            raise ValueError("finalization boundary cannot precede validation end")
        if self.package_kind != PACKAGE_KIND:
            raise ValueError("unsupported candidate package kind")
        if not self.local_lineage_reverified:
            raise ValueError("candidate package must reverify local lineage")
        if not self.paper_only or not self.prospective_only:
            raise ValueError("candidate package must remain paper/prospective")
        if self.promotion_eligible or self.execution_ready:
            raise ValueError("candidate package cannot authorize promotion/execution")
        if self.schema_version != PACKAGE_SCHEMA_VERSION:
            raise ValueError("unsupported candidate package schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "preset_name": self.preset_name,
            "preset_id": self.preset_id,
            "source_evidence_class": self.source_evidence_class,
            "validation_evidence_class": self.validation_evidence_class,
            "candidate_id": self.candidate_id,
            "training_plan_id": self.training_plan_id,
            "calibration_id": self.calibration_id,
            "bundle_id": self.bundle_id,
            "dataset_id": self.dataset_id,
            "model_artifact_id": self.model_artifact_id,
            "model_payload_sha256": self.model_payload_sha256,
            "validation_spec_id": self.validation_spec_id,
            "candidate_model_sha256": self.candidate_model_sha256,
            "validation_spec_sha256": self.validation_spec_sha256,
            "model_family": self.model_family,
            "calibration_variant": self.calibration_variant,
            "validation_start_ms": self.validation_start_ms,
            "validation_end_ms": self.validation_end_ms,
            "finalization_not_before_ms": self.finalization_not_before_ms,
            "package_kind": self.package_kind,
            "local_lineage_reverified": self.local_lineage_reverified,
            "paper_only": self.paper_only,
            "prospective_only": self.prospective_only,
            "promotion_eligible": self.promotion_eligible,
            "execution_ready": self.execution_ready,
            "schema_version": self.schema_version,
        }

    @property
    def package_id(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "package_id": self.package_id}


@dataclass(frozen=True, slots=True)
class LoadedArchiveCandidatePackage:
    package: HistoricalArchiveCandidatePackage
    runtime: ArchiveCleanFrozenRuntime
    package_root: Path


def _package_from_runtime(
    runtime: ArchiveCleanFrozenRuntime,
    *,
    candidate_model_bytes: bytes,
    validation_spec_bytes: bytes,
) -> HistoricalArchiveCandidatePackage:
    artifact = runtime.artifact
    spec = runtime.spec
    return HistoricalArchiveCandidatePackage(
        preset_name=artifact.preset_name,
        preset_id=artifact.preset_id,
        source_evidence_class=artifact.evidence_class,
        validation_evidence_class=spec.validation_evidence_class,
        candidate_id=artifact.candidate_id,
        training_plan_id=artifact.training_plan_id,
        calibration_id=artifact.calibration_id,
        bundle_id=artifact.bundle_id,
        dataset_id=artifact.dataset_id,
        model_artifact_id=artifact.artifact_id,
        model_payload_sha256=artifact.model_payload_sha256,
        validation_spec_id=spec.spec_id,
        candidate_model_sha256=_sha256_bytes(candidate_model_bytes),
        validation_spec_sha256=_sha256_bytes(validation_spec_bytes),
        model_family=artifact.model_family,
        calibration_variant=artifact.calibration_variant,
        validation_start_ms=spec.validation_start_ms,
        validation_end_ms=spec.validation_end_ms,
        finalization_not_before_ms=spec.finalization_not_before_ms,
    )


def build_archive_clean_candidate_package(
    preset: HistoricalArchiveExperimentPreset,
    *,
    archive_root: Path,
    source_root: Path,
    output_root: Path,
) -> HistoricalArchiveCandidatePackage:
    artifact = verify_archive_candidate_model_artifact(
        output_root / "candidate-model.json",
        preset=preset,
        archive_root=archive_root,
        source_root=source_root,
        output_root=output_root,
    )
    spec = verify_archive_clean_validation_spec(
        output_root / "candidate-validation-spec.json",
        preset=preset,
        archive_root=archive_root,
        source_root=source_root,
        output_root=output_root,
    )
    runtime = ArchiveCleanFrozenRuntime(artifact=artifact, spec=spec)
    candidate_model_bytes = (output_root / "candidate-model.json").read_bytes()
    validation_spec_bytes = (
        output_root / "candidate-validation-spec.json"
    ).read_bytes()
    return _package_from_runtime(
        runtime,
        candidate_model_bytes=candidate_model_bytes,
        validation_spec_bytes=validation_spec_bytes,
    )


def _write_consistent(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise HistoricalArchiveCandidatePackageError(
                f"conflicting candidate package file: {path.name}"
            )
        return
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def materialize_archive_clean_candidate_package(
    *,
    output_root: Path,
    package_root: Path,
    package: HistoricalArchiveCandidatePackage,
) -> Path:
    model_path = output_root / "candidate-model.json"
    spec_path = output_root / "candidate-validation-spec.json"
    try:
        model_bytes = model_path.read_bytes()
        spec_bytes = spec_path.read_bytes()
    except OSError as exc:
        raise HistoricalArchiveCandidatePackageError(
            "ARCHIVE_CANDIDATE_PACKAGE_SOURCE_FILE_MISSING"
        ) from exc
    if _sha256_bytes(model_bytes) != package.candidate_model_sha256:
        raise HistoricalArchiveCandidatePackageError(
            "ARCHIVE_CANDIDATE_PACKAGE_MODEL_DIGEST_MISMATCH"
        )
    if _sha256_bytes(spec_bytes) != package.validation_spec_sha256:
        raise HistoricalArchiveCandidatePackageError(
            "ARCHIVE_CANDIDATE_PACKAGE_SPEC_DIGEST_MISMATCH"
        )
    _write_consistent(package_root / "candidate-model.json", model_bytes)
    _write_consistent(package_root / "candidate-validation-spec.json", spec_bytes)
    receipt_path = package_root / "candidate-package.json"
    _write_consistent(
        receipt_path,
        (_canonical_json(package.to_dict()) + "\n").encode("utf-8"),
    )
    return receipt_path


def _package_from_payload(raw: dict[str, object]) -> HistoricalArchiveCandidatePackage:
    try:
        package = HistoricalArchiveCandidatePackage(
            preset_name=_string(raw.get("preset_name"), "preset_name"),
            preset_id=_string(raw.get("preset_id"), "preset_id"),
            source_evidence_class=_string(
                raw.get("source_evidence_class"),
                "source_evidence_class",
            ),
            validation_evidence_class=_string(
                raw.get("validation_evidence_class"),
                "validation_evidence_class",
            ),
            candidate_id=_string(raw.get("candidate_id"), "candidate_id"),
            training_plan_id=_string(
                raw.get("training_plan_id"),
                "training_plan_id",
            ),
            calibration_id=_string(
                raw.get("calibration_id"),
                "calibration_id",
            ),
            bundle_id=_string(raw.get("bundle_id"), "bundle_id"),
            dataset_id=_string(raw.get("dataset_id"), "dataset_id"),
            model_artifact_id=_string(
                raw.get("model_artifact_id"),
                "model_artifact_id",
            ),
            model_payload_sha256=_string(
                raw.get("model_payload_sha256"),
                "model_payload_sha256",
            ),
            validation_spec_id=_string(
                raw.get("validation_spec_id"),
                "validation_spec_id",
            ),
            candidate_model_sha256=_string(
                raw.get("candidate_model_sha256"),
                "candidate_model_sha256",
            ),
            validation_spec_sha256=_string(
                raw.get("validation_spec_sha256"),
                "validation_spec_sha256",
            ),
            model_family=_string(raw.get("model_family"), "model_family"),
            calibration_variant=_string(
                raw.get("calibration_variant"),
                "calibration_variant",
            ),
            validation_start_ms=_integer(
                raw.get("validation_start_ms"),
                "validation_start_ms",
            ),
            validation_end_ms=_integer(
                raw.get("validation_end_ms"),
                "validation_end_ms",
            ),
            finalization_not_before_ms=_integer(
                raw.get("finalization_not_before_ms"),
                "finalization_not_before_ms",
            ),
            package_kind=_string(raw.get("package_kind"), "package_kind"),
            local_lineage_reverified=_boolean(
                raw.get("local_lineage_reverified"),
                "local_lineage_reverified",
            ),
            paper_only=_boolean(raw.get("paper_only"), "paper_only"),
            prospective_only=_boolean(
                raw.get("prospective_only"),
                "prospective_only",
            ),
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
        raise HistoricalArchiveCandidatePackageError(
            "ARCHIVE_CANDIDATE_PACKAGE_INVALID"
        ) from exc
    if raw.get("package_id") != package.package_id:
        raise HistoricalArchiveCandidatePackageError(
            "ARCHIVE_CANDIDATE_PACKAGE_ID_MISMATCH"
        )
    return package


def load_archive_clean_candidate_package(
    package_root: Path,
) -> LoadedArchiveCandidatePackage:
    receipt_path = package_root / "candidate-package.json"
    model_path = package_root / "candidate-model.json"
    spec_path = package_root / "candidate-validation-spec.json"
    try:
        raw = _mapping(
            json.loads(receipt_path.read_text(encoding="utf-8")),
            "candidate package",
        )
        model_bytes = model_path.read_bytes()
        spec_bytes = spec_path.read_bytes()
    except (OSError, json.JSONDecodeError) as exc:
        raise HistoricalArchiveCandidatePackageError(
            "ARCHIVE_CANDIDATE_PACKAGE_INVALID"
        ) from exc
    package = _package_from_payload(raw)
    artifact = load_archive_candidate_model_artifact(model_path)
    spec = load_archive_clean_validation_spec(spec_path)
    runtime = ArchiveCleanFrozenRuntime(artifact=artifact, spec=spec)
    expected = _package_from_runtime(
        runtime,
        candidate_model_bytes=model_bytes,
        validation_spec_bytes=spec_bytes,
    )
    if package != expected:
        raise HistoricalArchiveCandidatePackageError(
            "ARCHIVE_CANDIDATE_PACKAGE_LINEAGE_MISMATCH"
        )
    if receipt_path.read_text(encoding="utf-8") != (
        _canonical_json(package.to_dict()) + "\n"
    ):
        raise HistoricalArchiveCandidatePackageError(
            "ARCHIVE_CANDIDATE_PACKAGE_NON_CANONICAL"
        )
    return LoadedArchiveCandidatePackage(
        package=package,
        runtime=runtime,
        package_root=package_root,
    )


def verify_archive_clean_candidate_package(
    preset: HistoricalArchiveExperimentPreset,
    *,
    archive_root: Path,
    source_root: Path,
    output_root: Path,
    package_root: Path,
) -> LoadedArchiveCandidatePackage:
    expected = build_archive_clean_candidate_package(
        preset,
        archive_root=archive_root,
        source_root=source_root,
        output_root=output_root,
    )
    loaded = load_archive_clean_candidate_package(package_root)
    if loaded.package != expected:
        raise HistoricalArchiveCandidatePackageError(
            "ARCHIVE_CANDIDATE_PACKAGE_EVIDENCE_MISMATCH"
        )
    return loaded
