from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

JsonObject = dict[str, object]

_CAMPAIGN_NAME = "Scheduled Genuine Mainnet Evidence Campaign V3"
_CAMPAIGN_PATH = ".github/workflows/evidence-campaign-scheduled.yml"
_SCHEDULE_HOURS = (1, 7, 13, 19)
_SCHEDULE_MINUTE = 37
_SCHEDULE_GRACE = timedelta(minutes=90)
_ACTIVATION_LEAD = timedelta(hours=1)


def _parse_time(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"{label} timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError(f"{label} timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise RuntimeError(f"{label} timestamp is not timezone-aware")
    return parsed.astimezone(UTC)


def _slots_around(now: datetime) -> list[datetime]:
    current = now.astimezone(UTC)
    slots: list[datetime] = []
    for offset in (-1, 0, 1):
        day = (current + timedelta(days=offset)).date()
        for hour in _SCHEDULE_HOURS:
            slots.append(
                datetime(
                    day.year,
                    day.month,
                    day.day,
                    hour,
                    _SCHEDULE_MINUTE,
                    tzinfo=UTC,
                )
            )
    return sorted(slots)


def _slot_label(slot: datetime) -> str:
    return slot.astimezone(UTC).strftime("%H:%M UTC")


def _scheduler_health(
    now: datetime,
    latest_scheduled: JsonObject | None,
    workflow_updated: datetime,
) -> str:
    current = now.astimezone(UTC)
    updated = workflow_updated.astimezone(UTC)
    slots = _slots_around(current)
    previous = max(slot for slot in slots if slot <= current)
    following = min(slot for slot in slots if slot > current)

    if previous <= updated or previous - updated < _ACTIVATION_LEAD:
        return f"activation pending — next configured slot {_slot_label(following)}"

    latest_time = None
    if latest_scheduled is not None:
        latest_time = _parse_time(latest_scheduled.get("created_at"), "scheduled run")

    if latest_time is not None and latest_time >= previous:
        return "healthy — latest configured slot observed"

    if latest_time is not None and updated < latest_time < previous:
        return f"drift — latest scheduled run preceded {_slot_label(previous)}"

    if current <= previous + _SCHEDULE_GRACE:
        return f"within scheduling grace — {_slot_label(previous)} slot pending"

    return f"stale — configured {_slot_label(previous)} slot not observed"


def _gh_value(repo: str, endpoint: str) -> object:
    result = subprocess.run(
        ["gh", "api", f"repos/{repo}/{endpoint}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _repository_name(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    full_name = value.get("full_name")
    return full_name if isinstance(full_name, str) and full_name else None


def _latest_scheduled_run(repo: str) -> JsonObject | None:
    payload = _gh_value(repo, "actions/runs?event=schedule&per_page=100")
    if not isinstance(payload, dict):
        raise RuntimeError("scheduled workflow run response is invalid")
    raw = payload.get("workflow_runs")
    if not isinstance(raw, list):
        raise RuntimeError("scheduled workflow run list is invalid")
    matches = [
        item
        for item in raw
        if isinstance(item, dict)
        and item.get("name") == _CAMPAIGN_NAME
        and item.get("path") == _CAMPAIGN_PATH
        and item.get("event") == "schedule"
        and _repository_name(item.get("repository")) == repo
        and _repository_name(item.get("head_repository")) == repo
    ]
    if not matches:
        return None
    return max(matches, key=lambda item: str(item.get("created_at", "")))


def _workflow_updated(repo: str) -> datetime:
    payload = _gh_value(
        repo,
        f"commits?sha=main&path={_CAMPAIGN_PATH}&per_page=1",
    )
    if not isinstance(payload, list) or len(payload) != 1:
        raise RuntimeError("campaign workflow commit history is invalid")
    commit = payload[0]
    if not isinstance(commit, dict):
        raise RuntimeError("campaign workflow commit is invalid")
    metadata = commit.get("commit")
    if not isinstance(metadata, dict):
        raise RuntimeError("campaign workflow commit metadata is invalid")
    committer = metadata.get("committer")
    author = metadata.get("author")
    preferred = committer if isinstance(committer, dict) else author
    if not isinstance(preferred, dict):
        raise RuntimeError("campaign workflow commit timestamp metadata is invalid")
    return _parse_time(preferred.get("date"), "campaign workflow commit")


def _apply_scheduler_health(patch: JsonObject, summary: str) -> JsonObject:
    body = patch.get("body")
    if not isinstance(body, str):
        raise RuntimeError("dashboard patch body is invalid")
    prefix = "- V3 scheduler health: **"
    replacement = f"{prefix}{summary}**"
    lines = body.splitlines()
    existing = [index for index, line in enumerate(lines) if line.startswith(prefix)]
    if len(existing) > 1:
        raise RuntimeError("dashboard has duplicate V3 scheduler health lines")
    if existing:
        lines[existing[0]] = replacement
    else:
        campaign_prefix = "- Latest Campaign V3: **"
        campaign_lines = [
            index for index, line in enumerate(lines) if line.startswith(campaign_prefix)
        ]
        if len(campaign_lines) != 1:
            raise RuntimeError("dashboard must contain exactly one V3 campaign line")
        lines.insert(campaign_lines[0] + 1, replacement)
    return {**patch, "body": "\n".join(lines)}


def _read_patch(path: Path) -> JsonObject:
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("dashboard patch is invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("dashboard patch must be an object")
    return {str(key): value for key, value in payload.items()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--patch", required=True)
    args = parser.parse_args()

    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not repo or "/" not in repo:
        raise RuntimeError("GITHUB_REPOSITORY is invalid")

    patch_path = Path(args.patch).resolve()
    patch = _read_patch(patch_path)
    summary = _scheduler_health(
        datetime.now(UTC),
        _latest_scheduled_run(repo),
        _workflow_updated(repo),
    )
    updated = _apply_scheduler_health(patch, summary)
    patch_path.write_text(
        json.dumps(updated, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
