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

READINESS_FAILURE_KIND = "prospective-hype-readiness-audit-failure"
READINESS_FAILURE_SCHEMA_VERSION = 1
_ALLOWED_STAGES = {"build", "upload"}
_REASON_CODE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ProspectiveReadinessFailureError(RuntimeError):
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
        raise ProspectiveReadinessFailureError(code)
    return value


def _optional_sha256(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ProspectiveReadinessFailureError(f"{field}_INVALID")
    return value


@dataclass(frozen=True, slots=True)
class ProspectiveReadinessFailure:
    audited_at_ms: int
    stage: str
    reason_code: str
    observer_workflow_sha256: str | None = None
    campaign_id: str = EXPECTED_CAMPAIGN_ID
    candidate_spec_id: str = EXPECTED_CANDIDATE_SPEC_ID
    validation_plan_id: str = EXPECTED_VALIDATION_PLAN_ID
    observer_source_revision: str = FROZEN_OBSERVER_SOURCE_REVISION
    kind: str = READINESS_FAILURE_KIND
    interim_economics_redacted: bool = True
    schema_version: int = READINESS_FAILURE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.audited_at_ms < 0:
            raise ValueError("audited_at_ms must be non-negative")
        if self.stage not in _ALLOWED_STAGES:
            raise ValueError("unsupported readiness failure stage")
        if (
            len(self.reason_code) > 96
            or _REASON_CODE.fullmatch(self.reason_code) is None
        ):
            raise ValueError("reason_code must be a bounded uppercase identifier")
        if (
            self.observer_workflow_sha256 is not None
            and _SHA256.fullmatch(self.observer_workflow_sha256) is None
        ):
            raise ValueError("observer_workflow_sha256 must be SHA-256 when present")
        if self.campaign_id != EXPECTED_CAMPAIGN_ID:
            raise ValueError("readiness failure campaign mismatch")
        if self.candidate_spec_id != EXPECTED_CANDIDATE_SPEC_ID:
            raise ValueError("readiness failure candidate mismatch")
        if self.validation_plan_id != EXPECTED_VALIDATION_PLAN_ID:
            raise ValueError("readiness failure validation plan mismatch")
        if self.observer_source_revision != FROZEN_OBSERVER_SOURCE_REVISION:
            raise ValueError("readiness failure observer revision mismatch")
        if self.kind != READINESS_FAILURE_KIND:
            raise ValueError("unsupported readiness failure kind")
        if self.interim_economics_redacted is not True:
            raise ValueError("readiness failure must keep economics redacted")
        if self.schema_version != READINESS_FAILURE_SCHEMA_VERSION:
            raise ValueError("unsupported readiness failure schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "audited_at_ms": self.audited_at_ms,
            "stage": self.stage,
            "reason_code": self.reason_code,
            "observer_workflow_sha256": self.observer_workflow_sha256,
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


def build_prospective_readiness_failure(
    *,
    audited_at_ms: int,
    stage: str,
    reason_code: str,
    observer_workflow_sha256: str | None = None,
) -> ProspectiveReadinessFailure:
    return ProspectiveReadinessFailure(
        audited_at_ms=audited_at_ms,
        stage=stage,
        reason_code=reason_code,
        observer_workflow_sha256=observer_workflow_sha256,
    )


def verify_prospective_readiness_failure(
    path: str | Path,
) -> ProspectiveReadinessFailure:
    resolved = Path(path)
    if not resolved.is_file():
        raise ProspectiveReadinessFailureError("READINESS_FAILURE_RECEIPT_MISSING")
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProspectiveReadinessFailureError(
            "READINESS_FAILURE_RECEIPT_INVALID"
        ) from exc
    if not isinstance(raw, dict):
        raise ProspectiveReadinessFailureError("READINESS_FAILURE_RECEIPT_INVALID")
    payload = cast(dict[str, object], raw)
    expected_keys = {
        "audited_at_ms",
        "stage",
        "reason_code",
        "observer_workflow_sha256",
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
        raise ProspectiveReadinessFailureError("READINESS_FAILURE_FIELDS_INVALID")

    audited_at_ms = payload["audited_at_ms"]
    stage = _string(payload["stage"], "READINESS_FAILURE_STAGE_INVALID")
    reason_code = _string(
        payload["reason_code"],
        "READINESS_FAILURE_REASON_INVALID",
    )
    campaign_id = _string(
        payload["campaign_id"],
        "READINESS_FAILURE_CAMPAIGN_INVALID",
    )
    candidate_spec_id = _string(
        payload["candidate_spec_id"],
        "READINESS_FAILURE_CANDIDATE_INVALID",
    )
    validation_plan_id = _string(
        payload["validation_plan_id"],
        "READINESS_FAILURE_PLAN_INVALID",
    )
    observer_source_revision = _string(
        payload["observer_source_revision"],
        "READINESS_FAILURE_REVISION_INVALID",
    )
    kind = _string(payload["kind"], "READINESS_FAILURE_KIND_INVALID")
    redacted = payload["interim_economics_redacted"]
    schema_version = payload["schema_version"]
    failure_id = payload["failure_id"]

    if isinstance(audited_at_ms, bool) or not isinstance(audited_at_ms, int):
        raise ProspectiveReadinessFailureError("READINESS_FAILURE_TIME_INVALID")
    if not isinstance(redacted, bool):
        raise ProspectiveReadinessFailureError("READINESS_FAILURE_REDACTION_INVALID")
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        raise ProspectiveReadinessFailureError("READINESS_FAILURE_SCHEMA_INVALID")
    if not isinstance(failure_id, str) or len(failure_id) != 64:
        raise ProspectiveReadinessFailureError("READINESS_FAILURE_ID_INVALID")

    try:
        receipt = ProspectiveReadinessFailure(
            audited_at_ms=audited_at_ms,
            stage=stage,
            reason_code=reason_code,
            observer_workflow_sha256=_optional_sha256(
                payload["observer_workflow_sha256"],
                "OBSERVER_WORKFLOW_SHA256",
            ),
            campaign_id=campaign_id,
            candidate_spec_id=candidate_spec_id,
            validation_plan_id=validation_plan_id,
            observer_source_revision=observer_source_revision,
            kind=kind,
            interim_economics_redacted=redacted,
            schema_version=schema_version,
        )
    except ValueError as exc:
        raise ProspectiveReadinessFailureError(
            "READINESS_FAILURE_RECEIPT_INVALID"
        ) from exc
    if receipt.failure_id != failure_id:
        raise ProspectiveReadinessFailureError("READINESS_FAILURE_ID_MISMATCH")
    return receipt
