from __future__ import annotations

import argparse
import json
import os
import subprocess
import zipfile
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any

JsonObject = dict[str, object]

_CURATOR_NAME = "Verified V3 Mainnet Evidence Corpus Curator"
_CURATOR_PATH = ".github/workflows/evidence-corpus-curator-v3.yml"
_CAMPAIGN_NAME = "Scheduled Genuine Mainnet Evidence Campaign V3"
_CAMPAIGN_PATH = ".github/workflows/evidence-campaign-scheduled.yml"
_INTAKE_PREFIX = "v3-mainnet-intake-"
_SOURCE_PREFIX = "scheduled-genuine-mainnet-evidence-v3-"
_SAFE_REASONS = {
    "replay_incomplete",
    "dataset_incomplete",
    "open_exposure",
}
_SAFE_DIAGNOSTIC_STATUSES = {
    "artifact_unavailable",
    "artifact_lookup_failed",
    "artifact_download_failed",
    "artifact_unzip_failed",
    "eligibility_probe_unavailable",
    "eligibility_probe_invalid",
    "eligibility_probe",
}


def _repository_name(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    full_name = value.get("full_name")
    return full_name if isinstance(full_name, str) and full_name else None


def _int_field(payload: JsonObject, field: str) -> int:
    value = payload.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeError(f"V3 intake {field} is invalid")
    return value


def _base_intake_valid(report: JsonObject) -> None:
    if report.get("schema_version") != 1:
        raise RuntimeError("V3 intake schema version is invalid")
    if report.get("protocol") != "v3-lifecycle-aware-mainnet":
        raise RuntimeError("V3 intake protocol is invalid")
    _int_field(report, "source_run_id")
    conclusion = report.get("source_conclusion")
    if not isinstance(conclusion, str) or not conclusion:
        raise RuntimeError("V3 intake source conclusion is invalid")
    if not isinstance(report.get("source_verified"), bool):
        raise RuntimeError("V3 intake source verification flag is invalid")
    if not isinstance(report.get("corpus_mutated"), bool):
        raise RuntimeError("V3 intake corpus mutation flag is invalid")
    if report.get("economic_claim") != "none":
        raise RuntimeError("V3 intake economic claim is invalid")
    if report.get("live_orders") is not False:
        raise RuntimeError("V3 intake live-order state is invalid")


def _probe_diagnostic_fields(probe: JsonObject) -> JsonObject | None:
    reasons = probe.get("economic_ineligibility_reasons")
    if not isinstance(reasons, list) or not all(
        isinstance(item, str) and item for item in reasons
    ):
        return None
    if any(item not in _SAFE_REASONS for item in reasons):
        return None
    for field in (
        "replay_data_complete",
        "dataset_data_complete",
        "dataset_gap_refs_empty",
        "flat_replay",
    ):
        if not isinstance(probe.get(field), bool):
            return None
    if probe.get("network_access") is not False or probe.get("live_orders") is not False:
        return None
    return {
        "diagnostic_status": "eligibility_probe",
        "economic_ineligibility_reasons": list(reasons),
        "replay_data_complete": probe["replay_data_complete"],
        "dataset_data_complete": probe["dataset_data_complete"],
        "dataset_gap_refs_empty": probe["dataset_gap_refs_empty"],
        "flat_replay": probe["flat_replay"],
        "network_access": False,
    }


def _enrich_legacy_failed_report(
    report: JsonObject,
    probe: JsonObject | None,
) -> JsonObject:
    _base_intake_valid(report)
    if (
        report.get("source_conclusion") != "failure"
        or report.get("source_verified") is not False
        or report.get("corpus_mutated") is not False
        or report.get("reason") != "source_workflow_not_successful"
        or "diagnostic_status" in report
        or probe is None
    ):
        return dict(report)
    fields = _probe_diagnostic_fields(probe)
    if fields is None:
        return dict(report)
    return {**report, **fields}


def _intake_summary(report: JsonObject) -> str:
    _base_intake_valid(report)
    conclusion = report["source_conclusion"]
    verified = report["source_verified"]
    mutated = report["corpus_mutated"]

    if conclusion == "success":
        if verified is not True or mutated is not True:
            raise RuntimeError("successful V3 intake is not verified and admitted")
        return "accepted into V3 corpus"

    if verified is not False or mutated is not False:
        raise RuntimeError("failed V3 intake cannot be verified or mutate the corpus")
    if report.get("reason") != "source_workflow_not_successful":
        raise RuntimeError("failed V3 intake reason is invalid")

    status = report.get("diagnostic_status")
    if status is None:
        return "rejected — diagnostic detail unavailable"
    if not isinstance(status, str) or status not in _SAFE_DIAGNOSTIC_STATUSES:
        raise RuntimeError("V3 intake diagnostic status is invalid")
    if status != "eligibility_probe":
        return f"rejected — diagnostics: {status}"

    if report.get("network_access") is not False:
        raise RuntimeError("V3 intake diagnostic network state is invalid")
    reasons = report.get("economic_ineligibility_reasons")
    if not isinstance(reasons, list) or not all(isinstance(item, str) for item in reasons):
        raise RuntimeError("V3 intake diagnostic reasons are invalid")
    if any(item not in _SAFE_REASONS for item in reasons):
        raise RuntimeError("V3 intake diagnostic reason is not whitelisted")
    for field in (
        "replay_data_complete",
        "dataset_data_complete",
        "dataset_gap_refs_empty",
        "flat_replay",
    ):
        if not isinstance(report.get(field), bool):
            raise RuntimeError(f"V3 intake diagnostic {field} is invalid")
    if reasons:
        return "rejected — " + ", ".join(reasons)
    return "rejected — eligibility probe had no ineligibility reason"


def _gh_json(repo: str, endpoint: str) -> JsonObject:
    result = subprocess.run(
        ["gh", "api", f"repos/{repo}/{endpoint}"],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict):
        raise RuntimeError(f"GitHub API response is invalid: {endpoint}")
    return payload


def _gh_bytes(repo: str, endpoint: str) -> bytes:
    return subprocess.run(
        ["gh", "api", f"repos/{repo}/{endpoint}"],
        check=True,
        capture_output=True,
    ).stdout


def _latest_curator_run(repo: str) -> JsonObject | None:
    payload = _gh_json(repo, "actions/runs?per_page=100")
    raw = payload.get("workflow_runs")
    if not isinstance(raw, list):
        raise RuntimeError("GitHub workflow run list is invalid")
    matches = [
        item
        for item in raw
        if isinstance(item, dict)
        and item.get("name") == _CURATOR_NAME
        and item.get("path") == _CURATOR_PATH
        and item.get("event") == "workflow_run"
        and item.get("status") == "completed"
        and _repository_name(item.get("repository")) == repo
        and _repository_name(item.get("head_repository")) == repo
    ]
    if not matches:
        return None
    return max(matches, key=lambda item: str(item.get("created_at", "")))


def _report_from_zip(blob: bytes) -> JsonObject:
    with zipfile.ZipFile(BytesIO(blob)) as archive:
        matches = [
            name
            for name in archive.namelist()
            if PurePosixPath(name).name == "intake-report.json" and not name.endswith("/")
        ]
        if len(matches) != 1:
            raise RuntimeError("V3 intake artifact must contain one intake report")
        payload = json.loads(archive.read(matches[0]).decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("V3 intake report is not an object")
    return payload


def _probe_from_zip(blob: bytes) -> JsonObject | None:
    try:
        with zipfile.ZipFile(BytesIO(blob)) as archive:
            matches = [
                name
                for name in archive.namelist()
                if PurePosixPath(name).name == "eligibility-probe.json"
                and not name.endswith("/")
            ]
            if len(matches) != 1:
                return None
            payload = json.loads(archive.read(matches[0]).decode("utf-8"))
    except (zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _legacy_source_probe(repo: str, report: JsonObject) -> JsonObject | None:
    if report.get("source_conclusion") != "failure" or "diagnostic_status" in report:
        return None
    source_run_id = _int_field(report, "source_run_id")
    source = _gh_json(repo, f"actions/runs/{source_run_id}")
    trusted = (
        source.get("id") == source_run_id
        and source.get("name") == _CAMPAIGN_NAME
        and source.get("path") == _CAMPAIGN_PATH
        and source.get("event") in {"schedule", "workflow_dispatch"}
        and source.get("status") == "completed"
        and source.get("conclusion") == report.get("source_conclusion")
        and _repository_name(source.get("repository")) == repo
        and _repository_name(source.get("head_repository")) == repo
    )
    if not trusted:
        return None

    artifacts = _gh_json(repo, f"actions/runs/{source_run_id}/artifacts?per_page=100")
    raw = artifacts.get("artifacts")
    if not isinstance(raw, list):
        return None
    prefix = f"{_SOURCE_PREFIX}{source_run_id}-"
    matches = [
        item
        for item in raw
        if isinstance(item, dict)
        and str(item.get("name", "")).startswith(prefix)
        and item.get("expired") is False
    ]
    if len(matches) != 1:
        return None
    artifact_id = _int_field(matches[0], "id")
    blob = _gh_bytes(repo, f"actions/artifacts/{artifact_id}/zip")
    return _probe_from_zip(blob)


def _latest_intake_report(repo: str) -> JsonObject | None:
    run = _latest_curator_run(repo)
    if run is None:
        return None
    run_id = _int_field(run, "id")
    artifacts = _gh_json(repo, f"actions/runs/{run_id}/artifacts?per_page=100")
    raw = artifacts.get("artifacts")
    if not isinstance(raw, list):
        raise RuntimeError("V3 intake artifact list is invalid")
    matches = [
        item
        for item in raw
        if isinstance(item, dict)
        and str(item.get("name", "")).startswith(_INTAKE_PREFIX)
        and item.get("expired") is False
    ]
    if len(matches) != 1:
        return None
    artifact_id = _int_field(matches[0], "id")
    blob = _gh_bytes(repo, f"actions/artifacts/{artifact_id}/zip")
    report = _report_from_zip(blob)
    return _enrich_legacy_failed_report(
        report,
        _legacy_source_probe(repo, report),
    )


def _apply_intake_summary(patch: JsonObject, summary: str) -> JsonObject:
    body = patch.get("body")
    if not isinstance(body, str):
        raise RuntimeError("dashboard patch body is invalid")
    prefix = "- Latest V3 source intake: **"
    lines = body.splitlines()
    existing = [index for index, line in enumerate(lines) if line.startswith(prefix)]
    replacement = f"{prefix}{summary}**"
    if len(existing) > 1:
        raise RuntimeError("dashboard has duplicate V3 intake lines")
    if existing:
        lines[existing[0]] = replacement
    else:
        curator_prefix = "- Latest V3 curator: **"
        curator_lines = [
            index for index, line in enumerate(lines) if line.startswith(curator_prefix)
        ]
        if len(curator_lines) != 1:
            raise RuntimeError("dashboard must contain exactly one V3 curator line")
        lines.insert(curator_lines[0] + 1, replacement)
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
    report = _latest_intake_report(repo)
    summary = "unavailable" if report is None else _intake_summary(report)
    updated = _apply_intake_summary(patch, summary)
    patch_path.write_text(
        json.dumps(updated, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
