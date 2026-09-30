from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from cocomelon.research.prospective_candidate_failure_receipts import (
    ProspectiveCandidateFailureReceiptError,
    update_candidate_failure_receipts,
)


def _load(path: Path) -> dict[str, object]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ProspectiveCandidateFailureReceiptError(
            "JSON_OBJECT_REQUIRED"
        )
    return raw


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="update-prospective-candidate-failure-receipts",
    )
    parser.add_argument("readiness_path", type=Path)
    parser.add_argument(
        "--source-readiness-run-id",
        type=int,
        required=True,
    )
    parser.add_argument(
        "--source-readiness-run-attempt",
        type=int,
        required=True,
    )
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--json-out", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    previous = None
    if args.previous is not None:
        previous = _load(args.previous)
    ledger = update_candidate_failure_receipts(
        _load(args.readiness_path),
        source_readiness_run_id=args.source_readiness_run_id,
        source_readiness_run_attempt=args.source_readiness_run_attempt,
        previous=previous,
    )
    encoded = json.dumps(
        ledger,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
