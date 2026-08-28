from __future__ import annotations

import argparse
import base64
import hashlib
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

PHASE9_V3_ONE_SHOT_NAME = "Phase 9 V3 One-Shot Evaluation"
PHASE9_V3_ONE_SHOT_PATH = ".github/workflows/phase9-v3-one-shot.yml"
PHASE9_V3_STATE_BRANCH = "phase9-v3-protocol-state"
PHASE9_V3_FREEZE_FILE = "phase9-v3-freeze.json"
PHASE9_V3_FINAL_FILE = "phase9-v3-final.json"

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


def _gh_optional_json(repo: str, endpoint: str) -> JsonObject | None:
    result = subprocess.run(
        ["gh", "api", f"repos/{repo}/{endpoint}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        if "HTTP 404" in result.stderr:
            return None
        raise RuntimeError(
            f"GitHub API request failed for {endpoint}: {result.stderr.strip()}"
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


def _is_trusted_v3_one_shot(run: JsonObject, repo: str) -> bool:
    return (
        run.get("name") == PHASE9_V3_ONE_SHOT_NAME
        and run.get("path") == PHASE9_V3_ONE_SHOT_PATH
        and run.get("event") == "workflow_run"
        and run.get("status") == "completed"
        and _repository_name(run.get("repository")) == repo
        and _repository_name(run.get("head_repository")) == repo
    )


def _event_workflow_run(repo: str) -> JsonObject | None:
    event_id = os.environ.get("EVENT_WORKFLOW_RUN_ID", "").strip()
    if not event_id or event_id == "null":
        return None
    run = _gh_json(repo, f"actions/runs/{int(event_id)}")
    try:
        _protocol_for_curator(run, repo)
        return run
    except RuntimeError:
        if _is_trusted_v3_one_shot(run, repo):
            return run
    raise RuntimeError("event workflow run provenance is invalid")


def _event_curator(run: JsonObject | None, repo: str) -> JsonObject | None:
    if run is None:
        return None
    try:
        _protocol_for_curator(run, repo)
    except RuntimeError:
        return None
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


def _content_json(repo: str, path: str, ref: str) -> JsonObject | None:
    meta = _gh_optional_json(repo, f"contents/{path}?ref={ref}")
    if meta is None:
        return None
    encoding = meta.get("encoding")
    content = meta.get("content")
    if encoding != "base64" or not isinstance(content, str):
        raise RuntimeError(f"GitHub content metadata is invalid: {path}")
    try:
        raw = base64.b64decode(content, validate=False).decode("utf-8")
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"GitHub content is invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"GitHub content is not a JSON object: {path}")
    return payload


def _verify_canonical_id(payload: JsonObject, field: str, label: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"{label} {field} is invalid")
    base = {key: item for key, item in payload.items() if key != field}
    encoded = json.dumps(
        base,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    if value != hashlib.sha256(encoded).hexdigest():
        raise RuntimeError(f"{label} {field} is invalid")
    return value


def _phase9_v3_state(repo: str) -> JsonObject:
    branch = _gh_optional_json(repo, f"branches/{PHASE9_V3_STATE_BRANCH}")
    if branch is None:
        return {
            "durable_freeze_exists": False,
            "durable_final_exists": False,
            "freeze": None,
            "final": None,
        }

    freeze = _content_json(repo, PHASE9_V3_FREEZE_FILE, PHASE9_V3_STATE_BRANCH)
    final = _content_json(repo, PHASE9_V3_FINAL_FILE, PHASE9_V3_STATE_BRANCH)

    if freeze is not None:
        _verify_canonical_id(freeze, "freeze_id", "V3 freeze")
        if freeze.get("protocol_id") != "v3-phase9-one-shot":
            raise RuntimeError("V3 freeze protocol id is invalid")
        if freeze.get("freeze_state") != "frozen":
            raise RuntimeError("V3 freeze state is invalid")
        if freeze.get("one_shot_oos") is not True:
            raise RuntimeError("V3 freeze is not one-shot OOS")
        if freeze.get("network_access") is not False or freeze.get("live_orders") is not False:
            raise RuntimeError("V3 freeze violates offline-only semantics")

    if final is not None:
        _verify_canonical_id(final, "final_id", "V3 final state")
        if freeze is None:
            raise RuntimeError("V3 final state exists without durable freeze")
        if final.get("protocol_id") != "v3-phase9-one-shot":
            raise RuntimeError("V3 final state protocol id is invalid")
        if final.get("one_shot_oos") is not True:
            raise RuntimeError("V3 final state is not one-shot OOS")
        if final.get("network_access") is not False or final.get("live_orders") is not False:
            raise RuntimeError("V3 final state violates offline-only semantics")
        if final.get("freeze_id") != freeze.get("freeze_id"):
            raise RuntimeError("V3 final state freeze id mismatch")

    return {
        "durable_freeze_exists": freeze is not None,
        "durable_final_exists": final is not None,
        "freeze": freeze,
        "final": final,
    }


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


def _phase9_v3_state_summary(state: JsonObject) -> list[str]:
    freeze_obj = state.get("freeze")
    final_obj = state.get("final")
    freeze = freeze_obj if isinstance(freeze_obj, dict) else None
    final = final_obj if isinstance(final_obj, dict) else None

    if freeze is None and final is None:
        status = "waiting for finalizable snapshot"
    elif freeze is not None and final is None:
        status = "frozen; finalization pending"
    elif freeze is not None and final is not None:
        protocol_state = final.get("protocol_state")
        if protocol_state == "insufficient_evidence":
            status = "terminal insufficient evidence"
        elif protocol_state == "evaluated":
            status = "evaluated"
        else:
            raise RuntimeError("V3 one-shot final protocol state is invalid")
    else:
        raise RuntimeError("V3 one-shot state is invalid")

    lines = [f"**V3 one-shot state:** {status}  "]
    if freeze is None:
        return lines

    revision = freeze.get("evaluator_revision")
    freeze_id = freeze.get("freeze_id")
    curator_run = freeze.get("source_curator_run_id")
    artifact_id = freeze.get("corpus_artifact_id")
    if not isinstance(revision, str) or not revision:
        raise RuntimeError("V3 freeze evaluator revision is invalid")
    if not isinstance(freeze_id, str) or not freeze_id:
        raise RuntimeError("V3 freeze ID is invalid")
    if isinstance(curator_run, bool) or not isinstance(curator_run, int):
        raise RuntimeError("V3 freeze source curator run is invalid")
    if isinstance(artifact_id, bool) or not isinstance(artifact_id, int):
        raise RuntimeError("V3 freeze corpus artifact ID is invalid")

    lines.extend(
        [
            f"**Frozen evaluator revision:** `{revision}`  ",
            f"**Freeze ID:** `{freeze_id[:16]}…`  ",
            f"**Source curator run:** `{curator_run}`  ",
            f"**Source corpus artifact ID:** `{artifact_id}`  ",
        ]
    )
    return lines


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
    event_workflow_run: JsonObject | None,
    event_curator: JsonObject | None,
    phase9_v3_state: JsonObject,
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
            "## V3 one-shot integrity state",
            "",
        ]
    )
    lines.extend(_phase9_v3_state_summary(phase9_v3_state))
    lines.extend(
        [
            "",
            "This section exposes only immutable protocol/provenance state. "
            "It does not reveal interim trade performance before a final one-shot result.",
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
    if event_workflow_run is not None:
        lines.append(
            f"- Dashboard trigger workflow: **{_state(event_workflow_run)}** — "
            f"{_run_link(repo, event_workflow_run)}"
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
            "- [V3 Phase 9 one-shot]"
            f"(https://github.com/{repo}/actions/workflows/phase9-v3-one-shot.yml)",
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
    event_workflow_run = _event_workflow_run(repo)
    event_curator = _event_curator(event_workflow_run, repo)
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
    phase9_v3_state = _phase9_v3_state(repo)

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
            event_workflow_run=event_workflow_run,
            event_curator=event_curator,
            phase9_v3_state=phase9_v3_state,
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
