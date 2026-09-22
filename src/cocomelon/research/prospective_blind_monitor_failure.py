from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import cast

FAILURE_RECEIPT_KIND = "prospective-hype-blind-monitor-failure"
FAILURE_RECEIPT_SCHEMA_VERSION = 1
_ALLOWED_STAGES = {"discovery", "download", "build"}
_REASON_CODE = re.compile(r"^[A-Z][A-Z0-9_]*$")


class ProspectiveBlindMonitorFailureError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _optional_artifact_id(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.isdigit():
        raise ProspectiveBlindMonitorFailureError(f"{field}_INVALID")
    return value


@dataclass(frozen=True, slots=True)
class ProspectiveBlindMonitorFailure:
    audited_at_ms: int
    stage: str
    reason_code: str
    health_artifact_id: str | None = None
    lineage_artifact_id: str | None = None
    state_artifact_id: str | None = None
    kind: str = FAILURE_RECEIPT_KIND
    interim_economics_redacted: bool = True
    schema_version: int = FAILURE_RECEIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.audited_at_ms < 0:
            raise ValueError("audited_at_ms must be non-negative")
        if self.stage not in _ALLOWED_STAGES:
            raise ValueError("unsupported failure stage")
        if (
            len(self.reason_code) > 96
            or _REASON_CODE.fullmatch(self.reason_code) is None
        ):
            raise ValueError("reason_code must be a bounded uppercase identifier")
        for field in (
            "health_artifact_id",
            "lineage_artifact_id",
            "state_artifact_id",
        ):
            value = cast(str | None, getattr(self, field))
            if value is not None and not value.isdigit():
                raise ValueError(f"{field} must be numeric when present")
        if self.kind != FAILURE_RECEIPT_KIND:
            raise ValueError("unsupported failure receipt kind")
        if self.interim_economics_redacted is not True:
            raise ValueError("failure receipt must keep economics redacted")
        if self.schema_version != FAILURE_RECEIPT_SCHEMA_VERSION:
            raise ValueError("unsupported failure receipt schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "audited_at_ms": self.audited_at_ms,
            "stage": self.stage,
            "reason_code": self.reason_code,
            "health_artifact_id": self.health_artifact_id,
            "lineage_artifact_id": self.lineage_artifact_id,
            "state_artifact_id": self.state_artifact_id,
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


def build_prospective_blind_monitor_failure(
    *,
    audited_at_ms: int,
    stage: str,
    reason_code: str,
    health_artifact_id: str | None = None,
    lineage_artifact_id: str | None = None,
    state_artifact_id: str | None = None,
) -> ProspectiveBlindMonitorFailure:
    return ProspectiveBlindMonitorFailure(
        audited_at_ms=audited_at_ms,
        stage=stage,
        reason_code=reason_code,
        health_artifact_id=health_artifact_id,
        lineage_artifact_id=lineage_artifact_id,
        state_artifact_id=state_artifact_id,
    )


def verify_prospective_blind_monitor_failure(
    path: str | Path,
) -> ProspectiveBlindMonitorFailure:
    resolved = Path(path)
    if not resolved.is_file():
        raise ProspectiveBlindMonitorFailureError("FAILURE_RECEIPT_MISSING")
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProspectiveBlindMonitorFailureError("FAILURE_RECEIPT_INVALID") from exc
    if not isinstance(raw, dict):
        raise ProspectiveBlindMonitorFailureError("FAILURE_RECEIPT_INVALID")
    payload = cast(dict[str, object], raw)
    expected_keys = {
        "audited_at_ms",
        "stage",
        "reason_code",
        "health_artifact_id",
        "lineage_artifact_id",
        "state_artifact_id",
        "kind",
        "interim_economics_redacted",
        "schema_version",
        "failure_id",
    }
    if set(payload) != expected_keys:
        raise ProspectiveBlindMonitorFailureError("FAILURE_RECEIPT_FIELDS_INVALID")

    audited_at_ms = payload["audited_at_ms"]
    stage = payload["stage"]
    reason_code = payload["reason_code"]
    kind = payload["kind"]
    redacted = payload["interim_economics_redacted"]
    schema_version = payload["schema_version"]
    failure_id = payload["failure_id"]
    if isinstance(audited_at_ms, bool) or not isinstance(audited_at_ms, int):
        raise ProspectiveBlindMonitorFailureError("AUDITED_AT_MS_INVALID")
    if not isinstance(stage, str):
        raise ProspectiveBlindMonitorFailureError("FAILURE_STAGE_INVALID")
    if not isinstance(reason_code, str):
        raise ProspectiveBlindMonitorFailureError("FAILURE_REASON_INVALID")
    if not isinstance(kind, str):
        raise ProspectiveBlindMonitorFailureError("FAILURE_KIND_INVALID")
    if not isinstance(redacted, bool):
        raise ProspectiveBlindMonitorFailureError("FAILURE_REDACTION_INVALID")
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        raise ProspectiveBlindMonitorFailureError("FAILURE_SCHEMA_INVALID")
    if not isinstance(failure_id, str) or len(failure_id) != 64:
        raise ProspectiveBlindMonitorFailureError("FAILURE_RECEIPT_ID_INVALID")

    try:
        receipt = ProspectiveBlindMonitorFailure(
            audited_at_ms=audited_at_ms,
            stage=stage,
            reason_code=reason_code,
            health_artifact_id=_optional_artifact_id(
                payload["health_artifact_id"],
                "HEALTH_ARTIFACT_ID",
            ),
            lineage_artifact_id=_optional_artifact_id(
                payload["lineage_artifact_id"],
                "LINEAGE_ARTIFACT_ID",
            ),
            state_artifact_id=_optional_artifact_id(
                payload["state_artifact_id"],
                "STATE_ARTIFACT_ID",
            ),
            kind=kind,
            interim_economics_redacted=redacted,
            schema_version=schema_version,
        )
    except ValueError as exc:
        raise ProspectiveBlindMonitorFailureError("FAILURE_RECEIPT_INVALID") from exc
    if receipt.failure_id != failure_id:
        raise ProspectiveBlindMonitorFailureError("FAILURE_RECEIPT_ID_MISMATCH")
    return receipt
