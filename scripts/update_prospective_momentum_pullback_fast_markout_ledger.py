from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from cocomelon.research.prospective_momentum_pullback_entry import (
    ProspectiveMomentumPullbackEntryError,
    ProspectiveMomentumPullbackEntryState,
)
from cocomelon.research.prospective_momentum_pullback_forward_markout_ledger import (
    ProspectiveMomentumPullbackForwardMarkoutLedgerError,
    load_momentum_pullback_forward_markout_ledger,
    update_momentum_pullback_forward_markout_ledger,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="update-prospective-momentum-pullback-fast-markout-ledger",
        description=(
            "Build or extend the append-only terminal fast forward-markout "
            "ledger for the frozen momentum-pullback challenger."
        ),
    )
    parser.add_argument("summary_path", type=Path)
    parser.add_argument("state_path", type=Path)
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
        raise ProspectiveMomentumPullbackForwardMarkoutLedgerError(
            f"{label} file is invalid"
        ) from exc


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = _load_json(
            args.summary_path,
            label="momentum-pullback fast-markout summary",
        )
        state = ProspectiveMomentumPullbackEntryState.from_payload(
            _load_json(
                args.state_path,
                label="momentum-pullback state",
            )
        )
        previous = (
            None
            if args.previous is None
            else load_momentum_pullback_forward_markout_ledger(
                args.previous
            )
        )
        ledger = update_momentum_pullback_forward_markout_ledger(
            summary,
            state,
            previous=previous,
            source_paper_run_id=args.source_paper_run_id,
            source_paper_run_attempt=args.source_paper_run_attempt,
            source_artifact_name=args.source_artifact_name,
            source_artifact_digest=args.source_artifact_digest,
        )
    except (
        ProspectiveMomentumPullbackForwardMarkoutLedgerError,
        ProspectiveMomentumPullbackEntryError,
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
                "candidate_id": ledger["candidate_id"],
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
