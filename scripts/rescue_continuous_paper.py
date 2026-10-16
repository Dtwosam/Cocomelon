"""Fail-closed, independent recovery of the exact continuous paper account.

This is a control-plane liveness check, not a strategy or execution entrypoint.
It never changes paper positions or authorizes live trading.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

WORKFLOW_PATH = ".github/workflows/continuous-paper.yml"
TRADER_STEP = "Run continuous paper trader"
FAST_UPLOAD_STEP = "Upload fast continuous paper resume state"
DURABLE_UPLOAD_STEP = "Upload durable continuous paper state"
LIVE_STATUS_ISSUE = "469"
HEARTBEAT_STALE_SECONDS = 15 * 60
HEARTBEAT_FUTURE_ALLOWANCE_SECONDS = 120


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
            # A speculative push/scheduled workflow can be cancelled or
            # fail during workflow admission without materializing ANY job.
            # It has not run a trader and does not own an account state.
            # A run with any jobs, a pending/in-progress run, or an exact
            # workflow_dispatch remains fail-closed.
            if (
                not jobs
                and status == "completed"
                and run.get("event") in {"push", "schedule"}
                and run.get("conclusion") in {"cancelled", "failure", "skipped"}
            ):
                continue
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
            attempt = run.get("run_attempt")
            if (
                isinstance(attempt, bool) or not isinstance(attempt, int)
                or attempt <= 0
            ):
                raise PaperRescueError("invalid active paper run attempt")
            return "active", (run_id, attempt)
        if trader.get("status") != "completed":
            return "blocked", None
        if trader.get("conclusion") == "skipped":
            continue
        trader_conclusion = trader.get("conclusion")
        if trader_conclusion not in {"success", "failure"}:
            return "blocked", None
        # A failed trader is NOT automatically resumable: its last good
        # heartbeat or a predecessor archive could omit newer paper writes.
        # Only a successfully measured, post-exit packed and uploaded exact
        # terminal fast snapshot is eligible for an attempted restore.
        # The successor's normal journal/account restore checks remain
        # authoritative; returning ready never certifies its economics.
        if trader_conclusion == "failure" and not all((
            _step_succeeded(job, "Measure durable continuous paper state"),
            _step_succeeded(job, "Pack fast continuous paper resume state"),
            _step_succeeded(job, FAST_UPLOAD_STEP),
        )):
            return "blocked", None
        if status == "completed" and run.get("conclusion") not in {
            "success", "failure", "cancelled"
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
        fast_ready = _step_succeeded(job, FAST_UPLOAD_STEP) and fast_name in names
        if status == "completed" and run.get("conclusion") == "cancelled":
            # The observed Oct 13 worker was cancelled during a deferred
            # research tail, AFTER its exact terminal fast archive existed.
            # Never interpret cancellation itself as evidence of a snapshot.
            # Require the actual trader to have finished and all terminal
            # custody steps to have succeeded for this exact run/attempt.
            matching_fast = [
                item for item in artifacts
                if isinstance(item, dict)
                and item.get("name") == fast_name
                and item.get("expired") is False
            ]
            verified_fast = [
                item for item in matching_fast
                if type(item.get("size_in_bytes")) is int
                and item["size_in_bytes"] > 0
                and isinstance(item.get("digest"), str)
                and re.fullmatch(r"sha256:[0-9a-f]{64}", item["digest"])
            ]
            if (
                fast_ready and len(matching_fast) == len(verified_fast) == 1
                and all(_step_succeeded(job, step) for step in (
                    "Measure durable continuous paper state",
                    "Pack fast continuous paper resume state",
                    FAST_UPLOAD_STEP,
                ))
            ):
                return "ready", (run_id, attempt)
            return "blocked", None
        durable_ready = (
            _step_succeeded(job, DURABLE_UPLOAD_STEP)
            and durable_name in names
        )
        if trader_conclusion == "failure":
            # No durable-only failover from a failed trader: the independently
            # observable terminal fast pack is required and must be exact.
            if fast_ready:
                return "ready", (run_id, attempt)
        elif fast_ready or durable_ready:
            return "ready", (run_id, attempt)
        return "blocked", None
    return "no_source", None


def find_new_exact_successor(
    runs: list[dict[str, Any]],
    *,
    repository: str,
    source_run_id: int,
    previously_seen_ids: frozenset[int],
) -> int | None:
    """Confirm dispatch materialized, not that its trader has run.

    An old or guard-skipped run with the same title is NOT a new receipt.
    Only a newly seen GitHub workflow_dispatch for this exact predecessor
    can explain this invocation's accepted dispatch response.
    """
    if type(source_run_id) is not int or source_run_id <= 0:
        raise PaperRescueError("invalid exact paper predecessor run ID")
    matches = []
    for run in runs:
        if not isinstance(run, dict):
            raise PaperRescueError("malformed exact successor run listing")
        run_id = run.get("id")
        if (
            run.get("display_title") == f"Continuous Paper · {source_run_id}"
            and run.get("event") == "workflow_dispatch"
            and run.get("path") == WORKFLOW_PATH
            and run.get("head_branch") == "main"
            and (run.get("head_repository") or {}).get("full_name")
            == repository
        ):
            if type(run_id) is not int or run_id <= source_run_id:
                raise PaperRescueError("invalid materialized exact successor ID")
            if run_id not in previously_seen_ids:
                matches.append(run_id)
    if len(matches) > 1:
        raise PaperRescueError("multiple new exact successor dispatches detected")
    return matches[0] if matches else None


def verify_active_heartbeat(
    body: object,
    *,
    active_run_id: int,
    run_started_at: object,
    now: datetime,
) -> str:
    """Observe the exact running paper trader without granting a new lease.

    This is a reporting guard ONLY. A stale heartbeat must never be
    interpreted as authority to dispatch another trader over open positions.
    """
    if now.tzinfo is None:
        raise PaperRescueError("heartbeat clock must have timezone")
    if type(active_run_id) is not int or active_run_id <= 0:
        raise PaperRescueError("active paper run identity invalid")
    if not isinstance(body, str):
        raise PaperRescueError("live status issue body missing")
    if not isinstance(run_started_at, str):
        raise PaperRescueError("active run start timestamp missing")
    try:
        started = datetime.fromisoformat(
            run_started_at.replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise PaperRescueError("invalid paper run start timestamp") from exc
    if started.tzinfo is None:
        raise PaperRescueError("paper run start timestamp lacks timezone")
    start_age = (now - started).total_seconds()
    if start_age < -HEARTBEAT_FUTURE_ALLOWANCE_SECONDS:
        raise PaperRescueError("paper run start is future-dated")
    run_match = re.search(r"(?m)^Worker run:\s*(\d+)\s*$", body)
    updated_match = re.search(r"(?m)^Updated:\s*(\S+)\s*$", body)
    worker_id = int(run_match.group(1)) if run_match else None
    if worker_id != active_run_id:
        if 0 <= start_age <= HEARTBEAT_STALE_SECONDS:
            return "startup_grace"
        raise PaperRescueError(
            f"active trader {active_run_id} has no current heartbeat; "
            f"issue still describes worker {worker_id}"
        )
    if updated_match is None:
        raise PaperRescueError("active worker heartbeat timestamp missing")
    try:
        updated = datetime.fromisoformat(
            updated_match.group(1).replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise PaperRescueError("invalid active heartbeat timestamp") from exc
    if updated.tzinfo is None:
        raise PaperRescueError("active heartbeat has no timezone")
    age = (now - updated).total_seconds()
    if (
        age < -HEARTBEAT_FUTURE_ALLOWANCE_SECONDS
        or age > HEARTBEAT_STALE_SECONDS
        or (started - updated).total_seconds()
        > HEARTBEAT_FUTURE_ALLOWANCE_SECONDS
    ):
        raise PaperRescueError(
            f"active trader {active_run_id} heartbeat stale or "
            f"future-dated: age_seconds={age:.1f}"
        )
    return "fresh"


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
        if source is None:
            raise PaperRescueError("active paper trader identity missing")
        run_id, _attempt = source
        active_run = next(
            (run for run in runs if run.get("id") == run_id),
            None,
        )
        if active_run is None:
            raise PaperRescueError("active paper run absent from source listing")
        issue = _gh_json(
            f"repos/{repository}/issues/{LIVE_STATUS_ISSUE}"
        )
        health = verify_active_heartbeat(
            issue.get("body"),
            active_run_id=run_id,
            run_started_at=active_run.get("run_started_at"),
            now=datetime.now(UTC),
        )
        print(
            f"Active paper trader {run_id} heartbeat={health}; "
            "no overlapping rescue dispatch."
        )
        return 0
    if status == "queued_exact":
        print("Exact successor already queued; no duplicate rescue dispatch.")
        return 0
    if status != "ready" or source is None:
        # Fail visibly instead of reporting green liveness when account
        # continuity cannot be proved from exact artifacts.
        raise PaperRescueError(f"Paper trader unverified; recovery {status}")
    run_id, attempt = source
    # Close the observation-to-dispatch race before mutating GitHub. A
    # scheduled watchdog and a just-published exact dispatch must never
    # both take ownership of the same PAPER snapshot.
    latest_runs = _collection(
        f"repos/{repository}/actions/workflows/continuous-paper.yml/runs?per_page=100",
        "workflow_runs",
    )
    latest_status, latest_source = choose_exact_source(
        latest_runs,
        repository=repository,
        get_jobs=lambda candidate: _collection(
            f"repos/{repository}/actions/runs/{candidate}/jobs?per_page=100",
            "jobs",
        ),
        get_artifacts=lambda candidate: _collection(
            f"repos/{repository}/actions/runs/{candidate}/artifacts?per_page=100",
            "artifacts",
        ),
    )
    if latest_status != "ready" or latest_source != source:
        if latest_status in {"active", "queued_exact"}:
            print(
                "PAPER lease taken by another actual or queued exact worker; "
                f"current_state={latest_status}. No duplicate dispatch."
            )
            return 0
        # Missing/blocked/newer unverified worker is NOT a green recovery.
        # It must appear as an operational failure for human diagnosis.
        raise PaperRescueError(
            "PAPER lease changed to unverifiable exact state before "
            f"dispatch: {latest_status}; no stale-state rescue"
        )

    dispatch_path = f"repos/{repository}/actions/runs?event=workflow_dispatch&per_page=100"
    baseline = _collection(dispatch_path, "workflow_runs")
    prior_ids = frozenset(
        row["id"] for row in baseline
        if type(row.get("id")) is int
    )
    subprocess.run(
        [
            "gh", "workflow", "run", "continuous-paper.yml", "--ref", "main",
            "-f", f"source_run_id={run_id}",
            "-f", f"source_run_attempt={attempt}",
        ],
        check=True,
        timeout=45,
    )
    # A successful gh command is NOT evidence that GitHub created a new
    # workflow run, much less that the trader actually restored its state.
    for poll in range(12):
        observed = _collection(dispatch_path, "workflow_runs")
        successor = find_new_exact_successor(
            observed,
            repository=repository,
            source_run_id=run_id,
            previously_seen_ids=prior_ids,
        )
        if successor is not None:
            print(
                f"Exact PAPER dispatch materialized: run={successor}; "
                f"source_run_id={run_id} source_run_attempt={attempt}. "
                "Trader start, authenticated heartbeat, and continuity "
                "are NOT YET VERIFIED."
            )
            return 0
        if poll < 11:
            time.sleep(5)
    raise PaperRescueError(
        "GitHub accepted exact PAPER dispatch but no NEW successor run "
        "materialized during bounded verification; trading unverified"
    )


if __name__ == "__main__":
    raise SystemExit(main())
