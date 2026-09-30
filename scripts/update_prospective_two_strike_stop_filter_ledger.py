from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from cocomelon.journal.store import JournalStore
from cocomelon.research.prospective_two_strike_stop_filter import (
    ProspectiveTwoStrikeStopFilterState,
)
from cocomelon.research.prospective_two_strike_stop_filter_ledger import (
    ProspectiveTwoStrikeStopFilterLedgerError,
    load_two_strike_ledger,
    update_two_strike_ledger,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="update-prospective-two-strike-stop-filter-ledger",
        description=(
            "Build or extend the append-only future-only ledger for "
            "the frozen two-strike stop-filter challenger."
        ),
    )
    parser.add_argument("journal_path", type=Path)
    parser.add_argument("state_path", type=Path)
    parser.add_argument("--previous", type=Path)
    parser.add_argument(
        "--source-paper-run-id",
        type=int,
        required=True,
    )
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


def _load_state(
    path: Path,
) -> ProspectiveTwoStrikeStopFilterState:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return ProspectiveTwoStrikeStopFilterState.from_payload(raw)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    journal = JournalStore(args.journal_path)
    try:
        trades = tuple(journal.iter_trades())
    finally:
        journal.close()

    try:
        state = _load_state(args.state_path)
        previous = (
            None
            if args.previous is None
            else load_two_strike_ledger(args.previous)
        )
        ledger = update_two_strike_ledger(
            trades,
            state,
            previous=previous,
            source_paper_run_id=args.source_paper_run_id,
            source_paper_run_attempt=args.source_paper_run_attempt,
            source_artifact_name=args.source_artifact_name,
            source_artifact_digest=args.source_artifact_digest,
        )
    except (
        OSError,
        json.JSONDecodeError,
        ValueError,
        ProspectiveTwoStrikeStopFilterLedgerError,
    ) as exc:
        raise SystemExit(str(exc)) from exc

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
