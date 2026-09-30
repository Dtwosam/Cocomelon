from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from cocomelon.journal.store import JournalStore
from cocomelon.research.delayed_entry_execution_shadow import (
    DelayedEntryOutcome,
)
from cocomelon.research.prospective_side_conditioned_delay import (
    ProspectiveSideConditionedDelayState,
)
from cocomelon.research.prospective_timing_ledger import (
    ProspectiveTimingLedgerError,
    extract_prospective_timing_rows,
    load_timing_ledger,
    update_timing_ledger,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="update-prospective-side-conditioned-timing-ledger",
        description=(
            "Build or extend the append-only row ledger for the frozen "
            "LONG=120s / SHORT=60s prospective timing candidate."
        ),
    )
    parser.add_argument("state_root", type=Path)
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
        "--source-timing-artifact-name",
        required=True,
    )
    parser.add_argument("--json-out", type=Path, required=True)
    return parser


def _outcomes(path: Path) -> tuple[DelayedEntryOutcome, ...]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    values = raw.get("outcomes")
    if not isinstance(values, list):
        raise ProspectiveTimingLedgerError(
            f"{path.name} outcomes must be a list"
        )
    return tuple(
        DelayedEntryOutcome.from_payload(value)
        for value in values
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    state_root: Path = args.state_root
    try:
        state = ProspectiveSideConditionedDelayState.from_payload(
            json.loads(
                (
                    state_root
                    / "prospective-side-conditioned-delay-state.json"
                ).read_text(encoding="utf-8")
            )
        )
        base = _outcomes(
            state_root
            / "delayed-entry-execution-shadow-state.json"
        )
        challenger = _outcomes(
            state_root
            / "delayed-entry-120s-execution-shadow-state.json"
        )
        journal = JournalStore(state_root / "journal.sqlite3")
        try:
            rows, diagnostics = extract_prospective_timing_rows(
                journal,
                base,
                challenger,
                state,
            )
        finally:
            journal.close()
        previous = (
            None
            if args.previous is None
            else load_timing_ledger(args.previous)
        )
        ledger = update_timing_ledger(
            rows,
            diagnostics,
            state,
            previous=previous,
            source_paper_run_id=args.source_paper_run_id,
            source_paper_run_attempt=args.source_paper_run_attempt,
            source_timing_artifact_name=(
                args.source_timing_artifact_name
            ),
        )
    except (
        OSError,
        json.JSONDecodeError,
        ProspectiveTimingLedgerError,
        ValueError,
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
