from __future__ import annotations

import argparse
import json
import os
import subprocess
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import PurePosixPath
from typing import Any

CURATOR_NAME = "Verified V2 Mainnet Evidence Corpus Curator"
CURATOR_PATH = ".github/workflows/evidence-corpus-curator.yml"
CAMPAIGN_NAME = "Scheduled Genuine Mainnet Evidence Campaign V2"
CAMPAIGN_PATH = ".github/workflows/evidence-campaign-scheduled.yml"
CORPUS_ARTIFACT_NAME = "v2-mainnet-corpus"

JsonObject = dict[str, Any]


def _gh_json(endpoint: str) -> JsonObject:
    result = subprocess.run(
        ["gh", "api", endpoint],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict):
        raise RuntimeError(f"GitHub API response is not an object: {endpoint}")
    return payload


def _gh_bytes(endpoint: str) -> bytes:
    result = subprocess.run(
        ["gh", "api", endpoint],
        check=True,
        capture_output=True,
    )
    return result.stdout


def _latest_run(
    payload: JsonObject,
    *,
    name: str,
    path: str,
    completed_only: bool = False,
) -> JsonObject:
    raw_runs = payload.get("workflow_runs", [])
    if not isinstance(raw_runs, list):
        raise RuntimeError("workflow_runs is invalid")
    matches = [
        item
        for item in raw_runs
        if isinstance(item, dict)
        and item.get("name") == name
        and item.get("path") == path
        and (not completed_only or item.get("status") == "completed")
    ]
    if not matches:
        raise RuntimeError(f"No matching workflow run is available: {name}")
    return max(matches, key=lambda item: str(item.get("created_at", "")))


def _assert_trusted_curator(run: JsonObject) -> None:
    if run.get("name") != CURATOR_NAME:
        raise RuntimeError("unexpected curator workflow name")
    if run.get("path") != CURATOR_PATH:
        raise RuntimeError("unexpected curator workflow path")
    if run.get("status") != "completed":
        raise RuntimeError("curator workflow is not complete")


def _resolve_curator_run(repo: str) -> JsonObject:
    event_run_id = os.environ.get("EVENT_CURATOR_RUN_ID", "").strip()
    if event_run_id and event_run_id != "null":
        run = _gh_json(f"repos/{repo}/actions/runs/{int(event_run_id)}")
    else:
        runs = _gh_json(f"repos/{repo}/actions/runs?per_page=100")
        run = _latest_run(
            runs,
            name=CURATOR_NAME,
            path=CURATOR_PATH,
            completed_only=True,
        )
    _assert_trusted_curator(run)
    return run


def _artifact_candidates(payload: JsonObject) -> list[JsonObject]:
    raw = payload.get("artifacts", [])
    if not isinstance(raw, list):
        raise RuntimeError("artifacts is invalid")
    return sorted(
        [
            item
            for item in raw
            if isinstance(item, dict)
            and item.get("name") == CORPUS_ARTIFACT_NAME
            and item.get("expired") is not True
        ],
        key=lambda item: str(item.get("created_at", "")),
        reverse=True,
    )


def _artifact_run_id(artifact: JsonObject) -> int:
    raw = artifact.get("workflow_run")
    if not isinstance(raw, dict) or not isinstance(raw.get("id"), int):
        raise RuntimeError("corpus artifact producer run id is invalid")
    return int(raw["id"])


def _resolve_corpus_artifact(repo: str, curator_run_id: int) -> tuple[JsonObject, int]:
    direct = _gh_json(
        f"repos/{repo}/actions/runs/{curator_run_id}/artifacts?per_page=100"
    )
    direct_candidates = _artifact_candidates(direct)
    if direct_candidates:
        artifact = direct_candidates[0]
        return artifact, _artifact_run_id(artifact)

    fallback = _gh_json(
        f"repos/{repo}/actions/artifacts?name={CORPUS_ARTIFACT_NAME}&per_page=100"
    )
    for artifact in _artifact_candidates(fallback):
        producer_run_id = _artifact_run_id(artifact)
        producer = _gh_json(f"repos/{repo}/actions/runs/{producer_run_id}")
        try:
            _assert_trusted_curator(producer)
        except RuntimeError:
            continue
        return artifact, producer_run_id
    raise RuntimeError("No trusted v2-mainnet-corpus artifact is available")


def _json_from_zip(blob: bytes, filename: str) -> JsonObject:
    with zipfile.ZipFile(BytesIO(blob)) as archive:
        matches = [
            name
            for name in archive.namelist()
            if PurePosixPath(name).name == filename and not name.endswith("/")
        ]
        if len(matches) != 1:
            raise RuntimeError(
                f"trusted corpus artifact must contain exactly one {filename}"
            )
        payload = json.loads(archive.read(matches[0]).decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"{filename} is not a JSON object")
    return payload


def _latest_campaign(repo: str) -> JsonObject:
    runs = _gh_json(f"repos/{repo}/actions/runs?per_page=100")
    return _latest_run(runs, name=CAMPAIGN_NAME, path=CAMPAIGN_PATH)


def _int_field(payload: JsonObject, field: str, default: int) -> int:
    value = payload.get(field, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeError(f"{field} is invalid")
    return value


def _render_body(
    *,
    repo: str,
    progress: JsonObject,
    index: JsonObject,
    curator: JsonObject,
    campaign: JsonObject,
    artifact_id: int,
    corpus_producer_run_id: int,
) -> str:
    trades = _int_field(progress, "closed_trade_count", 0)
    trade_days = _int_field(progress, "closed_trade_days", 0)
    min_trades = _int_field(progress, "minimum_oos_trade_requirement", 100)
    min_days = _int_field(progress, "minimum_oos_day_requirement", 30)
    cohorts = _int_field(progress, "attested_run_count", 0)

    latest_aggregate = index.get("latest_aggregate", {})
    if not isinstance(latest_aggregate, dict):
        raise RuntimeError("latest_aggregate is invalid")
    decisions = _int_field(latest_aggregate, "decision_fact_count", 0)

    raw_ready = progress.get("raw_corpus_can_satisfy_oos_minimums") is True
    live_orders = progress.get("live_orders") is True
    economic_claim = str(progress.get("economic_claim", "none"))
    attestation = str(progress.get("mainnet_attestation_id", ""))

    curator_run_id = _int_field(curator, "id", 0)
    campaign_run_id = _int_field(campaign, "id", 0)
    curator_conclusion = str(curator.get("conclusion") or "unknown")
    campaign_status = str(campaign.get("status", "unknown"))
    campaign_conclusion = campaign.get("conclusion")
    campaign_state = (
        campaign_status
        if campaign_status != "completed"
        else str(campaign_conclusion or "completed")
    )

    readiness = "YES" if raw_ready else "NO"
    orders = "ENABLED" if live_orders else "DISABLED"
    edge = economic_claim if economic_claim != "none" else "Not measured yet"
    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    attestation_short = f"{attestation[:16]}…" if attestation else "unavailable"

    return f"""# Cocomelon Evidence Dashboard

> Auto-refreshed from trusted GitHub evidence artifacts. Last updated **{updated}**.

## Phase 9 progress

| Metric | Current | Target |
| --- | ---: | ---: |
| Accepted genuine-mainnet cohorts | **{cohorts}** | — |
| Closed paper trades | **{trades}** | **{min_trades}** |
| Closed-trade days | **{trade_days}** | **{min_days}** |
| Strategy decisions in corpus | **{decisions}** | — |

**Raw Phase 9 minimums met:** {readiness}  
**Economic edge:** {edge}  
**Live orders:** {orders}

## Pipeline health

- Latest Campaign V2: **{campaign_state}** — [run {campaign_run_id}](https://github.com/{repo}/actions/runs/{campaign_run_id})
- Triggering curator: **{curator_conclusion}** — [run {curator_run_id}](https://github.com/{repo}/actions/runs/{curator_run_id})
- Corpus producer: [run {corpus_producer_run_id}](https://github.com/{repo}/actions/runs/{corpus_producer_run_id})
- Corpus artifact ID: `{artifact_id}`
- Mainnet attestation: `{attestation_short}`

A curator can finish red **after** safely writing a verified corpus artifact; the dashboard therefore shows curator outcome separately from accepted-corpus counts. Failed or unverified campaign evidence is never counted just because a job ran.

## Direct tracking links

- [Campaign V2 runs](https://github.com/{repo}/actions/workflows/evidence-campaign-scheduled.yml)
- [Evidence corpus curator](https://github.com/{repo}/actions/workflows/evidence-corpus-curator.yml)
- [Repository status](https://github.com/{repo}/blob/main/docs/STATUS.md)

This page is informational only. It does not enable real-money trading or change strategy/risk rules.
"""


def build_issue_patch(repo: str) -> JsonObject:
    curator = _resolve_curator_run(repo)
    curator_run_id = _int_field(curator, "id", 0)
    artifact, producer_run_id = _resolve_corpus_artifact(repo, curator_run_id)
    artifact_id = _int_field(artifact, "id", 0)
    blob = _gh_bytes(f"repos/{repo}/actions/artifacts/{artifact_id}/zip")
    progress = _json_from_zip(blob, "progress.json")
    index = _json_from_zip(blob, "corpus-index.json")
    campaign = _latest_campaign(repo)
    body = _render_body(
        repo=repo,
        progress=progress,
        index=index,
        curator=curator,
        campaign=campaign,
        artifact_id=artifact_id,
        corpus_producer_run_id=producer_run_id,
    )
    return {"body": body}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not repo or "/" not in repo:
        raise RuntimeError("GITHUB_REPOSITORY is invalid")
    payload = build_issue_patch(repo)
    output = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(output), exist_ok=True)
    with open(output, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
        handle.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
