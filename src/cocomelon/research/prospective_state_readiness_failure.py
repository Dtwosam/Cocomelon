from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from cocomelon.research.historical_discovery_freeze import (
    HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
)
from cocomelon.research.prospective_campaign_readiness import (
    FROZEN_OBSERVER_SOURCE_REVISION,
)
from cocomelon.research.prospective_context_evidence import ProspectiveCampaignManifest
from cocomelon.research.prospective_context_report import HYPE_PROSPECTIVE_VALIDATION_V1

STATE_READINESS_FAILURE_KIND = "prospective-hype-state-readiness-audit-failure"
STATE_READINESS_FAILURE_SCHEMA_VERSION = 1
_ALLOWED_STAGES = {"discovery", "download", "verify", "upload"}
_REASON_CODE = re.compile(r"^[A-Z][A-Z0-9_]*$")


class ProspectiveStateReadinessFailureError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _expected_campaign_id() -> str:
    spec = HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1
    return ProspectiveCampaignManifest(
        candidate_spec_id=spec.spec_id,
        candidate_id=spec.candidate_id,
        validation_not_before_ms=spec.validation_not_before_ms,
    ).campaign_id


EXPECTED_CAMPAIGN_ID = _expected_campaign_id()
EXPECTED_CANDIDATE_SPEC_ID = HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1.spec_id
EXPECTED_VALIDATION_PLAN_ID = HYPE_PROSPECTIVE_VALIDATION_V1.plan_id


def _string(value: object, code: str) -> str:
    if not isinstance(value, str):
        raise ProspectiveStateReadinessFailureError(code)
    return value


def _optional_artifact_id(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.isdigit():
        raise ProspectiveStateReadinessFailureError(
            "STATE_READINESS_FAILURE_ARTIFACT_ID_INVALID"
        )
    return value


@dataclass(frozen=True, slots=True)
class ProspectiveStateReadinessFailure:
    audited_at_ms: int
    stage: str
    reason_code: str
    state_artifact_id: str | None = None
    campaign_id: str = EXPECTED_CAMPAIGN_ID
    candidate_spec_id: str = EXPECTED_CANDIDATE_SPEC_ID
    validation_plan_id: str = EXPECTED_VALIDATION_PLAN_ID
    observer_source_revision: str = FROZEN_OBSERVER_SOURCE_REVISION
    kind: str = STATE_READINESS_FAILURE_KIND
    interim_economics_redacted: bool = True
    schema_version: int = STATE_READINESS_FAILURE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.audited_at_ms < 0:
            raise ValueError("audited_at_ms must be non-negative")
        if self.stage not in _ALLOWED_STAGES:
            raise ValueError("unsupported state-readiness failure stage")
        if (
            len(self.reason_code) > 96
            or _REASON_CODE.fullmatch(self.reason_code) is None
        ):
            raise ValueError("reason_code must be a bounded uppercase identifier")
        if self.state_artifact_id is not None and not self.state_artifact_id.isdigit():
            raise ValueError("state_artifact_id must be numeric when present")
        if self.campaign_id != EXPECTED_CAMPAIGN_ID:
            raise ValueError("state-readiness failure campaign mismatch")
        if self.candidate_spec_id != EXPECTED_CANDIDATE_SPEC_ID:
            raise ValueError("state-readiness failure candidate mismatch")
        if self.validation_plan_id != EXPECTED_VALIDATION_PLAN_ID:
            raise ValueError("state-readiness failure validation plan mismatch")
        if self.observer_source_revision != FROZEN_OBSERVER_SOURCE_REVISION:
            raise ValueError("state-readiness failure observer revision mismatch")
        if self.kind != STATE_READINESS_FAILURE_KIND:
            raise ValueError("unsupported state-readiness failure kind")
        if self.interim_economics_redacted is not True:
            raise ValueError("state-readiness failure must keep economics redacted")
        if self.schema_version != STATE_READINESS_FAILURE_SCHEMA_VERSION:
            raise ValueError("unsupported state-readiness failure schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "audited_at_ms": self.audited_at_ms,
            "stage": self.stage,
            "reason_code": self.reason_code,
            "state_artifact_id": self.state_artifact_id,
            "campaign_id": self.campaign_id,
            "candidate_spec_id": self.candidate_spec_id,
            "validation_plan_id": self.validation_plan_id,
            "observer_source_revision": self.observer_source_revision,
            "kind": self.kind,
            "interim_economics_redacted": self.interim_economics_redacted,
            "schema_version": self.schema_version,
        }

    @property
    def failure_id(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "failure_id": self.failure_id}

    def write(self, path: str | Path) -> None:
        resolved = Path(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        temporary = resolved.with_name(f".{resolved.name}.tmp")
        encoded = _canonical_json(self.to_dict()) + "\n"
        try:
            with temporary.open("x", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, resolved)
        finally:
            if temporary.exists():
                temporary.unlink()


def build_prospective_state_readiness_failure(
    *,
    audited_at_ms: int,
    stage: str,
    reason_code: str,
    state_artifact_id: str | None = None,
) -> ProspectiveStateReadinessFailure:
    return ProspectiveStateReadinessFailure(
        audited_at_ms=audited_at_ms,
        stage=stage,
        reason_code=reason_code,
        state_artifact_id=state_artifact_id,
    )


def verify_prospective_state_readiness_failure(
    path: str | Path,
) -> ProspectiveStateReadinessFailure:
    resolved = Path(path)
    if not resolved.is_file():
        raise ProspectiveStateReadinessFailureError(
            "STATE_READINESS_FAILURE_RECEIPT_MISSING"
        )
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProspectiveStateReadinessFailureError(
            "STATE_READINESS_FAILURE_RECEIPT_INVALID"
        ) from exc
    if not isinstance(raw, dict):
        raise ProspectiveStateReadinessFailureError(
            "STATE_READINESS_FAILURE_RECEIPT_INVALID"
        )
    payload = cast(dict[str, object], raw)
    expected_keys = {
        "audited_at_ms",
        "stage",
        "reason_code",
        "state_artifact_id",
        "campaign_id",
        "candidate_spec_id",
        "validation_plan_id",
        "observer_source_revision",
        "kind",
        "interim_economics_redacted",
        "schema_version",
        "failure_id",
    }
    if set(payload) != expected_keys:
        raise ProspectiveStateReadinessFailureError(
            "STATE_READINESS_FAILURE_FIELDS_INVALID"
        )

    audited_at_ms = payload["audited_at_ms"]
    if isinstance(audited_at_ms, bool) or not isinstance(audited_at_ms, int):
        raise ProspectiveStateReadinessFailureError(
            "STATE_READINESS_FAILURE_TIME_INVALID"
        )
    redacted = payload["interim_economics_redacted"]
    if not isinstance(redacted, bool):
        raise ProspectiveStateReadinessFailureError(
            "STATE_READINESS_FAILURE_REDACTION_INVALID"
        )
    schema_version = payload["schema_version"]
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        raise ProspectiveStateReadinessFailureError(
            "STATE_READINESS_FAILURE_SCHEMA_INVALID"
        )
    failure_id = payload["failure_id"]
    if not isinstance(failure_id, str) or len(failure_id) != 64:
        raise ProspectiveStateReadinessFailureError(
            "STATE_READINESS_FAILURE_ID_INVALID"
        )

    try:
        receipt = ProspectiveStateReadinessFailure(
            audited_at_ms=audited_at_ms,
            stage=_string(
                payload["stage"],
                "STATE_READINESS_FAILURE_STAGE_INVALID",
            ),
            reason_code=_string(
                payload["reason_code"],
                "STATE_READINESS_FAILURE_REASON_INVALID",
            ),
            state_artifact_id=_optional_artifact_id(payload["state_artifact_id"]),
            campaign_id=_string(
                payload["campaign_id"],
                "STATE_READINESS_FAILURE_CAMPAIGN_INVALID",
            ),
            candidate_spec_id=_string(
                payload["candidate_spec_id"],
                "STATE_READINESS_FAILURE_CANDIDATE_INVALID",
            ),
            validation_plan_id=_string(
                payload["validation_plan_id"],
                "STATE_READINESS_FAILURE_PLAN_INVALID",
            ),
            observer_source_revision=_string(
                payload["observer_source_revision"],
                "STATE_READINESS_FAILURE_REVISION_INVALID",
            ),
            kind=_string(
                payload["kind"],
                "STATE_READINESS_FAILURE_KIND_INVALID",
            ),
            interim_economics_redacted=redacted,
            schema_version=schema_version,
        )
    except ValueError as exc:
        raise ProspectiveStateReadinessFailureError(
            "STATE_READINESS_FAILURE_RECEIPT_INVALID"
        ) from exc

    if receipt.failure_id != failure_id:
        raise ProspectiveStateReadinessFailureError(
            "STATE_READINESS_FAILURE_ID_MISMATCH"
        )
    return receipt
