from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import cast

EXPECTED_TRANSPORT_SEMANTICS = "redundant-mainnet-merged-feed-v1"


def _read_optional_text(path: Path) -> str | None:
    if not path.is_file():
        return None
    value = path.read_text(encoding="utf-8").strip()
    return value or None


def _read_optional_int(path: Path) -> int | None:
    value = _read_optional_text(path)
    if value is None:
        return None
    return int(value)


def _read_optional_json(
    path: Path,
    *,
    tolerate_invalid: bool = False,
) -> dict[str, object] | None:
    if not path.is_file() or path.stat().st_size == 0:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        if tolerate_invalid:
            return None
        raise
    if not isinstance(payload, dict):
        if tolerate_invalid:
            return None
        raise ValueError(f"expected a JSON object in {path}")
    return cast(dict[str, object], payload)


def _int_field(payload: dict[str, object] | None, key: str) -> int | None:
    if payload is None:
        return None
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _str_field(payload: dict[str, object] | None, key: str) -> str | None:
    if payload is None:
        return None
    value = payload.get(key)
    return value if isinstance(value, str) and value else None


def _bool_field(payload: dict[str, object] | None, key: str) -> bool | None:
    if payload is None:
        return None
    value = payload.get(key)
    return value if isinstance(value, bool) else None


def _attempt_number(path: Path) -> int:
    prefix = "attempt-"
    if not path.name.startswith(prefix):
        raise ValueError(f"invalid attempt directory name: {path.name}")
    value = path.name.removeprefix(prefix)
    if not value.isdigit() or int(value) <= 0:
        raise ValueError(f"invalid attempt directory name: {path.name}")
    return int(value)


def _has_gap_files(attempt_root: Path) -> bool:
    gap_root = attempt_root / "gaps"
    if not gap_root.is_dir():
        return False
    return any(path.is_file() and path.stat().st_size > 0 for path in gap_root.rglob("*.jsonl"))


def _rejection_reasons(
    *,
    attempt_root: Path,
    record: dict[str, object] | None,
    recorder_status: int | None,
    gap_watch_status: int | None,
    normalize_status: int | None,
    gap_count: int | None,
    duplicate_count: int | None,
    anomaly_count: int | None,
) -> list[str]:
    reasons: list[str] = []
    if recorder_status is None:
        reasons.append("missing_recorder_status")
    elif recorder_status != 0:
        reasons.append("recorder_exit_nonzero")
    if gap_watch_status == 20 or _has_gap_files(attempt_root):
        reasons.append("gap_detected")
    if normalize_status is None:
        reasons.append("missing_normalize_status")
    elif normalize_status != 0:
        reasons.append("normalization_failed")
    if record is None:
        reasons.append("missing_normalized_record")
        return reasons
    if gap_count is None:
        reasons.append("missing_gap_count")
    elif gap_count != 0:
        reasons.append("gap_count_nonzero")
    if duplicate_count is None:
        reasons.append("missing_duplicate_count")
    elif duplicate_count != 0:
        reasons.append("duplicate_count_nonzero")
    if anomaly_count is None:
        reasons.append("missing_anomaly_count")
    elif anomaly_count != 0:
        reasons.append("anomaly_count_nonzero")
    if _int_field(record, "redundant_ws_lane_count") != 2:
        reasons.append("redundant_lane_count_invalid")
    if _str_field(record, "transport_health_semantics") != EXPECTED_TRANSPORT_SEMANTICS:
        reasons.append("transport_semantics_invalid")
    if _bool_field(record, "live_orders") is not False:
        reasons.append("live_orders_invalid")
    if _bool_field(record, "network_access") is not True:
        reasons.append("network_access_invalid")
    return reasons


def build_attempt_ledger(
    diagnostics_root: str | Path,
    *,
    admitted_attempt: int | None = None,
) -> dict[str, object]:
    root = Path(diagnostics_root)
    if not root.is_dir():
        raise ValueError(f"diagnostics root does not exist: {root}")

    attempt_dirs = sorted(
        (path for path in root.iterdir() if path.is_dir() and path.name.startswith("attempt-")),
        key=_attempt_number,
    )
    if not attempt_dirs:
        raise ValueError("no campaign attempt diagnostics found")

    entries: list[dict[str, object]] = []
    admitted_seen = False
    for attempt_root in attempt_dirs:
        attempt = _attempt_number(attempt_root)
        record = _read_optional_json(attempt_root / "record.json")
        transport = _read_optional_json(
            attempt_root / "record-transport.json",
            tolerate_invalid=True,
        )
        session = _read_optional_json(attempt_root / "recording-session.json")
        counter_source = record if record is not None else transport
        recorder_status = _read_optional_int(attempt_root / "recorder-exit-status.txt")
        gap_watch_status = _read_optional_int(attempt_root / "gap-watch-exit-status.txt")
        normalize_status = _read_optional_int(attempt_root / "normalize-exit-status.txt")
        gap_count = _int_field(counter_source, "gap_count")
        duplicate_count = _int_field(counter_source, "duplicate_count")
        anomaly_count = _int_field(counter_source, "anomaly_count")
        reasons = _rejection_reasons(
            attempt_root=attempt_root,
            record=record,
            recorder_status=recorder_status,
            gap_watch_status=gap_watch_status,
            normalize_status=normalize_status,
            gap_count=gap_count,
            duplicate_count=duplicate_count,
            anomaly_count=anomaly_count,
        )
        admitted = admitted_attempt == attempt
        if admitted:
            admitted_seen = True
            if reasons:
                joined = ",".join(reasons)
                raise ValueError(f"admitted attempt {attempt} has rejection reasons: {joined}")
        elif not reasons:
            raise ValueError(f"rejected attempt {attempt} has no rejection reason")

        entries.append(
            {
                "attempt": attempt,
                "started_at_utc": _read_optional_text(attempt_root / "started-at-utc.txt"),
                "finished_at_utc": _read_optional_text(attempt_root / "finished-at-utc.txt"),
                "recording_session_id": (
                    _str_field(record, "session_id") or _str_field(session, "session_id")
                ),
                "recorder_exit_status": recorder_status,
                "gap_watch_exit_status": gap_watch_status,
                "normalize_exit_status": normalize_status,
                "gap_count": gap_count,
                "duplicate_count": duplicate_count,
                "anomaly_count": anomaly_count,
                "admitted": admitted,
                "status": "admitted" if admitted else "rejected",
                "rejection_reasons": reasons,
            }
        )

    if admitted_attempt is not None and not admitted_seen:
        raise ValueError(f"admitted attempt {admitted_attempt} is absent from diagnostics")

    return {
        "schema_version": 1,
        "economic_claim": "none",
        "selection_audit_only": True,
        "attempt_count": len(entries),
        "admitted_attempt": admitted_attempt,
        "attempts": entries,
        "network_access": False,
        "live_orders": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cocomelon-attempt-ledger")
    parser.add_argument("--diagnostics-root", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--admitted-attempt", default="")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    admitted_raw = str(args.admitted_attempt).strip()
    admitted_attempt = int(admitted_raw) if admitted_raw else None
    payload = build_attempt_ledger(
        cast(Path, args.diagnostics_root),
        admitted_attempt=admitted_attempt,
    )
    output = cast(Path, args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
