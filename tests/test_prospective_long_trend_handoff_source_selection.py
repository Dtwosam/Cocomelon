"""Exercise the exact paper-source admission script used by both LONG horizons."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(".github/workflows")
REPO = "Dtwosam/Cocomelon"


def _admission_python(horizon: str) -> str:
    source = (ROOT / f"prospective-long-trend-{horizon}-exact.yml").read_text(
        encoding="utf-8"
    )
    start = (
        '            python - "$run_path" "$jobs_path" "$candidate_attempt" '
        '"$GITHUB_REPOSITORY" <<\'PY\'\n'
    )
    assert source.count(start) == 1
    script = source.split(start, 1)[1].split("\n          PY\n", 1)[0]
    return "\n".join(line.removeprefix("          ") for line in script.splitlines())


def _run_case(
    tmp_path: Path,
    horizon: str,
    status: str,
    step_overrides: dict[str, str],
    *,
    correct_identity: bool = True,
    paper_status: str | None = None,
    conclusion: str | None = None,
) -> subprocess.CompletedProcess[str]:
    steps = {
        "Run continuous paper trader": "success",
        "Measure durable continuous paper state": "success",
        "Upload durable continuous paper state": "success",
        "Queue exact successor from fast resume": "success",
        "Upload compact exact LONG trend research source": "success",
    }
    steps.update(step_overrides)
    run = {
        "path": ".github/workflows/continuous-paper.yml",
        "head_branch": "main",
        "head_repository": {"full_name": REPO if correct_identity else "untrusted/repo"},
        "run_attempt": 1,
        "status": status,
        "conclusion": conclusion if status == "in_progress" else (conclusion or "success"),
    }
    job = {
        "name": "paper",
        "status": paper_status or ("in_progress" if status == "in_progress" else "completed"),
        "conclusion": None if status == "in_progress" else run["conclusion"],
        "steps": [
            {"name": name, "conclusion": value} for name, value in steps.items()
        ],
    }
    run_path = tmp_path / f"run-{horizon}.json"
    jobs_path = tmp_path / f"jobs-{horizon}.json"
    run_path.write_text(json.dumps(run), encoding="utf-8")
    jobs_path.write_text(json.dumps({"jobs": [job]}), encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            "-c",
            _admission_python(horizon),
            str(run_path),
            str(jobs_path),
            "1",
            REPO,
        ],
        check=False,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("horizon", ["5m", "15m"])
def test_authenticated_post_handoff_running_paper_source_is_allowed(
    tmp_path: Path, horizon: str
) -> None:
    result = _run_case(tmp_path, horizon, "in_progress", {})
    assert result.returncode == 0, result.stderr
    source = (ROOT / f"prospective-long-trend-{horizon}-exact.yml").read_text(
        encoding="utf-8"
    )
    assert "branch=main&per_page=100" in source
    assert 'run.get("status") in {"completed", "in_progress"}' in source
    assert "source run status is not evidence-eligible" in source
    assert "sha256sum" in source


@pytest.mark.parametrize("horizon", ["5m", "15m"])
@pytest.mark.parametrize(
    "overrides",
    [
        {"Run continuous paper trader": "in_progress"},
        {"Measure durable continuous paper state": "pending"},
        {"Upload durable continuous paper state": "failure"},
        {"Queue exact successor from fast resume": "pending"},
        {"Upload compact exact LONG trend research source": "pending"},
        {"Upload compact exact LONG trend research source": "failure"},
    ],
)
def test_no_in_progress_source_before_authenticated_handoff(
    tmp_path: Path, horizon: str, overrides: dict[str, str]
) -> None:
    result = _run_case(tmp_path, horizon, "in_progress", overrides)
    assert result.returncode != 0


@pytest.mark.parametrize("horizon", ["5m", "15m"])
def test_durable_successful_fallback_dispatch_allows_finished_trader(
    tmp_path: Path, horizon: str
) -> None:
    result = _run_case(
        tmp_path,
        horizon,
        "in_progress",
        {
            "Queue exact successor from fast resume": "skipped",
            "Queue fallback exact successor continuous paper worker": "success",
        },
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("horizon", ["5m", "15m"])
def test_unauthorized_repo_or_job_state_is_rejected(
    tmp_path: Path, horizon: str
) -> None:
    assert _run_case(
        tmp_path, horizon, "in_progress", {}, correct_identity=False
    ).returncode != 0
    assert _run_case(
        tmp_path, horizon, "in_progress", {}, paper_status="queued"
    ).returncode != 0
    assert _run_case(
        tmp_path, horizon, "in_progress", {}, conclusion="success"
    ).returncode != 0


@pytest.mark.parametrize("horizon", ["5m", "15m"])
def test_existing_completed_success_keeps_legacy_compatibility(
    tmp_path: Path, horizon: str
) -> None:
    assert _run_case(
        tmp_path, horizon, "completed", {}, conclusion="success"
    ).returncode == 0
    assert _run_case(
        tmp_path, horizon, "queued", {}
    ).returncode != 0
