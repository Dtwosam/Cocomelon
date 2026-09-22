from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cocomelon.research.historical_archive_clean_checkpoint import (
    ArchiveCleanOperationalCheckpoint,
    build_archive_clean_initial_checkpoint,
    load_archive_clean_operational_checkpoint,
)
from cocomelon.research.historical_archive_clean_control_plane import (
    ArchiveCleanControlPlaneAttestation,
    build_archive_clean_control_plane,
    load_archive_clean_control_plane,
)
from cocomelon.research.historical_archive_clean_finalization import (
    ArchiveCleanFinalization,
    verify_archive_clean_finalization,
)
from cocomelon.research.historical_archive_clean_runtime import (
    PinnedArchiveCleanRuntime,
)

READINESS_SCHEMA_VERSION = 1
STATUS_BOOTSTRAP_REQUIRED = "bootstrap_required"
STATUS_READY_FOR_CUTOVER = "ready_for_cutover"
STATUS_ACTIVE = "active"
STATUS_POST_VALIDATION_SETTLEMENT = "post_validation_settlement"
STATUS_TERMINAL_SETTLEMENT = "terminal_settlement"
STATUS_FINALIZED = "finalized"
STATUS_BLOCKED = "blocked"


class HistoricalArchiveCleanReadinessError(RuntimeError):
    pass


def _checkpoint_lineage_tuple(
    checkpoint: ArchiveCleanOperationalCheckpoint,
) -> tuple[object, ...]:
    return (
        checkpoint.validation_spec_id,
        checkpoint.candidate_id,
        checkpoint.model_artifact_id,
        checkpoint.campaign_id,
        checkpoint.runtime_id,
        checkpoint.pin_id,
        checkpoint.first_expected_anchor_ms,
        checkpoint.anchor_interval_ms,
        checkpoint.expected_anchor_count,
        checkpoint.stability_blocks,
        checkpoint.anchors_per_stability_block,
    )


def _verify_checkpoint_lineage(
    pinned: PinnedArchiveCleanRuntime,
    checkpoint: ArchiveCleanOperationalCheckpoint,
) -> None:
    initial = build_archive_clean_initial_checkpoint(
        pinned.runtime.spec,
        runtime_id=pinned.bundle.runtime_id,
        pin_id=pinned.pin.pin_id,
    )
    if _checkpoint_lineage_tuple(checkpoint) != _checkpoint_lineage_tuple(initial):
        raise HistoricalArchiveCleanReadinessError(
            "ARCHIVE_CLEAN_READINESS_CHECKPOINT_LINEAGE_MISMATCH"
        )


@dataclass(frozen=True, slots=True)
class ArchiveCleanActivationReadiness:
    status: str
    enabled: bool
    activation_ready: bool
    operationally_valid: bool
    as_of_ms: int
    runtime_id: str
    pin_id: str
    campaign_id: str
    candidate_id: str
    validation_spec_id: str
    model_artifact_id: str
    control_plane_id: str | None
    checkpoint_id: str | None
    checkpoint_as_of_ms: int | None
    finalization_id: str | None
    terminal_verdict: str | None
    validation_start_ms: int
    validation_end_ms: int
    finalization_not_before_ms: int
    reasons: tuple[str, ...]
    paper_only: bool = True
    prospective_only: bool = True
    promotion_eligible: bool = False
    execution_ready: bool = False
    schema_version: int = READINESS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        allowed = {
            STATUS_BOOTSTRAP_REQUIRED,
            STATUS_READY_FOR_CUTOVER,
            STATUS_ACTIVE,
            STATUS_POST_VALIDATION_SETTLEMENT,
            STATUS_TERMINAL_SETTLEMENT,
            STATUS_FINALIZED,
            STATUS_BLOCKED,
        }
        if self.status not in allowed:
            raise ValueError("unsupported archive clean readiness status")
        for field in (
            "runtime_id",
            "pin_id",
            "campaign_id",
            "candidate_id",
            "validation_spec_id",
            "model_artifact_id",
        ):
            value = getattr(self, field)
            if len(value) != 64:
                raise ValueError(f"{field} must be SHA-256")
        for field in ("control_plane_id", "checkpoint_id", "finalization_id"):
            value = getattr(self, field)
            if value is not None and len(value) != 64:
                raise ValueError(f"{field} must be SHA-256 when present")
        if self.as_of_ms < 0:
            raise ValueError("as_of_ms must be non-negative")
        if self.validation_start_ms < 0:
            raise ValueError("validation_start_ms must be non-negative")
        if self.validation_end_ms <= self.validation_start_ms:
            raise ValueError("validation_end_ms must follow validation_start_ms")
        if self.finalization_not_before_ms < self.validation_end_ms:
            raise ValueError("finalization boundary cannot precede validation end")
        if self.checkpoint_as_of_ms is not None and self.checkpoint_as_of_ms < 0:
            raise ValueError("checkpoint_as_of_ms must be non-negative")
        if tuple(sorted(set(self.reasons))) != self.reasons:
            raise ValueError("reasons must be sorted unique")
        if self.status == STATUS_FINALIZED:
            if self.finalization_id is None or self.terminal_verdict is None:
                raise ValueError("finalized readiness requires terminal identity")
            if self.activation_ready:
                raise ValueError("finalized campaign is not activation ready")
            if not self.operationally_valid:
                raise ValueError("valid finalization must remain operationally valid")
        elif self.finalization_id is not None or self.terminal_verdict is not None:
            raise ValueError("terminal identity only belongs to finalized status")
        if self.activation_ready != (
            self.status
            in {
                STATUS_READY_FOR_CUTOVER,
                STATUS_ACTIVE,
                STATUS_POST_VALIDATION_SETTLEMENT,
                STATUS_TERMINAL_SETTLEMENT,
            }
        ):
            raise ValueError("activation_ready must match readiness status")
        if self.operationally_valid != (
            self.activation_ready or self.status == STATUS_FINALIZED
        ):
            raise ValueError("operationally_valid must match status")
        if not self.paper_only or not self.prospective_only:
            raise ValueError("archive clean readiness must remain paper/prospective")
        if self.promotion_eligible or self.execution_ready:
            raise ValueError("readiness cannot authorize promotion or execution")
        if self.schema_version != READINESS_SCHEMA_VERSION:
            raise ValueError("unsupported readiness schema")

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "enabled": self.enabled,
            "activation_ready": self.activation_ready,
            "operationally_valid": self.operationally_valid,
            "as_of_ms": self.as_of_ms,
            "runtime_id": self.runtime_id,
            "pin_id": self.pin_id,
            "campaign_id": self.campaign_id,
            "candidate_id": self.candidate_id,
            "validation_spec_id": self.validation_spec_id,
            "model_artifact_id": self.model_artifact_id,
            "control_plane_id": self.control_plane_id,
            "checkpoint_id": self.checkpoint_id,
            "checkpoint_as_of_ms": self.checkpoint_as_of_ms,
            "finalization_id": self.finalization_id,
            "terminal_verdict": self.terminal_verdict,
            "validation_start_ms": self.validation_start_ms,
            "validation_end_ms": self.validation_end_ms,
            "finalization_not_before_ms": self.finalization_not_before_ms,
            "reasons": self.reasons,
            "paper_only": self.paper_only,
            "prospective_only": self.prospective_only,
            "promotion_eligible": self.promotion_eligible,
            "execution_ready": self.execution_ready,
            "schema_version": self.schema_version,
        }


def _load_checkpoint(
    pinned: PinnedArchiveCleanRuntime,
    state_root: Path,
) -> ArchiveCleanOperationalCheckpoint | None:
    path = state_root / "checkpoint.json"
    if not path.exists():
        return None
    checkpoint = load_archive_clean_operational_checkpoint(path)
    _verify_checkpoint_lineage(pinned, checkpoint)
    return checkpoint


def _load_control_plane(
    pinned: PinnedArchiveCleanRuntime,
    state_root: Path,
    *,
    frozen_revision: str,
    runtime_artifact_id: str,
) -> ArchiveCleanControlPlaneAttestation | None:
    path = state_root / "control-plane.json"
    if not path.exists():
        return None
    loaded = load_archive_clean_control_plane(path)
    expected = build_archive_clean_control_plane(
        pinned,
        frozen_revision=frozen_revision,
        runtime_artifact_id=runtime_artifact_id,
    )
    if loaded != expected:
        raise HistoricalArchiveCleanReadinessError(
            "ARCHIVE_CLEAN_READINESS_CONTROL_PLANE_MISMATCH"
        )
    return loaded


def _load_finalization(
    pinned: PinnedArchiveCleanRuntime,
    state_root: Path,
    checkpoint: ArchiveCleanOperationalCheckpoint | None,
) -> ArchiveCleanFinalization | None:
    path = state_root / "finalization" / "finalization.json"
    if not path.exists():
        return None
    if checkpoint is None:
        raise HistoricalArchiveCleanReadinessError(
            "ARCHIVE_CLEAN_READINESS_FINALIZATION_WITHOUT_CHECKPOINT"
        )
    return verify_archive_clean_finalization(
        path,
        spec=pinned.runtime.spec,
        runtime_id=pinned.bundle.runtime_id,
        pin_id=pinned.pin.pin_id,
        checkpoint=checkpoint,
    )


def build_archive_clean_activation_readiness(
    pinned: PinnedArchiveCleanRuntime,
    *,
    state_root: Path,
    frozen_revision: str,
    runtime_artifact_id: str,
    enabled: bool,
    as_of_ms: int,
) -> ArchiveCleanActivationReadiness:
    if as_of_ms < 0:
        raise ValueError("as_of_ms must be non-negative")

    initial = build_archive_clean_initial_checkpoint(
        pinned.runtime.spec,
        runtime_id=pinned.bundle.runtime_id,
        pin_id=pinned.pin.pin_id,
    )
    checkpoint = _load_checkpoint(pinned, state_root)
    control_plane = _load_control_plane(
        pinned,
        state_root,
        frozen_revision=frozen_revision,
        runtime_artifact_id=runtime_artifact_id,
    )
    finalization = _load_finalization(pinned, state_root, checkpoint)

    if checkpoint is not None and checkpoint.as_of_ms > as_of_ms:
        raise HistoricalArchiveCleanReadinessError(
            "ARCHIVE_CLEAN_READINESS_CHECKPOINT_FROM_FUTURE"
        )

    if finalization is not None:
        return ArchiveCleanActivationReadiness(
            status=STATUS_FINALIZED,
            enabled=enabled,
            activation_ready=False,
            operationally_valid=True,
            as_of_ms=as_of_ms,
            runtime_id=pinned.bundle.runtime_id,
            pin_id=pinned.pin.pin_id,
            campaign_id=initial.campaign_id,
            candidate_id=pinned.bundle.candidate_id,
            validation_spec_id=pinned.bundle.validation_spec_id,
            model_artifact_id=pinned.bundle.model_artifact_id,
            control_plane_id=(
                None if control_plane is None else control_plane.control_plane_id
            ),
            checkpoint_id=checkpoint.checkpoint_id,
            checkpoint_as_of_ms=checkpoint.as_of_ms,
            finalization_id=finalization.finalization_id,
            terminal_verdict=finalization.verdict,
            validation_start_ms=pinned.runtime.spec.validation_start_ms,
            validation_end_ms=pinned.runtime.spec.validation_end_ms,
            finalization_not_before_ms=(
                pinned.runtime.spec.finalization_not_before_ms
            ),
            reasons=(),
        )

    reasons: list[str] = []
    if not enabled:
        reasons.append("campaign_not_enabled")
    if checkpoint is None:
        reasons.append("bootstrap_checkpoint_missing")
    if control_plane is None:
        reasons.append("control_plane_attestation_missing")
    if as_of_ms >= pinned.runtime.spec.validation_start_ms:
        if checkpoint is None:
            reasons.append("post_cutover_checkpoint_missing")
        if control_plane is None:
            reasons.append("post_cutover_control_plane_missing")

    reason_codes = tuple(sorted(set(reasons)))
    if reason_codes:
        bootstrap_only = (
            as_of_ms < pinned.runtime.spec.validation_start_ms
            and set(reason_codes)
            <= {
                "campaign_not_enabled",
                "bootstrap_checkpoint_missing",
                "control_plane_attestation_missing",
            }
        )
        status = (
            STATUS_BOOTSTRAP_REQUIRED if bootstrap_only else STATUS_BLOCKED
        )
    elif as_of_ms < pinned.runtime.spec.validation_start_ms:
        status = STATUS_READY_FOR_CUTOVER
    elif as_of_ms < pinned.runtime.spec.validation_end_ms:
        status = STATUS_ACTIVE
    elif as_of_ms < pinned.runtime.spec.finalization_not_before_ms:
        status = STATUS_POST_VALIDATION_SETTLEMENT
    else:
        status = STATUS_TERMINAL_SETTLEMENT

    activation_ready = status in {
        STATUS_READY_FOR_CUTOVER,
        STATUS_ACTIVE,
        STATUS_POST_VALIDATION_SETTLEMENT,
        STATUS_TERMINAL_SETTLEMENT,
    }
    return ArchiveCleanActivationReadiness(
        status=status,
        enabled=enabled,
        activation_ready=activation_ready,
        operationally_valid=activation_ready,
        as_of_ms=as_of_ms,
        runtime_id=pinned.bundle.runtime_id,
        pin_id=pinned.pin.pin_id,
        campaign_id=initial.campaign_id,
        candidate_id=pinned.bundle.candidate_id,
        validation_spec_id=pinned.bundle.validation_spec_id,
        model_artifact_id=pinned.bundle.model_artifact_id,
        control_plane_id=(
            None if control_plane is None else control_plane.control_plane_id
        ),
        checkpoint_id=None if checkpoint is None else checkpoint.checkpoint_id,
        checkpoint_as_of_ms=(
            None if checkpoint is None else checkpoint.as_of_ms
        ),
        finalization_id=None,
        terminal_verdict=None,
        validation_start_ms=pinned.runtime.spec.validation_start_ms,
        validation_end_ms=pinned.runtime.spec.validation_end_ms,
        finalization_not_before_ms=pinned.runtime.spec.finalization_not_before_ms,
        reasons=reason_codes,
    )
