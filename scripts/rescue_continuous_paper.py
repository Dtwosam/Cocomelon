"""Fail-closed, independent recovery of the exact continuous paper account.

This is a control-plane liveness check, not a strategy or execution entrypoint.
It never changes paper positions or authorizes live trading.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from typing import Any

WORKFLOW_PATH = ".github/workflows/continuous-paper.yml"
TRADER_STEP = "Run continuous paper trader"
FAST_UPLOAD_STEP = "Upload fast continuous paper resume state"
DURABLE_UPLOAD_STEP = "Upload durable continuous paper state"


class PaperRescueError(RuntimeError):
    """Refuse to infer state or liveness from incomplete GitHub evidence."""


def _step(job: dict[str, Any], name: str) -> dict[str, Any] | None:
    for step in job.get("steps", []):
        if isinstance(step, dict) and step.get("name") == name:
            return step
    return None


def _step_succeeded(job: dict[str, Any], name: str) -> bool:
    step = _step(job, name)
    return (
        step is not None
        and step.get("status") == "completed"
        and step.get("conclusion") == "success"
    )


def choose_exact_source(
    runs: list[dict[str, Any]],
    *,
    repository: str,
    get_jobs: Callable[[int], list[dict[str, Any]]],
    get_artifacts: Callable[[int], list[dict[str, Any]]],
) -> tuple[str, tuple[int, int] | None]:
    """Prefer running trader safety, then latest provably archived trader.

    queued push/schedule jobs are speculative and cannot hold a worker lease.
    queued exact dispatches *are* honored to avoid duplicate dispatches.
    Returns (active|queued_exact|ready|blocked|no_source, exact_run_attempt).
    """
    if not repository or not isinstance(runs, list):
        raise PaperRescueError("repository or workflow-run listing missing")
    for run in sorted(runs, key=lambda row: row.get("id", 0), reverse=True):
        if not isinstance(run, dict):
            raise PaperRescueError("malformed workflow-run record")
        if (
            run.get("path") != WORKFLOW_PATH
            or run.get("head_branch") != "main"
            or (run.get("head_repository") or {}).get("full_name") != repository
        ):
            continue
        run_id = run.get("id")
        if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id <= 0:
            raise PaperRescueError("invalid paper run id")
        status = run.get("status")
        if status in {"queued", "pending"}:
            if run.get("event") in {"push", "schedule"}:
                continue
            return "queued_exact", None
        if status not in {"in_progress", "completed"}:
            return "blocked", None
        jobs = get_jobs(run_id)
        if not isinstance(jobs, list):
            raise PaperRescueError("missing paper jobs")
        paper_jobs = [
            job
            for job in jobs
            if isinstance(job, dict) and job.get("name") == "paper"
        ]
        if len(paper_jobs) != 1:
            return "blocked", None
        job = paper_jobs[0]
        # A successful guard-only run has no trader. Do not confuse its green
        # workflow conclusion with actual execution or a safe state archive.
        checkout = _step(job, "Run actions/checkout@v7")
        if checkout is not None and checkout.get("conclusion") == "skipped":
            continue
        trader = _step(job, TRADER_STEP)
        if trader is None:
            return "blocked", None
        if trader.get("status") in {"queued", "pending", "in_progress"}:
            return "active", None
        if trader.get("status") != "completed":
            return "blocked", None
        if trader.get("conclusion") == "skipped":
            continue
        if trader.get("conclusion") != "success":
            # A crashed worker may have changed the account without having
            # archived its final state. Never roll back to older history.
            return "blocked", None
        if status == "completed" and run.get("conclusion") not in {
            "success", "failure"
        }:
            return "blocked", None
        attempt = run.get("run_attempt")
        if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt <= 0:
            raise PaperRescueError("invalid exact run attempt")
        artifacts = get_artifacts(run_id)
        if not isinstance(artifacts, list):
            raise PaperRescueError("missing exact paper artifacts")
        names = {
            item.get("name")
            for item in artifacts
            if isinstance(item, dict)
            and item.get("expired") is False
            and isinstance(item.get("name"), str)
        }
        fast_name = f"continuous-paper-resume-{run_id}-{attempt}"
        durable_name = f"continuous-paper-state-{run_id}-{attempt}"
        if (
            _step_succeeded(job, FAST_UPLOAD_STEP)
            and fast_name in names
        ) or (
            _step_succeeded(job, DURABLE_UPLOAD_STEP)
            and durable_name in names
        ):
            return "ready", (run_id, attempt)
        return "blocked", None
    return "no_source", None


def _gh_json(resource: str) -> dict[str, Any]:
    result = subprocess.run(
        ["gh", "api", resource],
        check=True,
        capture_output=True,
        text=True,
        timeout=45,
    )
    data = json.loads(result.stdout)
    if not isinstance(data, dict):
        raise PaperRescueError("GitHub API returned a non-object")
    return data


def _collection(resource: str, name: str) -> list[dict[str, Any]]:
    data = _gh_json(resource)
    rows = data.get(name)
    if not isinstance(rows, list):
        raise PaperRescueError(f"missing GitHub collection {name}")
    return rows


def main() -> int:
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    if not repository or "/" not in repository:
        raise PaperRescueError("GITHUB_REPOSITORY is required")
    runs = _collection(
        f"repos/{repository}/actions/workflows/continuous-paper.yml/runs?per_page=100",
        "workflow_runs",
    )
    status, source = choose_exact_source(
        runs,
        repository=repository,
        get_jobs=lambda run_id: _collection(
            f"repos/{repository}/actions/runs/{run_id}/jobs?per_page=100",
            "jobs",
        ),
        get_artifacts=lambda run_id: _collection(
            f"repos/{repository}/actions/runs/{run_id}/artifacts?per_page=100",
            "artifacts",
        ),
    )
    if status == "active":
        print("Active paper trader confirmed; no rescue dispatch.")
        return 0
    if status == "queued_exact":
        print("Exact successor already queued; no duplicate rescue dispatch.")
        return 0
    if status != "ready" or source is None:
        # Fail visibly instead of reporting green liveness when account
        # continuity cannot be proved from exact artifacts.
        raise PaperRescueError(f"Paper trader unverified; recovery {status}")
    run_id, attempt = source
    subprocess.run(
        [
            "gh", "workflow", "run", "continuous-paper.yml", "--ref", "main",
            "-f", f"source_run_id={run_id}",
            "-f", f"source_run_attempt={attempt}",
        ],
        check=True,
        timeout=45,
    )
    print(
        f"Exact paper successor dispatch accepted: "
        f"source_run_id={run_id} source_run_attempt={attempt}. "
        "Confirm its actual trader step and heartbeat separately."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
