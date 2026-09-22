from __future__ import annotations

import re
from datetime import datetime
from typing import cast

_HEALTH_NAME = re.compile(
    r"^prospective-hype-clean-health-(?P<run_id>[0-9]+)-(?P<attempt>[0-9]+)$"
)
_MAX_STATE_TO_HEALTH_SECONDS = 10 * 60


class ProspectiveArtifactSelectionError(RuntimeError):
    pass


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
        raise ProspectiveArtifactSelectionError(
            f"{field}_WORKFLOW_RUN_INVALID"
        )
    return cast(dict[str, object], value)


def _sort_key(item: dict[str, object]) -> tuple[datetime, int]:
    return (
        _created_at(item, "STATE"),
        int(_artifact_id(item, "STATE")),
    )


def select_state_artifact_for_health(
    raw_artifacts: object,
    health_artifact: dict[str, object],
) -> str:
    if not isinstance(raw_artifacts, list):
        raise ProspectiveArtifactSelectionError(
            "ARTIFACT_DISCOVERY_PAYLOAD_INVALID"
        )

    health_name = health_artifact.get("name")
    if not isinstance(health_name, str):
        raise ProspectiveArtifactSelectionError(
            "HEALTH_ARTIFACT_IDENTITY_INVALID"
        )
    match = _HEALTH_NAME.fullmatch(health_name)
    if match is None:
        raise ProspectiveArtifactSelectionError(
            "HEALTH_ARTIFACT_IDENTITY_INVALID"
        )

    health_workflow = _workflow_run(health_artifact, "HEALTH")
    run_id = health_workflow.get("id")
    if (
        isinstance(run_id, bool)
        or not isinstance(run_id, int)
        or run_id <= 0
        or int(match.group("run_id")) != run_id
        or int(match.group("attempt")) <= 0
    ):
        raise ProspectiveArtifactSelectionError(
            "HEALTH_ARTIFACT_IDENTITY_INVALID"
        )

    health_created = _created_at(health_artifact, "HEALTH")
    candidates: list[dict[str, object]] = []
    for raw in raw_artifacts:
        if not isinstance(raw, dict):
            continue
        item = cast(dict[str, object], raw)
        if (
            item.get("expired") is not False
            or item.get("name") != "prospective-hype-clean-state"
        ):
            continue
        workflow = item.get("workflow_run")
        if not isinstance(workflow, dict):
            continue
        if workflow.get("head_branch") != "main" or workflow.get("id") != run_id:
            continue
        created = _created_at(item, "STATE")
        if created <= health_created:
            candidates.append(item)

    if not candidates:
        raise ProspectiveArtifactSelectionError(
            "STATE_ARTIFACT_MATCH_INVALID"
        )

    state = max(candidates, key=_sort_key)
    state_created = _created_at(state, "STATE")
    gap_seconds = (health_created - state_created).total_seconds()
    if not 0 <= gap_seconds <= _MAX_STATE_TO_HEALTH_SECONDS:
        raise ProspectiveArtifactSelectionError(
            "STATE_ARTIFACT_MATCH_INVALID"
        )
    return _artifact_id(state, "STATE")
