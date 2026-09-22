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
class LineageStatePair:
    previous_artifact_id: str
    current_artifact_id: str
    previous_audited_at_ms: int
    current_audited_at_ms: int
    previous_run_id: int
    current_run_id: int


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


def select_lineage_state_pair(raw_artifacts: object) -> LineageStatePair:
    if not isinstance(raw_artifacts, list):
        raise ProspectiveArtifactSelectionError(
            "ARTIFACT_DISCOVERY_PAYLOAD_INVALID"
        )

    states: list[dict[str, object]] = []
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
        run_id = workflow.get("id")
        if (
            workflow.get("head_branch") != "main"
            or isinstance(run_id, bool)
            or not isinstance(run_id, int)
            or run_id <= 0
        ):
            continue
        _created_at(item, "STATE")
        _artifact_id(item, "STATE")
        states.append(item)

    latest_by_run: dict[int, dict[str, object]] = {}
    for state in states:
        run_id = cast(int, cast(dict[str, object], state["workflow_run"])["id"])
        current = latest_by_run.get(run_id)
        if current is None or _sort_key(state) > _sort_key(current):
            latest_by_run[run_id] = state

    distinct_states = sorted(latest_by_run.values(), key=_sort_key)
    if len(distinct_states) < 2:
        raise ProspectiveArtifactSelectionError(
            "DISTINCT_STATE_RUNS_INSUFFICIENT"
        )

    previous, current = distinct_states[-2:]
    previous_run_id = cast(
        int,
        cast(dict[str, object], previous["workflow_run"])["id"],
    )
    current_run_id = cast(
        int,
        cast(dict[str, object], current["workflow_run"])["id"],
    )
    if previous_run_id == current_run_id:
        raise ProspectiveArtifactSelectionError(
            "DISTINCT_STATE_RUNS_INSUFFICIENT"
        )

    previous_created = _created_at(previous, "STATE")
    current_created = _created_at(current, "STATE")
    if previous_created >= current_created:
        raise ProspectiveArtifactSelectionError(
            "STATE_ARTIFACT_ORDER_INVALID"
        )

    return LineageStatePair(
        previous_artifact_id=_artifact_id(previous, "STATE"),
        current_artifact_id=_artifact_id(current, "STATE"),
        previous_audited_at_ms=int(previous_created.timestamp() * 1000),
        current_audited_at_ms=int(current_created.timestamp() * 1000),
        previous_run_id=previous_run_id,
        current_run_id=current_run_id,
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
