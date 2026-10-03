from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from cocomelon.research.prospective_risk_rejected_stop_path_ledger import (
    RiskRejectedStopPathLedgerError,
    load_risk_rejected_stop_path_ledger,
    update_risk_rejected_stop_path_ledger,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="update-prospective-risk-rejected-stop-path-ledger",
        description=(
            "Build or extend the append-only observed stop-path overlay "
            "for risk-rejected full-stack opportunities."
        ),
    )
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


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RiskRejectedStopPathLedgerError(
            "risk-rejected stop-path summary file is invalid"
        ) from exc


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = _load_json(args.summary_path)
        previous = (
            None
            if args.previous is None
            else load_risk_rejected_stop_path_ledger(args.previous)
        )
        ledger = update_risk_rejected_stop_path_ledger(
            summary,
            previous=previous,
            source_paper_run_id=args.source_paper_run_id,
            source_paper_run_attempt=args.source_paper_run_attempt,
            source_artifact_name=args.source_artifact_name,
            source_artifact_digest=args.source_artifact_digest,
        )
    except (RiskRejectedStopPathLedgerError, ValueError) as exc:
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
