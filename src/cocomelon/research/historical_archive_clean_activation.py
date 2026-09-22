from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from cocomelon.research.historical_archive_clean_bootstrap import (
    verify_archive_clean_bootstrap_state,
)
from cocomelon.research.historical_archive_clean_checkpoint import (
    build_archive_clean_initial_checkpoint,
)
from cocomelon.research.historical_archive_clean_control_plane import (
    build_archive_clean_control_plane,
    load_archive_clean_control_plane,
)
from cocomelon.research.historical_archive_clean_readiness import (
    STATUS_READY_FOR_CUTOVER,
    build_archive_clean_activation_readiness,
)
from cocomelon.research.historical_archive_clean_runtime import (
    PinnedArchiveCleanRuntime,
)

ACTIVATION_KIND = "historical-archive-clean-activation-authorization"
ACTIVATION_SCHEMA_VERSION = 1


class HistoricalArchiveCleanActivationError(RuntimeError):
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
        raise HistoricalArchiveCleanActivationError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalArchiveCleanActivationError(
            f"{field} must be a non-empty string"
        )
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise HistoricalArchiveCleanActivationError(f"{field} must be an integer")
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise HistoricalArchiveCleanActivationError(f"{field} must be boolean")
    return value


@dataclass(frozen=True, slots=True)
class ArchiveCleanActivationAuthorization:
    runtime_id: str
    pin_id: str
    campaign_id: str
    candidate_id: str
    validation_spec_id: str
    model_artifact_id: str
    candidate_package_id: str
    candidate_package_sha256: str
    bootstrap_id: str
    bootstrap_checkpoint_id: str
    control_plane_id: str
    frozen_revision: str
    authorization_source_revision: str
    runtime_artifact_id: str
    authorized_at_ms: int
    validation_start_ms: int
    validation_end_ms: int
    finalization_not_before_ms: int
    activation_artifact_name: str
    readiness_status: str = STATUS_READY_FOR_CUTOVER
    kind: str = ACTIVATION_KIND
    paper_only: bool = True
    prospective_only: bool = True
    campaign_enabled_at_authorization: bool = False
    activation_authorized: bool = True
    promotion_eligible: bool = False
    execution_ready: bool = False
    schema_version: int = ACTIVATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in (
            "runtime_id",
            "pin_id",
            "campaign_id",
            "candidate_id",
            "validation_spec_id",
            "model_artifact_id",
            "candidate_package_id",
            "candidate_package_sha256",
            "bootstrap_id",
            "bootstrap_checkpoint_id",
            "control_plane_id",
        ):
            _require_sha256(getattr(self, field), field)
        if not re.fullmatch(r"[0-9a-f]{40}", self.frozen_revision):
            raise ValueError("frozen_revision must be a lowercase git SHA")
        if not re.fullmatch(r"[0-9a-f]{40}", self.authorization_source_revision):
            raise ValueError(
                "authorization_source_revision must be a lowercase git SHA"
            )
        if not self.runtime_artifact_id.isdigit():
            raise ValueError("runtime_artifact_id must be numeric")
        if self.authorized_at_ms < 0:
            raise ValueError("authorized_at_ms must be non-negative")
        if self.validation_start_ms <= 0:
            raise ValueError("validation_start_ms must be positive")
        if self.authorized_at_ms >= self.validation_start_ms:
            raise ValueError("activation authorization must be pre-cutover")
        if self.validation_end_ms <= self.validation_start_ms:
            raise ValueError("validation_end_ms must follow validation_start_ms")
        if self.finalization_not_before_ms < self.validation_end_ms:
            raise ValueError("finalization boundary cannot precede validation end")
        expected_name = f"historical-archive-clean-activation-{self.pin_id}"
        if self.activation_artifact_name != expected_name:
            raise ValueError("activation artifact name must be pin scoped")
        if self.readiness_status != STATUS_READY_FOR_CUTOVER:
            raise ValueError("activation authorization requires cutover readiness")
        if self.kind != ACTIVATION_KIND:
            raise ValueError("unsupported archive clean activation kind")
        if not self.paper_only or not self.prospective_only:
            raise ValueError("activation authorization must remain paper/prospective")
        if self.campaign_enabled_at_authorization:
            raise ValueError("campaign must remain disabled during authorization")
        if not self.activation_authorized:
            raise ValueError("activation authorization must be explicitly authorized")
        if self.promotion_eligible or self.execution_ready:
            raise ValueError("activation authorization cannot enable execution")
        if self.schema_version != ACTIVATION_SCHEMA_VERSION:
            raise ValueError("unsupported activation authorization schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "runtime_id": self.runtime_id,
            "pin_id": self.pin_id,
            "campaign_id": self.campaign_id,
            "candidate_id": self.candidate_id,
            "validation_spec_id": self.validation_spec_id,
            "model_artifact_id": self.model_artifact_id,
            "candidate_package_id": self.candidate_package_id,
            "candidate_package_sha256": self.candidate_package_sha256,
            "bootstrap_id": self.bootstrap_id,
            "bootstrap_checkpoint_id": self.bootstrap_checkpoint_id,
            "control_plane_id": self.control_plane_id,
            "frozen_revision": self.frozen_revision,
            "authorization_source_revision": self.authorization_source_revision,
            "runtime_artifact_id": self.runtime_artifact_id,
            "authorized_at_ms": self.authorized_at_ms,
            "validation_start_ms": self.validation_start_ms,
            "validation_end_ms": self.validation_end_ms,
            "finalization_not_before_ms": self.finalization_not_before_ms,
            "activation_artifact_name": self.activation_artifact_name,
            "readiness_status": self.readiness_status,
            "paper_only": self.paper_only,
            "prospective_only": self.prospective_only,
            "campaign_enabled_at_authorization": (
                self.campaign_enabled_at_authorization
            ),
            "activation_authorized": self.activation_authorized,
            "promotion_eligible": self.promotion_eligible,
            "execution_ready": self.execution_ready,
            "schema_version": self.schema_version,
        }

    @property
    def authorization_id(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "authorization_id": self.authorization_id}


def _expected_authorization(
    pinned: PinnedArchiveCleanRuntime,
    *,
    bootstrap_id: str,
    bootstrap_checkpoint_id: str,
    control_plane_id: str,
    frozen_revision: str,
    authorization_source_revision: str,
    runtime_artifact_id: str,
    authorized_at_ms: int,
) -> ArchiveCleanActivationAuthorization:
    bundle = pinned.bundle
    spec = pinned.runtime.spec
    if (
        not bundle.portable_package_bound
        or bundle.candidate_package_id is None
        or bundle.candidate_package_sha256 is None
        or pinned.pin.candidate_package_id != bundle.candidate_package_id
        or not pinned.pin.portable_package_bound
    ):
        raise HistoricalArchiveCleanActivationError(
            "ARCHIVE_CLEAN_ACTIVATION_PORTABLE_PACKAGE_REQUIRED"
        )
    return ArchiveCleanActivationAuthorization(
        runtime_id=bundle.runtime_id,
        pin_id=pinned.pin.pin_id,
        campaign_id=build_archive_clean_initial_checkpoint(
            spec,
            runtime_id=bundle.runtime_id,
            pin_id=pinned.pin.pin_id,
        ).campaign_id,
        candidate_id=bundle.candidate_id,
        validation_spec_id=bundle.validation_spec_id,
        model_artifact_id=bundle.model_artifact_id,
        candidate_package_id=bundle.candidate_package_id,
        candidate_package_sha256=bundle.candidate_package_sha256,
        bootstrap_id=bootstrap_id,
        bootstrap_checkpoint_id=bootstrap_checkpoint_id,
        control_plane_id=control_plane_id,
        frozen_revision=frozen_revision,
        authorization_source_revision=authorization_source_revision,
        runtime_artifact_id=runtime_artifact_id,
        authorized_at_ms=authorized_at_ms,
        validation_start_ms=spec.validation_start_ms,
        validation_end_ms=spec.validation_end_ms,
        finalization_not_before_ms=spec.finalization_not_before_ms,
        activation_artifact_name=(
            f"historical-archive-clean-activation-{pinned.pin.pin_id}"
        ),
    )


def build_archive_clean_activation_authorization(
    pinned: PinnedArchiveCleanRuntime,
    *,
    state_root: Path,
    frozen_revision: str,
    authorization_source_revision: str,
    runtime_artifact_id: str,
    as_of_ms: int,
) -> ArchiveCleanActivationAuthorization:
    if as_of_ms < 0:
        raise ValueError("as_of_ms must be non-negative")
    if as_of_ms >= pinned.runtime.spec.validation_start_ms:
        raise HistoricalArchiveCleanActivationError(
            "POST_CUTOVER_ARCHIVE_CLEAN_ACTIVATION_AUTHORIZATION_FORBIDDEN"
        )
    bootstrap = verify_archive_clean_bootstrap_state(
        pinned,
        state_root=state_root,
        frozen_revision=frozen_revision,
        runtime_artifact_id=runtime_artifact_id,
    )
    readiness = build_archive_clean_activation_readiness(
        pinned,
        state_root=state_root,
        frozen_revision=frozen_revision,
        runtime_artifact_id=runtime_artifact_id,
        enabled=True,
        as_of_ms=as_of_ms,
    )
    if (
        readiness.status != STATUS_READY_FOR_CUTOVER
        or not readiness.activation_ready
        or not readiness.operationally_valid
        or readiness.reasons
        or readiness.checkpoint_id != bootstrap.checkpoint_id
        or readiness.control_plane_id != bootstrap.control_plane_id
    ):
        raise HistoricalArchiveCleanActivationError(
            "ARCHIVE_CLEAN_ACTIVATION_NOT_READY"
        )
    return _expected_authorization(
        pinned,
        bootstrap_id=bootstrap.bootstrap_id,
        bootstrap_checkpoint_id=bootstrap.checkpoint_id,
        control_plane_id=bootstrap.control_plane_id,
        frozen_revision=frozen_revision,
        authorization_source_revision=authorization_source_revision,
        runtime_artifact_id=runtime_artifact_id,
        authorized_at_ms=as_of_ms,
    )


def write_archive_clean_activation_authorization(
    output_root: Path,
    authorization: ArchiveCleanActivationAuthorization,
) -> Path:
    path = output_root / "activation.json"
    data = (_canonical_json(authorization.to_dict()) + "\n").encode("utf-8")
    output_root.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise HistoricalArchiveCleanActivationError(
                "ARCHIVE_CLEAN_ACTIVATION_AUTHORIZATION_CONFLICT"
            )
        return path
    temporary = output_root / ".activation.json.tmp"
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return path


def load_archive_clean_activation_authorization(
    path: Path,
) -> ArchiveCleanActivationAuthorization:
    try:
        raw = _mapping(
            json.loads(path.read_text(encoding="utf-8")),
            "archive clean activation authorization",
        )
        authorization = ArchiveCleanActivationAuthorization(
            runtime_id=_string(raw.get("runtime_id"), "runtime_id"),
            pin_id=_string(raw.get("pin_id"), "pin_id"),
            campaign_id=_string(raw.get("campaign_id"), "campaign_id"),
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
            bootstrap_id=_string(raw.get("bootstrap_id"), "bootstrap_id"),
            bootstrap_checkpoint_id=_string(
                raw.get("bootstrap_checkpoint_id"),
                "bootstrap_checkpoint_id",
            ),
            control_plane_id=_string(
                raw.get("control_plane_id"),
                "control_plane_id",
            ),
            frozen_revision=_string(
                raw.get("frozen_revision"),
                "frozen_revision",
            ),
            authorization_source_revision=_string(
                raw.get("authorization_source_revision"),
                "authorization_source_revision",
            ),
            runtime_artifact_id=_string(
                raw.get("runtime_artifact_id"),
                "runtime_artifact_id",
            ),
            authorized_at_ms=_integer(
                raw.get("authorized_at_ms"),
                "authorized_at_ms",
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
            activation_artifact_name=_string(
                raw.get("activation_artifact_name"),
                "activation_artifact_name",
            ),
            readiness_status=_string(
                raw.get("readiness_status"),
                "readiness_status",
            ),
            kind=_string(raw.get("kind"), "kind"),
            paper_only=_boolean(raw.get("paper_only"), "paper_only"),
            prospective_only=_boolean(
                raw.get("prospective_only"),
                "prospective_only",
            ),
            campaign_enabled_at_authorization=_boolean(
                raw.get("campaign_enabled_at_authorization"),
                "campaign_enabled_at_authorization",
            ),
            activation_authorized=_boolean(
                raw.get("activation_authorized"),
                "activation_authorized",
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
        raise HistoricalArchiveCleanActivationError(
            "ARCHIVE_CLEAN_ACTIVATION_AUTHORIZATION_INVALID"
        ) from exc
    if raw.get("authorization_id") != authorization.authorization_id:
        raise HistoricalArchiveCleanActivationError(
            "ARCHIVE_CLEAN_ACTIVATION_AUTHORIZATION_ID_MISMATCH"
        )
    if path.read_text(encoding="utf-8") != _canonical_json(
        authorization.to_dict()
    ) + "\n":
        raise HistoricalArchiveCleanActivationError(
            "ARCHIVE_CLEAN_ACTIVATION_AUTHORIZATION_NON_CANONICAL"
        )
    return authorization


def verify_archive_clean_activation_authorization(
    path: Path,
    *,
    pinned: PinnedArchiveCleanRuntime,
    state_root: Path,
    frozen_revision: str,
    runtime_artifact_id: str,
) -> ArchiveCleanActivationAuthorization:
    authorization = load_archive_clean_activation_authorization(path)
    control_plane = load_archive_clean_control_plane(
        state_root / "control-plane.json"
    )
    expected_control = build_archive_clean_control_plane(
        pinned,
        frozen_revision=frozen_revision,
        runtime_artifact_id=runtime_artifact_id,
    )
    if control_plane != expected_control:
        raise HistoricalArchiveCleanActivationError(
            "ARCHIVE_CLEAN_ACTIVATION_CONTROL_PLANE_MISMATCH"
        )
    expected = _expected_authorization(
        pinned,
        bootstrap_id=authorization.bootstrap_id,
        bootstrap_checkpoint_id=authorization.bootstrap_checkpoint_id,
        control_plane_id=control_plane.control_plane_id,
        frozen_revision=frozen_revision,
        authorization_source_revision=authorization.authorization_source_revision,
        runtime_artifact_id=runtime_artifact_id,
        authorized_at_ms=authorization.authorized_at_ms,
    )
    if authorization != expected:
        raise HistoricalArchiveCleanActivationError(
            "ARCHIVE_CLEAN_ACTIVATION_AUTHORIZATION_MISMATCH"
        )
    return authorization
