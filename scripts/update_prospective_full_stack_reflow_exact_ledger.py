from __future__ import annotations

import argparse
import json
from pathlib import Path

from cocomelon.research.prospective_full_stack_reflow_exact_ledger import (
    load_full_stack_reflow_exact_ledger,
    update_full_stack_reflow_exact_ledger,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Extend the append-only full-stack reflow exact-PnL ledger."
        )
    )
    parser.add_argument("summary", type=Path)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--source-paper-run-id", type=int, required=True)
    parser.add_argument(
        "--source-paper-run-attempt",
        type=int,
        required=True,
    )
    parser.add_argument(
        "--source-artifact-name",
        required=True,
    )
    parser.add_argument(
        "--source-artifact-digest",
        required=True,
    )
    parser.add_argument("--json-out", type=Path, required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    previous = (
        None
        if args.previous is None
        else load_full_stack_reflow_exact_ledger(args.previous)
    )
    ledger = update_full_stack_reflow_exact_ledger(
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
                "pending_option_horizons": (
                    ledger["pending_option_horizons"]
                ),
                "ledger_sha256": ledger["ledger_sha256"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
