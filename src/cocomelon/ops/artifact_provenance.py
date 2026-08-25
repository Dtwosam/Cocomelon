from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

CURATOR_WORKFLOW_PATH = ".github/workflows/evidence-corpus-curator.yml"
CURATOR_EVENT = "workflow_run"


@dataclass(frozen=True, slots=True)
class ArtifactCandidate:
    artifact_id: int
    workflow_run_id: int
    created_at: str


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def ranked_artifact_candidates(
    payload: Mapping[str, object],
    artifact_name: str,
) -> tuple[ArtifactCandidate, ...]:
    if not artifact_name.strip():
        raise ValueError("artifact_name must not be empty")
    raw_artifacts = payload.get("artifacts")
    if not isinstance(raw_artifacts, list):
        return ()

    candidates: list[ArtifactCandidate] = []
    for raw in raw_artifacts:
        if not isinstance(raw, dict):
            continue
        if raw.get("name") != artifact_name or raw.get("expired") is not False:
            continue
        artifact_id = _positive_int(raw.get("id"))
        workflow_run = raw.get("workflow_run")
        if artifact_id is None or not isinstance(workflow_run, dict):
            continue
        workflow_run_id = _positive_int(workflow_run.get("id"))
        created_at = raw.get("created_at")
        if workflow_run_id is None or not isinstance(created_at, str) or not created_at:
            continue
        candidates.append(
            ArtifactCandidate(
                artifact_id=artifact_id,
                workflow_run_id=workflow_run_id,
                created_at=created_at,
            )
        )

    return tuple(
        sorted(
            candidates,
            key=lambda item: (item.created_at, item.artifact_id),
            reverse=True,
        )
    )


def _repository_name(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    full_name = value.get("full_name")
    if not isinstance(full_name, str) or not full_name.strip():
        return None
    return full_name


def trusted_curator_run(
    payload: Mapping[str, object],
    *,
    repository: str,
    expected_run_id: int | None = None,
) -> bool:
    if not repository.strip():
        raise ValueError("repository must not be empty")
    run_id = _positive_int(payload.get("id"))
    if run_id is None:
        return False
    if expected_run_id is not None and run_id != expected_run_id:
        return False
    if payload.get("path") != CURATOR_WORKFLOW_PATH:
        return False
    if payload.get("event") != CURATOR_EVENT:
        return False
    if _repository_name(payload.get("repository")) != repository:
        return False
    if _repository_name(payload.get("head_repository")) != repository:
        return False
    return True
