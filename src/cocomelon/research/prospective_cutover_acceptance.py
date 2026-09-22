from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from cocomelon.research.historical_discovery_freeze import (
    HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
)
from cocomelon.research.prospective_context_evidence import (
    ProspectiveCampaignManifest,
    ProspectiveEvidenceStore,
)
from cocomelon.research.prospective_context_report import (
    HYPE_PROSPECTIVE_VALIDATION_V1,
)
from cocomelon.research.prospective_state_readiness import (
    verify_prospective_hype_state_readiness,
)

CUTOVER_ACCEPTANCE_SCHEMA_VERSION = 1
CUTOVER_ACCEPTANCE_STATUS = "cutover_integrity_valid"


class ProspectiveCutoverAcceptanceError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _object(path: str | Path, field: str) -> dict[str, object]:
    resolved = Path(path)
    if not resolved.is_file():
        raise ProspectiveCutoverAcceptanceError(f"{field}_MISSING")
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProspectiveCutoverAcceptanceError(f"{field}_INVALID") from exc
    if not isinstance(raw, dict):
        raise ProspectiveCutoverAcceptanceError(f"{field}_INVALID")
    return cast(dict[str, object], raw)


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProspectiveCutoverAcceptanceError(f"{field}_INVALID")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProspectiveCutoverAcceptanceError(f"{field}_INVALID")
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ProspectiveCutoverAcceptanceError(f"{field}_INVALID")
    return value


def _verify_identity(
    payload: dict[str, object],
    *,
    identity_field: str,
    error_code: str,
) -> None:
    supplied = _string(payload.get(identity_field), identity_field.upper())
    identity = {
        key: value
        for key, value in payload.items()
        if key != identity_field
    }
    expected = hashlib.sha256(
        _canonical_json(identity).encode("utf-8")
    ).hexdigest()
    if supplied != expected:
        raise ProspectiveCutoverAcceptanceError(error_code)


def _expected_campaign_id() -> str:
    spec = HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1
    return ProspectiveCampaignManifest(
        candidate_spec_id=spec.spec_id,
        candidate_id=spec.candidate_id,
        validation_not_before_ms=spec.validation_not_before_ms,
    ).campaign_id


@dataclass(frozen=True, slots=True)
class ProspectiveCutoverAcceptance:
    audited_at_ms: int
    campaign_id: str
    validation_plan_id: str
    monitor_id: str
    state_artifact_id: str
    state_digest: str
    first_expected_anchor_ms: int
    expected_anchor_count_to_date: int
    observation_count_to_date: int
    missed_anchor_count_to_date: int
    first_anchor_status: str
    earliest_observation_anchor_ms: int | None
    latest_observation_anchor_ms: int | None
    observation_grid_valid: bool
    pre_cutover_observation_count: int
    campaign_health_status: str
    lineage_status: str
    cutover_status: str = CUTOVER_ACCEPTANCE_STATUS
    interim_economics_redacted: bool = True
    schema_version: int = CUTOVER_ACCEPTANCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.audited_at_ms < 0:
            raise ValueError("audited_at_ms must be non-negative")
        for field in (
            "campaign_id",
            "validation_plan_id",
            "monitor_id",
            "state_digest",
        ):
            value = cast(str, getattr(self, field))
            if len(value) != 64:
                raise ValueError(f"{field} must be SHA-256")
        if not self.state_artifact_id.isdigit():
            raise ValueError("state_artifact_id must be numeric")
        if self.first_expected_anchor_ms < 0:
            raise ValueError("first_expected_anchor_ms must be non-negative")
        if self.audited_at_ms < self.first_expected_anchor_ms:
            raise ValueError("cutover acceptance cannot predate first expected anchor")
        for field in (
            "expected_anchor_count_to_date",
            "observation_count_to_date",
            "missed_anchor_count_to_date",
            "pre_cutover_observation_count",
        ):
            if cast(int, getattr(self, field)) < 0:
                raise ValueError(f"{field} must be non-negative")
        if self.expected_anchor_count_to_date < 1:
            raise ValueError("cutover acceptance requires at least one expected anchor")
        if self.observation_count_to_date > self.expected_anchor_count_to_date:
            raise ValueError("observation_count_to_date cannot exceed expected anchors")
        if self.missed_anchor_count_to_date != (
            self.expected_anchor_count_to_date - self.observation_count_to_date
        ):
            raise ValueError("missed_anchor_count_to_date must reconcile")
        if self.first_anchor_status not in {"captured", "missed"}:
            raise ValueError("unsupported first_anchor_status")
        if self.first_anchor_status == "captured":
            if self.earliest_observation_anchor_ms != self.first_expected_anchor_ms:
                raise ValueError("captured first anchor must be earliest observation")
        elif (
            self.earliest_observation_anchor_ms is not None
            and self.earliest_observation_anchor_ms <= self.first_expected_anchor_ms
        ):
            raise ValueError("missed first anchor requires a later earliest observation")
        if self.earliest_observation_anchor_ms is None:
            if self.latest_observation_anchor_ms is not None:
                raise ValueError("latest observation requires earliest observation")
        else:
            if self.latest_observation_anchor_ms is None:
                raise ValueError("earliest observation requires latest observation")
            if self.latest_observation_anchor_ms < self.earliest_observation_anchor_ms:
                raise ValueError("latest observation must not predate earliest observation")
        if not self.observation_grid_valid:
            raise ValueError("cutover acceptance requires valid observation grid")
        if self.pre_cutover_observation_count != 0:
            raise ValueError("cutover acceptance requires zero pre-cutover observations")
        if self.campaign_health_status not in {"healthy", "degraded"}:
            raise ValueError("cutover acceptance requires healthy or degraded campaign state")
        if self.lineage_status != "append_only_valid":
            raise ValueError("cutover acceptance requires append-only lineage")
        if self.cutover_status != CUTOVER_ACCEPTANCE_STATUS:
            raise ValueError("unsupported cutover_status")
        if not self.interim_economics_redacted:
            raise ValueError("interim economics must remain redacted")
        if self.schema_version != CUTOVER_ACCEPTANCE_SCHEMA_VERSION:
            raise ValueError("unsupported cutover acceptance schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "audited_at_ms": self.audited_at_ms,
            "campaign_id": self.campaign_id,
            "validation_plan_id": self.validation_plan_id,
            "monitor_id": self.monitor_id,
            "state_artifact_id": self.state_artifact_id,
            "state_digest": self.state_digest,
            "first_expected_anchor_ms": self.first_expected_anchor_ms,
            "expected_anchor_count_to_date": self.expected_anchor_count_to_date,
            "observation_count_to_date": self.observation_count_to_date,
            "missed_anchor_count_to_date": self.missed_anchor_count_to_date,
            "first_anchor_status": self.first_anchor_status,
            "earliest_observation_anchor_ms": self.earliest_observation_anchor_ms,
            "latest_observation_anchor_ms": self.latest_observation_anchor_ms,
            "observation_grid_valid": self.observation_grid_valid,
            "pre_cutover_observation_count": self.pre_cutover_observation_count,
            "campaign_health_status": self.campaign_health_status,
            "lineage_status": self.lineage_status,
            "cutover_status": self.cutover_status,
            "interim_economics_redacted": self.interim_economics_redacted,
            "schema_version": self.schema_version,
        }

    @property
    def receipt_id(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "receipt_id": self.receipt_id}


def verify_prospective_hype_cutover_receipt(
    path: str | Path,
) -> ProspectiveCutoverAcceptance:
    payload = _object(path, "CUTOVER_RECEIPT")
    _verify_identity(
        payload,
        identity_field="receipt_id",
        error_code="CUTOVER_RECEIPT_ID_MISMATCH",
    )
    expected_campaign_id = _expected_campaign_id()
    plan = HYPE_PROSPECTIVE_VALIDATION_V1
    if _string(payload.get("campaign_id"), "CAMPAIGN_ID") != expected_campaign_id:
        raise ProspectiveCutoverAcceptanceError("CAMPAIGN_ID_MISMATCH")
    if _string(payload.get("validation_plan_id"), "VALIDATION_PLAN_ID") != plan.plan_id:
        raise ProspectiveCutoverAcceptanceError("VALIDATION_PLAN_ID_MISMATCH")
    if _integer(
        payload.get("first_expected_anchor_ms"),
        "FIRST_EXPECTED_ANCHOR_MS",
    ) != plan.first_expected_anchor_ms:
        raise ProspectiveCutoverAcceptanceError("FIRST_EXPECTED_ANCHOR_MISMATCH")

    try:
        return ProspectiveCutoverAcceptance(
            audited_at_ms=_integer(payload.get("audited_at_ms"), "AUDITED_AT_MS"),
            campaign_id=_string(payload.get("campaign_id"), "CAMPAIGN_ID"),
            validation_plan_id=_string(
                payload.get("validation_plan_id"),
                "VALIDATION_PLAN_ID",
            ),
            monitor_id=_string(payload.get("monitor_id"), "MONITOR_ID"),
            state_artifact_id=_string(
                payload.get("state_artifact_id"),
                "STATE_ARTIFACT_ID",
            ),
            state_digest=_string(payload.get("state_digest"), "STATE_DIGEST"),
            first_expected_anchor_ms=_integer(
                payload.get("first_expected_anchor_ms"),
                "FIRST_EXPECTED_ANCHOR_MS",
            ),
            expected_anchor_count_to_date=_integer(
                payload.get("expected_anchor_count_to_date"),
                "EXPECTED_ANCHOR_COUNT_TO_DATE",
            ),
            observation_count_to_date=_integer(
                payload.get("observation_count_to_date"),
                "OBSERVATION_COUNT_TO_DATE",
            ),
            missed_anchor_count_to_date=_integer(
                payload.get("missed_anchor_count_to_date"),
                "MISSED_ANCHOR_COUNT_TO_DATE",
            ),
            first_anchor_status=_string(
                payload.get("first_anchor_status"),
                "FIRST_ANCHOR_STATUS",
            ),
            earliest_observation_anchor_ms=(
                None
                if payload.get("earliest_observation_anchor_ms") is None
                else _integer(
                    payload.get("earliest_observation_anchor_ms"),
                    "EARLIEST_OBSERVATION_ANCHOR_MS",
                )
            ),
            latest_observation_anchor_ms=(
                None
                if payload.get("latest_observation_anchor_ms") is None
                else _integer(
                    payload.get("latest_observation_anchor_ms"),
                    "LATEST_OBSERVATION_ANCHOR_MS",
                )
            ),
            observation_grid_valid=_boolean(
                payload.get("observation_grid_valid"),
                "OBSERVATION_GRID_VALID",
            ),
            pre_cutover_observation_count=_integer(
                payload.get("pre_cutover_observation_count"),
                "PRE_CUTOVER_OBSERVATION_COUNT",
            ),
            campaign_health_status=_string(
                payload.get("campaign_health_status"),
                "CAMPAIGN_HEALTH_STATUS",
            ),
            lineage_status=_string(payload.get("lineage_status"), "LINEAGE_STATUS"),
            cutover_status=_string(payload.get("cutover_status"), "CUTOVER_STATUS"),
            interim_economics_redacted=_boolean(
                payload.get("interim_economics_redacted"),
                "INTERIM_ECONOMICS_REDACTED",
            ),
            schema_version=_integer(payload.get("schema_version"), "SCHEMA_VERSION"),
        )
    except ValueError as exc:
        raise ProspectiveCutoverAcceptanceError("CUTOVER_RECEIPT_INVALID") from exc


def build_prospective_hype_cutover_acceptance(
    monitor_path: str | Path,
    state_root: str | Path,
    *,
    state_artifact_id: str,
    state_audited_at_ms: int,
    audited_at_ms: int,
) -> ProspectiveCutoverAcceptance:
    if audited_at_ms < 0:
        raise ValueError("audited_at_ms must be non-negative")
    if state_audited_at_ms < 0:
        raise ValueError("state_audited_at_ms must be non-negative")
    if not state_artifact_id.isdigit():
        raise ValueError("state_artifact_id must be numeric")

    monitor = _object(monitor_path, "BLIND_MONITOR")
    _verify_identity(
        monitor,
        identity_field="monitor_id",
        error_code="BLIND_MONITOR_ID_MISMATCH",
    )
    if not _boolean(
        monitor.get("interim_economics_redacted"),
        "INTERIM_ECONOMICS_REDACTED",
    ):
        raise ProspectiveCutoverAcceptanceError("INTERIM_ECONOMICS_NOT_REDACTED")

    plan = HYPE_PROSPECTIVE_VALIDATION_V1
    campaign_id = _expected_campaign_id()
    monitor_campaign_id = _string(monitor.get("campaign_id"), "CAMPAIGN_ID")
    if monitor_campaign_id != campaign_id:
        raise ProspectiveCutoverAcceptanceError("CAMPAIGN_ID_MISMATCH")

    monitor_as_of_ms = _integer(monitor.get("as_of_ms"), "MONITOR_AS_OF_MS")
    if monitor_as_of_ms < plan.first_expected_anchor_ms:
        raise ProspectiveCutoverAcceptanceError("FIRST_EXPECTED_ANCHOR_NOT_REACHED")

    expected_to_date = _integer(
        monitor.get("expected_anchor_count_to_date"),
        "EXPECTED_ANCHOR_COUNT_TO_DATE",
    )
    observed_to_date = _integer(
        monitor.get("observation_count_to_date"),
        "OBSERVATION_COUNT_TO_DATE",
    )
    missed_to_date = _integer(
        monitor.get("missed_anchor_count_to_date"),
        "MISSED_ANCHOR_COUNT_TO_DATE",
    )
    if expected_to_date < 1:
        raise ProspectiveCutoverAcceptanceError("EXPECTED_ANCHOR_COUNT_NOT_STARTED")
    if missed_to_date != expected_to_date - observed_to_date:
        raise ProspectiveCutoverAcceptanceError("CAPTURE_COUNT_RECONCILIATION_FAILED")

    campaign_health_status = _string(
        monitor.get("campaign_health_status"),
        "CAMPAIGN_HEALTH_STATUS",
    )
    if campaign_health_status not in {"healthy", "degraded"}:
        raise ProspectiveCutoverAcceptanceError("CUTOVER_CAMPAIGN_HEALTH_INVALID")
    lineage_status = _string(monitor.get("lineage_status"), "LINEAGE_STATUS")
    if lineage_status != "append_only_valid":
        raise ProspectiveCutoverAcceptanceError("CUTOVER_LINEAGE_NOT_READY")

    monitor_state_id = _string(
        monitor.get("state_artifact_id"),
        "STATE_ARTIFACT_ID",
    )
    if monitor_state_id != state_artifact_id:
        raise ProspectiveCutoverAcceptanceError("STATE_ARTIFACT_ID_MISMATCH")

    readiness = verify_prospective_hype_state_readiness(
        state_root,
        artifact_id=state_artifact_id,
        audited_at_ms=state_audited_at_ms,
    )
    if readiness.readiness_status != "post_cutover_state_valid":
        raise ProspectiveCutoverAcceptanceError("STATE_NOT_POST_CUTOVER")
    if readiness.campaign_id != campaign_id:
        raise ProspectiveCutoverAcceptanceError("STATE_CAMPAIGN_ID_MISMATCH")
    monitor_state_digest = _string(monitor.get("current_state_digest"), "STATE_DIGEST")
    if readiness.state_digest != monitor_state_digest:
        raise ProspectiveCutoverAcceptanceError("STATE_DIGEST_MISMATCH")
    if readiness.observation_count != observed_to_date:
        raise ProspectiveCutoverAcceptanceError("STATE_OBSERVATION_COUNT_MISMATCH")

    store = ProspectiveEvidenceStore(
        Path(state_root),
        spec=HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
    )
    observations = store.iter_observations()
    if len(observations) != observed_to_date:
        raise ProspectiveCutoverAcceptanceError("STATE_OBSERVATION_COUNT_MISMATCH")

    pre_cutover = tuple(
        item
        for item in observations
        if item.anchor_end_ms < plan.first_expected_anchor_ms
    )
    if pre_cutover:
        raise ProspectiveCutoverAcceptanceError("PRE_CUTOVER_OBSERVATION_PRESENT")

    invalid_grid = tuple(
        item
        for item in observations
        if item.anchor_end_ms >= plan.validation_end_ms
        or (
            item.anchor_end_ms - plan.first_expected_anchor_ms
        )
        % plan.anchor_interval_ms
        != 0
    )
    if invalid_grid:
        raise ProspectiveCutoverAcceptanceError("OBSERVATION_ANCHOR_GRID_INVALID")

    anchors = tuple(sorted(item.anchor_end_ms for item in observations))
    first_anchor_status = (
        "captured"
        if plan.first_expected_anchor_ms in anchors
        else "missed"
    )
    return ProspectiveCutoverAcceptance(
        audited_at_ms=audited_at_ms,
        campaign_id=campaign_id,
        validation_plan_id=plan.plan_id,
        monitor_id=_string(monitor.get("monitor_id"), "MONITOR_ID"),
        state_artifact_id=state_artifact_id,
        state_digest=readiness.state_digest,
        first_expected_anchor_ms=plan.first_expected_anchor_ms,
        expected_anchor_count_to_date=expected_to_date,
        observation_count_to_date=observed_to_date,
        missed_anchor_count_to_date=missed_to_date,
        first_anchor_status=first_anchor_status,
        earliest_observation_anchor_ms=(None if not anchors else anchors[0]),
        latest_observation_anchor_ms=(None if not anchors else anchors[-1]),
        observation_grid_valid=True,
        pre_cutover_observation_count=0,
        campaign_health_status=campaign_health_status,
        lineage_status=lineage_status,
    )
