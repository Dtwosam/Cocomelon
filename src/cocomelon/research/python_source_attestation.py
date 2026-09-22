from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

SOURCE_ATTESTATION_SCHEMA_VERSION = 1


class PythonSourceAttestationError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _require_sha256(value: str, field: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} must be lowercase SHA-256")


@dataclass(frozen=True, slots=True)
class PythonSourceFileAttestation:
    relative_path: str
    sha256: str
    byte_count: int

    def __post_init__(self) -> None:
        if not self.relative_path or self.relative_path.startswith("/"):
            raise ValueError("relative_path must be relative")
        if ".." in Path(self.relative_path).parts:
            raise ValueError("relative_path must not escape source root")
        if not self.relative_path.endswith(".py"):
            raise ValueError("source attestation only supports Python files")
        _require_sha256(self.sha256, "sha256")
        if self.byte_count < 0:
            raise ValueError("byte_count must be non-negative")

    def to_dict(self) -> dict[str, object]:
        return {
            "relative_path": self.relative_path,
            "sha256": self.sha256,
            "byte_count": self.byte_count,
        }


@dataclass(frozen=True, slots=True)
class PythonSourceTreeAttestation:
    subject_type: str
    subject_id: str
    source_root_name: str
    files: tuple[PythonSourceFileAttestation, ...]
    schema_version: int = SOURCE_ATTESTATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.subject_type.strip():
            raise ValueError("subject_type must not be empty")
        if not self.subject_id.strip():
            raise ValueError("subject_id must not be empty")
        if not self.source_root_name.strip():
            raise ValueError("source_root_name must not be empty")
        if not self.files:
            raise ValueError("files must not be empty")
        paths = tuple(item.relative_path for item in self.files)
        if paths != tuple(sorted(paths)):
            raise ValueError("files must be sorted by relative_path")
        if len(set(paths)) != len(paths):
            raise ValueError("files must not contain duplicate relative paths")
        if self.schema_version != SOURCE_ATTESTATION_SCHEMA_VERSION:
            raise ValueError("unsupported Python source attestation schema")

    @property
    def source_tree_sha256(self) -> str:
        payload = tuple(item.to_dict() for item in self.files)
        return hashlib.sha256(
            _canonical_json(payload).encode("utf-8")
        ).hexdigest()

    def identity_payload(self) -> dict[str, object]:
        return {
            "subject_type": self.subject_type,
            "subject_id": self.subject_id,
            "source_root_name": self.source_root_name,
            "source_tree_sha256": self.source_tree_sha256,
            "file_count": len(self.files),
            "files": tuple(item.to_dict() for item in self.files),
            "schema_version": self.schema_version,
        }

    @property
    def attestation_id(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "attestation_id": self.attestation_id,
        }


def build_python_source_tree_attestation(
    source_root: Path,
    *,
    subject_type: str,
    subject_id: str,
) -> PythonSourceTreeAttestation:
    resolved = source_root.resolve()
    if not resolved.is_dir():
        raise PythonSourceAttestationError("SOURCE_ROOT_NOT_DIRECTORY")

    files: list[PythonSourceFileAttestation] = []
    for path in sorted(resolved.rglob("*.py")):
        if not path.is_file():
            continue
        relative = path.relative_to(resolved).as_posix()
        files.append(
            PythonSourceFileAttestation(
                relative_path=relative,
                sha256=_sha256_path(path),
                byte_count=path.stat().st_size,
            )
        )
    if not files:
        raise PythonSourceAttestationError("SOURCE_TREE_EMPTY")
    return PythonSourceTreeAttestation(
        subject_type=subject_type,
        subject_id=subject_id,
        source_root_name=resolved.name,
        files=tuple(files),
    )


def write_python_source_tree_attestation(
    path: Path,
    attestation: PythonSourceTreeAttestation,
) -> None:
    payload = (_canonical_json(attestation.to_dict()) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise PythonSourceAttestationError("SOURCE_ATTESTATION_CONFLICT")
        return

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


def verify_python_source_tree_attestation(
    path: Path,
    *,
    expected_subject_type: str,
    expected_subject_id: str,
) -> PythonSourceTreeAttestation:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PythonSourceAttestationError("SOURCE_ATTESTATION_INVALID") from exc
    if not isinstance(raw, dict):
        raise PythonSourceAttestationError("SOURCE_ATTESTATION_INVALID")

    raw_files = raw.get("files")
    if not isinstance(raw_files, list):
        raise PythonSourceAttestationError("SOURCE_ATTESTATION_INVALID")
    files: list[PythonSourceFileAttestation] = []
    try:
        for item in raw_files:
            if not isinstance(item, dict):
                raise ValueError("source file entry must be an object")
            files.append(
                PythonSourceFileAttestation(
                    relative_path=str(item["relative_path"]),
                    sha256=str(item["sha256"]),
                    byte_count=int(item["byte_count"]),
                )
            )
        attestation = PythonSourceTreeAttestation(
            subject_type=str(raw["subject_type"]),
            subject_id=str(raw["subject_id"]),
            source_root_name=str(raw["source_root_name"]),
            files=tuple(files),
            schema_version=int(raw["schema_version"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise PythonSourceAttestationError("SOURCE_ATTESTATION_INVALID") from exc

    if raw.get("source_tree_sha256") != attestation.source_tree_sha256:
        raise PythonSourceAttestationError("SOURCE_TREE_SHA256_MISMATCH")
    if raw.get("file_count") != len(attestation.files):
        raise PythonSourceAttestationError("SOURCE_FILE_COUNT_MISMATCH")
    if raw.get("attestation_id") != attestation.attestation_id:
        raise PythonSourceAttestationError("SOURCE_ATTESTATION_ID_MISMATCH")
    if (
        attestation.subject_type != expected_subject_type
        or attestation.subject_id != expected_subject_id
    ):
        raise PythonSourceAttestationError("SOURCE_ATTESTATION_SUBJECT_MISMATCH")

    canonical = _canonical_json(attestation.to_dict()) + "\n"
    if path.read_text(encoding="utf-8") != canonical:
        raise PythonSourceAttestationError("SOURCE_ATTESTATION_NON_CANONICAL")
    return attestation
