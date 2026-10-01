from __future__ import annotations

import argparse
import json
from pathlib import Path

from cocomelon.journal.store import JournalStore
from cocomelon.research.prospective_breakeven_profit_lock import (
    ProspectiveBreakevenProfitLockState,
    prospective_breakeven_from_execution_ledger,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="evaluate-prospective-breakeven-profit-lock",
        description=(
            "Evaluate the frozen future-only breakeven profit-lock "
            "candidate from the authenticated paper journal and immutable "
            "profit-lock execution ledger."
        ),
    )
    parser.add_argument("journal")
    parser.add_argument("candidate_state")
    parser.add_argument("execution_ledger")
    parser.add_argument("--json-out")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    state_raw = json.loads(
        Path(args.candidate_state).read_text(encoding="utf-8")
    )
    state = ProspectiveBreakevenProfitLockState.from_payload(
        state_raw
    )
    ledger = json.loads(
        Path(args.execution_ledger).read_text(encoding="utf-8")
    )
    journal = JournalStore(args.journal)
    try:
        payload = prospective_breakeven_from_execution_ledger(
            tuple(journal.iter_trades()),
            ledger,
            state,
        )
    finally:
        journal.close()

    text = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    if args.json_out:
        Path(args.json_out).write_text(
            text + "\n",
            encoding="utf-8",
        )
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
