from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import cast

_HEALTH_NAME = re.compile(
    r"^prospective-hype-clean-health-(?P<run_id>[0-9]+)-(?P<attempt>[0-9]+)$"
)
_MAX_STATE_TO_HEALTH_SECONDS = 10 * 60


class ProspectiveArtifactSelectionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class BlindMonitorArtifactSelection:
    health_artifact_id: str
    lineage_artifact_id: str
    state_artifact_id: str
    observer_run_id: str
    observer_run_attempt: int


def _created_at(item: dict[str, object], field: str) -> datetime:
    value = item.get("created_at")
    if not isinstance(value, str) or not value:
        raise ProspectiveArtifactSelectionError(f"{field}_CREATED_AT_INVALID")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProspectiveArtifactSelectionError(
            f"{field}_CREATED_AT_INVALID"
        ) from exc


def _artifact_id(item: dict[str, object], field: str) -> str:
    value = item.get("id")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ProspectiveArtifactSelectionError(f"{field}_ID_INVALID")
    return str(value)


def _workflow_run(item: dict[str, object], field: str) -> dict[str, object]:
    value = item.get("workflow_run")
    if not isinstance(value, dict):
        raise ProspectiveArtifactSelectionError(f"{field}_WORKFLOW_RUN_INVALID")
    return cast(dict[str, object], value)


def _sort_key(item: dict[str, object]) -> tuple[datetime, int]:
    artifact_id = _artifact_id(item, "ARTIFACT")
    return (_created_at(item, "ARTIFACT"), int(artifact_id))


def select_blind_monitor_artifacts(
    raw_artifacts: object,
) -> BlindMonitorArtifactSelection:
    if not isinstance(raw_artifacts, list):
        raise ProspectiveArtifactSelectionError("ARTIFACT_DISCOVERY_PAYLOAD_INVALID")

    artifacts = [
        cast(dict[str, object], item)
        for item in raw_artifacts
        if isinstance(item, dict)
        and item.get("expired") is False
        and isinstance(item.get("workflow_run"), dict)
        and cast(dict[str, object], item["workflow_run"]).get("head_branch") == "main"
    ]

    health_items = [
        item
        for item in artifacts
        if str(item.get("name", "")).startswith("prospective-hype-clean-health-")
    ]
    if not health_items:
        raise ProspectiveArtifactSelectionError("HEALTH_ARTIFACT_MISSING")
    health = max(health_items, key=_sort_key)

    lineage_items = [
        item
        for item in artifacts
        if str(item.get("name", "")).startswith("prospective-hype-lineage-")
    ]
    if not lineage_items:
        raise ProspectiveArtifactSelectionError("LINEAGE_ARTIFACT_MISSING")
    lineage = max(lineage_items, key=_sort_key)

    health_name = str(health.get("name", ""))
    match = _HEALTH_NAME.fullmatch(health_name)
    if match is None:
        raise ProspectiveArtifactSelectionError("HEALTH_ARTIFACT_IDENTITY_INVALID")

    health_workflow = _workflow_run(health, "HEALTH")
    run_id = health_workflow.get("id")
    if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id <= 0:
        raise ProspectiveArtifactSelectionError("HEALTH_WORKFLOW_RUN_ID_INVALID")
    if int(match.group("run_id")) != run_id:
        raise ProspectiveArtifactSelectionError("HEALTH_ARTIFACT_IDENTITY_INVALID")
    attempt = int(match.group("attempt"))
    if attempt <= 0:
        raise ProspectiveArtifactSelectionError("HEALTH_ARTIFACT_IDENTITY_INVALID")

    health_created = _created_at(health, "HEALTH")
    state_candidates: list[dict[str, object]] = []
    for item in artifacts:
        if item.get("name") != "prospective-hype-clean-state":
            continue
        workflow = _workflow_run(item, "STATE")
        if workflow.get("id") != run_id:
            continue
        created = _created_at(item, "STATE")
        if created <= health_created:
            state_candidates.append(item)

    if not state_candidates:
        raise ProspectiveArtifactSelectionError("STATE_ARTIFACT_MATCH_INVALID")

    state = max(state_candidates, key=_sort_key)
    state_created = _created_at(state, "STATE")
    gap_seconds = (health_created - state_created).total_seconds()
    if not 0 <= gap_seconds <= _MAX_STATE_TO_HEALTH_SECONDS:
        raise ProspectiveArtifactSelectionError("STATE_ARTIFACT_MATCH_INVALID")

    return BlindMonitorArtifactSelection(
        health_artifact_id=_artifact_id(health, "HEALTH"),
        lineage_artifact_id=_artifact_id(lineage, "LINEAGE"),
        state_artifact_id=_artifact_id(state, "STATE"),
        observer_run_id=str(run_id),
        observer_run_attempt=attempt,
    )
