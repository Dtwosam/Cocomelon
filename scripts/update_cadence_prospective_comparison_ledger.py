from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from cocomelon.research.prospective_comparison_ledger import (
    ProspectiveComparisonLedgerError,
    load_comparison_ledger,
    update_comparison_ledger,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="update-cadence-prospective-comparison-ledger",
        description=(
            "Build or extend the append-only paired prediction ledger "
            "for the frozen prospective cadence model A/B."
        ),
    )
    parser.add_argument("comparison_path", type=Path)
    parser.add_argument("microstructure_path", type=Path)
    parser.add_argument("baseline_path", type=Path)
    parser.add_argument("--previous", type=Path)
    parser.add_argument(
        "--source-comparison-run-id",
        type=int,
        required=True,
    )
    parser.add_argument(
        "--source-comparison-run-attempt",
        type=int,
        required=True,
    )
    parser.add_argument(
        "--source-artifact-name",
        required=True,
    )
    parser.add_argument("--json-out", type=Path, required=True)
    return parser


def _load_object(path: Path) -> dict[str, object]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ProspectiveComparisonLedgerError(
            f"{path.name} must contain an object"
        )
    return raw


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        comparison = _load_object(args.comparison_path)
        microstructure = _load_object(args.microstructure_path)
        baseline = _load_object(args.baseline_path)
        previous = (
            None
            if args.previous is None
            else load_comparison_ledger(args.previous)
        )
        ledger = update_comparison_ledger(
            comparison,
            microstructure,
            baseline,
            previous=previous,
            source_comparison_run_id=(
                args.source_comparison_run_id
            ),
            source_comparison_run_attempt=(
                args.source_comparison_run_attempt
            ),
            source_artifact_name=args.source_artifact_name,
        )
    except (
        OSError,
        json.JSONDecodeError,
        ProspectiveComparisonLedgerError,
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
