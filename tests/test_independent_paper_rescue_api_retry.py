"""Fail-closed paper watchdog API retry must never manufacture a free lease."""
from __future__ import annotations

import subprocess

import pytest

import scripts.rescue_continuous_paper as rescue


def test_transient_control_plane_error_retries_without_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[tuple[str, ...]] = []
    sleeps: list[int] = []

    def fake_run(
        cmd: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        attempts.append(tuple(cmd))
        assert cmd[0:2] == ["gh", "api"]
        assert kwargs == {
            "check": True, "capture_output": True, "text": True, "timeout": 45,
        }
        if len(attempts) < 3:
            raise subprocess.CalledProcessError(
                1, cmd, stderr="temporary GitHub API outage"
            )
        return subprocess.CompletedProcess(
            cmd, 0, stdout='{"workflow_runs":[]}'
        )

    monkeypatch.setattr(rescue.subprocess, "run", fake_run)
    monkeypatch.setattr(rescue.time, "sleep", sleeps.append)
    result = rescue._gh_json(
        "repos/Dtwosam/Cocomelon/actions/workflows/continuous-paper.yml/runs"
    )
    assert result == {"workflow_runs": []}
    assert len(attempts) == 3
    assert len(set(attempts)) == 1
    assert sleeps == [2, 5]
    assert all(cmd[1] == "api" for cmd in attempts)


@pytest.mark.parametrize("error_kind", ["cli", "timeout"])
def test_persistent_api_failures_never_claim_paper_state(
    monkeypatch: pytest.MonkeyPatch, error_kind: str,
) -> None:
    calls = 0
    sleeps: list[int] = []

    def fake_run(
        cmd: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        if error_kind == "timeout":
            raise subprocess.TimeoutExpired(cmd, timeout=45)
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(rescue.subprocess, "run", fake_run)
    monkeypatch.setattr(rescue.time, "sleep", sleeps.append)
    with pytest.raises(rescue.PaperRescueError, match="outcome unverified"):
        rescue._gh_json("repos/Dtwosam/Cocomelon/actions/runs")
    assert calls == 4
    assert sleeps == [2, 5, 10]


def test_malformed_successful_api_response_does_not_retry_into_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    sleeps: list[int] = []

    def fake_run(
        cmd: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(cmd, 0, stdout="[]")

    monkeypatch.setattr(rescue.subprocess, "run", fake_run)
    monkeypatch.setattr(rescue.time, "sleep", sleeps.append)
    with pytest.raises(rescue.PaperRescueError, match="non-object"):
        rescue._gh_json("repos/Dtwosam/Cocomelon/actions/runs")
    assert calls == 1
    assert sleeps == []
