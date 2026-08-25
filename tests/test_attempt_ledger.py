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


def _write_eligibility_probe(
    attempt_root: Path,
    *,
    economic_eligible: bool,
    reasons: list[str],
    opened_positions: int,
    closed_positions: int,
) -> None:
    _write_json(
        attempt_root / "eligibility-probe.json",
        {
            "schema_version": 1,
            "economic_claim": "none",
            "economic_eligible": economic_eligible,
            "economic_ineligibility_reasons": reasons,
            "replay_data_complete": True,
            "dataset_data_complete": True,
            "dataset_gap_refs_empty": True,
            "opened_positions": opened_positions,
            "closed_positions": closed_positions,
            "flat_replay": opened_positions == closed_positions,
            "network_access": False,
            "live_orders": False,
        },
    )


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


def test_attempt_ledger_records_right_censored_retry_selection(tmp_path: Path) -> None:
    diagnostics = tmp_path / "diagnostics"
    first_attempt = _make_attempt(diagnostics, 1, gap_count=0)
    second_attempt = _make_attempt(diagnostics, 2, gap_count=0)
    _write_eligibility_probe(
        first_attempt,
        economic_eligible=False,
        reasons=["open_exposure"],
        opened_positions=1,
        closed_positions=0,
    )
    _write_eligibility_probe(
        second_attempt,
        economic_eligible=True,
        reasons=[],
        opened_positions=1,
        closed_positions=1,
    )
    output = diagnostics / "cohort-attempts.json"

    result = _run_ledger(diagnostics, output, admitted_attempt="2")

    assert result.returncode == 0, result.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["attempt_count"] == 2
    assert payload["admitted_attempt"] == 2
    first = payload["attempts"][0]
    second = payload["attempts"][1]
    assert first["status"] == "rejected"
    assert first["rejection_reasons"] == ["admission_open_exposure"]
    assert first["eligibility_probe"] == {
        "dataset_data_complete": True,
        "dataset_gap_refs_empty": True,
        "economic_claim": "none",
        "economic_eligible": False,
        "economic_ineligibility_reasons": ["open_exposure"],
        "flat_replay": False,
        "network_access": False,
        "opened_positions": 1,
        "closed_positions": 0,
        "replay_data_complete": True,
        "schema_version": 1,
        "live_orders": False,
    }
    assert second["status"] == "admitted"
    assert second["rejection_reasons"] == []
    assert second["eligibility_probe"]["economic_eligible"] is True


def test_attempt_ledger_survives_truncated_transport_after_gap_abort(tmp_path: Path) -> None:
    diagnostics = tmp_path / "diagnostics"
    attempt_root = diagnostics / "attempt-1"
    _write_text(attempt_root / "started-at-utc.txt", "2026-08-25T01:00:00Z")
    _write_text(attempt_root / "finished-at-utc.txt", "2026-08-25T01:00:10Z")
    _write_text(attempt_root / "recorder-exit-status.txt", "143")
    _write_text(attempt_root / "gap-watch-exit-status.txt", "20")
    _write_text(attempt_root / "normalize-exit-status.txt", "1")
    _write_text(attempt_root / "record-transport.json", '{"session_id":')
    _write_json(attempt_root / "recording-session.json", {"session_id": "aborted-session"})
    gap = attempt_root / "gaps" / "2026-08-25" / "segment-0001.jsonl"
    _write_text(gap, '{"record_type":"data_gap"}')
    output = diagnostics / "cohort-attempts.json"

    result = _run_ledger(diagnostics, output)

    assert result.returncode == 0, result.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    attempt = payload["attempts"][0]
    assert attempt["recording_session_id"] == "aborted-session"
    assert attempt["gap_count"] is None
    assert attempt["duplicate_count"] is None
    assert attempt["anomaly_count"] is None
    assert attempt["status"] == "rejected"
    assert attempt["rejection_reasons"] == [
        "recorder_exit_nonzero",
        "gap_detected",
        "normalization_failed",
        "missing_normalized_record",
    ]
