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
    prospective_side_conditioned_delay_summary,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="evaluate-prospective-side-conditioned-delay",
        description=(
            "Evaluate the frozen LONG=120s / SHORT=60s prospective "
            "candidate from an exact continuous-paper state root."
        ),
    )
    parser.add_argument("state_root", type=Path)
    parser.add_argument("--json-out", type=Path)
    return parser


def _outcomes(path: Path) -> tuple[DelayedEntryOutcome, ...]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    values = raw.get("outcomes")
    if not isinstance(values, list):
        raise ValueError(f"{path.name} outcomes must be a list")
    return tuple(
        DelayedEntryOutcome.from_payload(value)
        for value in values
    )


def evaluate_state(state_root: Path) -> dict[str, object]:
    state = ProspectiveSideConditionedDelayState.from_payload(
        json.loads(
            (
                state_root
                / "prospective-side-conditioned-delay-state.json"
            ).read_text(encoding="utf-8")
        )
    )
    base = _outcomes(
        state_root / "delayed-entry-execution-shadow-state.json"
    )
    challenger = _outcomes(
        state_root / "delayed-entry-120s-execution-shadow-state.json"
    )
    journal = JournalStore(state_root / "journal.sqlite3")
    try:
        return prospective_side_conditioned_delay_summary(
            journal,
            base,
            challenger,
            state,
        )
    finally:
        journal.close()


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = evaluate_state(args.state_root)
    encoded = json.dumps(
        report,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
