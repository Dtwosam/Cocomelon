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
from cocomelon.research.prospective_context_evidence import ProspectiveCampaignManifest
from cocomelon.research.prospective_context_report import HYPE_PROSPECTIVE_VALIDATION_V1

CUTOVER_FAILURE_KIND = "prospective-hype-cutover-failure"
CUTOVER_FAILURE_SCHEMA_VERSION = 1
_ALLOWED_STAGES = {
    "discovery",
    "existing_receipt",
    "monitor",
    "readiness",
    "state",
    "build",
    "upload",
}
_REASON_CODE = re.compile(r"^[A-Z][A-Z0-9_]*$")


class ProspectiveCutoverFailureError(RuntimeError):
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
EXPECTED_VALIDATION_PLAN_ID = HYPE_PROSPECTIVE_VALIDATION_V1.plan_id


def _optional_artifact_id(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.isdigit():
        raise ProspectiveCutoverFailureError(f"{field}_INVALID")
    return value


@dataclass(frozen=True, slots=True)
class ProspectiveCutoverFailure:
    audited_at_ms: int
    stage: str
    reason_code: str
    monitor_artifact_id: str | None = None
    state_artifact_id: str | None = None
    receipt_artifact_id: str | None = None
    campaign_id: str = EXPECTED_CAMPAIGN_ID
    validation_plan_id: str = EXPECTED_VALIDATION_PLAN_ID
    kind: str = CUTOVER_FAILURE_KIND
    interim_economics_redacted: bool = True
    schema_version: int = CUTOVER_FAILURE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.audited_at_ms < 0:
            raise ValueError("audited_at_ms must be non-negative")
        if self.stage not in _ALLOWED_STAGES:
            raise ValueError("unsupported cutover failure stage")
        if (
            len(self.reason_code) > 96
            or _REASON_CODE.fullmatch(self.reason_code) is None
        ):
            raise ValueError("reason_code must be a bounded uppercase identifier")
        for field in (
            "monitor_artifact_id",
            "state_artifact_id",
            "receipt_artifact_id",
        ):
            value = cast(str | None, getattr(self, field))
            if value is not None and not value.isdigit():
                raise ValueError(f"{field} must be numeric when present")
        if self.campaign_id != EXPECTED_CAMPAIGN_ID:
            raise ValueError("cutover failure campaign mismatch")
        if self.validation_plan_id != EXPECTED_VALIDATION_PLAN_ID:
            raise ValueError("cutover failure validation plan mismatch")
        if self.kind != CUTOVER_FAILURE_KIND:
            raise ValueError("unsupported cutover failure kind")
        if self.interim_economics_redacted is not True:
            raise ValueError("cutover failure must keep economics redacted")
        if self.schema_version != CUTOVER_FAILURE_SCHEMA_VERSION:
            raise ValueError("unsupported cutover failure schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "audited_at_ms": self.audited_at_ms,
            "stage": self.stage,
            "reason_code": self.reason_code,
            "monitor_artifact_id": self.monitor_artifact_id,
            "state_artifact_id": self.state_artifact_id,
            "receipt_artifact_id": self.receipt_artifact_id,
            "campaign_id": self.campaign_id,
            "validation_plan_id": self.validation_plan_id,
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


def build_prospective_cutover_failure(
    *,
    audited_at_ms: int,
    stage: str,
    reason_code: str,
    monitor_artifact_id: str | None = None,
    state_artifact_id: str | None = None,
    receipt_artifact_id: str | None = None,
) -> ProspectiveCutoverFailure:
    return ProspectiveCutoverFailure(
        audited_at_ms=audited_at_ms,
        stage=stage,
        reason_code=reason_code,
        monitor_artifact_id=monitor_artifact_id,
        state_artifact_id=state_artifact_id,
        receipt_artifact_id=receipt_artifact_id,
    )


def verify_prospective_cutover_failure(
    path: str | Path,
) -> ProspectiveCutoverFailure:
    resolved = Path(path)
    if not resolved.is_file():
        raise ProspectiveCutoverFailureError("CUTOVER_FAILURE_RECEIPT_MISSING")
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProspectiveCutoverFailureError("CUTOVER_FAILURE_RECEIPT_INVALID") from exc
    if not isinstance(raw, dict):
        raise ProspectiveCutoverFailureError("CUTOVER_FAILURE_RECEIPT_INVALID")
    payload = cast(dict[str, object], raw)
    expected_keys = {
        "audited_at_ms",
        "stage",
        "reason_code",
        "monitor_artifact_id",
        "state_artifact_id",
        "receipt_artifact_id",
        "campaign_id",
        "validation_plan_id",
        "kind",
        "interim_economics_redacted",
        "schema_version",
        "failure_id",
    }
    if set(payload) != expected_keys:
        raise ProspectiveCutoverFailureError("CUTOVER_FAILURE_FIELDS_INVALID")

    audited_at_ms = payload["audited_at_ms"]
    stage = payload["stage"]
    reason_code = payload["reason_code"]
    campaign_id = payload["campaign_id"]
    validation_plan_id = payload["validation_plan_id"]
    kind = payload["kind"]
    redacted = payload["interim_economics_redacted"]
    schema_version = payload["schema_version"]
    failure_id = payload["failure_id"]

    if isinstance(audited_at_ms, bool) or not isinstance(audited_at_ms, int):
        raise ProspectiveCutoverFailureError("CUTOVER_FAILURE_TIME_INVALID")
    if not isinstance(stage, str):
        raise ProspectiveCutoverFailureError("CUTOVER_FAILURE_STAGE_INVALID")
    if not isinstance(reason_code, str):
        raise ProspectiveCutoverFailureError("CUTOVER_FAILURE_REASON_INVALID")
    if not isinstance(campaign_id, str):
        raise ProspectiveCutoverFailureError("CUTOVER_FAILURE_CAMPAIGN_INVALID")
    if not isinstance(validation_plan_id, str):
        raise ProspectiveCutoverFailureError("CUTOVER_FAILURE_PLAN_INVALID")
    if not isinstance(kind, str):
        raise ProspectiveCutoverFailureError("CUTOVER_FAILURE_KIND_INVALID")
    if not isinstance(redacted, bool):
        raise ProspectiveCutoverFailureError("CUTOVER_FAILURE_REDACTION_INVALID")
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        raise ProspectiveCutoverFailureError("CUTOVER_FAILURE_SCHEMA_INVALID")
    if not isinstance(failure_id, str) or len(failure_id) != 64:
        raise ProspectiveCutoverFailureError("CUTOVER_FAILURE_ID_INVALID")

    try:
        receipt = ProspectiveCutoverFailure(
            audited_at_ms=audited_at_ms,
            stage=stage,
            reason_code=reason_code,
            monitor_artifact_id=_optional_artifact_id(
                payload["monitor_artifact_id"],
                "MONITOR_ARTIFACT_ID",
            ),
            state_artifact_id=_optional_artifact_id(
                payload["state_artifact_id"],
                "STATE_ARTIFACT_ID",
            ),
            receipt_artifact_id=_optional_artifact_id(
                payload["receipt_artifact_id"],
                "RECEIPT_ARTIFACT_ID",
            ),
            campaign_id=campaign_id,
            validation_plan_id=validation_plan_id,
            kind=kind,
            interim_economics_redacted=redacted,
            schema_version=schema_version,
        )
    except ValueError as exc:
        raise ProspectiveCutoverFailureError(
            "CUTOVER_FAILURE_RECEIPT_INVALID"
        ) from exc
    if receipt.failure_id != failure_id:
        raise ProspectiveCutoverFailureError("CUTOVER_FAILURE_ID_MISMATCH")
    return receipt
