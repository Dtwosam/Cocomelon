from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from cocomelon.research.historical_discovery_freeze import (
    HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
)
from cocomelon.research.prospective_context_report import (
    HYPE_PROSPECTIVE_VALIDATION_V1,
)

FROZEN_OBSERVER_SOURCE_REVISION = "0131fccdb09a2b9ba959dd5785ea213a6297f719"
READINESS_SCHEMA_VERSION = 1


class ProspectiveCampaignReadinessError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _require(source: str, needle: str, code: str) -> None:
    if needle not in source:
        raise ProspectiveCampaignReadinessError(code)


def _require_before(source: str, first: str, second: str, code: str) -> None:
    left = source.find(first)
    right = source.find(second)
    if left < 0 or right < 0 or left >= right:
        raise ProspectiveCampaignReadinessError(code)


@dataclass(frozen=True, slots=True)
class ProspectiveCampaignReadiness:
    observer_workflow_sha256: str
    audited_at_ms: int
    readiness_status: str
    candidate_spec_id: str
    validation_plan_id: str
    observer_source_revision: str
    validation_start_ms: int
    first_expected_anchor_ms: int
    validation_end_ms: int
    finalization_not_before_ms: int
    expected_anchor_count: int
    schema_version: int = READINESS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if len(self.observer_workflow_sha256) != 64:
            raise ValueError("observer_workflow_sha256 must be SHA-256")
        if self.audited_at_ms < 0:
            raise ValueError("audited_at_ms must be non-negative")
        if self.readiness_status not in {
            "ready_pre_cutover",
            "post_cutover_contract_valid",
        }:
            raise ValueError("unsupported readiness_status")
        if len(self.candidate_spec_id) != 64:
            raise ValueError("candidate_spec_id must be SHA-256")
        if len(self.validation_plan_id) != 64:
            raise ValueError("validation_plan_id must be SHA-256")
        if len(self.observer_source_revision) != 40:
            raise ValueError("observer_source_revision must be a git SHA")
        if self.expected_anchor_count <= 0:
            raise ValueError("expected_anchor_count must be positive")
        if self.schema_version != READINESS_SCHEMA_VERSION:
            raise ValueError("unsupported readiness schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "observer_workflow_sha256": self.observer_workflow_sha256,
            "audited_at_ms": self.audited_at_ms,
            "readiness_status": self.readiness_status,
            "candidate_spec_id": self.candidate_spec_id,
            "validation_plan_id": self.validation_plan_id,
            "observer_source_revision": self.observer_source_revision,
            "validation_start_ms": self.validation_start_ms,
            "first_expected_anchor_ms": self.first_expected_anchor_ms,
            "validation_end_ms": self.validation_end_ms,
            "finalization_not_before_ms": self.finalization_not_before_ms,
            "expected_anchor_count": self.expected_anchor_count,
            "schema_version": self.schema_version,
        }

    @property
    def readiness_id(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "readiness_id": self.readiness_id,
        }


def verify_prospective_hype_campaign_readiness(
    workflow_source: str,
    *,
    audited_at_ms: int,
) -> ProspectiveCampaignReadiness:
    if audited_at_ms < 0:
        raise ValueError("audited_at_ms must be non-negative")
    spec = HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1
    plan = HYPE_PROSPECTIVE_VALIDATION_V1
    if plan.candidate_spec_id != spec.spec_id:
        raise ProspectiveCampaignReadinessError("CANDIDATE_PLAN_ID_MISMATCH")
    if plan.validation_start_ms != spec.validation_not_before_ms:
        raise ProspectiveCampaignReadinessError("CANDIDATE_PLAN_CUTOVER_MISMATCH")
    if plan.horizon_ms != spec.horizon_ms:
        raise ProspectiveCampaignReadinessError("CANDIDATE_PLAN_HORIZON_MISMATCH")

    exact_requirements = (
        ('cron: "3,8,13 * * * *"', "FROZEN_CRON_MISSING"),
        ("contents: read", "CONTENTS_PERMISSION_NOT_READ_ONLY"),
        ("actions: read", "ACTIONS_PERMISSION_NOT_READ_ONLY"),
        ("group: prospective-hype-clean-observer", "FROZEN_CONCURRENCY_GROUP_MISSING"),
        ("cancel-in-progress: false", "FROZEN_CONCURRENCY_MODE_MISSING"),
        ("timeout-minutes: 10", "FROZEN_TIMEOUT_MISSING"),
        ("COCOMELON_EXECUTION_MODE: paper", "PAPER_MODE_MISSING"),
        (
            "COCOMELON_API_URL: https://api.hyperliquid.xyz",
            "CANONICAL_MAINNET_API_MISSING",
        ),
        (
            "COCOMELON_WS_URL: wss://api.hyperliquid.xyz/ws",
            "CANONICAL_MAINNET_WS_MISSING",
        ),
        (
            "EVIDENCE_ROOT: artifacts/prospective-hype-clean",
            "FROZEN_EVIDENCE_ROOT_MISSING",
        ),
        (
            "STATE_ARTIFACT_NAME: prospective-hype-clean-state",
            "FROZEN_STATE_ARTIFACT_MISSING",
        ),
        (
            f"OBSERVER_SOURCE_REVISION: {FROZEN_OBSERVER_SOURCE_REVISION}",
            "FROZEN_OBSERVER_ENV_REVISION_MISSING",
        ),
        (
            f"ref: {FROZEN_OBSERVER_SOURCE_REVISION}",
            "FROZEN_OBSERVER_CHECKOUT_REVISION_MISSING",
        ),
        ("persist-credentials: false", "CHECKOUT_CREDENTIAL_PERSISTENCE_NOT_DISABLED"),
        ("Verify frozen observer source revision", "SOURCE_REVISION_VERIFY_STEP_MISSING"),
        ("Restore latest clean evidence state", "STATE_RESTORE_STEP_MISSING"),
        ("Verify cumulative state continuity", "STATE_CONTINUITY_STEP_MISSING"),
        ("Verify prospective runtime attestation", "RUNTIME_ATTESTATION_STEP_MISSING"),
        (
            "Verify prospective control-plane attestation",
            "CONTROL_PLANE_ATTESTATION_STEP_MISSING",
        ),
        ("Run prospective clean observer", "OBSERVER_STEP_MISSING"),
        ("Build current frozen validation report", "VALIDATION_REPORT_STEP_MISSING"),
        (
            "Build workflow-only campaign recoverability health",
            "RECOVERABILITY_HEALTH_STEP_MISSING",
        ),
        (
            "Build or verify canonical campaign finalization",
            "FINALIZATION_STEP_MISSING",
        ),
        ("Upload cumulative clean evidence state", "STATE_UPLOAD_STEP_MISSING"),
        ("Upload immutable finalization status", "FINALIZATION_STATUS_UPLOAD_MISSING"),
        (
            "Fail closed on finalization conflict",
            "FINALIZATION_CONFLICT_GATE_MISSING",
        ),
        (
            "Fail closed if frozen campaign is irrecoverable",
            "IRRECOVERABLE_GATE_MISSING",
        ),
        ("retention-days: 90", "FROZEN_RETENTION_MISSING"),
        ("POST_CUTOVER_RUNTIME_ATTESTATION_REQUIRED", "RUNTIME_FAIL_CLOSED_MISSING"),
        (
            "POST_CUTOVER_CONTROL_PLANE_ATTESTATION_REQUIRED",
            "CONTROL_PLANE_FAIL_CLOSED_MISSING",
        ),
    )
    for needle, code in exact_requirements:
        _require(workflow_source, needle, code)

    if "testnet" in workflow_source.lower():
        raise ProspectiveCampaignReadinessError("TESTNET_REFERENCE_FORBIDDEN")

    _require_before(
        workflow_source,
        "Restore latest clean evidence state",
        "Verify cumulative state continuity",
        "STATE_RESTORE_ORDER_INVALID",
    )
    _require_before(
        workflow_source,
        "Verify cumulative state continuity",
        "Run prospective clean observer",
        "CONTINUITY_GATE_ORDER_INVALID",
    )
    _require_before(
        workflow_source,
        "Verify prospective runtime attestation",
        "Run prospective clean observer",
        "RUNTIME_ATTESTATION_ORDER_INVALID",
    )
    _require_before(
        workflow_source,
        "Verify prospective control-plane attestation",
        "Run prospective clean observer",
        "CONTROL_PLANE_ATTESTATION_ORDER_INVALID",
    )
    _require_before(
        workflow_source,
        "Upload cumulative clean evidence state",
        "Fail closed if frozen campaign is irrecoverable",
        "STATE_PRESERVATION_ORDER_INVALID",
    )
    _require_before(
        workflow_source,
        "Upload immutable finalization status",
        "Fail closed on finalization conflict",
        "FINALIZATION_PRESERVATION_ORDER_INVALID",
    )

    workflow_sha = hashlib.sha256(workflow_source.encode("utf-8")).hexdigest()
    status = (
        "ready_pre_cutover"
        if audited_at_ms < plan.validation_start_ms
        else "post_cutover_contract_valid"
    )
    return ProspectiveCampaignReadiness(
        observer_workflow_sha256=workflow_sha,
        audited_at_ms=audited_at_ms,
        readiness_status=status,
        candidate_spec_id=spec.spec_id,
        validation_plan_id=plan.plan_id,
        observer_source_revision=FROZEN_OBSERVER_SOURCE_REVISION,
        validation_start_ms=plan.validation_start_ms,
        first_expected_anchor_ms=plan.first_expected_anchor_ms,
        validation_end_ms=plan.validation_end_ms,
        finalization_not_before_ms=plan.finalization_not_before_ms,
        expected_anchor_count=plan.expected_anchor_count,
    )


def verify_prospective_hype_campaign_readiness_file(
    workflow_path: str | Path,
    *,
    audited_at_ms: int,
) -> ProspectiveCampaignReadiness:
    path = Path(workflow_path)
    if not path.is_file():
        raise ProspectiveCampaignReadinessError("OBSERVER_WORKFLOW_MISSING")
    return verify_prospective_hype_campaign_readiness(
        path.read_text(encoding="utf-8"),
        audited_at_ms=audited_at_ms,
    )
