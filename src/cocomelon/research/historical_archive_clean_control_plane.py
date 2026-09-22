from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from cocomelon.research.historical_archive_clean_runtime import (
    PinnedArchiveCleanRuntime,
)
from cocomelon.research.prospective_context_evidence import (
    MAX_ENTRY_CANDLE_AGE_MS,
)

CONTROL_PLANE_KIND = "historical-archive-clean-control-plane"
CONTROL_PLANE_SCHEMA_VERSION = 2
CAPTURE_SCHEDULE_CRON = "2,7,12,17,22,27,32,37,42,47,52,57 * * * *"
CAPTURE_ATTEMPT_MINUTES_UTC = (2, 7, 12, 17, 22, 27, 32, 37, 42, 47, 52, 57)
WORKFLOW_PATH = ".github/workflows/historical-archive-clean.yml"
EXECUTION_MODE = "paper"
API_URL = "https://api.hyperliquid.xyz"
WS_URL = "wss://api.hyperliquid.xyz/ws"
JOB_TIMEOUT_MINUTES = 12
CONTENTS_PERMISSION = "read"
ACTIONS_PERMISSION = "read"
ARTIFACT_RETENTION_DAYS = 90


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
        raise HistoricalArchiveCleanControlPlaneError(
            f"{field} must be an object"
        )
    return cast(dict[str, object], value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalArchiveCleanControlPlaneError(
            f"{field} must be a non-empty string"
        )
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise HistoricalArchiveCleanControlPlaneError(
            f"{field} must be an integer"
        )
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise HistoricalArchiveCleanControlPlaneError(
            f"{field} must be boolean"
        )
    return value


def _sequence(value: object, field: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise HistoricalArchiveCleanControlPlaneError(
            f"{field} must be a sequence"
        )
    return tuple(value)


@dataclass(frozen=True, slots=True)
class ArchiveCleanControlPlaneAttestation:
    runtime_id: str
    pin_id: str
    candidate_id: str
    validation_spec_id: str
    model_artifact_id: str
    candidate_package_id: str
    candidate_package_sha256: str
    frozen_revision: str
    runtime_artifact_id: str
    workflow_path: str
    schedule_cron: str
    attempt_minutes_utc: tuple[int, ...]
    max_entry_candle_age_ms: int
    state_artifact_name: str
    execution_mode: str
    api_url: str
    ws_url: str
    concurrency_group: str
    cancel_in_progress: bool
    job_timeout_minutes: int
    contents_permission: str
    actions_permission: str
    artifact_retention_days: int
    kind: str = CONTROL_PLANE_KIND
    schema_version: int = CONTROL_PLANE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in (
            "runtime_id",
            "pin_id",
            "candidate_id",
            "validation_spec_id",
            "model_artifact_id",
            "candidate_package_id",
            "candidate_package_sha256",
        ):
            _require_sha256(getattr(self, field), field)
        if not re.fullmatch(r"[0-9a-f]{40}", self.frozen_revision):
            raise ValueError("frozen_revision must be a lowercase git SHA")
        if not self.runtime_artifact_id.isdigit():
            raise ValueError("runtime_artifact_id must be numeric")
        if self.workflow_path != WORKFLOW_PATH:
            raise ValueError("workflow_path must match frozen control plane")
        if self.schedule_cron != CAPTURE_SCHEDULE_CRON:
            raise ValueError("schedule_cron must match frozen control plane")
        if self.attempt_minutes_utc != CAPTURE_ATTEMPT_MINUTES_UTC:
            raise ValueError(
                "attempt_minutes_utc must match frozen control plane"
            )
        if self.max_entry_candle_age_ms != MAX_ENTRY_CANDLE_AGE_MS:
            raise ValueError(
                "max_entry_candle_age_ms must match observer freshness"
            )
        expected_state_name = f"historical-archive-clean-state-{self.pin_id}"
        if self.state_artifact_name != expected_state_name:
            raise ValueError("state_artifact_name must be pin scoped")
        if self.execution_mode != EXECUTION_MODE:
            raise ValueError("execution_mode must remain paper")
        if self.api_url != API_URL or self.ws_url != WS_URL:
            raise ValueError("control plane must use canonical mainnet endpoints")
        expected_group = f"historical-archive-clean-{self.pin_id}"
        if self.concurrency_group != expected_group:
            raise ValueError("concurrency_group must be pin scoped")
        if self.cancel_in_progress:
            raise ValueError("clean observer runs must not cancel in progress")
        if self.job_timeout_minutes != JOB_TIMEOUT_MINUTES:
            raise ValueError("job_timeout_minutes must match frozen control plane")
        if self.contents_permission != CONTENTS_PERMISSION:
            raise ValueError("contents_permission must remain read-only")
        if self.actions_permission != ACTIONS_PERMISSION:
            raise ValueError("actions_permission must remain read-only")
        if self.artifact_retention_days != ARTIFACT_RETENTION_DAYS:
            raise ValueError(
                "artifact_retention_days must match frozen control plane"
            )
        if self.kind != CONTROL_PLANE_KIND:
            raise ValueError("unsupported control plane kind")
        if self.schema_version != CONTROL_PLANE_SCHEMA_VERSION:
            raise ValueError("unsupported control plane schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "runtime_id": self.runtime_id,
            "pin_id": self.pin_id,
            "candidate_id": self.candidate_id,
            "validation_spec_id": self.validation_spec_id,
            "model_artifact_id": self.model_artifact_id,
            "candidate_package_id": self.candidate_package_id,
            "candidate_package_sha256": self.candidate_package_sha256,
            "frozen_revision": self.frozen_revision,
            "runtime_artifact_id": self.runtime_artifact_id,
            "workflow_path": self.workflow_path,
            "schedule_cron": self.schedule_cron,
            "attempt_minutes_utc": self.attempt_minutes_utc,
            "max_entry_candle_age_ms": self.max_entry_candle_age_ms,
            "state_artifact_name": self.state_artifact_name,
            "execution_mode": self.execution_mode,
            "api_url": self.api_url,
            "ws_url": self.ws_url,
            "concurrency_group": self.concurrency_group,
            "cancel_in_progress": self.cancel_in_progress,
            "job_timeout_minutes": self.job_timeout_minutes,
            "contents_permission": self.contents_permission,
            "actions_permission": self.actions_permission,
            "artifact_retention_days": self.artifact_retention_days,
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


def build_archive_clean_control_plane(
    pinned: PinnedArchiveCleanRuntime,
    *,
    frozen_revision: str,
    runtime_artifact_id: str,
) -> ArchiveCleanControlPlaneAttestation:
    if (
        not pinned.bundle.portable_package_bound
        or pinned.bundle.candidate_package_id is None
        or pinned.bundle.candidate_package_sha256 is None
        or pinned.pin.candidate_package_id
        != pinned.bundle.candidate_package_id
        or not pinned.pin.portable_package_bound
    ):
        raise HistoricalArchiveCleanControlPlaneError(
            "ARCHIVE_CLEAN_CONTROL_PLANE_PORTABLE_PACKAGE_REQUIRED"
        )
    pin_id = pinned.pin.pin_id
    return ArchiveCleanControlPlaneAttestation(
        runtime_id=pinned.bundle.runtime_id,
        pin_id=pin_id,
        candidate_id=pinned.bundle.candidate_id,
        validation_spec_id=pinned.bundle.validation_spec_id,
        model_artifact_id=pinned.bundle.model_artifact_id,
        candidate_package_id=pinned.bundle.candidate_package_id,
        candidate_package_sha256=pinned.bundle.candidate_package_sha256,
        frozen_revision=frozen_revision,
        runtime_artifact_id=runtime_artifact_id,
        workflow_path=WORKFLOW_PATH,
        schedule_cron=CAPTURE_SCHEDULE_CRON,
        attempt_minutes_utc=CAPTURE_ATTEMPT_MINUTES_UTC,
        max_entry_candle_age_ms=MAX_ENTRY_CANDLE_AGE_MS,
        state_artifact_name=f"historical-archive-clean-state-{pin_id}",
        execution_mode=EXECUTION_MODE,
        api_url=API_URL,
        ws_url=WS_URL,
        concurrency_group=f"historical-archive-clean-{pin_id}",
        cancel_in_progress=False,
        job_timeout_minutes=JOB_TIMEOUT_MINUTES,
        contents_permission=CONTENTS_PERMISSION,
        actions_permission=ACTIONS_PERMISSION,
        artifact_retention_days=ARTIFACT_RETENTION_DAYS,
    )


def load_archive_clean_control_plane(
    path: Path,
) -> ArchiveCleanControlPlaneAttestation:
    try:
        raw = _mapping(
            json.loads(path.read_text(encoding="utf-8")),
            "archive clean control plane",
        )
        attestation = ArchiveCleanControlPlaneAttestation(
            runtime_id=_string(raw.get("runtime_id"), "runtime_id"),
            pin_id=_string(raw.get("pin_id"), "pin_id"),
            candidate_id=_string(raw.get("candidate_id"), "candidate_id"),
            validation_spec_id=_string(
                raw.get("validation_spec_id"),
                "validation_spec_id",
            ),
            model_artifact_id=_string(
                raw.get("model_artifact_id"),
                "model_artifact_id",
            ),
            candidate_package_id=_string(
                raw.get("candidate_package_id"),
                "candidate_package_id",
            ),
            candidate_package_sha256=_string(
                raw.get("candidate_package_sha256"),
                "candidate_package_sha256",
            ),
            frozen_revision=_string(
                raw.get("frozen_revision"),
                "frozen_revision",
            ),
            runtime_artifact_id=_string(
                raw.get("runtime_artifact_id"),
                "runtime_artifact_id",
            ),
            workflow_path=_string(raw.get("workflow_path"), "workflow_path"),
            schedule_cron=_string(raw.get("schedule_cron"), "schedule_cron"),
            attempt_minutes_utc=tuple(
                _integer(item, "attempt_minutes_utc")
                for item in _sequence(
                    raw.get("attempt_minutes_utc"),
                    "attempt_minutes_utc",
                )
            ),
            max_entry_candle_age_ms=_integer(
                raw.get("max_entry_candle_age_ms"),
                "max_entry_candle_age_ms",
            ),
            state_artifact_name=_string(
                raw.get("state_artifact_name"),
                "state_artifact_name",
            ),
            execution_mode=_string(
                raw.get("execution_mode"),
                "execution_mode",
            ),
            api_url=_string(raw.get("api_url"), "api_url"),
            ws_url=_string(raw.get("ws_url"), "ws_url"),
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
            contents_permission=_string(
                raw.get("contents_permission"),
                "contents_permission",
            ),
            actions_permission=_string(
                raw.get("actions_permission"),
                "actions_permission",
            ),
            artifact_retention_days=_integer(
                raw.get("artifact_retention_days"),
                "artifact_retention_days",
            ),
            kind=_string(raw.get("kind"), "kind"),
            schema_version=_integer(
                raw.get("schema_version"),
                "schema_version",
            ),
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise HistoricalArchiveCleanControlPlaneError(
            "ARCHIVE_CLEAN_CONTROL_PLANE_INVALID"
        ) from exc
    if raw.get("control_plane_id") != attestation.control_plane_id:
        raise HistoricalArchiveCleanControlPlaneError(
            "ARCHIVE_CLEAN_CONTROL_PLANE_ID_MISMATCH"
        )
    if path.read_text(encoding="utf-8") != (
        _canonical_json(attestation.to_dict()) + "\n"
    ):
        raise HistoricalArchiveCleanControlPlaneError(
            "ARCHIVE_CLEAN_CONTROL_PLANE_NON_CANONICAL"
        )
    return attestation


def write_archive_clean_control_plane(
    path: Path,
    attestation: ArchiveCleanControlPlaneAttestation,
) -> Path:
    payload = (_canonical_json(attestation.to_dict()) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise HistoricalArchiveCleanControlPlaneError(
                "CONFLICTING_ARCHIVE_CLEAN_CONTROL_PLANE_ATTESTATION"
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


def ensure_archive_clean_control_plane(
    state_root: Path,
    *,
    pinned: PinnedArchiveCleanRuntime,
    frozen_revision: str,
    runtime_artifact_id: str,
    as_of_ms: int,
) -> ArchiveCleanControlPlaneAttestation:
    expected = build_archive_clean_control_plane(
        pinned,
        frozen_revision=frozen_revision,
        runtime_artifact_id=runtime_artifact_id,
    )
    path = state_root / "control-plane.json"
    if path.exists():
        existing = load_archive_clean_control_plane(path)
        if existing != expected:
            raise HistoricalArchiveCleanControlPlaneError(
                "CONFLICTING_ARCHIVE_CLEAN_CONTROL_PLANE_ATTESTATION"
            )
        return existing
    if as_of_ms >= pinned.runtime.spec.validation_start_ms:
        raise HistoricalArchiveCleanControlPlaneError(
            "POST_CUTOVER_ARCHIVE_CLEAN_CONTROL_PLANE_REQUIRED"
        )
    write_archive_clean_control_plane(path, expected)
    return expected
