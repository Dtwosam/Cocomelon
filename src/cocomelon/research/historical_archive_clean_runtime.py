from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from cocomelon.research.historical_archive_clean_observer import (
    ArchiveCleanFrozenRuntime,
    load_archive_clean_frozen_runtime,
)
from cocomelon.research.historical_archive_model_artifact import (
    load_archive_candidate_model_artifact,
)
from cocomelon.research.historical_archive_validation_spec import (
    load_archive_clean_validation_spec,
)
from cocomelon.research.python_source_attestation import (
    PythonSourceTreeAttestation,
    build_python_source_tree_attestation,
    verify_python_source_tree_attestation,
    write_python_source_tree_attestation,
)

RUNTIME_BUNDLE_SCHEMA_VERSION = 1
RUNTIME_PIN_SCHEMA_VERSION = 1
RUNTIME_SOURCE_SUBJECT_TYPE = "historical_archive_clean_observer_runtime"


class HistoricalArchiveCleanRuntimeError(RuntimeError):
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


def _require_sha256(value: str, field: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} must be lowercase SHA-256")


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise HistoricalArchiveCleanRuntimeError(f"{field} must be an object")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalArchiveCleanRuntimeError(
            f"{field} must be a non-empty string"
        )
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise HistoricalArchiveCleanRuntimeError(f"{field} must be an integer")
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise HistoricalArchiveCleanRuntimeError(f"{field} must be boolean")
    return value


def _package_source_root() -> Path:
    return Path(__file__).resolve().parents[1]


@dataclass(frozen=True, slots=True)
class ArchiveCleanRuntimeBundle:
    candidate_id: str
    model_artifact_id: str
    model_payload_sha256: str
    validation_spec_id: str
    candidate_model_sha256: str
    validation_spec_sha256: str
    observer_source_attestation_id: str
    observer_source_tree_sha256: str
    validation_start_ms: int
    validation_end_ms: int
    finalization_not_before_ms: int
    paper_only: bool = True
    prospective_only: bool = True
    promotion_eligible: bool = False
    execution_ready: bool = False
    schema_version: int = RUNTIME_BUNDLE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in (
            "candidate_id",
            "model_artifact_id",
            "model_payload_sha256",
            "validation_spec_id",
            "candidate_model_sha256",
            "validation_spec_sha256",
            "observer_source_attestation_id",
            "observer_source_tree_sha256",
        ):
            _require_sha256(getattr(self, field), field)
        if self.validation_start_ms < 0:
            raise ValueError("validation_start_ms must be non-negative")
        if self.validation_end_ms <= self.validation_start_ms:
            raise ValueError("validation_end_ms must follow validation_start_ms")
        if self.finalization_not_before_ms < self.validation_end_ms:
            raise ValueError("finalization_not_before_ms must follow validation end")
        if not self.paper_only or not self.prospective_only:
            raise ValueError("clean runtime bundle must remain paper/prospective only")
        if self.promotion_eligible or self.execution_ready:
            raise ValueError("clean runtime bundle must remain non-promotable")
        if self.schema_version != RUNTIME_BUNDLE_SCHEMA_VERSION:
            raise ValueError("unsupported archive clean runtime bundle schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "model_artifact_id": self.model_artifact_id,
            "model_payload_sha256": self.model_payload_sha256,
            "validation_spec_id": self.validation_spec_id,
            "candidate_model_sha256": self.candidate_model_sha256,
            "validation_spec_sha256": self.validation_spec_sha256,
            "observer_source_attestation_id": self.observer_source_attestation_id,
            "observer_source_tree_sha256": self.observer_source_tree_sha256,
            "validation_start_ms": self.validation_start_ms,
            "validation_end_ms": self.validation_end_ms,
            "finalization_not_before_ms": self.finalization_not_before_ms,
            "paper_only": self.paper_only,
            "prospective_only": self.prospective_only,
            "promotion_eligible": self.promotion_eligible,
            "execution_ready": self.execution_ready,
            "schema_version": self.schema_version,
        }

    @property
    def runtime_id(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "runtime_id": self.runtime_id}


@dataclass(frozen=True, slots=True)
class ArchiveCleanRuntimePin:
    runtime_id: str
    candidate_id: str
    model_artifact_id: str
    validation_spec_id: str
    pinned_at_ms: int
    validation_start_ms: int
    schema_version: int = RUNTIME_PIN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in (
            "runtime_id",
            "candidate_id",
            "model_artifact_id",
            "validation_spec_id",
        ):
            _require_sha256(getattr(self, field), field)
        if self.pinned_at_ms < 0:
            raise ValueError("pinned_at_ms must be non-negative")
        if self.validation_start_ms < 0:
            raise ValueError("validation_start_ms must be non-negative")
        if self.pinned_at_ms >= self.validation_start_ms:
            raise ValueError("runtime pin must be created before validation cutover")
        if self.schema_version != RUNTIME_PIN_SCHEMA_VERSION:
            raise ValueError("unsupported archive clean runtime pin schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "runtime_id": self.runtime_id,
            "candidate_id": self.candidate_id,
            "model_artifact_id": self.model_artifact_id,
            "validation_spec_id": self.validation_spec_id,
            "pinned_at_ms": self.pinned_at_ms,
            "validation_start_ms": self.validation_start_ms,
            "schema_version": self.schema_version,
        }

    @property
    def pin_id(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "pin_id": self.pin_id}


@dataclass(frozen=True, slots=True)
class PinnedArchiveCleanRuntime:
    runtime: ArchiveCleanFrozenRuntime
    bundle: ArchiveCleanRuntimeBundle
    pin: ArchiveCleanRuntimePin
    source_attestation: PythonSourceTreeAttestation


def _write_consistent(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise HistoricalArchiveCleanRuntimeError(
                f"conflicting runtime publication file: {path.name}"
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


def _build_source_attestation(
    *,
    validation_spec_id: str,
) -> PythonSourceTreeAttestation:
    return build_python_source_tree_attestation(
        _package_source_root(),
        subject_type=RUNTIME_SOURCE_SUBJECT_TYPE,
        subject_id=validation_spec_id,
    )


def _runtime_bundle_from_files(
    runtime: ArchiveCleanFrozenRuntime,
    *,
    candidate_model_bytes: bytes,
    validation_spec_bytes: bytes,
    source_attestation: PythonSourceTreeAttestation,
) -> ArchiveCleanRuntimeBundle:
    spec = runtime.spec
    artifact = runtime.artifact
    return ArchiveCleanRuntimeBundle(
        candidate_id=artifact.candidate_id,
        model_artifact_id=artifact.artifact_id,
        model_payload_sha256=artifact.model_payload_sha256,
        validation_spec_id=spec.spec_id,
        candidate_model_sha256=_sha256_bytes(candidate_model_bytes),
        validation_spec_sha256=_sha256_bytes(validation_spec_bytes),
        observer_source_attestation_id=source_attestation.attestation_id,
        observer_source_tree_sha256=source_attestation.source_tree_sha256,
        validation_start_ms=spec.validation_start_ms,
        validation_end_ms=spec.validation_end_ms,
        finalization_not_before_ms=spec.finalization_not_before_ms,
    )


def publish_archive_clean_runtime(
    *,
    output_root: Path,
    publish_root: Path,
    pinned_at_ms: int,
) -> tuple[ArchiveCleanRuntimeBundle, ArchiveCleanRuntimePin]:
    runtime = load_archive_clean_frozen_runtime(output_root)
    spec = runtime.spec
    model_path = output_root / "candidate-model.json"
    validation_path = output_root / "candidate-validation-spec.json"
    try:
        model_bytes = model_path.read_bytes()
        validation_bytes = validation_path.read_bytes()
    except OSError as exc:
        raise HistoricalArchiveCleanRuntimeError(
            "ARCHIVE_CLEAN_RUNTIME_SOURCE_FILE_MISSING"
        ) from exc

    source_attestation = _build_source_attestation(
        validation_spec_id=spec.spec_id,
    )
    bundle = _runtime_bundle_from_files(
        runtime,
        candidate_model_bytes=model_bytes,
        validation_spec_bytes=validation_bytes,
        source_attestation=source_attestation,
    )
    bundle_root = publish_root / "bundles" / bundle.runtime_id
    _write_consistent(bundle_root / "candidate-model.json", model_bytes)
    _write_consistent(
        bundle_root / "candidate-validation-spec.json",
        validation_bytes,
    )
    write_python_source_tree_attestation(
        bundle_root / "observer-source.json",
        source_attestation,
    )
    _write_consistent(
        bundle_root / "runtime.json",
        (_canonical_json(bundle.to_dict()) + "\n").encode("utf-8"),
    )

    pin = ArchiveCleanRuntimePin(
        runtime_id=bundle.runtime_id,
        candidate_id=bundle.candidate_id,
        model_artifact_id=bundle.model_artifact_id,
        validation_spec_id=bundle.validation_spec_id,
        pinned_at_ms=pinned_at_ms,
        validation_start_ms=bundle.validation_start_ms,
    )
    pin_path = publish_root / "pin.json"
    if pin_path.exists():
        existing = load_archive_clean_runtime_pin(pin_path)
        if existing != pin:
            raise HistoricalArchiveCleanRuntimeError(
                "ARCHIVE_CLEAN_RUNTIME_PIN_CONFLICT"
            )
        return bundle, existing
    _write_consistent(
        pin_path,
        (_canonical_json(pin.to_dict()) + "\n").encode("utf-8"),
    )
    return bundle, pin


def load_archive_clean_runtime_pin(path: Path) -> ArchiveCleanRuntimePin:
    try:
        raw = _mapping(
            json.loads(path.read_text(encoding="utf-8")),
            "archive clean runtime pin",
        )
        pin = ArchiveCleanRuntimePin(
            runtime_id=_string(raw.get("runtime_id"), "runtime_id"),
            candidate_id=_string(raw.get("candidate_id"), "candidate_id"),
            model_artifact_id=_string(
                raw.get("model_artifact_id"),
                "model_artifact_id",
            ),
            validation_spec_id=_string(
                raw.get("validation_spec_id"),
                "validation_spec_id",
            ),
            pinned_at_ms=_integer(raw.get("pinned_at_ms"), "pinned_at_ms"),
            validation_start_ms=_integer(
                raw.get("validation_start_ms"),
                "validation_start_ms",
            ),
            schema_version=_integer(raw.get("schema_version"), "schema_version"),
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise HistoricalArchiveCleanRuntimeError(
            "ARCHIVE_CLEAN_RUNTIME_PIN_INVALID"
        ) from exc
    if raw.get("pin_id") != pin.pin_id:
        raise HistoricalArchiveCleanRuntimeError(
            "ARCHIVE_CLEAN_RUNTIME_PIN_ID_MISMATCH"
        )
    if path.read_text(encoding="utf-8") != _canonical_json(pin.to_dict()) + "\n":
        raise HistoricalArchiveCleanRuntimeError(
            "ARCHIVE_CLEAN_RUNTIME_PIN_NON_CANONICAL"
        )
    return pin


def _load_runtime_bundle(path: Path) -> ArchiveCleanRuntimeBundle:
    try:
        raw = _mapping(
            json.loads(path.read_text(encoding="utf-8")),
            "archive clean runtime bundle",
        )
        bundle = ArchiveCleanRuntimeBundle(
            candidate_id=_string(raw.get("candidate_id"), "candidate_id"),
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
            observer_source_attestation_id=_string(
                raw.get("observer_source_attestation_id"),
                "observer_source_attestation_id",
            ),
            observer_source_tree_sha256=_string(
                raw.get("observer_source_tree_sha256"),
                "observer_source_tree_sha256",
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
            schema_version=_integer(
                raw.get("schema_version"),
                "schema_version",
            ),
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise HistoricalArchiveCleanRuntimeError(
            "ARCHIVE_CLEAN_RUNTIME_BUNDLE_INVALID"
        ) from exc
    if raw.get("runtime_id") != bundle.runtime_id:
        raise HistoricalArchiveCleanRuntimeError(
            "ARCHIVE_CLEAN_RUNTIME_ID_MISMATCH"
        )
    if path.read_text(encoding="utf-8") != _canonical_json(bundle.to_dict()) + "\n":
        raise HistoricalArchiveCleanRuntimeError(
            "ARCHIVE_CLEAN_RUNTIME_BUNDLE_NON_CANONICAL"
        )
    return bundle


def load_pinned_archive_clean_runtime(
    publish_root: Path,
    *,
    expected_pin_id: str,
) -> PinnedArchiveCleanRuntime:
    _require_sha256(expected_pin_id, "expected_pin_id")
    pin = load_archive_clean_runtime_pin(publish_root / "pin.json")
    if pin.pin_id != expected_pin_id:
        raise HistoricalArchiveCleanRuntimeError(
            "ARCHIVE_CLEAN_RUNTIME_PIN_NOT_EXPECTED"
        )
    bundle_root = publish_root / "bundles" / pin.runtime_id
    bundle = _load_runtime_bundle(bundle_root / "runtime.json")
    if bundle.runtime_id != pin.runtime_id:
        raise HistoricalArchiveCleanRuntimeError(
            "ARCHIVE_CLEAN_RUNTIME_PIN_BUNDLE_MISMATCH"
        )
    if (
        bundle.candidate_id != pin.candidate_id
        or bundle.model_artifact_id != pin.model_artifact_id
        or bundle.validation_spec_id != pin.validation_spec_id
        or bundle.validation_start_ms != pin.validation_start_ms
    ):
        raise HistoricalArchiveCleanRuntimeError(
            "ARCHIVE_CLEAN_RUNTIME_PIN_LINEAGE_MISMATCH"
        )

    model_path = bundle_root / "candidate-model.json"
    spec_path = bundle_root / "candidate-validation-spec.json"
    try:
        model_bytes = model_path.read_bytes()
        spec_bytes = spec_path.read_bytes()
    except OSError as exc:
        raise HistoricalArchiveCleanRuntimeError(
            "ARCHIVE_CLEAN_RUNTIME_BUNDLE_FILE_MISSING"
        ) from exc
    if _sha256_bytes(model_bytes) != bundle.candidate_model_sha256:
        raise HistoricalArchiveCleanRuntimeError(
            "ARCHIVE_CLEAN_RUNTIME_MODEL_DIGEST_MISMATCH"
        )
    if _sha256_bytes(spec_bytes) != bundle.validation_spec_sha256:
        raise HistoricalArchiveCleanRuntimeError(
            "ARCHIVE_CLEAN_RUNTIME_SPEC_DIGEST_MISMATCH"
        )

    source_attestation = verify_python_source_tree_attestation(
        bundle_root / "observer-source.json",
        expected_subject_type=RUNTIME_SOURCE_SUBJECT_TYPE,
        expected_subject_id=bundle.validation_spec_id,
    )
    if (
        source_attestation.attestation_id
        != bundle.observer_source_attestation_id
        or source_attestation.source_tree_sha256
        != bundle.observer_source_tree_sha256
    ):
        raise HistoricalArchiveCleanRuntimeError(
            "ARCHIVE_CLEAN_RUNTIME_SOURCE_ATTESTATION_MISMATCH"
        )
    current_source = _build_source_attestation(
        validation_spec_id=bundle.validation_spec_id,
    )
    if current_source != source_attestation:
        raise HistoricalArchiveCleanRuntimeError(
            "ARCHIVE_CLEAN_RUNTIME_SOURCE_TREE_DRIFT"
        )

    artifact = load_archive_candidate_model_artifact(model_path)
    spec = load_archive_clean_validation_spec(spec_path)
    runtime = ArchiveCleanFrozenRuntime(artifact=artifact, spec=spec)
    if (
        artifact.candidate_id != bundle.candidate_id
        or artifact.artifact_id != bundle.model_artifact_id
        or artifact.model_payload_sha256 != bundle.model_payload_sha256
        or spec.spec_id != bundle.validation_spec_id
        or spec.validation_start_ms != bundle.validation_start_ms
        or spec.validation_end_ms != bundle.validation_end_ms
        or spec.finalization_not_before_ms != bundle.finalization_not_before_ms
    ):
        raise HistoricalArchiveCleanRuntimeError(
            "ARCHIVE_CLEAN_RUNTIME_BUNDLE_LINEAGE_MISMATCH"
        )
    return PinnedArchiveCleanRuntime(
        runtime=runtime,
        bundle=bundle,
        pin=pin,
        source_attestation=source_attestation,
    )
