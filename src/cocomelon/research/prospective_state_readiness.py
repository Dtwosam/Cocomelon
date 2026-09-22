from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from cocomelon.research.historical_discovery_freeze import (
    HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
)
from cocomelon.research.prospective_campaign_readiness import (
    FROZEN_OBSERVER_SOURCE_REVISION,
)
from cocomelon.research.prospective_context_evidence import (
    MAX_ENTRY_CANDLE_AGE_MS,
    ProspectiveCampaignManifest,
    ProspectiveEvidenceStore,
)
from cocomelon.research.prospective_context_report import (
    HYPE_PROSPECTIVE_VALIDATION_V1,
)
from cocomelon.research.prospective_runtime_attestation import (
    ProspectiveRuntimeAttestation,
)

STATE_READINESS_SCHEMA_VERSION = 1


class ProspectiveStateReadinessError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProspectiveStateReadinessError(f"{field}_INVALID")
    return value


def _object(path: Path, field: str) -> dict[str, object]:
    if not path.is_file():
        raise ProspectiveStateReadinessError(f"{field}_MISSING")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProspectiveStateReadinessError(f"{field}_INVALID") from exc
    if not isinstance(raw, dict):
        raise ProspectiveStateReadinessError(f"{field}_INVALID")
    return cast(dict[str, object], raw)


@dataclass(frozen=True, slots=True)
class ProspectiveStateReadiness:
    artifact_id: str
    audited_at_ms: int
    readiness_status: str
    campaign_id: str
    state_digest: str
    runtime_attestation_id: str
    control_plane_id: str
    observation_count: int
    outcome_count: int
    schema_version: int = STATE_READINESS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.artifact_id.isdigit():
            raise ValueError("artifact_id must be numeric")
        if self.audited_at_ms < 0:
            raise ValueError("audited_at_ms must be non-negative")
        if self.readiness_status not in {
            "ready_pre_cutover_state",
            "post_cutover_state_valid",
        }:
            raise ValueError("unsupported readiness_status")
        for field in ("campaign_id", "state_digest", "runtime_attestation_id", "control_plane_id"):
            if len(cast(str, getattr(self, field))) != 64:
                raise ValueError(f"{field} must be SHA-256")
        if self.observation_count < 0 or self.outcome_count < 0:
            raise ValueError("record counts must be non-negative")

    def identity_payload(self) -> dict[str, object]:
        return {
            "artifact_id": self.artifact_id,
            "audited_at_ms": self.audited_at_ms,
            "readiness_status": self.readiness_status,
            "campaign_id": self.campaign_id,
            "state_digest": self.state_digest,
            "runtime_attestation_id": self.runtime_attestation_id,
            "control_plane_id": self.control_plane_id,
            "observation_count": self.observation_count,
            "outcome_count": self.outcome_count,
            "schema_version": self.schema_version,
        }

    @property
    def receipt_id(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "receipt_id": self.receipt_id}


def verify_prospective_hype_state_readiness(
    root: str | Path,
    *,
    artifact_id: str,
    audited_at_ms: int,
) -> ProspectiveStateReadiness:
    if audited_at_ms < 0:
        raise ValueError("audited_at_ms must be non-negative")
    if not artifact_id.isdigit():
        raise ValueError("artifact_id must be numeric")

    spec = HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1
    plan = HYPE_PROSPECTIVE_VALIDATION_V1
    root_path = Path(root)

    manifest_raw = _object(root_path / "manifest.json", "CAMPAIGN_MANIFEST")
    expected_manifest = ProspectiveCampaignManifest(
        candidate_spec_id=spec.spec_id,
        candidate_id=spec.candidate_id,
        validation_not_before_ms=spec.validation_not_before_ms,
    )
    expected_manifest_payload = json.loads(
        _canonical_json(
            {
                **expected_manifest.identity_payload(),
                "campaign_id": expected_manifest.campaign_id,
            }
        )
    )
    if manifest_raw != expected_manifest_payload:
        raise ProspectiveStateReadinessError("CAMPAIGN_MANIFEST_MISMATCH")

    runtime_raw = _object(root_path / "runtime.json", "RUNTIME_ATTESTATION")
    try:
        runtime = ProspectiveRuntimeAttestation(
            candidate_spec_id=str(runtime_raw["candidate_spec_id"]),
            validation_plan_id=str(runtime_raw["validation_plan_id"]),
            observer_source_revision=str(runtime_raw["observer_source_revision"]),
            schema_version=_integer(
                runtime_raw.get("schema_version"),
                "RUNTIME_SCHEMA_VERSION",
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ProspectiveStateReadinessError("RUNTIME_ATTESTATION_INVALID") from exc
    if runtime_raw.get("attestation_id") != runtime.attestation_id:
        raise ProspectiveStateReadinessError("RUNTIME_ATTESTATION_ID_MISMATCH")
    if runtime.candidate_spec_id != spec.spec_id:
        raise ProspectiveStateReadinessError("RUNTIME_CANDIDATE_MISMATCH")
    if runtime.validation_plan_id != plan.plan_id:
        raise ProspectiveStateReadinessError("RUNTIME_PLAN_MISMATCH")
    if runtime.observer_source_revision != FROZEN_OBSERVER_SOURCE_REVISION:
        raise ProspectiveStateReadinessError("RUNTIME_SOURCE_REVISION_MISMATCH")

    control = _object(root_path / "control-plane.json", "CONTROL_PLANE")
    expected_control = {
        "kind": "prospective-hype-clean-control-plane",
        "candidate_spec_id": spec.spec_id,
        "validation_plan_id": plan.plan_id,
        "observer_source_revision": FROZEN_OBSERVER_SOURCE_REVISION,
        "schedule_cron": "3,8,13 * * * *",
        "attempt_minutes_utc": [3, 8, 13],
        "max_entry_candle_age_ms": MAX_ENTRY_CANDLE_AGE_MS,
        "state_artifact_name": "prospective-hype-clean-state",
        "evidence_root": "artifacts/prospective-hype-clean",
        "concurrency_group": "prospective-hype-clean-observer",
        "cancel_in_progress": False,
        "job_timeout_minutes": 10,
        "execution_mode": "paper",
        "api_url": "https://api.hyperliquid.xyz",
        "ws_url": "wss://api.hyperliquid.xyz/ws",
        "contents_permission": "read",
        "actions_permission": "read",
        "artifact_retention_days": 90,
        "schema_version": 1,
    }
    expected_control["control_plane_id"] = hashlib.sha256(
        _canonical_json(expected_control).encode("utf-8")
    ).hexdigest()
    if control != expected_control:
        raise ProspectiveStateReadinessError("CONTROL_PLANE_MISMATCH")

    store = ProspectiveEvidenceStore(root_path, spec=spec)
    observations = store.iter_observations()
    outcomes = store.iter_outcomes()
    if audited_at_ms < plan.validation_start_ms and (observations or outcomes):
        raise ProspectiveStateReadinessError("PRE_CUTOVER_STATE_CONTAMINATED")
    if any(item.anchor_end_ms < plan.validation_start_ms for item in observations):
        raise ProspectiveStateReadinessError("PRE_CUTOVER_OBSERVATION_PRESENT")

    status = (
        "ready_pre_cutover_state"
        if audited_at_ms < plan.validation_start_ms
        else "post_cutover_state_valid"
    )
    return ProspectiveStateReadiness(
        artifact_id=artifact_id,
        audited_at_ms=audited_at_ms,
        readiness_status=status,
        campaign_id=store.manifest.campaign_id,
        state_digest=store.state_digest,
        runtime_attestation_id=runtime.attestation_id,
        control_plane_id=str(control["control_plane_id"]),
        observation_count=len(observations),
        outcome_count=len(outcomes),
    )
