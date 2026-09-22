from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import cast

CHECKPOINT_ARTIFACT_NAME = "archive-clean-operational-checkpoint"


class ArchiveCleanArtifactSelectionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ArchiveCleanCheckpointArtifactSelection:
    artifact_id: str
    workflow_run_id: int
    created_at: str


def _created_at(item: dict[str, object]) -> datetime:
    value = item.get("created_at")
    if not isinstance(value, str) or not value.strip():
        raise ArchiveCleanArtifactSelectionError("CHECKPOINT_ARTIFACT_CREATED_AT_INVALID")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ArchiveCleanArtifactSelectionError(
            "CHECKPOINT_ARTIFACT_CREATED_AT_INVALID"
        ) from exc


def _artifact_id(item: dict[str, object]) -> int:
    value = item.get("id")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ArchiveCleanArtifactSelectionError("CHECKPOINT_ARTIFACT_ID_INVALID")
    return value


def _run_id(item: dict[str, object]) -> int:
    raw = item.get("workflow_run")
    if not isinstance(raw, dict):
        raise ArchiveCleanArtifactSelectionError(
            "CHECKPOINT_ARTIFACT_WORKFLOW_RUN_INVALID"
        )
    value = cast(dict[str, object], raw).get("id")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ArchiveCleanArtifactSelectionError(
            "CHECKPOINT_ARTIFACT_WORKFLOW_RUN_INVALID"
        )
    return value


def select_latest_archive_clean_checkpoint_artifact(
    raw_artifacts: object,
) -> ArchiveCleanCheckpointArtifactSelection | None:
    if not isinstance(raw_artifacts, list):
        raise ArchiveCleanArtifactSelectionError(
            "CHECKPOINT_ARTIFACT_DISCOVERY_PAYLOAD_INVALID"
        )

    eligible: list[dict[str, object]] = []
    for raw in raw_artifacts:
        if not isinstance(raw, dict):
            continue
        item = cast(dict[str, object], raw)
        workflow = item.get("workflow_run")
        if not isinstance(workflow, dict):
            continue
        workflow_map = cast(dict[str, object], workflow)
        if (
            item.get("name") != CHECKPOINT_ARTIFACT_NAME
            or item.get("expired") is not False
            or workflow_map.get("head_branch") != "main"
        ):
            continue
        _artifact_id(item)
        _run_id(item)
        _created_at(item)
        eligible.append(item)

    if not eligible:
        return None

    latest_run_id = max(_run_id(item) for item in eligible)
    same_run = tuple(
        item for item in eligible if _run_id(item) == latest_run_id
    )
    selected = max(
        same_run,
        key=lambda item: (_created_at(item), _artifact_id(item)),
    )
    return ArchiveCleanCheckpointArtifactSelection(
        artifact_id=str(_artifact_id(selected)),
        workflow_run_id=latest_run_id,
        created_at=cast(str, selected["created_at"]),
    )
