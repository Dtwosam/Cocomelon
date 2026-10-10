"""Select oldest unread exact full-stack paper source for scheduled parity.

Independent of GitHub's workflow_run chain-depth cap. Never choose a worker
based on PnL, filter decisions, or a more convenient historical mismatch.
Only original, completed, post-causal main-branch paper runs are eligible.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

CAUSAL_SOURCE_START = "2026-10-10T18:06:46Z"
WORKFLOW_PATH = ".github/workflows/continuous-paper.yml"
REPORT_PREFIX = "immutable-terminal-source-parity-"


class ScheduledParitySourceError(RuntimeError):
    pass


def eligible_completed_runs(
    payload: object, *, repository: str
) -> tuple[tuple[int, int], ...]:
    if not isinstance(payload, dict) or not isinstance(payload.get("workflow_runs"), list):
        raise ScheduledParitySourceError("completed paper-run listing is invalid")
    candidates: list[tuple[str, int, int]] = []
    seen: set[tuple[int, int]] = set()
    for raw in payload["workflow_runs"]:
        if not isinstance(raw, dict):
            continue
        run_id = raw.get("id")
        attempt = raw.get("run_attempt")
        created = raw.get("created_at")
        if (
            isinstance(run_id, int) and not isinstance(run_id, bool)
            and isinstance(attempt, int) and not isinstance(attempt, bool) and attempt > 0
            and isinstance(created, str) and created >= CAUSAL_SOURCE_START
            and raw.get("path") == WORKFLOW_PATH
            and raw.get("head_branch") == "main"
            and raw.get("status") == "completed"
            and raw.get("conclusion") in {"success", "failure"}
            and isinstance(raw.get("head_repository"), dict)
            and raw["head_repository"].get("full_name") == repository
            and isinstance(raw.get("head_sha"), str)
            and len(raw["head_sha"]) == 40
        ):
            identity = run_id, attempt
            if identity in seen:
                raise ScheduledParitySourceError("repeated completed paper identity")
            seen.add(identity)
            candidates.append((created, run_id, attempt))
    return tuple((id_, attempt) for _, id_, attempt in sorted(candidates))


def select_oldest_unreported(
    completed_runs: object,
    *,
    repository: str,
    fetch_json: Callable[[str], object],
) -> tuple[int, int] | None:
    for run_id, attempt in eligible_completed_runs(completed_runs, repository=repository):
        expected = f"continuous-paper-full-stack-forward-markout-{run_id}-{attempt}"
        artifacts = fetch_json(
            f"repos/{repository}/actions/runs/{run_id}/artifacts?per_page=100"
        )
        if not isinstance(artifacts, dict) or not isinstance(artifacts.get("artifacts"), list):
            raise ScheduledParitySourceError("completed worker artifact listing is invalid")
        source_matches = [
            x for x in artifacts["artifacts"]
            if isinstance(x, dict)
            and x.get("name") == expected
            and x.get("expired") is False
            and isinstance(x.get("id"), int) and not isinstance(x["id"], bool)
            and isinstance(x.get("digest"), str)
            and x["digest"].startswith("sha256:")
        ]
        if len(source_matches) > 1:
            raise ScheduledParitySourceError("duplicate exact source artifact")
        if not source_matches:
            continue
        report_name = f"{REPORT_PREFIX}{run_id}-{attempt}"
        reports = fetch_json(
            f"repos/{repository}/actions/artifacts?name={report_name}&per_page=100"
        )
        if not isinstance(reports, dict) or not isinstance(reports.get("artifacts"), list):
            raise ScheduledParitySourceError("parity audit artifact listing is invalid")
        already = [
            x for x in reports["artifacts"]
            if isinstance(x, dict)
            and x.get("name") == report_name
            and x.get("expired") is False
        ]
        if already:
            continue
        return run_id, attempt
    return None


def _api(path: str) -> object:
    try:
        out = subprocess.run(
            ["gh", "api", path],
            check=True,
            text=True,
            capture_output=True,
        )
        return json.loads(out.stdout)
    except (subprocess.CalledProcessError, OSError, json.JSONDecodeError) as exc:
        raise ScheduledParitySourceError("GitHub parity source listing unavailable") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only causal parity source catch-up")
    parser.add_argument("--repository", required=True)
    args = parser.parse_args()
    repo = args.repository
    if (
        not isinstance(repo, str)
        or repo.count("/") != 1
        or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_/" for ch in repo)
    ):
        raise SystemExit("invalid repository identity")
    try:
        runs = _api(
            f"repos/{repo}/actions/workflows/continuous-paper.yml/runs?"
            "branch=main&status=completed&per_page=100"
        )
        selected = select_oldest_unreported(runs, repository=repo, fetch_json=_api)
    except ScheduledParitySourceError as exc:
        raise SystemExit(str(exc)) from exc
    if selected is not None:
        print(f"{selected[0]}\t{selected[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
