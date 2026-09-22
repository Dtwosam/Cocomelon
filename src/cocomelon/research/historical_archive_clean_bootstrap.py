from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from cocomelon.research.historical_archive_clean_checkpoint import (
    ArchiveCleanCheckpointEvidenceStore,
    ArchiveCleanOperationalCheckpoint,
    build_archive_clean_initial_checkpoint,
    load_archive_clean_operational_checkpoint,
)
from cocomelon.research.historical_archive_clean_control_plane import (
    ArchiveCleanControlPlaneAttestation,
    build_archive_clean_control_plane,
    ensure_archive_clean_control_plane,
)
from cocomelon.research.historical_archive_clean_runtime import (
    PinnedArchiveCleanRuntime,
)

BOOTSTRAP_SCHEMA_VERSION = 1
BOOTSTRAP_KIND = "historical-archive-clean-bootstrap"


class HistoricalArchiveCleanBootstrapError(RuntimeError):
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
        raise HistoricalArchiveCleanBootstrapError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalArchiveCleanBootstrapError(
            f"{field} must be a non-empty string"
        )
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise HistoricalArchiveCleanBootstrapError(f"{field} must be an integer")
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise HistoricalArchiveCleanBootstrapError(f"{field} must be boolean")
    return value


@dataclass(frozen=True, slots=True)
class ArchiveCleanBootstrapReceipt:
    runtime_id: str
    pin_id: str
    candidate_id: str
    validation_spec_id: str
    model_artifact_id: str
    candidate_package_id: str
    candidate_package_sha256: str
    checkpoint_id: str
    control_plane_id: str
    frozen_revision: str
    runtime_artifact_id: str
    bootstrap_as_of_ms: int
    validation_start_ms: int
    state_artifact_name: str
    kind: str = BOOTSTRAP_KIND
    paper_only: bool = True
    prospective_only: bool = True
    campaign_enabled: bool = False
    promotion_eligible: bool = False
    execution_ready: bool = False
    schema_version: int = BOOTSTRAP_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in (
            "runtime_id",
            "pin_id",
            "candidate_id",
            "validation_spec_id",
            "model_artifact_id",
            "candidate_package_id",
            "candidate_package_sha256",
            "checkpoint_id",
            "control_plane_id",
        ):
            _require_sha256(getattr(self, field), field)
        if not re.fullmatch(r"[0-9a-f]{40}", self.frozen_revision):
            raise ValueError("frozen_revision must be a lowercase git SHA")
        if not self.runtime_artifact_id.isdigit():
            raise ValueError("runtime_artifact_id must be numeric")
        if self.bootstrap_as_of_ms < 0:
            raise ValueError("bootstrap_as_of_ms must be non-negative")
        if self.validation_start_ms <= 0:
            raise ValueError("validation_start_ms must be positive")
        if self.bootstrap_as_of_ms >= self.validation_start_ms:
            raise ValueError("bootstrap must complete before validation cutover")
        expected_state_name = (
            f"historical-archive-clean-bootstrap-state-{self.pin_id}"
        )
        if self.state_artifact_name != expected_state_name:
            raise ValueError("state_artifact_name must be bootstrap pin scoped")
        if self.kind != BOOTSTRAP_KIND:
            raise ValueError("unsupported archive clean bootstrap kind")
        if not self.paper_only or not self.prospective_only:
            raise ValueError("bootstrap must remain paper/prospective only")
        if self.campaign_enabled:
            raise ValueError("bootstrap cannot enable the clean campaign")
        if self.promotion_eligible or self.execution_ready:
            raise ValueError("bootstrap cannot authorize promotion or execution")
        if self.schema_version != BOOTSTRAP_SCHEMA_VERSION:
            raise ValueError("unsupported archive clean bootstrap schema")

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
            "checkpoint_id": self.checkpoint_id,
            "control_plane_id": self.control_plane_id,
            "frozen_revision": self.frozen_revision,
            "runtime_artifact_id": self.runtime_artifact_id,
            "bootstrap_as_of_ms": self.bootstrap_as_of_ms,
            "validation_start_ms": self.validation_start_ms,
            "state_artifact_name": self.state_artifact_name,
            "paper_only": self.paper_only,
            "prospective_only": self.prospective_only,
            "campaign_enabled": self.campaign_enabled,
            "promotion_eligible": self.promotion_eligible,
            "execution_ready": self.execution_ready,
            "schema_version": self.schema_version,
        }

    @property
    def bootstrap_id(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "bootstrap_id": self.bootstrap_id}


def _expected_empty_checkpoint(
    pinned: PinnedArchiveCleanRuntime,
) -> ArchiveCleanOperationalCheckpoint:
    return build_archive_clean_initial_checkpoint(
        pinned.runtime.spec,
        runtime_id=pinned.bundle.runtime_id,
        pin_id=pinned.pin.pin_id,
    )


def _verify_empty_checkpoint(
    pinned: PinnedArchiveCleanRuntime,
    checkpoint: ArchiveCleanOperationalCheckpoint,
) -> None:
    expected = _expected_empty_checkpoint(pinned)
    lineage_fields = (
        "validation_spec_id",
        "candidate_id",
        "model_artifact_id",
        "campaign_id",
        "runtime_id",
        "pin_id",
        "first_expected_anchor_ms",
        "anchor_interval_ms",
        "expected_anchor_count",
        "stability_blocks",
        "anchors_per_stability_block",
    )
    if any(
        getattr(checkpoint, field) != getattr(expected, field)
        for field in lineage_fields
    ):
        raise HistoricalArchiveCleanBootstrapError(
            "ARCHIVE_CLEAN_BOOTSTRAP_CHECKPOINT_LINEAGE_MISMATCH"
        )
    if (
        checkpoint.captured_anchor_count != 0
        or checkpoint.latest_anchor_end_ms is not None
        or checkpoint.latest_observation_id is not None
        or checkpoint.latest_state != expected.latest_state
        or checkpoint.pending_observations
        or checkpoint.settled_outcome_count != 0
        or checkpoint.block_economics != expected.block_economics
    ):
        raise HistoricalArchiveCleanBootstrapError(
            "ARCHIVE_CLEAN_BOOTSTRAP_CHECKPOINT_NOT_EMPTY"
        )
    if checkpoint.as_of_ms >= pinned.runtime.spec.validation_start_ms:
        raise HistoricalArchiveCleanBootstrapError(
            "ARCHIVE_CLEAN_BOOTSTRAP_CHECKPOINT_POST_CUTOVER"
        )


def _receipt_from_payload(raw: dict[str, object]) -> ArchiveCleanBootstrapReceipt:
    try:
        receipt = ArchiveCleanBootstrapReceipt(
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
            checkpoint_id=_string(raw.get("checkpoint_id"), "checkpoint_id"),
            control_plane_id=_string(
                raw.get("control_plane_id"),
                "control_plane_id",
            ),
            frozen_revision=_string(
                raw.get("frozen_revision"),
                "frozen_revision",
            ),
            runtime_artifact_id=_string(
                raw.get("runtime_artifact_id"),
                "runtime_artifact_id",
            ),
            bootstrap_as_of_ms=_integer(
                raw.get("bootstrap_as_of_ms"),
                "bootstrap_as_of_ms",
            ),
            validation_start_ms=_integer(
                raw.get("validation_start_ms"),
                "validation_start_ms",
            ),
            state_artifact_name=_string(
                raw.get("state_artifact_name"),
                "state_artifact_name",
            ),
            kind=_string(raw.get("kind"), "kind"),
            paper_only=_boolean(raw.get("paper_only"), "paper_only"),
            prospective_only=_boolean(
                raw.get("prospective_only"),
                "prospective_only",
            ),
            campaign_enabled=_boolean(
                raw.get("campaign_enabled"),
                "campaign_enabled",
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
    except ValueError as exc:
        raise HistoricalArchiveCleanBootstrapError(
            "ARCHIVE_CLEAN_BOOTSTRAP_INVALID"
        ) from exc
    if raw.get("bootstrap_id") != receipt.bootstrap_id:
        raise HistoricalArchiveCleanBootstrapError(
            "ARCHIVE_CLEAN_BOOTSTRAP_ID_MISMATCH"
        )
    return receipt


def load_archive_clean_bootstrap_receipt(
    path: Path,
) -> ArchiveCleanBootstrapReceipt:
    try:
        raw = _mapping(
            json.loads(path.read_text(encoding="utf-8")),
            "archive clean bootstrap",
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise HistoricalArchiveCleanBootstrapError(
            "ARCHIVE_CLEAN_BOOTSTRAP_INVALID"
        ) from exc
    receipt = _receipt_from_payload(raw)
    if path.read_text(encoding="utf-8") != (
        _canonical_json(receipt.to_dict()) + "\n"
    ):
        raise HistoricalArchiveCleanBootstrapError(
            "ARCHIVE_CLEAN_BOOTSTRAP_NON_CANONICAL"
        )
    return receipt


def _write_consistent(path: Path, payload: dict[str, object]) -> Path:
    data = (_canonical_json(payload) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise HistoricalArchiveCleanBootstrapError(
                f"conflicting archive clean bootstrap file: {path.name}"
            )
        return path
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
    return path


def _expected_receipt(
    pinned: PinnedArchiveCleanRuntime,
    *,
    checkpoint: ArchiveCleanOperationalCheckpoint,
    control_plane: ArchiveCleanControlPlaneAttestation,
    frozen_revision: str,
    runtime_artifact_id: str,
    bootstrap_as_of_ms: int,
) -> ArchiveCleanBootstrapReceipt:
    package_id = pinned.bundle.candidate_package_id
    package_sha256 = pinned.bundle.candidate_package_sha256
    if (
        not pinned.bundle.portable_package_bound
        or package_id is None
        or package_sha256 is None
        or not pinned.pin.portable_package_bound
        or pinned.pin.candidate_package_id != package_id
    ):
        raise HistoricalArchiveCleanBootstrapError(
            "ARCHIVE_CLEAN_BOOTSTRAP_PORTABLE_PACKAGE_REQUIRED"
        )
    return ArchiveCleanBootstrapReceipt(
        runtime_id=pinned.bundle.runtime_id,
        pin_id=pinned.pin.pin_id,
        candidate_id=pinned.bundle.candidate_id,
        validation_spec_id=pinned.bundle.validation_spec_id,
        model_artifact_id=pinned.bundle.model_artifact_id,
        candidate_package_id=package_id,
        candidate_package_sha256=package_sha256,
        checkpoint_id=checkpoint.checkpoint_id,
        control_plane_id=control_plane.control_plane_id,
        frozen_revision=frozen_revision,
        runtime_artifact_id=runtime_artifact_id,
        bootstrap_as_of_ms=bootstrap_as_of_ms,
        validation_start_ms=pinned.runtime.spec.validation_start_ms,
        state_artifact_name=(
            f"historical-archive-clean-bootstrap-state-{pinned.pin.pin_id}"
        ),
    )


def bootstrap_archive_clean_state(
    pinned: PinnedArchiveCleanRuntime,
    *,
    state_root: Path,
    frozen_revision: str,
    runtime_artifact_id: str,
    as_of_ms: int,
) -> ArchiveCleanBootstrapReceipt:
    if as_of_ms < 0:
        raise ValueError("as_of_ms must be non-negative")
    if as_of_ms >= pinned.runtime.spec.validation_start_ms:
        raise HistoricalArchiveCleanBootstrapError(
            "POST_CUTOVER_ARCHIVE_CLEAN_BOOTSTRAP_FORBIDDEN"
        )

    # Validate immutable runtime/package/control-plane lineage before
    # touching bootstrap state.
    build_archive_clean_control_plane(
        pinned,
        frozen_revision=frozen_revision,
        runtime_artifact_id=runtime_artifact_id,
    )

    receipt_path = state_root / "bootstrap.json"
    checkpoint_path = state_root / "checkpoint.json"
    control_plane_path = state_root / "control-plane.json"

    if receipt_path.exists():
        receipt = load_archive_clean_bootstrap_receipt(receipt_path)
        if not checkpoint_path.is_file() or not control_plane_path.is_file():
            raise HistoricalArchiveCleanBootstrapError(
                "ARCHIVE_CLEAN_BOOTSTRAP_STATE_INCOMPLETE"
            )
        checkpoint = load_archive_clean_operational_checkpoint(checkpoint_path)
        _verify_empty_checkpoint(pinned, checkpoint)
        control_plane = ensure_archive_clean_control_plane(
            state_root,
            pinned=pinned,
            frozen_revision=frozen_revision,
            runtime_artifact_id=runtime_artifact_id,
            as_of_ms=as_of_ms,
        )
        expected = _expected_receipt(
            pinned,
            checkpoint=checkpoint,
            control_plane=control_plane,
            frozen_revision=frozen_revision,
            runtime_artifact_id=runtime_artifact_id,
            bootstrap_as_of_ms=receipt.bootstrap_as_of_ms,
        )
        if receipt != expected:
            raise HistoricalArchiveCleanBootstrapError(
                "ARCHIVE_CLEAN_BOOTSTRAP_RECEIPT_MISMATCH"
            )
        return receipt

    if checkpoint_path.exists() or control_plane_path.exists():
        raise HistoricalArchiveCleanBootstrapError(
            "ARCHIVE_CLEAN_BOOTSTRAP_UNATTESTED_STATE_PRESENT"
        )

    store = ArchiveCleanCheckpointEvidenceStore(
        checkpoint_path,
        cycle_evidence_root=state_root / ".bootstrap-evidence",
        spec=pinned.runtime.spec,
        runtime_id=pinned.bundle.runtime_id,
        pin_id=pinned.pin.pin_id,
    )
    checkpoint = store.save(as_of_ms=as_of_ms)
    _verify_empty_checkpoint(pinned, checkpoint)
    control_plane = ensure_archive_clean_control_plane(
        state_root,
        pinned=pinned,
        frozen_revision=frozen_revision,
        runtime_artifact_id=runtime_artifact_id,
        as_of_ms=as_of_ms,
    )
    receipt = _expected_receipt(
        pinned,
        checkpoint=checkpoint,
        control_plane=control_plane,
        frozen_revision=frozen_revision,
        runtime_artifact_id=runtime_artifact_id,
        bootstrap_as_of_ms=as_of_ms,
    )
    _write_consistent(receipt_path, receipt.to_dict())
    return receipt
