from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from cocomelon.research.prospective_combined_entry_filter import (
    ProspectiveCombinedEntryFilterError,
    ProspectiveCombinedEntryFilterState,
)
from cocomelon.research.prospective_full_stack_forward_markout_ledger import (
    ProspectiveFullStackForwardMarkoutLedgerError,
    load_full_stack_forward_markout_ledger,
    update_full_stack_forward_markout_ledger,
)
from cocomelon.research.prospective_momentum_band_entry import (
    ProspectiveMomentumBandEntryError,
    ProspectiveMomentumBandEntryState,
)
from cocomelon.research.prospective_two_strike_stop_filter import (
    ProspectiveTwoStrikeStopFilterError,
    ProspectiveTwoStrikeStopFilterState,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="update-prospective-full-stack-fast-markout-ledger",
        description=(
            "Build or extend the append-only terminal forward-markout ledger "
            "for the frozen combined + two-strike + momentum entry stack."
        ),
    )
    parser.add_argument("summary_path", type=Path)
    parser.add_argument("combined_state_path", type=Path)
    parser.add_argument("two_strike_state_path", type=Path)
    parser.add_argument("momentum_state_path", type=Path)
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


def _load_json(path: Path, *, label: str) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProspectiveFullStackForwardMarkoutLedgerError(
            f"{label} file is invalid"
        ) from exc


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = _load_json(
            args.summary_path,
            label="full-stack fast-markout summary",
        )
        combined = ProspectiveCombinedEntryFilterState.from_payload(
            _load_json(
                args.combined_state_path,
                label="combined-filter state",
            )
        )
        two_strike = ProspectiveTwoStrikeStopFilterState.from_payload(
            _load_json(
                args.two_strike_state_path,
                label="two-strike state",
            )
        )
        momentum = ProspectiveMomentumBandEntryState.from_payload(
            _load_json(
                args.momentum_state_path,
                label="momentum-band state",
            )
        )
        previous = (
            None
            if args.previous is None
            else load_full_stack_forward_markout_ledger(
                args.previous
            )
        )
        ledger = update_full_stack_forward_markout_ledger(
            summary,
            combined,
            two_strike,
            momentum,
            previous=previous,
            source_paper_run_id=args.source_paper_run_id,
            source_paper_run_attempt=args.source_paper_run_attempt,
            source_artifact_name=args.source_artifact_name,
            source_artifact_digest=args.source_artifact_digest,
        )
    except (
        ProspectiveFullStackForwardMarkoutLedgerError,
        ProspectiveCombinedEntryFilterError,
        ProspectiveTwoStrikeStopFilterError,
        ProspectiveMomentumBandEntryError,
        ValueError,
    ) as exc:
        raise SystemExit(str(exc)) from exc

    args.json_out.write_text(
        json.dumps(
            ledger,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "candidate_stack": ledger["candidate_stack"],
                "row_count": ledger["row_count"],
                "new_row_count": ledger["new_row_count"],
                "pending_opportunity_count": ledger[
                    "pending_opportunity_count"
                ],
                "ledger_sha256": ledger["ledger_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
