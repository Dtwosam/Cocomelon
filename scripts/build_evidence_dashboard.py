from __future__ import annotations

import argparse
import json
import os
import subprocess
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path, PurePosixPath


@dataclass(frozen=True, slots=True)
class ProtocolSpec:
    label: str
    curator_name: str
    curator_path: str
    campaign_name: str
    campaign_path: str
    corpus_name: str


V3 = ProtocolSpec(
    label="V3 lifecycle-aware",
    curator_name="Verified V3 Mainnet Evidence Corpus Curator",
    curator_path=".github/workflows/evidence-corpus-curator-v3.yml",
    campaign_name="Scheduled Genuine Mainnet Evidence Campaign V3",
    campaign_path=".github/workflows/evidence-campaign-scheduled.yml",
    corpus_name="v3-mainnet-corpus",
)
V2 = ProtocolSpec(
    label="V2 historical",
    curator_name="Verified V2 Mainnet Evidence Corpus Curator",
    curator_path=".github/workflows/evidence-corpus-curator.yml",
    campaign_name="Scheduled Genuine Mainnet Evidence Campaign V2",
    campaign_path=".github/workflows/evidence-campaign-scheduled.yml",
    corpus_name="v2-mainnet-corpus",
)
TRUSTED_PROTOCOLS = (V3, V2)

JsonObject = dict[str, object]
CorpusSnapshot = tuple[JsonObject, JsonObject, int, int]


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


def _repository_name(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    full_name = value.get("full_name")
    return full_name if isinstance(full_name, str) and full_name else None


def _protocol_for_curator(run: JsonObject, repo: str) -> ProtocolSpec:
    for spec in TRUSTED_PROTOCOLS:
        trusted = (
            run.get("name") == spec.curator_name
            and run.get("path") == spec.curator_path
            and run.get("event") == "workflow_run"
            and run.get("status") == "completed"
            and _repository_name(run.get("repository")) == repo
            and _repository_name(run.get("head_repository")) == repo
        )
        if trusted:
            return spec
    raise RuntimeError("curator run provenance is invalid")


def _event_curator(repo: str) -> JsonObject | None:
    event_id = os.environ.get("EVENT_CURATOR_RUN_ID", "").strip()
    if not event_id or event_id == "null":
        return None
    run = _gh_json(repo, f"actions/runs/{int(event_id)}")
    _protocol_for_curator(run, repo)
    return run


def _runs(payload: JsonObject) -> list[JsonObject]:
    raw = payload.get("workflow_runs", [])
    if not isinstance(raw, list):
        raise RuntimeError("workflow_runs is invalid")
    return [item for item in raw if isinstance(item, dict)]


def _latest_protocol_run(
    runs: list[JsonObject],
    *,
    name: str,
    path: str,
    event: str | None = None,
) -> JsonObject | None:
    matches = [
        item
        for item in runs
        if item.get("name") == name
        and item.get("path") == path
        and (event is None or item.get("event") == event)
    ]
    if not matches:
        return None
    return max(matches, key=lambda item: str(item.get("created_at", "")))


def _run_id(payload: JsonObject, field: str = "id") -> int:
    value = payload.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeError(f"{field} is invalid")
    return value


def _artifact_items(payload: JsonObject, corpus_name: str) -> list[JsonObject]:
    raw = payload.get("artifacts", [])
    if not isinstance(raw, list):
        raise RuntimeError("artifacts is invalid")
    items = [
        item
        for item in raw
        if isinstance(item, dict)
        and item.get("name") == corpus_name
        and item.get("expired") is False
    ]
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


def _trusted_artifact(
    repo: str,
    spec: ProtocolSpec,
    *,
    preferred_curator_id: int | None = None,
) -> tuple[JsonObject, int] | None:
    if preferred_curator_id is not None:
        direct = _gh_json(
            repo,
            f"actions/runs/{preferred_curator_id}/artifacts?per_page=100",
        )
        direct_items = _artifact_items(direct, spec.corpus_name)
        if direct_items:
            return direct_items[0], preferred_curator_id

    candidates = _gh_json(
        repo,
        f"actions/artifacts?name={spec.corpus_name}&per_page=100",
    )
    for artifact in _artifact_items(candidates, spec.corpus_name):
        producer_id = _producer_run_id(artifact)
        producer = _gh_json(repo, f"actions/runs/{producer_id}")
        try:
            producer_spec = _protocol_for_curator(producer, repo)
        except RuntimeError:
            continue
        if producer_spec == spec:
            return artifact, producer_id
    return None


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


def _corpus_snapshot(
    repo: str,
    spec: ProtocolSpec,
    *,
    preferred_curator_id: int | None = None,
) -> CorpusSnapshot | None:
    selected = _trusted_artifact(
        repo,
        spec,
        preferred_curator_id=preferred_curator_id,
    )
    if selected is None:
        return None
    artifact, producer_id = selected
    artifact_id = _run_id(artifact)
    blob = _gh_bytes(repo, f"actions/artifacts/{artifact_id}/zip")
    progress = _json_from_zip(blob, "progress.json")
    index = _json_from_zip(blob, "corpus-index.json")
    return progress, index, artifact_id, producer_id


def _int(payload: JsonObject, field: str, default: int = 0) -> int:
    value = payload.get(field, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeError(f"{field} is invalid")
    return value


def _decision_count(index: JsonObject) -> int:
    aggregate = index.get("latest_aggregate", {})
    if not isinstance(aggregate, dict):
        raise RuntimeError("latest_aggregate is invalid")
    return _int(aggregate, "decision_fact_count")


def _state(run: JsonObject | None) -> str:
    if run is None:
        return "not run yet"
    status = str(run.get("status", "unknown"))
    if status == "completed":
        return str(run.get("conclusion") or "completed")
    return status


def _run_link(repo: str, run: JsonObject | None) -> str:
    if run is None:
        return "not run yet"
    run_id = _run_id(run)
    return f"[{run_id}](https://github.com/{repo}/actions/runs/{run_id})"


def _zero_v3_progress() -> JsonObject:
    return {
        "attested_run_count": 0,
        "closed_trade_count": 0,
        "closed_trade_days": 0,
        "minimum_oos_trade_requirement": 100,
        "minimum_oos_day_requirement": 30,
        "raw_corpus_can_satisfy_oos_minimums": False,
        "economic_claim": "none",
        "live_orders": False,
    }


def _body(
    *,
    repo: str,
    active_progress: JsonObject,
    active_index: JsonObject | None,
    active_snapshot: CorpusSnapshot | None,
    historical_v2_progress: JsonObject | None,
    historical_v2_snapshot: CorpusSnapshot | None,
    latest_v3_campaign: JsonObject | None,
    latest_v3_curator: JsonObject | None,
    event_curator: JsonObject | None,
) -> str:
    active_decisions = _decision_count(active_index) if active_index is not None else 0
    raw_ready = active_progress.get("raw_corpus_can_satisfy_oos_minimums") is True
    edge = str(active_progress.get("economic_claim", "none"))
    if edge == "none":
        edge = "Not measured yet"
    orders = "ENABLED" if active_progress.get("live_orders") is True else "DISABLED"
    updated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "# Cocomelon Evidence Dashboard",
        "",
        "> Auto-refreshed from trusted GitHub evidence artifacts. "
        f"Last updated **{updated}**.",
        "",
        "**Active evidence protocol: V3 lifecycle-aware**  ",
        "V3 uses a fixed 45-minute entry window followed by a bounded "
        "closeout-only window. Historical V2 evidence is shown separately and "
        "is not counted as V3 progress.",
        "",
        "## Active V3 evidence progress",
        "",
        "| Metric | Current | Target |",
        "| --- | ---: | ---: |",
        "| Accepted genuine-mainnet cohorts | "
        f"**{_int(active_progress, 'attested_run_count')}** | — |",
        "| Closed paper trades | "
        f"**{_int(active_progress, 'closed_trade_count')}** | "
        f"**{_int(active_progress, 'minimum_oos_trade_requirement', 100)}** |",
        "| Closed-trade days | "
        f"**{_int(active_progress, 'closed_trade_days')}** | "
        f"**{_int(active_progress, 'minimum_oos_day_requirement', 30)}** |",
        f"| Strategy decisions in corpus | **{active_decisions}** | — |",
        "",
    ]
    if active_snapshot is None:
        lines.extend(["**V3 accepted corpus not established yet.**", ""])

    lines.extend(
        [
            f"**Raw Phase 9 minimums met:** {'YES' if raw_ready else 'NO'}  ",
            f"**Economic edge:** {edge}  ",
            f"**Live orders:** {orders}",
            "",
            "## Historical V2 evidence",
            "",
        ]
    )
    if historical_v2_progress is None:
        lines.append("Historical V2 accepted cohorts: unavailable.")
    else:
        lines.extend(
            [
                "Historical V2 accepted cohorts: "
                f"**{_int(historical_v2_progress, 'attested_run_count')}**  ",
                "Historical V2 closed paper trades: "
                f"**{_int(historical_v2_progress, 'closed_trade_count')}**  ",
                "Historical V2 closed-trade days: "
                f"**{_int(historical_v2_progress, 'closed_trade_days')}**",
            ]
        )
    lines.extend(
        [
            "",
            "These V2 counts are retained for audit/history only and do not "
            "advance the V3 evidence gate.",
            "",
            "## Pipeline health",
            "",
            f"- Latest Campaign V3: **{_state(latest_v3_campaign)}** — "
            f"{_run_link(repo, latest_v3_campaign)}",
            f"- Latest V3 curator: **{_state(latest_v3_curator)}** — "
            f"{_run_link(repo, latest_v3_curator)}",
        ]
    )
    if event_curator is not None:
        lines.append(
            f"- Dashboard trigger curator: **{_state(event_curator)}** — "
            f"{_run_link(repo, event_curator)}"
        )
    if active_snapshot is not None:
        active_artifact_id = active_snapshot[2]
        active_producer_id = active_snapshot[3]
        attestation = str(active_progress.get("mainnet_attestation_id", ""))
        attestation = f"{attestation[:16]}…" if attestation else "unavailable"
        lines.extend(
            [
                f"- V3 corpus producer: [run {active_producer_id}]"
                f"(https://github.com/{repo}/actions/runs/{active_producer_id})",
                f"- V3 corpus artifact ID: `{active_artifact_id}`",
                f"- V3 mainnet attestation: `{attestation}`",
            ]
        )
    if historical_v2_snapshot is not None:
        lines.append(f"- Historical V2 corpus artifact ID: `{historical_v2_snapshot[2]}`")

    lines.extend(
        [
            "",
            "A curator can finish red after safely writing a verified corpus artifact. "
            "Curator outcome is therefore kept separate from accepted-corpus counts. "
            "Failed or unverified campaign evidence is never counted just because a job ran.",
            "",
            "## Direct tracking links",
            "",
            "- [Campaign V3 runs]"
            f"(https://github.com/{repo}/actions/workflows/evidence-campaign-scheduled.yml)",
            "- [V3 evidence corpus curator]"
            f"(https://github.com/{repo}/actions/workflows/evidence-corpus-curator-v3.yml)",
            "- [Historical V2 curator]"
            f"(https://github.com/{repo}/actions/workflows/evidence-corpus-curator.yml)",
            "- [Repository status]"
            f"(https://github.com/{repo}/blob/main/docs/STATUS.md)",
            "",
            "This page is informational only. It does not enable real-money trading "
            "or change strategy/risk rules.",
            "",
        ]
    )
    return "\n".join(lines)


def build_issue_patch(repo: str) -> JsonObject:
    event_curator = _event_curator(repo)
    event_spec = _protocol_for_curator(event_curator, repo) if event_curator else None
    event_id = _run_id(event_curator) if event_curator else None

    runs_payload = _gh_json(repo, "actions/runs?per_page=100")
    runs = _runs(runs_payload)
    latest_v3_campaign = _latest_protocol_run(
        runs,
        name=V3.campaign_name,
        path=V3.campaign_path,
    )
    latest_v3_curator = _latest_protocol_run(
        runs,
        name=V3.curator_name,
        path=V3.curator_path,
        event="workflow_run",
    )

    active_snapshot = _corpus_snapshot(
        repo,
        V3,
        preferred_curator_id=event_id if event_spec == V3 else None,
    )
    historical_v2_snapshot = _corpus_snapshot(
        repo,
        V2,
        preferred_curator_id=event_id if event_spec == V2 else None,
    )

    active_progress = active_snapshot[0] if active_snapshot else _zero_v3_progress()
    active_index = active_snapshot[1] if active_snapshot else None
    historical_v2_progress = (
        historical_v2_snapshot[0] if historical_v2_snapshot else None
    )
    return {
        "body": _body(
            repo=repo,
            active_progress=active_progress,
            active_index=active_index,
            active_snapshot=active_snapshot,
            historical_v2_progress=historical_v2_progress,
            historical_v2_snapshot=historical_v2_snapshot,
            latest_v3_campaign=latest_v3_campaign,
            latest_v3_curator=latest_v3_curator,
            event_curator=event_curator,
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
