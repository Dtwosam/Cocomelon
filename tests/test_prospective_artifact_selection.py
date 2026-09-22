from __future__ import annotations

import pytest

from cocomelon.research.prospective_artifact_selection import (
    ProspectiveArtifactSelectionError,
    select_state_artifact_for_health,
)


def _artifact(
    artifact_id: int,
    *,
    name: str,
    created_at: str,
    run_id: int = 35721665228,
    expired: bool = False,
) -> dict[str, object]:
    return {
        "id": artifact_id,
        "name": name,
        "created_at": created_at,
        "expired": expired,
        "workflow_run": {
            "id": run_id,
            "head_branch": "main",
        },
    }


def test_selects_latest_state_preceding_latest_rerun_health() -> None:
    artifacts = [
        _artifact(
            10691392286,
            name="prospective-hype-clean-state",
            created_at="2026-09-22T11:29:02Z",
        ),
        _artifact(
            10691747039,
            name="prospective-hype-clean-health-35721665228-1",
            created_at="2026-09-22T11:29:06Z",
        ),
        _artifact(
            10697590747,
            name="prospective-hype-clean-state",
            created_at="2026-09-22T13:43:58Z",
        ),
        _artifact(
            10697206107,
            name="prospective-hype-clean-health-35721665228-2",
            created_at="2026-09-22T13:44:02Z",
        ),
    ]
    health = artifacts[-1]

    assert (
        select_state_artifact_for_health(artifacts, health)
        == "10697590747"
    )


def test_rejects_state_from_other_run_even_when_newer() -> None:
    health = _artifact(
        10,
        name="prospective-hype-clean-health-35721665228-2",
        created_at="2026-09-22T13:44:02Z",
    )
    artifacts = [
        _artifact(
            11,
            name="prospective-hype-clean-state",
            created_at="2026-09-22T13:44:01Z",
            run_id=999,
        ),
    ]

    with pytest.raises(
        ProspectiveArtifactSelectionError,
        match="STATE_ARTIFACT_MATCH_INVALID",
    ):
        select_state_artifact_for_health(artifacts, health)


def test_rejects_state_too_far_before_health() -> None:
    health = _artifact(
        20,
        name="prospective-hype-clean-health-35721665228-2",
        created_at="2026-09-22T13:44:02Z",
    )
    artifacts = [
        _artifact(
            21,
            name="prospective-hype-clean-state",
            created_at="2026-09-22T13:20:00Z",
        ),
    ]

    with pytest.raises(
        ProspectiveArtifactSelectionError,
        match="STATE_ARTIFACT_MATCH_INVALID",
    ):
        select_state_artifact_for_health(artifacts, health)


def test_rejects_health_name_that_does_not_bind_workflow_run() -> None:
    health = _artifact(
        30,
        name="prospective-hype-clean-health-999-2",
        created_at="2026-09-22T13:44:02Z",
    )

    with pytest.raises(
        ProspectiveArtifactSelectionError,
        match="HEALTH_ARTIFACT_IDENTITY_INVALID",
    ):
        select_state_artifact_for_health([], health)
