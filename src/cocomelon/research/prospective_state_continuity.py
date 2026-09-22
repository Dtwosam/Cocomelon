from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from cocomelon.research.historical_discovery_freeze import (
    HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
    HistoricalDiscoveryFreezeSpec,
)
from cocomelon.research.prospective_context_evidence import ProspectiveEvidenceStore


class ProspectiveStateContinuityError(RuntimeError):
    pass


class ProspectiveStateContinuityStatus(StrEnum):
    PRE_CUTOVER_BOOTSTRAP = "pre_cutover_bootstrap"
    RESTORED = "restored"


@dataclass(frozen=True, slots=True)
class ProspectiveStateContinuity:
    status: ProspectiveStateContinuityStatus
    as_of_ms: int
    restored_artifact_id: str | None
    campaign_id: str | None
    prior_state_digest: str | None
    validation_not_before_ms: int

    def __post_init__(self) -> None:
        if self.as_of_ms < 0:
            raise ValueError("as_of_ms must be non-negative")
        if self.validation_not_before_ms < 0:
            raise ValueError("validation_not_before_ms must be non-negative")
        if self.status is ProspectiveStateContinuityStatus.RESTORED:
            if self.restored_artifact_id is None:
                raise ValueError("restored continuity requires an artifact id")
            if self.campaign_id is None or self.prior_state_digest is None:
                raise ValueError("restored continuity requires campaign state")
        if self.status is ProspectiveStateContinuityStatus.PRE_CUTOVER_BOOTSTRAP:
            if self.as_of_ms >= self.validation_not_before_ms:
                raise ValueError("bootstrap continuity is pre-cutover only")

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "as_of_ms": self.as_of_ms,
            "restored_artifact_id": self.restored_artifact_id,
            "campaign_id": self.campaign_id,
            "prior_state_digest": self.prior_state_digest,
            "validation_not_before_ms": self.validation_not_before_ms,
        }


def _normalize_artifact_id(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped or stripped.lower() == "none":
        return None
    if not stripped.isdigit():
        raise ProspectiveStateContinuityError(
            "restored prospective artifact id must be numeric"
        )
    return stripped


def verify_prospective_state_continuity(
    root: str | Path,
    *,
    restored_artifact_id: str | None,
    as_of_ms: int,
    spec: HistoricalDiscoveryFreezeSpec = (
        HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1
    ),
) -> ProspectiveStateContinuity:
    if as_of_ms < 0:
        raise ValueError("as_of_ms must be non-negative")

    resolved_root = Path(root)
    artifact_id = _normalize_artifact_id(restored_artifact_id)
    manifest_path = resolved_root / "manifest.json"

    if artifact_id is None:
        if as_of_ms >= spec.validation_not_before_ms:
            raise ProspectiveStateContinuityError(
                "POST_CUTOVER_PROSPECTIVE_STATE_RESTORE_REQUIRED"
            )
        if manifest_path.exists():
            raise ProspectiveStateContinuityError(
                "unattributed prospective state exists without restored artifact"
            )
        return ProspectiveStateContinuity(
            status=ProspectiveStateContinuityStatus.PRE_CUTOVER_BOOTSTRAP,
            as_of_ms=as_of_ms,
            restored_artifact_id=None,
            campaign_id=None,
            prior_state_digest=None,
            validation_not_before_ms=spec.validation_not_before_ms,
        )

    if not manifest_path.is_file():
        raise ProspectiveStateContinuityError(
            "RESTORED_PROSPECTIVE_MANIFEST_MISSING"
        )

    store = ProspectiveEvidenceStore(resolved_root, spec=spec)
    observations = store.iter_observations()
    if any(
        observation.anchor_end_ms < spec.validation_not_before_ms
        for observation in observations
    ):
        raise ProspectiveStateContinuityError(
            "restored prospective state contains pre-cutover observation"
        )

    return ProspectiveStateContinuity(
        status=ProspectiveStateContinuityStatus.RESTORED,
        as_of_ms=as_of_ms,
        restored_artifact_id=artifact_id,
        campaign_id=store.manifest.campaign_id,
        prior_state_digest=store.state_digest,
        validation_not_before_ms=spec.validation_not_before_ms,
    )
