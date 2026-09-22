from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from cocomelon.research.historical_archive_clean_runtime import (
    PinnedArchiveCleanRuntime,
    load_pinned_archive_clean_runtime,
)

CONTROL_PLANE_SCHEMA_VERSION = 1
CONTROL_PLANE_WORKFLOW_PATH = ".github/workflows/archive-clean-observer.yml"
CONTROL_PLANE_RUNTIME_ROOT = "runtime/archive-clean"
CONTROL_PLANE_CRON = "2,7,12,17,22,27,32,37,42,47,52,57 * * * *"
CONTROL_PLANE_CONCURRENCY_GROUP = "archive-clean-prospective-observer"
CONTROL_PLANE_TIMEOUT_MINUTES = 10
CONTROL_PLANE_CHECKPOINT_ARTIFACT = "archive-clean-operational-checkpoint"
CONTROL_PLANE_CYCLE_EVIDENCE_PREFIX = "archive-clean-cycle-evidence"
CONTROL_PLANE_CYCLE_SOURCE_PREFIX = "archive-clean-cycle-sources"
CONTROL_PLANE_ARTIFACT_RETENTION_DAYS = 90
CONTROL_PLANE_EXECUTION_MODE = "paper"
CONTROL_PLANE_API_URL = "https://api.hyperliquid.xyz"
CONTROL_PLANE_PERMISSIONS = ("actions:read", "contents:read")
CONTROL_PLANE_CHECKPOINT_SELECTION_POLICY = (
    "highest_workflow_run_id_latest_artifact_within_run_v1"
)
CONTROL_PLANE_RUNTIME_PIN_VARIABLE = "ARCHIVE_CLEAN_RUNTIME_PIN_ID"
CONTROL_PLANE_ID_VARIABLE = "ARCHIVE_CLEAN_CONTROL_PLANE_ID"


class HistoricalArchiveCleanControlPlaneError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _require_sha256(value: str, field: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} must be lowercase SHA-256")


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise HistoricalArchiveCleanControlPlaneError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalArchiveCleanControlPlaneError(
            f"{field} must be a non-empty string"
        )
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise HistoricalArchiveCleanControlPlaneError(f"{field} must be an integer")
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise HistoricalArchiveCleanControlPlaneError(f"{field} must be boolean")
    return value


@dataclass(frozen=True, slots=True)
class ArchiveCleanControlPlaneAttestation:
    runtime_id: str
    pin_id: str
    candidate_id: str
    model_artifact_id: str
    validation_spec_id: str
    observer_source_attestation_id: str
    observer_source_tree_sha256: str
    workflow_path: str
    workflow_sha256: str
    runtime_root: str
    schedule_cron: str
    concurrency_group: str
    cancel_in_progress: bool
    job_timeout_minutes: int
    checkpoint_artifact_name: str
    cycle_evidence_artifact_prefix: str
    cycle_source_artifact_prefix: str
    artifact_retention_days: int
    checkpoint_selection_policy: str
    execution_mode: str
    api_url: str
    permissions: tuple[str, ...]
    runtime_pin_variable: str
    control_plane_id_variable: str
    frozen_at_ms: int
    validation_start_ms: int
    validation_end_ms: int
    paper_only: bool = True
    prospective_only: bool = True
    promotion_eligible: bool = False
    execution_ready: bool = False
    schema_version: int = CONTROL_PLANE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in (
            "runtime_id",
            "pin_id",
            "candidate_id",
            "model_artifact_id",
            "validation_spec_id",
            "observer_source_attestation_id",
            "observer_source_tree_sha256",
            "workflow_sha256",
        ):
            _require_sha256(getattr(self, field), field)
        if self.workflow_path != CONTROL_PLANE_WORKFLOW_PATH:
            raise ValueError("unexpected archive clean workflow path")
        if self.runtime_root != CONTROL_PLANE_RUNTIME_ROOT:
            raise ValueError("unexpected archive clean runtime root")
        if self.schedule_cron != CONTROL_PLANE_CRON:
            raise ValueError("archive clean schedule must remain frozen")
        if self.concurrency_group != CONTROL_PLANE_CONCURRENCY_GROUP:
            raise ValueError("archive clean concurrency group must remain frozen")
        if self.cancel_in_progress:
            raise ValueError("archive clean observer cannot cancel in-progress runs")
        if self.job_timeout_minutes != CONTROL_PLANE_TIMEOUT_MINUTES:
            raise ValueError("archive clean timeout must remain frozen")
        if self.checkpoint_artifact_name != CONTROL_PLANE_CHECKPOINT_ARTIFACT:
            raise ValueError("archive clean checkpoint artifact name drift")
        if (
            self.cycle_evidence_artifact_prefix
            != CONTROL_PLANE_CYCLE_EVIDENCE_PREFIX
        ):
            raise ValueError("archive clean evidence artifact prefix drift")
        if self.cycle_source_artifact_prefix != CONTROL_PLANE_CYCLE_SOURCE_PREFIX:
            raise ValueError("archive clean source artifact prefix drift")
        if self.artifact_retention_days != CONTROL_PLANE_ARTIFACT_RETENTION_DAYS:
            raise ValueError("archive clean artifact retention drift")
        if self.checkpoint_selection_policy != CONTROL_PLANE_CHECKPOINT_SELECTION_POLICY:
            raise ValueError("archive clean checkpoint selection policy drift")
        if self.execution_mode != CONTROL_PLANE_EXECUTION_MODE:
            raise ValueError("archive clean execution mode must remain paper")
        if self.api_url != CONTROL_PLANE_API_URL:
            raise ValueError("archive clean API URL drift")
        if self.permissions != CONTROL_PLANE_PERMISSIONS:
            raise ValueError("archive clean permissions must remain read-only")
        if self.runtime_pin_variable != CONTROL_PLANE_RUNTIME_PIN_VARIABLE:
            raise ValueError("runtime pin variable name drift")
        if self.control_plane_id_variable != CONTROL_PLANE_ID_VARIABLE:
            raise ValueError("control-plane ID variable name drift")
        if self.frozen_at_ms < 0:
            raise ValueError("frozen_at_ms must be non-negative")
        if self.validation_start_ms < 0:
            raise ValueError("validation_start_ms must be non-negative")
        if self.frozen_at_ms >= self.validation_start_ms:
            raise ValueError("control plane must be frozen before validation cutover")
        if self.validation_end_ms <= self.validation_start_ms:
            raise ValueError("validation_end_ms must follow validation_start_ms")
        if not self.paper_only or not self.prospective_only:
            raise ValueError("control plane must remain paper/prospective only")
        if self.promotion_eligible or self.execution_ready:
            raise ValueError("control plane must remain non-promotable")
        if self.schema_version != CONTROL_PLANE_SCHEMA_VERSION:
            raise ValueError("unsupported archive clean control-plane schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "runtime_id": self.runtime_id,
            "pin_id": self.pin_id,
            "candidate_id": self.candidate_id,
            "model_artifact_id": self.model_artifact_id,
            "validation_spec_id": self.validation_spec_id,
            "observer_source_attestation_id": self.observer_source_attestation_id,
            "observer_source_tree_sha256": self.observer_source_tree_sha256,
            "workflow_path": self.workflow_path,
            "workflow_sha256": self.workflow_sha256,
            "runtime_root": self.runtime_root,
            "schedule_cron": self.schedule_cron,
            "concurrency_group": self.concurrency_group,
            "cancel_in_progress": self.cancel_in_progress,
            "job_timeout_minutes": self.job_timeout_minutes,
            "checkpoint_artifact_name": self.checkpoint_artifact_name,
            "cycle_evidence_artifact_prefix": self.cycle_evidence_artifact_prefix,
            "cycle_source_artifact_prefix": self.cycle_source_artifact_prefix,
            "artifact_retention_days": self.artifact_retention_days,
            "checkpoint_selection_policy": self.checkpoint_selection_policy,
            "execution_mode": self.execution_mode,
            "api_url": self.api_url,
            "permissions": self.permissions,
            "runtime_pin_variable": self.runtime_pin_variable,
            "control_plane_id_variable": self.control_plane_id_variable,
            "frozen_at_ms": self.frozen_at_ms,
            "validation_start_ms": self.validation_start_ms,
            "validation_end_ms": self.validation_end_ms,
            "paper_only": self.paper_only,
            "prospective_only": self.prospective_only,
            "promotion_eligible": self.promotion_eligible,
            "execution_ready": self.execution_ready,
            "schema_version": self.schema_version,
        }

    @property
    def control_plane_id(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "control_plane_id": self.control_plane_id,
        }


def _workflow_sha256(path: Path) -> str:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise HistoricalArchiveCleanControlPlaneError(
            "ARCHIVE_CLEAN_WORKFLOW_FILE_MISSING"
        ) from exc
    return hashlib.sha256(data).hexdigest()


def _build_attestation(
    pinned: PinnedArchiveCleanRuntime,
    *,
    workflow_path: Path,
    frozen_at_ms: int,
) -> ArchiveCleanControlPlaneAttestation:
    bundle = pinned.bundle
    return ArchiveCleanControlPlaneAttestation(
        runtime_id=bundle.runtime_id,
        pin_id=pinned.pin.pin_id,
        candidate_id=bundle.candidate_id,
        model_artifact_id=bundle.model_artifact_id,
        validation_spec_id=bundle.validation_spec_id,
        observer_source_attestation_id=bundle.observer_source_attestation_id,
        observer_source_tree_sha256=bundle.observer_source_tree_sha256,
        workflow_path=CONTROL_PLANE_WORKFLOW_PATH,
        workflow_sha256=_workflow_sha256(workflow_path),
        runtime_root=CONTROL_PLANE_RUNTIME_ROOT,
        schedule_cron=CONTROL_PLANE_CRON,
        concurrency_group=CONTROL_PLANE_CONCURRENCY_GROUP,
        cancel_in_progress=False,
        job_timeout_minutes=CONTROL_PLANE_TIMEOUT_MINUTES,
        checkpoint_artifact_name=CONTROL_PLANE_CHECKPOINT_ARTIFACT,
        cycle_evidence_artifact_prefix=CONTROL_PLANE_CYCLE_EVIDENCE_PREFIX,
        cycle_source_artifact_prefix=CONTROL_PLANE_CYCLE_SOURCE_PREFIX,
        artifact_retention_days=CONTROL_PLANE_ARTIFACT_RETENTION_DAYS,
        checkpoint_selection_policy=CONTROL_PLANE_CHECKPOINT_SELECTION_POLICY,
        execution_mode=CONTROL_PLANE_EXECUTION_MODE,
        api_url=CONTROL_PLANE_API_URL,
        permissions=CONTROL_PLANE_PERMISSIONS,
        runtime_pin_variable=CONTROL_PLANE_RUNTIME_PIN_VARIABLE,
        control_plane_id_variable=CONTROL_PLANE_ID_VARIABLE,
        frozen_at_ms=frozen_at_ms,
        validation_start_ms=bundle.validation_start_ms,
        validation_end_ms=bundle.validation_end_ms,
    )


def freeze_archive_clean_control_plane(
    *,
    runtime_root: Path,
    expected_pin_id: str,
    workflow_path: Path,
    frozen_at_ms: int,
) -> ArchiveCleanControlPlaneAttestation:
    pinned = load_pinned_archive_clean_runtime(
        runtime_root,
        expected_pin_id=expected_pin_id,
    )
    path = runtime_root / "control-plane.json"
    if path.exists():
        return verify_archive_clean_control_plane(
            path,
            runtime_root=runtime_root,
            expected_pin_id=expected_pin_id,
            workflow_path=workflow_path,
        )
    if frozen_at_ms >= pinned.bundle.validation_start_ms:
        raise HistoricalArchiveCleanControlPlaneError(
            "POST_CUTOVER_ARCHIVE_CLEAN_CONTROL_PLANE_FREEZE_FORBIDDEN"
        )

    expected = _build_attestation(
        pinned,
        workflow_path=workflow_path,
        frozen_at_ms=frozen_at_ms,
    )
    payload = (_canonical_json(expected.to_dict()) + "\n").encode("utf-8")
    temporary = path.with_name(".control-plane.json.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return expected


def _load_control_plane(path: Path) -> ArchiveCleanControlPlaneAttestation:
    try:
        raw = _mapping(
            json.loads(path.read_text(encoding="utf-8")),
            "archive clean control plane",
        )
        permissions_raw = raw.get("permissions")
        if not isinstance(permissions_raw, list):
            raise ValueError("permissions must be an array")
        attestation = ArchiveCleanControlPlaneAttestation(
            runtime_id=_string(raw.get("runtime_id"), "runtime_id"),
            pin_id=_string(raw.get("pin_id"), "pin_id"),
            candidate_id=_string(raw.get("candidate_id"), "candidate_id"),
            model_artifact_id=_string(
                raw.get("model_artifact_id"),
                "model_artifact_id",
            ),
            validation_spec_id=_string(
                raw.get("validation_spec_id"),
                "validation_spec_id",
            ),
            observer_source_attestation_id=_string(
                raw.get("observer_source_attestation_id"),
                "observer_source_attestation_id",
            ),
            observer_source_tree_sha256=_string(
                raw.get("observer_source_tree_sha256"),
                "observer_source_tree_sha256",
            ),
            workflow_path=_string(raw.get("workflow_path"), "workflow_path"),
            workflow_sha256=_string(raw.get("workflow_sha256"), "workflow_sha256"),
            runtime_root=_string(raw.get("runtime_root"), "runtime_root"),
            schedule_cron=_string(raw.get("schedule_cron"), "schedule_cron"),
            concurrency_group=_string(
                raw.get("concurrency_group"),
                "concurrency_group",
            ),
            cancel_in_progress=_boolean(
                raw.get("cancel_in_progress"),
                "cancel_in_progress",
            ),
            job_timeout_minutes=_integer(
                raw.get("job_timeout_minutes"),
                "job_timeout_minutes",
            ),
            checkpoint_artifact_name=_string(
                raw.get("checkpoint_artifact_name"),
                "checkpoint_artifact_name",
            ),
            cycle_evidence_artifact_prefix=_string(
                raw.get("cycle_evidence_artifact_prefix"),
                "cycle_evidence_artifact_prefix",
            ),
            cycle_source_artifact_prefix=_string(
                raw.get("cycle_source_artifact_prefix"),
                "cycle_source_artifact_prefix",
            ),
            artifact_retention_days=_integer(
                raw.get("artifact_retention_days"),
                "artifact_retention_days",
            ),
            checkpoint_selection_policy=_string(
                raw.get("checkpoint_selection_policy"),
                "checkpoint_selection_policy",
            ),
            execution_mode=_string(raw.get("execution_mode"), "execution_mode"),
            api_url=_string(raw.get("api_url"), "api_url"),
            permissions=tuple(
                _string(item, "permission") for item in permissions_raw
            ),
            runtime_pin_variable=_string(
                raw.get("runtime_pin_variable"),
                "runtime_pin_variable",
            ),
            control_plane_id_variable=_string(
                raw.get("control_plane_id_variable"),
                "control_plane_id_variable",
            ),
            frozen_at_ms=_integer(raw.get("frozen_at_ms"), "frozen_at_ms"),
            validation_start_ms=_integer(
                raw.get("validation_start_ms"),
                "validation_start_ms",
            ),
            validation_end_ms=_integer(
                raw.get("validation_end_ms"),
                "validation_end_ms",
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
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise HistoricalArchiveCleanControlPlaneError(
            "ARCHIVE_CLEAN_CONTROL_PLANE_INVALID"
        ) from exc
    if raw.get("control_plane_id") != attestation.control_plane_id:
        raise HistoricalArchiveCleanControlPlaneError(
            "ARCHIVE_CLEAN_CONTROL_PLANE_ID_MISMATCH"
        )
    if path.read_text(encoding="utf-8") != _canonical_json(
        attestation.to_dict()
    ) + "\n":
        raise HistoricalArchiveCleanControlPlaneError(
            "ARCHIVE_CLEAN_CONTROL_PLANE_NON_CANONICAL"
        )
    return attestation


def verify_archive_clean_control_plane(
    path: Path,
    *,
    runtime_root: Path,
    expected_pin_id: str,
    workflow_path: Path,
    expected_control_plane_id: str | None = None,
) -> ArchiveCleanControlPlaneAttestation:
    attestation = _load_control_plane(path)
    if (
        expected_control_plane_id is not None
        and attestation.control_plane_id != expected_control_plane_id
    ):
        raise HistoricalArchiveCleanControlPlaneError(
            "ARCHIVE_CLEAN_CONTROL_PLANE_NOT_EXPECTED"
        )
    pinned = load_pinned_archive_clean_runtime(
        runtime_root,
        expected_pin_id=expected_pin_id,
    )
    expected = _build_attestation(
        pinned,
        workflow_path=workflow_path,
        frozen_at_ms=attestation.frozen_at_ms,
    )
    if expected != attestation:
        raise HistoricalArchiveCleanControlPlaneError(
            "ARCHIVE_CLEAN_CONTROL_PLANE_EVIDENCE_MISMATCH"
        )
    return attestation
