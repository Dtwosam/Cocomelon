from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from cocomelon.research.learning_candidate_freeze import (
    verify_learning_candidate_freeze,
)
from cocomelon.research.learning_experiment import verify_learning_experiment

LEARNING_CANDIDATE_PACKAGE_SCHEMA_VERSION = 1
LEARNING_CANDIDATE_PACKAGE_KIND = "learning-clean-validation-candidate-package-v1"

_EXPERIMENT_FILES = (
    "challenger-run.json",
    "dataset/manifest.json",
    "dataset/records.jsonl",
    "evaluation.json",
    "experiment.json",
    "training/manifest.json",
    "training/rows.jsonl",
)


class LearningCandidatePackageError(RuntimeError):
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
        raise ValueError(f"{field} must be a lowercase SHA-256 identity")


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise LearningCandidatePackageError(f"{field} must be a JSON object")
    return cast(dict[str, object], value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LearningCandidatePackageError(f"{field} must be a non-empty string")
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LearningCandidatePackageError(f"{field} must be a non-negative integer")
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise LearningCandidatePackageError(f"{field} must be boolean")
    return value


def _experiment_file_bytes(experiment_root: Path) -> tuple[tuple[str, bytes], ...]:
    actual: set[str] = set()
    try:
        for path in experiment_root.rglob("*"):
            if path.is_symlink():
                raise LearningCandidatePackageError(
                    "LEARNING_CANDIDATE_PACKAGE_SYMLINK_FORBIDDEN"
                )
            if path.is_file():
                actual.add(path.relative_to(experiment_root).as_posix())
    except OSError as exc:
        raise LearningCandidatePackageError(
            "LEARNING_CANDIDATE_PACKAGE_EXPERIMENT_UNREADABLE"
        ) from exc

    expected = set(_EXPERIMENT_FILES)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise LearningCandidatePackageError(
            "LEARNING_CANDIDATE_PACKAGE_EXPERIMENT_FILE_SET_INVALID:"
            f"missing={missing}:unexpected={unexpected}"
        )

    resolved: list[tuple[str, bytes]] = []
    for relative in _EXPERIMENT_FILES:
        try:
            resolved.append((relative, (experiment_root / relative).read_bytes()))
        except OSError as exc:
            raise LearningCandidatePackageError(
                "LEARNING_CANDIDATE_PACKAGE_EXPERIMENT_UNREADABLE"
            ) from exc
    return tuple(resolved)


@dataclass(frozen=True, slots=True)
class LearningCandidatePackage:
    candidate_id: str
    candidate_freeze_sha256: str
    experiment_id: str
    dataset_id: str
    dataset_lineage_id: str
    run_id: str
    training_set_id: str
    training_bundle_id: str
    evaluation_id: str
    model_family: str
    validation_not_before_ms: int
    experiment_files: tuple[tuple[str, str], ...]
    package_kind: str = LEARNING_CANDIDATE_PACKAGE_KIND
    local_lineage_reverified: bool = True
    prospective_only: bool = True
    research_only: bool = True
    promotion_eligible: bool = False
    execution_ready: bool = False
    schema_version: int = LEARNING_CANDIDATE_PACKAGE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in (
            "candidate_id",
            "candidate_freeze_sha256",
            "experiment_id",
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
        if self.validation_not_before_ms < 0:
            raise ValueError("validation_not_before_ms must be non-negative")
        paths = tuple(path for path, _digest in self.experiment_files)
        if paths != _EXPERIMENT_FILES:
            raise ValueError("experiment_files must contain the frozen file set")
        if len(set(paths)) != len(paths):
            raise ValueError("experiment file paths must be unique")
        for path, digest in self.experiment_files:
            if not path.strip() or path.startswith("/") or ".." in Path(path).parts:
                raise ValueError("experiment file path is invalid")
            _require_sha256(digest, f"experiment file digest:{path}")
        if self.package_kind != LEARNING_CANDIDATE_PACKAGE_KIND:
            raise ValueError("unsupported learning candidate package kind")
        if not self.local_lineage_reverified:
            raise ValueError("learning candidate package must reverify local lineage")
        if not self.prospective_only or not self.research_only:
            raise ValueError("learning candidate package must remain prospective research")
        if self.promotion_eligible:
            raise ValueError("learning candidate package cannot authorize promotion")
        if self.execution_ready:
            raise ValueError("learning candidate package cannot authorize execution")
        if self.schema_version != LEARNING_CANDIDATE_PACKAGE_SCHEMA_VERSION:
            raise ValueError("unsupported learning candidate package schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "candidate_freeze_sha256": self.candidate_freeze_sha256,
            "experiment_id": self.experiment_id,
            "dataset_id": self.dataset_id,
            "dataset_lineage_id": self.dataset_lineage_id,
            "run_id": self.run_id,
            "training_set_id": self.training_set_id,
            "training_bundle_id": self.training_bundle_id,
            "evaluation_id": self.evaluation_id,
            "model_family": self.model_family,
            "validation_not_before_ms": self.validation_not_before_ms,
            "experiment_files": tuple(
                {"path": path, "sha256": digest}
                for path, digest in self.experiment_files
            ),
            "package_kind": self.package_kind,
            "local_lineage_reverified": self.local_lineage_reverified,
            "prospective_only": self.prospective_only,
            "research_only": self.research_only,
            "promotion_eligible": self.promotion_eligible,
            "execution_ready": self.execution_ready,
            "schema_version": self.schema_version,
        }

    @property
    def package_id(self) -> str:
        return _sha256_bytes(
            _canonical_json(self.identity_payload()).encode("utf-8")
        )

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "package_id": self.package_id}


def build_learning_candidate_package(
    *,
    experiment_root: Path,
    candidate_freeze_path: Path,
) -> LearningCandidatePackage:
    verified = verify_learning_experiment(output_root=experiment_root)
    freeze = verify_learning_candidate_freeze(
        candidate_freeze_path,
        experiment_root=experiment_root,
    )
    try:
        freeze_bytes = candidate_freeze_path.read_bytes()
    except OSError as exc:
        raise LearningCandidatePackageError(
            "LEARNING_CANDIDATE_PACKAGE_FREEZE_UNREADABLE"
        ) from exc
    files = _experiment_file_bytes(experiment_root)
    return LearningCandidatePackage(
        candidate_id=freeze.candidate_id,
        candidate_freeze_sha256=_sha256_bytes(freeze_bytes),
        experiment_id=verified.experiment_id,
        dataset_id=verified.dataset_id,
        dataset_lineage_id=verified.dataset_lineage_id,
        run_id=verified.run_id,
        training_set_id=verified.training_set_id,
        training_bundle_id=verified.training_bundle_id,
        evaluation_id=verified.evaluation_id,
        model_family=verified.model_family,
        validation_not_before_ms=freeze.validation_not_before_ms,
        experiment_files=tuple(
            (path, _sha256_bytes(payload)) for path, payload in files
        ),
    )


def _write_consistent(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise LearningCandidatePackageError(
                f"LEARNING_CANDIDATE_PACKAGE_CONFLICT:{path.name}"
            )
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


def materialize_learning_candidate_package(
    *,
    experiment_root: Path,
    candidate_freeze_path: Path,
    package_root: Path,
) -> Path:
    package = build_learning_candidate_package(
        experiment_root=experiment_root,
        candidate_freeze_path=candidate_freeze_path,
    )
    try:
        freeze_bytes = candidate_freeze_path.read_bytes()
    except OSError as exc:
        raise LearningCandidatePackageError(
            "LEARNING_CANDIDATE_PACKAGE_FREEZE_UNREADABLE"
        ) from exc
    _write_consistent(package_root / "candidate-freeze.json", freeze_bytes)
    for relative, payload in _experiment_file_bytes(experiment_root):
        _write_consistent(package_root / "experiment" / relative, payload)
    receipt_path = package_root / "candidate-package.json"
    _write_consistent(
        receipt_path,
        (_canonical_json(package.to_dict()) + "\n").encode("utf-8"),
    )
    verify_learning_candidate_package(package_root)
    return receipt_path


def _package_from_payload(raw: dict[str, object]) -> LearningCandidatePackage:
    raw_files = raw.get("experiment_files")
    if not isinstance(raw_files, list):
        raise LearningCandidatePackageError(
            "LEARNING_CANDIDATE_PACKAGE_FILES_INVALID"
        )
    files: list[tuple[str, str]] = []
    for index, item in enumerate(raw_files):
        mapped = _mapping(item, f"experiment_files[{index}]")
        if set(mapped) != {"path", "sha256"}:
            raise LearningCandidatePackageError(
                "LEARNING_CANDIDATE_PACKAGE_FILES_INVALID"
            )
        files.append(
            (
                _string(mapped.get("path"), f"experiment_files[{index}].path"),
                _string(
                    mapped.get("sha256"),
                    f"experiment_files[{index}].sha256",
                ),
            )
        )
    try:
        package = LearningCandidatePackage(
            candidate_id=_string(raw.get("candidate_id"), "candidate_id"),
            candidate_freeze_sha256=_string(
                raw.get("candidate_freeze_sha256"),
                "candidate_freeze_sha256",
            ),
            experiment_id=_string(raw.get("experiment_id"), "experiment_id"),
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
            validation_not_before_ms=_integer(
                raw.get("validation_not_before_ms"),
                "validation_not_before_ms",
            ),
            experiment_files=tuple(files),
            package_kind=_string(raw.get("package_kind"), "package_kind"),
            local_lineage_reverified=_boolean(
                raw.get("local_lineage_reverified"),
                "local_lineage_reverified",
            ),
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
        raise LearningCandidatePackageError(
            "LEARNING_CANDIDATE_PACKAGE_INVALID"
        ) from exc
    if raw.get("package_id") != package.package_id:
        raise LearningCandidatePackageError(
            "LEARNING_CANDIDATE_PACKAGE_ID_MISMATCH"
        )
    return package


def verify_learning_candidate_package(
    package_root: Path,
) -> LearningCandidatePackage:
    receipt_path = package_root / "candidate-package.json"
    freeze_path = package_root / "candidate-freeze.json"
    experiment_root = package_root / "experiment"
    try:
        receipt_bytes = receipt_path.read_bytes()
        raw = _mapping(
            json.loads(receipt_bytes),
            "learning candidate package",
        )
        freeze_bytes = freeze_path.read_bytes()
    except (OSError, json.JSONDecodeError) as exc:
        raise LearningCandidatePackageError(
            "LEARNING_CANDIDATE_PACKAGE_INVALID"
        ) from exc

    package = _package_from_payload(raw)
    canonical = (_canonical_json(package.to_dict()) + "\n").encode("utf-8")
    if receipt_bytes != canonical:
        raise LearningCandidatePackageError(
            "LEARNING_CANDIDATE_PACKAGE_NON_CANONICAL"
        )
    if _sha256_bytes(freeze_bytes) != package.candidate_freeze_sha256:
        raise LearningCandidatePackageError(
            "LEARNING_CANDIDATE_PACKAGE_FREEZE_DIGEST_MISMATCH"
        )

    actual_files = _experiment_file_bytes(experiment_root)
    actual_digests = tuple(
        (path, _sha256_bytes(payload)) for path, payload in actual_files
    )
    if actual_digests != package.experiment_files:
        raise LearningCandidatePackageError(
            "LEARNING_CANDIDATE_PACKAGE_EXPERIMENT_DIGEST_MISMATCH"
        )

    expected = build_learning_candidate_package(
        experiment_root=experiment_root,
        candidate_freeze_path=freeze_path,
    )
    if expected != package:
        raise LearningCandidatePackageError(
            "LEARNING_CANDIDATE_PACKAGE_LINEAGE_MISMATCH"
        )

    allowed = {
        "candidate-freeze.json",
        "candidate-package.json",
        *(f"experiment/{path}" for path in _EXPERIMENT_FILES),
    }
    actual_package_files = {
        path.relative_to(package_root).as_posix()
        for path in package_root.rglob("*")
        if path.is_file()
    }
    if actual_package_files != allowed:
        raise LearningCandidatePackageError(
            "LEARNING_CANDIDATE_PACKAGE_FILE_SET_INVALID"
        )
    return package
