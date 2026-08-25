from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value + "\n", encoding="utf-8")


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _run_ledger(
    diagnostics: Path,
    output: Path,
    admitted_attempt: str = "",
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        "-m",
        "cocomelon.ops.attempt_ledger",
        "--diagnostics-root",
        str(diagnostics),
        "--out",
        str(output),
    ]
    if admitted_attempt:
        command.extend(["--admitted-attempt", admitted_attempt])
    return subprocess.run(command, check=False, capture_output=True, text=True)


def _make_attempt(
    root: Path,
    attempt: int,
    *,
    gap_count: int,
    duplicate_count: int = 0,
    anomaly_count: int = 0,
    recorder_status: int = 0,
    gap_watch_status: int = 0,
    normalize_status: int = 0,
) -> Path:
    attempt_root = root / f"attempt-{attempt}"
    _write_text(attempt_root / "started-at-utc.txt", f"2026-08-25T0{attempt}:00:00Z")
    _write_text(attempt_root / "finished-at-utc.txt", f"2026-08-25T0{attempt}:45:00Z")
    _write_text(attempt_root / "recorder-exit-status.txt", str(recorder_status))
    _write_text(attempt_root / "gap-watch-exit-status.txt", str(gap_watch_status))
    _write_text(attempt_root / "normalize-exit-status.txt", str(normalize_status))
    _write_json(
        attempt_root / "record.json",
        {
            "session_id": f"session-{attempt}",
            "gap_count": gap_count,
            "duplicate_count": duplicate_count,
            "anomaly_count": anomaly_count,
            "redundant_ws_lane_count": 2,
            "transport_health_semantics": "redundant-mainnet-merged-feed-v1",
            "live_orders": False,
            "network_access": True,
        },
    )
    return attempt_root


def test_attempt_ledger_records_rejected_gap_attempt(tmp_path: Path) -> None:
    diagnostics = tmp_path / "diagnostics"
    _make_attempt(diagnostics, 1, gap_count=1, gap_watch_status=20)
    output = diagnostics / "cohort-attempts.json"

    result = _run_ledger(diagnostics, output)

    assert result.returncode == 0, result.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["economic_claim"] == "none"
    assert payload["selection_audit_only"] is True
    assert payload["attempt_count"] == 1
    assert payload["admitted_attempt"] is None
    assert payload["network_access"] is False
    assert payload["live_orders"] is False
    attempt = payload["attempts"][0]
    assert attempt["attempt"] == 1
    assert attempt["recording_session_id"] == "session-1"
    assert attempt["gap_count"] == 1
    assert attempt["duplicate_count"] == 0
    assert attempt["anomaly_count"] == 0
    assert attempt["admitted"] is False
    assert attempt["status"] == "rejected"
    assert "gap_detected" in attempt["rejection_reasons"]
    assert "gap_count_nonzero" in attempt["rejection_reasons"]


def test_attempt_ledger_is_deterministic_and_marks_exact_admission(tmp_path: Path) -> None:
    diagnostics = tmp_path / "diagnostics"
    _make_attempt(diagnostics, 1, gap_count=0, duplicate_count=1)
    _make_attempt(diagnostics, 2, gap_count=0)
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"

    result_one = _run_ledger(diagnostics, first, admitted_attempt="2")
    result_two = _run_ledger(diagnostics, second, admitted_attempt="2")

    assert result_one.returncode == 0, result_one.stderr
    assert result_two.returncode == 0, result_two.stderr
    assert first.read_bytes() == second.read_bytes()
    payload = json.loads(first.read_text(encoding="utf-8"))
    assert payload["attempt_count"] == 2
    assert payload["admitted_attempt"] == 2
    assert [entry["attempt"] for entry in payload["attempts"]] == [1, 2]
    assert payload["attempts"][0]["status"] == "rejected"
    assert payload["attempts"][0]["rejection_reasons"] == ["duplicate_count_nonzero"]
    assert payload["attempts"][1]["status"] == "admitted"
    assert payload["attempts"][1]["admitted"] is True
    assert payload["attempts"][1]["rejection_reasons"] == []
