from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum

from cocomelon.research.prospective_context_report import (
    HYPE_PROSPECTIVE_VALIDATION_V1,
)

HOUR_MS = 3_600_000
MAX_OBSERVER_ARTIFACT_AGE_MS = 90 * 60 * 1_000
LIVENESS_SCHEMA_VERSION = 1


class ProspectiveLivenessError(RuntimeError):
    pass


class ProspectiveLivenessStatus(StrEnum):
    HEALTHY_PRE_CUTOVER = "healthy_pre_cutover"
    STALE_PRE_CUTOVER = "stale_pre_cutover"
    HEALTHY_ACTIVE = "healthy_active"
    STALE_ACTIVE = "stale_active"
    POST_CAMPAIGN = "post_campaign"


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


@dataclass(frozen=True, slots=True)
class ProspectiveObserverLiveness:
    artifact_id: str
    artifact_created_at_ms: int
    audited_at_ms: int
    artifact_age_ms: int
    status: ProspectiveLivenessStatus
    alert_required: bool
    validation_plan_id: str
    validation_start_ms: int
    validation_end_ms: int
    finalization_not_before_ms: int
    max_artifact_age_ms: int = MAX_OBSERVER_ARTIFACT_AGE_MS
    schema_version: int = LIVENESS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.artifact_id.isdigit():
            raise ValueError("artifact_id must be numeric")
        if self.artifact_created_at_ms < 0 or self.audited_at_ms < 0:
            raise ValueError("timestamps must be non-negative")
        if self.artifact_age_ms < 0:
            raise ValueError("artifact_age_ms must be non-negative")
        if self.max_artifact_age_ms <= 0:
            raise ValueError("max_artifact_age_ms must be positive")
        if len(self.validation_plan_id) != 64:
            raise ValueError("validation_plan_id must be SHA-256")
        expected_alert = self.status in {
            ProspectiveLivenessStatus.STALE_PRE_CUTOVER,
            ProspectiveLivenessStatus.STALE_ACTIVE,
        }
        if self.alert_required != expected_alert:
            raise ValueError("alert_required must match liveness status")
        if self.schema_version != LIVENESS_SCHEMA_VERSION:
            raise ValueError("unsupported liveness schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "artifact_id": self.artifact_id,
            "artifact_created_at_ms": self.artifact_created_at_ms,
            "audited_at_ms": self.audited_at_ms,
            "artifact_age_ms": self.artifact_age_ms,
            "status": self.status.value,
            "alert_required": self.alert_required,
            "validation_plan_id": self.validation_plan_id,
            "validation_start_ms": self.validation_start_ms,
            "validation_end_ms": self.validation_end_ms,
            "finalization_not_before_ms": self.finalization_not_before_ms,
            "max_artifact_age_ms": self.max_artifact_age_ms,
            "schema_version": self.schema_version,
        }

    @property
    def liveness_id(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "liveness_id": self.liveness_id}


def evaluate_prospective_observer_liveness(
    *,
    artifact_id: str,
    artifact_created_at_ms: int,
    audited_at_ms: int,
    max_artifact_age_ms: int = MAX_OBSERVER_ARTIFACT_AGE_MS,
) -> ProspectiveObserverLiveness:
    if not artifact_id.isdigit():
        raise ValueError("artifact_id must be numeric")
    if artifact_created_at_ms < 0 or audited_at_ms < 0:
        raise ValueError("timestamps must be non-negative")
    if artifact_created_at_ms > audited_at_ms:
        raise ProspectiveLivenessError("OBSERVER_ARTIFACT_FROM_FUTURE")
    if max_artifact_age_ms <= 0:
        raise ValueError("max_artifact_age_ms must be positive")

    plan = HYPE_PROSPECTIVE_VALIDATION_V1
    age_ms = audited_at_ms - artifact_created_at_ms
    stale = age_ms > max_artifact_age_ms

    if audited_at_ms < plan.validation_start_ms:
        status = (
            ProspectiveLivenessStatus.STALE_PRE_CUTOVER
            if stale
            else ProspectiveLivenessStatus.HEALTHY_PRE_CUTOVER
        )
    elif audited_at_ms <= plan.finalization_not_before_ms + max_artifact_age_ms:
        status = (
            ProspectiveLivenessStatus.STALE_ACTIVE
            if stale
            else ProspectiveLivenessStatus.HEALTHY_ACTIVE
        )
    else:
        status = ProspectiveLivenessStatus.POST_CAMPAIGN

    return ProspectiveObserverLiveness(
        artifact_id=artifact_id,
        artifact_created_at_ms=artifact_created_at_ms,
        audited_at_ms=audited_at_ms,
        artifact_age_ms=age_ms,
        status=status,
        alert_required=status in {
            ProspectiveLivenessStatus.STALE_PRE_CUTOVER,
            ProspectiveLivenessStatus.STALE_ACTIVE,
        },
        validation_plan_id=plan.plan_id,
        validation_start_ms=plan.validation_start_ms,
        validation_end_ms=plan.validation_end_ms,
        finalization_not_before_ms=plan.finalization_not_before_ms,
        max_artifact_age_ms=max_artifact_age_ms,
    )
