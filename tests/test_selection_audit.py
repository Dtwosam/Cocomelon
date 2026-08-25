from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from cocomelon.ops.attempt_ledger import build_attempt_ledger

LEDGER_REVISION = "2a9f01d86218dca98d2d84a4ae0e2e28c69975a7"
TRIGGER_SHA = "70e51d1e897cdafa236dc4ef06787939d2b726b4"
OTHER_TRIGGER_SHA = "61fab78355c4bac4a644b59dbd6011a65d70c9d8"
CAMPAIGN_WORKFLOW_ID = 341636172
CAMPAIGN_WORKFLOW_PATH = ".github/workflows/evidence-campaign-scheduled.yml"
REPOSITORY = "Dtwosam/Cocomelon"


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value + "\n", encoding="utf-8")


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _make_attempt(
    diagnostics: Path,
    attempt: int,
    *,
    duplicate_count: int = 0,
) -> None:
    root = diagnostics / f"attempt-{attempt}"
    _write_text(root / "started-at-utc.txt", f"2026-08-25T0{attempt}:00:00Z")
    _write_text(root / "finished-at-utc.txt", f"2026-08-25T0{attempt}:45:00Z")
    _write_text(root / "recorder-exit-status.txt", "0")
    _write_text(root / "gap-watch-exit-status.txt", "0")
    _write_text(root / "normalize-exit-status.txt", "0")
    _write_json(
        root / "record.json",
        {
            "session_id": f"session-{attempt}",
            "gap_count": 0,
            "duplicate_count": duplicate_count,
            "anomaly_count": 0,
            "redundant_ws_lane_count": 2,
            "transport_health_semantics": "redundant-mainnet-merged-feed-v1",
            "live_orders": False,
            "network_access": True,
        },
    )


def _make_cohort(root: Path) -> None:
    diagnostics = root / "diagnostics"
    _make_attempt(diagnostics, 1, duplicate_count=1)
    _make_attempt(diagnostics, 2)
    ledger = build_attempt_ledger(diagnostics, admitted_attempt=2)
    _write_json(diagnostics / "cohort-attempts.json", ledger)
    _write_text(diagnostics / "attempt-ledger-revision.txt", LEDGER_REVISION)
    _write_text(root / "output" / "acquisition-attempt.txt", "2")
    _write_text(root / "output" / "trigger-head.txt", TRIGGER_SHA)


def _write_workflow_event(
    path: Path,
    *,
    head_branch: str = "main",
    workflow_id: int = CAMPAIGN_WORKFLOW_ID,
    workflow_path: str = CAMPAIGN_WORKFLOW_PATH,
    repository: str = REPOSITORY,
) -> None:
    _write_json(
        path,
        {
            "workflow_run": {
                "head_sha": TRIGGER_SHA,
                "head_branch": head_branch,
                "workflow_id": workflow_id,
                "path": workflow_path,
                "repository": {"full_name": repository},
            }
        },
    )


def _run_audit(
    cohort: Path,
    output: Path,
    *,
    expected_trigger_sha: str | None = TRIGGER_SHA,
    event_path: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        "-m",
        "cocomelon.ops.selection_audit",
        "--cohort-root",
        str(cohort),
        "--source-run-id",
        "12345",
        "--source-artifact-id",
        "67890",
        "--expected-ledger-revision",
        LEDGER_REVISION,
    ]
    if expected_trigger_sha is not None:
        command.extend(["--expected-trigger-sha", expected_trigger_sha])
    command.extend(["--out", str(output)])
    env = os.environ.copy()
    if event_path is not None:
        env["GITHUB_EVENT_PATH"] = str(event_path)
        env["GITHUB_REPOSITORY"] = REPOSITORY
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_selection_audit_recomputes_and_binds_attempt_ledger(tmp_path: Path) -> None:
    cohort = tmp_path / "cohort"
    _make_cohort(cohort)
    first = tmp_path / "selection-audit-1.json"
    second = tmp_path / "selection-audit-2.json"

    result_one = _run_audit(cohort, first)
    result_two = _run_audit(cohort, second)

    assert result_one.returncode == 0, result_one.stderr
    assert result_two.returncode == 0, result_two.stderr
    assert first.read_bytes() == second.read_bytes()
    payload = json.loads(first.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["economic_claim"] == "none"
    assert payload["source_run_id"] == 12345
    assert payload["source_artifact_id"] == 67890
    assert payload["trigger_head_sha"] == TRIGGER_SHA
    assert payload["attempt_ledger_revision"] == LEDGER_REVISION
    assert payload["attempt_count"] == 2
    assert payload["rejected_attempt_count"] == 1
    assert payload["admitted_attempt"] == 2
    assert payload["network_access"] is False
    assert payload["live_orders"] is False
    assert payload["attempt_ledger"]["attempts"][0]["status"] == "rejected"
    assert payload["attempt_ledger"]["attempts"][1]["status"] == "admitted"
    audit_id = payload["selection_audit_id"]
    assert isinstance(audit_id, str)
    assert len(audit_id) == 64
    base = {key: value for key, value in payload.items() if key != "selection_audit_id"}
    encoded = json.dumps(
        base,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    assert audit_id == hashlib.sha256(encoded).hexdigest()


def test_selection_audit_accepts_authoritative_campaign_event(tmp_path: Path) -> None:
    cohort = tmp_path / "cohort"
    _make_cohort(cohort)
    event_path = tmp_path / "event.json"
    _write_workflow_event(event_path)
    output = tmp_path / "selection-audit.json"

    result = _run_audit(
        cohort,
        output,
        expected_trigger_sha=None,
        event_path=event_path,
    )

    assert result.returncode == 0, result.stderr
    assert output.exists()


def test_selection_audit_rejects_untrusted_campaign_event_provenance(tmp_path: Path) -> None:
    cohort = tmp_path / "cohort"
    _make_cohort(cohort)
    cases = (
        ({"head_branch": "feature"}, "source workflow branch"),
        ({"workflow_id": CAMPAIGN_WORKFLOW_ID + 1}, "source workflow id"),
        ({"workflow_path": ".github/workflows/fake.yml"}, "source workflow path"),
        ({"repository": "other/repo"}, "source workflow repository"),
    )

    for index, (overrides, expected_error) in enumerate(cases):
        event_path = tmp_path / f"event-{index}.json"
        _write_workflow_event(event_path, **overrides)  # type: ignore[arg-type]
        output = tmp_path / f"selection-audit-{index}.json"

        result = _run_audit(
            cohort,
            output,
            expected_trigger_sha=None,
            event_path=event_path,
        )

        assert result.returncode != 0
        assert expected_error in result.stderr
        assert not output.exists()


def test_selection_audit_rejects_tampered_persisted_ledger(tmp_path: Path) -> None:
    cohort = tmp_path / "cohort"
    _make_cohort(cohort)
    ledger_path = cohort / "diagnostics" / "cohort-attempts.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["attempt_count"] = 99
    _write_json(ledger_path, ledger)
    output = tmp_path / "selection-audit.json"

    result = _run_audit(cohort, output)

    assert result.returncode != 0
    assert "does not match recomputed attempt ledger" in result.stderr
    assert not output.exists()


def test_selection_audit_rejects_mismatched_admitted_attempt(tmp_path: Path) -> None:
    cohort = tmp_path / "cohort"
    _make_cohort(cohort)
    _write_text(cohort / "output" / "acquisition-attempt.txt", "1")
    output = tmp_path / "selection-audit.json"

    result = _run_audit(cohort, output)

    assert result.returncode != 0
    assert "admitted attempt does not match acquisition attempt" in result.stderr
    assert not output.exists()


def test_selection_audit_rejects_artifact_trigger_mismatch(tmp_path: Path) -> None:
    cohort = tmp_path / "cohort"
    _make_cohort(cohort)
    output = tmp_path / "selection-audit.json"

    result = _run_audit(
        cohort,
        output,
        expected_trigger_sha=OTHER_TRIGGER_SHA,
    )

    assert result.returncode != 0
    assert "trigger head sha does not match authoritative workflow run" in result.stderr
    assert not output.exists()
