from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from cocomelon.research.prospective_prediction_ledger import (
    ProspectivePredictionLedgerError,
    load_prediction_ledger,
    update_prediction_ledger,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="update-cadence-prospective-prediction-ledger",
        description=(
            "Build or extend the append-only prediction ledger for the "
            "frozen prospective cadence microstructure challenger."
        ),
    )
    parser.add_argument("report_path", type=Path)
    parser.add_argument("--previous", type=Path)
    parser.add_argument(
        "--source-audit-run-id",
        type=int,
        required=True,
    )
    parser.add_argument(
        "--source-audit-run-attempt",
        type=int,
        required=True,
    )
    parser.add_argument(
        "--source-report-artifact-name",
        required=True,
    )
    parser.add_argument("--json-out", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = json.loads(
            args.report_path.read_text(encoding="utf-8")
        )
        if not isinstance(report, dict):
            raise ProspectivePredictionLedgerError(
                "prospective report must be an object"
            )
        previous = (
            None
            if args.previous is None
            else load_prediction_ledger(args.previous)
        )
        ledger = update_prediction_ledger(
            report,
            previous=previous,
            source_audit_run_id=args.source_audit_run_id,
            source_audit_run_attempt=args.source_audit_run_attempt,
            source_report_artifact_name=(
                args.source_report_artifact_name
            ),
        )
    except (
        OSError,
        json.JSONDecodeError,
        ProspectivePredictionLedgerError,
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
