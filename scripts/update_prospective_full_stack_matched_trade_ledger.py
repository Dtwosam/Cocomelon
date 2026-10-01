from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from cocomelon.journal.store import JournalStore
from cocomelon.research.prospective_full_stack_matched_trade_ledger import (
    load_full_stack_matched_trade_ledger,
    update_full_stack_matched_trade_ledger,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Extend the append-only full-stack matched-trade ledger."
        )
    )
    parser.add_argument("journal_path", type=Path)
    parser.add_argument("summary_path", type=Path)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--source-paper-run-id", type=int, required=True)
    parser.add_argument(
        "--source-paper-run-attempt",
        type=int,
        required=True,
    )
    parser.add_argument("--source-artifact-name", required=True)
    parser.add_argument("--source-artifact-digest", required=True)
    parser.add_argument("--json-out", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = json.loads(
        args.summary_path.read_text(encoding="utf-8")
    )
    previous = (
        None
        if args.previous is None
        else load_full_stack_matched_trade_ledger(args.previous)
    )
    journal = JournalStore(args.journal_path)
    try:
        trades = tuple(journal.iter_trades())
    finally:
        journal.close()

    ledger = update_full_stack_matched_trade_ledger(
        trades,
        summary,
        previous=previous,
        source_paper_run_id=args.source_paper_run_id,
        source_paper_run_attempt=args.source_paper_run_attempt,
        source_artifact_name=args.source_artifact_name,
        source_artifact_digest=args.source_artifact_digest,
    )
    args.json_out.write_text(
        json.dumps(
            ledger,
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "row_count": ledger["row_count"],
                "new_row_count": ledger["new_row_count"],
                "pending_trade_count": ledger["pending_trade_count"],
                "ledger_sha256": ledger["ledger_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
