from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from cocomelon.domain.strategy import Direction
from cocomelon.research.historical_discovery_freeze import (
    HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
)
from cocomelon.research.prospective_context_evidence import (
    ProspectiveEvidenceStore,
    ProspectiveObservation,
    ProspectiveOutcome,
)
from cocomelon.research.prospective_state_readiness import (
    ProspectiveStateReadiness,
    verify_prospective_hype_state_readiness,
)

LINEAGE_SCHEMA_VERSION = 1


class ProspectiveArtifactLineageError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _artifact_id(value: str, field: str) -> str:
    stripped = value.strip()
    if not stripped.isdigit():
        raise ProspectiveArtifactLineageError(f"{field}_INVALID")
    return stripped


def _unique_observations(
    values: tuple[ProspectiveObservation, ...],
    *,
    snapshot: str,
) -> dict[str, ProspectiveObservation]:
    by_id: dict[str, ProspectiveObservation] = {}
    by_anchor: dict[int, str] = {}
    for value in values:
        if value.observation_id in by_id:
            raise ProspectiveArtifactLineageError(
                f"{snapshot}_DUPLICATE_OBSERVATION_ID"
            )
        existing = by_anchor.get(value.anchor_end_ms)
        if existing is not None:
            raise ProspectiveArtifactLineageError(
                f"{snapshot}_DUPLICATE_OBSERVATION_ANCHOR"
            )
        by_id[value.observation_id] = value
        by_anchor[value.anchor_end_ms] = value.observation_id
    return by_id


def _unique_outcomes(
    values: tuple[ProspectiveOutcome, ...],
    *,
    snapshot: str,
) -> dict[str, ProspectiveOutcome]:
    by_id: dict[str, ProspectiveOutcome] = {}
    by_observation: dict[str, str] = {}
    for value in values:
        if value.outcome_id in by_id:
            raise ProspectiveArtifactLineageError(
                f"{snapshot}_DUPLICATE_OUTCOME_ID"
            )
        existing = by_observation.get(value.observation_id)
        if existing is not None:
            raise ProspectiveArtifactLineageError(
                f"{snapshot}_MULTIPLE_OUTCOMES_FOR_OBSERVATION"
            )
        by_id[value.outcome_id] = value
        by_observation[value.observation_id] = value.outcome_id
    return by_id


def _verify_outcome_links(
    observations: dict[str, ProspectiveObservation],
    outcomes: dict[str, ProspectiveOutcome],
    *,
    snapshot: str,
) -> None:
    for outcome in outcomes.values():
        observation = observations.get(outcome.observation_id)
        if observation is None:
            raise ProspectiveArtifactLineageError(
                f"{snapshot}_ORPHAN_OUTCOME"
            )
        if observation.effective_direction not in {Direction.LONG, Direction.SHORT}:
            raise ProspectiveArtifactLineageError(
                f"{snapshot}_OUTCOME_FOR_NON_DIRECTIONAL_OBSERVATION"
            )
        if (
            outcome.candidate_spec_id != observation.candidate_spec_id
            or outcome.market != observation.market
            or outcome.anchor_end_ms != observation.anchor_end_ms
            or outcome.target_end_ms != observation.target_end_ms
            or outcome.direction != observation.effective_direction
            or outcome.entry_px != observation.entry_px
            or outcome.modeled_cost_fraction != observation.modeled_cost_fraction
        ):
            raise ProspectiveArtifactLineageError(
                f"{snapshot}_OUTCOME_OBSERVATION_LINK_MISMATCH"
            )


def _verify_preserved_records[T](
    previous: dict[str, T],
    current: dict[str, T],
    *,
    kind: str,
) -> None:
    for record_id, prior in previous.items():
        latest = current.get(record_id)
        if latest is None:
            raise ProspectiveArtifactLineageError(
                f"CURRENT_{kind}_REMOVED"
            )
        if latest != prior:
            raise ProspectiveArtifactLineageError(
                f"CURRENT_{kind}_MUTATED"
            )


@dataclass(frozen=True, slots=True)
class ProspectiveArtifactLineageReceipt:
    previous_artifact_id: str
    current_artifact_id: str
    previous_audited_at_ms: int
    current_audited_at_ms: int
    lineage_status: str
    campaign_id: str
    runtime_attestation_id: str
    control_plane_id: str
    previous_state_digest: str
    current_state_digest: str
    previous_observation_count: int
    current_observation_count: int
    previous_outcome_count: int
    current_outcome_count: int
    appended_observation_ids: tuple[str, ...]
    appended_outcome_ids: tuple[str, ...]
    schema_version: int = LINEAGE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.previous_artifact_id.isdigit():
            raise ValueError("previous_artifact_id must be numeric")
        if not self.current_artifact_id.isdigit():
            raise ValueError("current_artifact_id must be numeric")
        if self.previous_artifact_id == self.current_artifact_id:
            raise ValueError("artifact ids must differ")
        if self.previous_audited_at_ms < 0 or self.current_audited_at_ms < 0:
            raise ValueError("audit times must be non-negative")
        if self.current_audited_at_ms < self.previous_audited_at_ms:
            raise ValueError("current audit must not predate previous audit")
        if self.lineage_status != "append_only_valid":
            raise ValueError("unsupported lineage_status")
        for field in (
            "campaign_id",
            "runtime_attestation_id",
            "control_plane_id",
            "previous_state_digest",
            "current_state_digest",
        ):
            value = getattr(self, field)
            if len(value) != 64:
                raise ValueError(f"{field} must be SHA-256")
        for field in (
            "previous_observation_count",
            "current_observation_count",
            "previous_outcome_count",
            "current_outcome_count",
        ):
            if getattr(self, field) < 0:
                raise ValueError(f"{field} must be non-negative")
        if self.current_observation_count < self.previous_observation_count:
            raise ValueError("observation count must be monotonic")
        if self.current_outcome_count < self.previous_outcome_count:
            raise ValueError("outcome count must be monotonic")
        if self.schema_version != LINEAGE_SCHEMA_VERSION:
            raise ValueError("unsupported lineage schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "previous_artifact_id": self.previous_artifact_id,
            "current_artifact_id": self.current_artifact_id,
            "previous_audited_at_ms": self.previous_audited_at_ms,
            "current_audited_at_ms": self.current_audited_at_ms,
            "lineage_status": self.lineage_status,
            "campaign_id": self.campaign_id,
            "runtime_attestation_id": self.runtime_attestation_id,
            "control_plane_id": self.control_plane_id,
            "previous_state_digest": self.previous_state_digest,
            "current_state_digest": self.current_state_digest,
            "previous_observation_count": self.previous_observation_count,
            "current_observation_count": self.current_observation_count,
            "previous_outcome_count": self.previous_outcome_count,
            "current_outcome_count": self.current_outcome_count,
            "appended_observation_ids": self.appended_observation_ids,
            "appended_outcome_ids": self.appended_outcome_ids,
            "schema_version": self.schema_version,
        }

    @property
    def receipt_id(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "receipt_id": self.receipt_id}


def _verify_fixed_identity(
    previous: ProspectiveStateReadiness,
    current: ProspectiveStateReadiness,
) -> None:
    if previous.campaign_id != current.campaign_id:
        raise ProspectiveArtifactLineageError("CAMPAIGN_ID_DRIFT")
    if previous.runtime_attestation_id != current.runtime_attestation_id:
        raise ProspectiveArtifactLineageError("RUNTIME_ATTESTATION_DRIFT")
    if previous.control_plane_id != current.control_plane_id:
        raise ProspectiveArtifactLineageError("CONTROL_PLANE_DRIFT")


def verify_prospective_hype_artifact_lineage(
    previous_root: str | Path,
    current_root: str | Path,
    *,
    previous_artifact_id: str,
    current_artifact_id: str,
    previous_audited_at_ms: int,
    current_audited_at_ms: int,
) -> ProspectiveArtifactLineageReceipt:
    previous_id = _artifact_id(previous_artifact_id, "PREVIOUS_ARTIFACT_ID")
    current_id = _artifact_id(current_artifact_id, "CURRENT_ARTIFACT_ID")
    if previous_id == current_id:
        raise ProspectiveArtifactLineageError("ARTIFACT_IDS_MUST_DIFFER")
    if previous_audited_at_ms < 0 or current_audited_at_ms < 0:
        raise ValueError("audit times must be non-negative")
    if current_audited_at_ms < previous_audited_at_ms:
        raise ProspectiveArtifactLineageError("AUDIT_TIME_REGRESSION")

    previous_readiness = verify_prospective_hype_state_readiness(
        previous_root,
        artifact_id=previous_id,
        audited_at_ms=previous_audited_at_ms,
    )
    current_readiness = verify_prospective_hype_state_readiness(
        current_root,
        artifact_id=current_id,
        audited_at_ms=current_audited_at_ms,
    )
    _verify_fixed_identity(previous_readiness, current_readiness)

    spec = HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1
    previous_store = ProspectiveEvidenceStore(previous_root, spec=spec)
    current_store = ProspectiveEvidenceStore(current_root, spec=spec)

    previous_observations = _unique_observations(
        previous_store.iter_observations(),
        snapshot="PREVIOUS",
    )
    current_observations = _unique_observations(
        current_store.iter_observations(),
        snapshot="CURRENT",
    )
    previous_outcomes = _unique_outcomes(
        previous_store.iter_outcomes(),
        snapshot="PREVIOUS",
    )
    current_outcomes = _unique_outcomes(
        current_store.iter_outcomes(),
        snapshot="CURRENT",
    )

    _verify_outcome_links(
        previous_observations,
        previous_outcomes,
        snapshot="PREVIOUS",
    )
    _verify_outcome_links(
        current_observations,
        current_outcomes,
        snapshot="CURRENT",
    )
    _verify_preserved_records(
        previous_observations,
        current_observations,
        kind="OBSERVATION",
    )
    _verify_preserved_records(
        previous_outcomes,
        current_outcomes,
        kind="OUTCOME",
    )

    appended_observations = tuple(
        item
        for item in current_observations.values()
        if item.observation_id not in previous_observations
    )
    if previous_observations and appended_observations:
        latest_previous_anchor = max(
            item.anchor_end_ms for item in previous_observations.values()
        )
        if any(
            item.anchor_end_ms <= latest_previous_anchor
            for item in appended_observations
        ):
            raise ProspectiveArtifactLineageError(
                "HISTORICAL_OBSERVATION_BACKFILL_FORBIDDEN"
            )

    appended_observation_ids = tuple(
        item.observation_id
        for item in sorted(
            appended_observations,
            key=lambda item: (item.anchor_end_ms, item.observation_id),
        )
    )
    appended_outcome_ids = tuple(
        item.outcome_id
        for item in sorted(
            (
                outcome
                for outcome in current_outcomes.values()
                if outcome.outcome_id not in previous_outcomes
            ),
            key=lambda item: (item.target_end_ms, item.outcome_id),
        )
    )

    if (
        len(current_observations) == len(previous_observations)
        and len(current_outcomes) == len(previous_outcomes)
        and current_readiness.state_digest != previous_readiness.state_digest
    ):
        raise ProspectiveArtifactLineageError("UNCHANGED_RECORD_SET_DIGEST_DRIFT")

    return ProspectiveArtifactLineageReceipt(
        previous_artifact_id=previous_id,
        current_artifact_id=current_id,
        previous_audited_at_ms=previous_audited_at_ms,
        current_audited_at_ms=current_audited_at_ms,
        lineage_status="append_only_valid",
        campaign_id=current_readiness.campaign_id,
        runtime_attestation_id=current_readiness.runtime_attestation_id,
        control_plane_id=current_readiness.control_plane_id,
        previous_state_digest=previous_readiness.state_digest,
        current_state_digest=current_readiness.state_digest,
        previous_observation_count=len(previous_observations),
        current_observation_count=len(current_observations),
        previous_outcome_count=len(previous_outcomes),
        current_outcome_count=len(current_outcomes),
        appended_observation_ids=appended_observation_ids,
        appended_outcome_ids=appended_outcome_ids,
    )
