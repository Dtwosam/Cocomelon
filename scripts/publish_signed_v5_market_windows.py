"""Publish an exact predecessor/current v5 market PnL window after paper handoff.

Runs in a separate read-only Actions workflow. It never edits the paper runtime,
does not silently skip an artifact-bearing predecessor, and cannot promote v5.
"""
from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from scripts.compare_signed_v5_market_windows import (
    V5WindowComparisonError,
    compare,
)

RUN_TITLE = re.compile(r"Continuous Paper · ([1-9][0-9]*)\Z")
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
MAX_JSON_SIZE = 1_000_000
ARTIFACT_PREFIX = "continuous-paper-v5-market-economics-"


class V5WindowPublishError(ValueError):
    """Untrusted handoff identity, artifact metadata, or ZIP contents."""


def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise V5WindowPublishError(f"{name} is not an object")
    return value


def _int(value: object, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise V5WindowPublishError(f"{name} is not a positive integer")
    return value


def _event_target(event: object) -> tuple[int, int, int] | None:
    payload = _mapping(event, "GitHub event")
    if payload.get("action") != "completed":
        return None
    run = _mapping(payload.get("workflow_run"), "GitHub workflow run")
    if run.get("head_branch") != "main" or run.get("status") != "completed":
        return None
    current = _int(run.get("id"), "current run")
    attempt = _int(run.get("run_attempt"), "current attempt")
    title = run.get("display_title")
    if not isinstance(title, str):
        raise V5WindowPublishError("missing exact paper run title")
    match = RUN_TITLE.fullmatch(title)
    if match is None:
        # Bootstrap/scheduled workers do not certify a predecessor.
        return None
    predecessor = int(match.group(1))
    if predecessor == current:
        # On push/schedule GitHub's run-name expression falls back to
        # github.run_id; the resulting *guard-only* run has no predecessor.
        # A successful guard skip can trigger workflow_run subscribers.
        # Treat it as no pair, never as a failed economic observation.
        return None
    if predecessor > current:
        raise V5WindowPublishError("predecessor cannot exceed worker")
    return current, attempt, predecessor


def _artifact(
    payload: object,
    *,
    run_id: int,
    attempt: int,
) -> int | None:
    data = _mapping(payload, "artifact response")
    items = data.get("artifacts")
    if not isinstance(items, list):
        raise V5WindowPublishError("artifact list is not an array")
    count = data.get("total_count")
    if type(count) is not int or count != len(items):
        # Never select the first 100 results and call them exhaustive.
        raise V5WindowPublishError("artifact list incomplete or inconsistent")
    name = f"{ARTIFACT_PREFIX}{run_id}-{attempt}"
    found = [a for a in items if
             isinstance(a, dict) and a.get("name") == name]
    if len(found) > 1:
        raise V5WindowPublishError("duplicate exact signed market artifact")
    if not found:
        return None
    selected = found[0]
    if selected.get("expired") is not False:
        raise V5WindowPublishError("signed market artifact expired")
    return _int(selected.get("id"), "signed market artifact id")


def _archive(raw: bytes) -> dict[str, Any]:
    if len(raw) > 3_000_000:
        raise V5WindowPublishError("signed market zip too large")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            if (
                len(members) != 1
                or members[0].filename != "signed-v5-market-economics.json"
                or members[0].is_dir()
                or members[0].file_size > MAX_JSON_SIZE
            ):
                raise V5WindowPublishError(
                    "signed market zip must contain one bounded exact report"
                )
            with archive.open(members[0]) as file:
                content = file.read(MAX_JSON_SIZE + 1)
        if len(content) > MAX_JSON_SIZE:
            raise V5WindowPublishError("signed market JSON is too large")
        result = json.loads(content.decode("utf-8"))
    except (OSError, zipfile.BadZipFile, UnicodeError, json.JSONDecodeError) as exc:
        raise V5WindowPublishError("invalid signed market zip/JSON") from exc
    return _mapping(result, "signed market report")


def publish(
    event: object,
    repository: str,
    get_json: Callable[[str], object],
    get_zip: Callable[[str], bytes],
) -> tuple[dict[str, object] | None, str]:
    if not REPOSITORY.fullmatch(repository):
        raise V5WindowPublishError("invalid GitHub repository")
    target = _event_target(event)
    if target is None:
        return None, "not an exact completed predecessor-linked paper worker"
    current, attempt, predecessor = target
    prior_meta = _mapping(
        get_json(f"repos/{repository}/actions/runs/{predecessor}"),
        "predecessor workflow run",
    )
    if (
        prior_meta.get("id") != predecessor
        or prior_meta.get("status") != "completed"
        or prior_meta.get("head_branch") != "main"
    ):
        raise V5WindowPublishError("predecessor run identity/status mismatch")
    prior_attempt = _int(prior_meta.get("run_attempt"),
                         "predecessor run attempt")
    current_id = _artifact(
        get_json(f"repos/{repository}/actions/runs/{current}/artifacts?per_page=100"),
        run_id=current, attempt=attempt,
    )
    if current_id is None:
        return None, "current worker has no completed signed market report"
    previous_id = _artifact(
        get_json(
            f"repos/{repository}/actions/runs/{predecessor}/artifacts?per_page=100"
        ),
        run_id=predecessor, attempt=prior_attempt,
    )
    if previous_id is None:
        return None, "exact predecessor lacks a signed market report"
    prior_report = _archive(get_zip(
        f"repos/{repository}/actions/artifacts/{previous_id}/zip"
    ))
    current_report = _archive(get_zip(
        f"repos/{repository}/actions/artifacts/{current_id}/zip"
    ))
    result = compare(prior_report, current_report)
    result["artifact_lineage"] = {
        "current_run_id": current,
        "current_attempt": attempt,
        "current_artifact_id": current_id,
        "predecessor_run_id": predecessor,
        "predecessor_attempt": prior_attempt,
        "predecessor_artifact_id": previous_id,
        "verified_exact_predecessor_run": True,
        "verified_review_ledger_contiguity": False,
    }
    return result, "validated exact-predecessor signed-account market window"


def scheduled_catchup(
    repository: str,
    get_json: Callable[[str], object],
    get_zip: Callable[[str], bytes],
) -> tuple[dict[str, object] | None, str]:
    """Recover a missing workflow_run callback without fabricating checkpoints.

    GitHub caps workflow_run chains at three levels; an hourly, independent
    scheduled workflow must discover the authentic newest 100 paper runs.
    Select the OLDEST eligible exact predecessor pair that is not already
    represented by a retained interval artifact. A missing pair is skipped
    only after exact source artifact discovery returns no usable evidence.
    Never substitute an older signed checkpoint as the predecessor.
    """
    if not REPOSITORY.fullmatch(repository):
        raise V5WindowPublishError("invalid GitHub repository")
    payload = _mapping(
        get_json(
            f"repos/{repository}/actions/workflows/"
            "continuous-paper.yml/runs?per_page=100"
        ),
        "recent paper workflow runs",
    )
    runs = payload.get("workflow_runs")
    if not isinstance(runs, list) or len(runs) > 100:
        raise V5WindowPublishError("invalid bounded paper workflow run list")
    total = payload.get("total_count")
    if type(total) is not int or total < len(runs):
        raise V5WindowPublishError("paper run list total_count mismatch")
    candidates: list[tuple[int, int, dict[str, Any]]] = []
    seen: set[tuple[int, int]] = set()
    for raw in runs:
        run = _mapping(raw, "listed paper run")
        if run.get("path") != ".github/workflows/continuous-paper.yml":
            raise V5WindowPublishError("listed non-paper workflow")
        if run.get("head_branch") != "main" or run.get("status") != "completed":
            continue
        target = _event_target({"action": "completed", "workflow_run": run})
        if target is None:
            continue
        current, attempt, _ = target
        if (current, attempt) in seen:
            raise V5WindowPublishError("duplicate exact completed paper run")
        seen.add((current, attempt))
        candidates.append((current, attempt, run))

    for current, attempt, run in sorted(candidates):
        published_name = f"signed-v5-incremental-market-window-{current}-{attempt}"
        stored = _mapping(
            get_json(
                f"repos/{repository}/actions/artifacts?"
                f"name={published_name}&per_page=100"
            ),
            "published interval artifacts",
        )
        artifacts = stored.get("artifacts")
        count = stored.get("total_count")
        if (
            not isinstance(artifacts, list)
            or type(count) is not int
            or count != len(artifacts)
        ):
            raise V5WindowPublishError(
                "incomplete published interval artifact listing"
            )
        exact = [
            artifact for artifact in artifacts
            if isinstance(artifact, dict)
            and artifact.get("name") == published_name
        ]
        if len(exact) > 1:
            raise V5WindowPublishError("duplicate existing signed interval artifact")
        if exact:
            if exact[0].get("expired") is not False:
                # Expired output is not verified retained evidence; replace
                # only from the same immutable exact signed source pair.
                pass
            else:
                _int(exact[0].get("id"), "existing interval artifact")
                continue
        report, reason = publish(
            {"action": "completed", "workflow_run": run},
            repository, get_json, get_zip,
        )
        if report is not None:
            report["scheduled_catchup"] = {
                "discovery_limit_recent_paper_runs": 100,
                "source_run_id": current,
                "source_run_attempt": attempt,
                "not_review_authority": True,
            }
            return report, (
                "catch-up validated exact signed pair from completed "
                f"worker {current}/{attempt}"
            )
        # No authoritative report for this exact pair. This is not a
        # zero-return observation and cannot be replaced by old market data.
    return None, (
        "no unpublished authentic exact predecessor pair in the "
        "100 most recent paper workers"
    )


def _gh_json(endpoint: str) -> object:
    raw = subprocess.run(
        ["gh", "api", endpoint],
        check=True, capture_output=True, timeout=90,
    ).stdout
    return json.loads(raw)


def _gh_zip(endpoint: str) -> bytes:
    return subprocess.run(
        ["gh", "api", endpoint],
        check=True, capture_output=True, timeout=90,
    ).stdout


def main() -> int:
    repository = os.environ["GITHUB_REPOSITORY"]
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(
        encoding="utf-8"
    ))
    output = Path(os.environ.get(
        "V5_WINDOW_OUTPUT", "signed-v5-incremental-market-window.json"
    ))
    if output.exists():
        raise V5WindowPublishError("refuse stale output path")
    if os.environ.get("GITHUB_EVENT_NAME") == "schedule":
        result, reason = scheduled_catchup(
            repository, _gh_json, _gh_zip,
        )
    else:
        result, reason = publish(event, repository, _gh_json, _gh_zip)
    print(reason)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with Path(summary_path).open("a", encoding="utf-8") as summary:
            summary.write("## Exact consecutive v5 signed market-account economics\n\n")
            summary.write(f"- Status: {reason}\n")
            summary.write("- Research only; original frozen signed review controls "
                          "readiness; no changes to paper orders or capital.\n")
            if result is not None:
                summary.write(
                    "- Challenger minus baseline actual incremental PnL: "
                    f"{result['candidate_minus_baseline_window_pnl']}\n"
                )
                summary.write(
                    "- Original / challenger incremental marked PnL: "
                    f"{result['baseline']['marked_account_pnl_change']} / "
                    f"{result['candidate']['marked_account_pnl_change']}\n"
                )
                summary.write(
                    "- This compares exact predecessor worker reports; "
                    "it does not verify entire review-ledger chain.\n"
                )
    if result is None:
        return 0
    lineage = _mapping(result.get("artifact_lineage"), "exact interval lineage")
    artifact_name = (
        f"signed-v5-incremental-market-window-"
        f"{_int(lineage.get('current_run_id'), 'source worker')}-"
        f"{_int(lineage.get('current_attempt'), 'source attempt')}"
    )
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with Path(github_output).open("a", encoding="utf-8") as handle:
            handle.write(f"artifact_name={artifact_name}\n")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n",
                      encoding="utf-8")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (V5WindowPublishError, V5WindowComparisonError) as exc:
        print(f"FAILED CLOSED: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
