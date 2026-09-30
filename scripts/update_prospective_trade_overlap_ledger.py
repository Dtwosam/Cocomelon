from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from cocomelon.research.prospective_trade_overlap_ledger import (
    update_trade_overlap_ledger_from_files,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="update-prospective-trade-overlap-ledger",
        description=(
            "Join the immutable prospective cadence prediction ledger to "
            "exact closed paper trades by strategy decision ID."
        ),
    )
    parser.add_argument("prediction_ledger", type=Path)
    parser.add_argument("journal", type=Path)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--paper-run-id", type=int, required=True)
    parser.add_argument("--paper-run-attempt", type=int, required=True)
    parser.add_argument("--learning-artifact-name", required=True)
    parser.add_argument("--learning-artifact-digest", required=True)
    parser.add_argument("--json-out", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = update_trade_overlap_ledger_from_files(
        args.prediction_ledger,
        args.journal,
        previous_path=args.previous,
        source_paper_run_id=args.paper_run_id,
        source_paper_run_attempt=args.paper_run_attempt,
        source_learning_artifact_name=args.learning_artifact_name,
        source_learning_artifact_digest=args.learning_artifact_digest,
    )
    encoded = json.dumps(
        payload,
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
