from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from cocomelon.ops.attempt_ledger import build_attempt_ledger

_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def _read_json_object(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected a JSON object in {path}")
    return cast(dict[str, object], payload)


def _read_required_text(path: Path) -> str:
    if not path.is_file():
        raise ValueError(f"required selection-audit input is missing: {path}")
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise ValueError(f"required selection-audit input is empty: {path}")
    return value


def _read_positive_int(path: Path) -> int:
    value = int(_read_required_text(path))
    if value <= 0:
        raise ValueError(f"expected positive integer in {path}")
    return value


def _require_sha(value: str, *, label: str) -> str:
    if _SHA_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase 40-character git sha")
    return value


def _canonical_id(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_selection_audit(
    cohort_root: str | Path,
    *,
    source_run_id: int,
    source_artifact_id: int,
    expected_ledger_revision: str,
) -> dict[str, object]:
    root = Path(cohort_root)
    if source_run_id <= 0 or source_artifact_id <= 0:
        raise ValueError("source run and artifact ids must be positive")
    expected_revision = _require_sha(
        expected_ledger_revision,
        label="expected attempt ledger revision",
    )

    diagnostics = root / "diagnostics"
    output = root / "output"
    actual_revision = _require_sha(
        _read_required_text(diagnostics / "attempt-ledger-revision.txt"),
        label="attempt ledger revision",
    )
    if actual_revision != expected_revision:
        raise ValueError("attempt ledger revision does not match expected revision")

    trigger_sha = _require_sha(
        _read_required_text(output / "trigger-head.txt"),
        label="trigger head sha",
    )
    acquisition_attempt = _read_positive_int(output / "acquisition-attempt.txt")
    ledger_path = diagnostics / "cohort-attempts.json"
    if not ledger_path.is_file():
        raise ValueError("persisted attempt ledger is missing")
    persisted = _read_json_object(ledger_path)

    if persisted.get("admitted_attempt") != acquisition_attempt:
        raise ValueError("admitted attempt does not match acquisition attempt")

    recomputed = build_attempt_ledger(
        diagnostics,
        admitted_attempt=acquisition_attempt,
    )
    if persisted != recomputed:
        raise ValueError("persisted attempt ledger does not match recomputed attempt ledger")

    attempts = recomputed.get("attempts")
    if not isinstance(attempts, list):
        raise ValueError("recomputed attempt ledger has invalid attempts")
    rejected_attempt_count = sum(
        1
        for attempt in attempts
        if isinstance(attempt, dict) and attempt.get("status") == "rejected"
    )

    base: dict[str, object] = {
        "schema_version": 1,
        "economic_claim": "none",
        "source_run_id": source_run_id,
        "source_artifact_id": source_artifact_id,
        "trigger_head_sha": trigger_sha,
        "attempt_ledger_revision": actual_revision,
        "attempt_count": recomputed["attempt_count"],
        "rejected_attempt_count": rejected_attempt_count,
        "admitted_attempt": acquisition_attempt,
        "attempt_ledger": recomputed,
        "network_access": False,
        "live_orders": False,
    }
    return {**base, "selection_audit_id": _canonical_id(base)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cocomelon-selection-audit")
    parser.add_argument("--cohort-root", required=True, type=Path)
    parser.add_argument("--source-run-id", required=True, type=int)
    parser.add_argument("--source-artifact-id", required=True, type=int)
    parser.add_argument("--expected-ledger-revision", required=True)
    parser.add_argument("--out", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    payload = build_selection_audit(
        cast(Path, args.cohort_root),
        source_run_id=int(args.source_run_id),
        source_artifact_id=int(args.source_artifact_id),
        expected_ledger_revision=str(args.expected_ledger_revision),
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
