from __future__ import annotations

import argparse
import json
import os
import subprocess
import zipfile
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path, PurePosixPath

CURATOR_NAME = "Verified V2 Mainnet Evidence Corpus Curator"
CURATOR_PATH = ".github/workflows/evidence-corpus-curator.yml"
CAMPAIGN_NAME = "Scheduled Genuine Mainnet Evidence Campaign V2"
CAMPAIGN_PATH = ".github/workflows/evidence-campaign-scheduled.yml"
CORPUS_NAME = "v2-mainnet-corpus"

JsonObject = dict[str, object]


def _gh_json(repo: str, endpoint: str) -> JsonObject:
    result = subprocess.run(
        ["gh", "api", f"repos/{repo}/{endpoint}"],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict):
        raise RuntimeError(f"GitHub API response is not an object: {endpoint}")
    return payload


def _gh_bytes(repo: str, endpoint: str) -> bytes:
    return subprocess.run(
        ["gh", "api", f"repos/{repo}/{endpoint}"],
        check=True,
        capture_output=True,
    ).stdout


def _matching_runs(
    payload: JsonObject,
    *,
    name: str,
    path: str,
    completed_only: bool = False,
) -> list[JsonObject]:
    raw = payload.get("workflow_runs", [])
    if not isinstance(raw, list):
        raise RuntimeError("workflow_runs is invalid")
    matches: list[JsonObject] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        if item.get("name") != name or item.get("path") != path:
            continue
        if completed_only and item.get("status") != "completed":
            continue
        matches.append(item)
    return matches


def _latest(items: list[JsonObject], label: str) -> JsonObject:
    if not items:
        raise RuntimeError(f"No {label} is available")
    return max(items, key=lambda item: str(item.get("created_at", "")))


def _assert_curator(run: JsonObject) -> None:
    trusted = (
        run.get("name") == CURATOR_NAME
        and run.get("path") == CURATOR_PATH
        and run.get("status") == "completed"
    )
    if not trusted:
        raise RuntimeError("curator run provenance is invalid")


def _curator_run(repo: str) -> JsonObject:
    event_id = os.environ.get("EVENT_CURATOR_RUN_ID", "").strip()
    if event_id and event_id != "null":
        run = _gh_json(repo, f"actions/runs/{int(event_id)}")
    else:
        runs = _gh_json(repo, "actions/runs?per_page=100")
        run = _latest(
            _matching_runs(
                runs,
                name=CURATOR_NAME,
                path=CURATOR_PATH,
                completed_only=True,
            ),
            "completed curator run",
        )
    _assert_curator(run)
    return run


def _run_id(payload: JsonObject, field: str = "id") -> int:
    value = payload.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeError(f"{field} is invalid")
    return value


def _artifacts(payload: JsonObject) -> list[JsonObject]:
    raw = payload.get("artifacts", [])
    if not isinstance(raw, list):
        raise RuntimeError("artifacts is invalid")
    items: list[JsonObject] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        if item.get("name") != CORPUS_NAME or item.get("expired") is True:
            continue
        items.append(item)
    return sorted(
        items,
        key=lambda item: str(item.get("created_at", "")),
        reverse=True,
    )


def _producer_run_id(artifact: JsonObject) -> int:
    workflow_run = artifact.get("workflow_run")
    if not isinstance(workflow_run, dict):
        raise RuntimeError("corpus artifact producer is invalid")
    value = workflow_run.get("id")
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeError("corpus artifact producer id is invalid")
    return value


def _corpus_artifact(repo: str, curator_id: int) -> tuple[JsonObject, int]:
    direct = _gh_json(repo, f"actions/runs/{curator_id}/artifacts?per_page=100")
    direct_items = _artifacts(direct)
    if direct_items:
        artifact = direct_items[0]
        return artifact, _producer_run_id(artifact)

    candidates = _gh_json(
        repo,
        f"actions/artifacts?name={CORPUS_NAME}&per_page=100",
    )
    for artifact in _artifacts(candidates):
        producer_id = _producer_run_id(artifact)
        producer = _gh_json(repo, f"actions/runs/{producer_id}")
        try:
            _assert_curator(producer)
        except RuntimeError:
            continue
        return artifact, producer_id
    raise RuntimeError("No trusted mainnet corpus artifact is available")


def _json_from_zip(blob: bytes, filename: str) -> JsonObject:
    with zipfile.ZipFile(BytesIO(blob)) as archive:
        matches = [
            name
            for name in archive.namelist()
            if PurePosixPath(name).name == filename and not name.endswith("/")
        ]
        if len(matches) != 1:
            raise RuntimeError(f"corpus must contain exactly one {filename}")
        payload = json.loads(archive.read(matches[0]).decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"{filename} is not a JSON object")
    return payload


def _latest_campaign(repo: str) -> JsonObject:
    runs = _gh_json(repo, "actions/runs?per_page=100")
    return _latest(
        _matching_runs(runs, name=CAMPAIGN_NAME, path=CAMPAIGN_PATH),
        "Campaign V2 run",
    )


def _int(payload: JsonObject, field: str, default: int = 0) -> int:
    value = payload.get(field, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeError(f"{field} is invalid")
    return value


def _body(
    *,
    repo: str,
    progress: JsonObject,
    index: JsonObject,
    curator: JsonObject,
    campaign: JsonObject,
    artifact_id: int,
    producer_id: int,
) -> str:
    aggregate = index.get("latest_aggregate", {})
    if not isinstance(aggregate, dict):
        raise RuntimeError("latest_aggregate is invalid")

    campaign_status = str(campaign.get("status", "unknown"))
    campaign_state = campaign_status
    if campaign_status == "completed":
        campaign_state = str(campaign.get("conclusion") or "completed")

    edge = str(progress.get("economic_claim", "none"))
    if edge == "none":
        edge = "Not measured yet"
    raw_ready = progress.get("raw_corpus_can_satisfy_oos_minimums") is True
    orders = "ENABLED" if progress.get("live_orders") is True else "DISABLED"
    attestation = str(progress.get("mainnet_attestation_id", ""))
    attestation = f"{attestation[:16]}…" if attestation else "unavailable"

    campaign_id = _run_id(campaign)
    curator_id = _run_id(curator)
    updated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    curator_result = str(curator.get("conclusion") or "unknown")

    lines = [
        "# Cocomelon Evidence Dashboard",
        "",
        "> Auto-refreshed from trusted GitHub evidence artifacts. "
        f"Last updated **{updated}**.",
        "",
        "## Phase 9 progress",
        "",
        "| Metric | Current | Target |",
        "| --- | ---: | ---: |",
        "| Accepted genuine-mainnet cohorts | "
        f"**{_int(progress, 'attested_run_count')}** | — |",
        "| Closed paper trades | "
        f"**{_int(progress, 'closed_trade_count')}** | "
        f"**{_int(progress, 'minimum_oos_trade_requirement', 100)}** |",
        "| Closed-trade days | "
        f"**{_int(progress, 'closed_trade_days')}** | "
        f"**{_int(progress, 'minimum_oos_day_requirement', 30)}** |",
        "| Strategy decisions in corpus | "
        f"**{_int(aggregate, 'decision_fact_count')}** | — |",
        "",
        f"**Raw Phase 9 minimums met:** {'YES' if raw_ready else 'NO'}  ",
        f"**Economic edge:** {edge}  ",
        f"**Live orders:** {orders}",
        "",
        "## Pipeline health",
        "",
        f"- Latest Campaign V2: **{campaign_state}** — "
        f"[run {campaign_id}](https://github.com/{repo}/actions/runs/{campaign_id})",
        f"- Triggering curator: **{curator_result}** — "
        f"[run {curator_id}](https://github.com/{repo}/actions/runs/{curator_id})",
        f"- Corpus producer: [run {producer_id}]"
        f"(https://github.com/{repo}/actions/runs/{producer_id})",
        f"- Corpus artifact ID: `{artifact_id}`",
        f"- Mainnet attestation: `{attestation}`",
        "",
        "A curator can finish red after safely writing a verified corpus artifact. "
        "The dashboard keeps curator outcome separate from accepted-corpus counts.",
        "Failed or unverified campaign evidence is never counted just because a job ran.",
        "",
        "## Direct tracking links",
        "",
        "- [Campaign V2 runs]"
        f"(https://github.com/{repo}/actions/workflows/evidence-campaign-scheduled.yml)",
        "- [Evidence corpus curator]"
        f"(https://github.com/{repo}/actions/workflows/evidence-corpus-curator.yml)",
        "- [Repository status]"
        f"(https://github.com/{repo}/blob/main/docs/STATUS.md)",
        "",
        "This page is informational only. It does not enable real-money trading "
        "or change strategy/risk rules.",
        "",
    ]
    return "\n".join(lines)


def build_issue_patch(repo: str) -> JsonObject:
    curator = _curator_run(repo)
    curator_id = _run_id(curator)
    artifact, producer_id = _corpus_artifact(repo, curator_id)
    artifact_id = _run_id(artifact)
    blob = _gh_bytes(repo, f"actions/artifacts/{artifact_id}/zip")
    progress = _json_from_zip(blob, "progress.json")
    index = _json_from_zip(blob, "corpus-index.json")
    campaign = _latest_campaign(repo)
    return {
        "body": _body(
            repo=repo,
            progress=progress,
            index=index,
            curator=curator,
            campaign=campaign,
            artifact_id=artifact_id,
            producer_id=producer_id,
        )
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not repo or "/" not in repo:
        raise RuntimeError("GITHUB_REPOSITORY is invalid")
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(build_issue_patch(repo), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
