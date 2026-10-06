from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from cocomelon.research.no_trade_context_prospective import (
    load_and_score_no_trade_context_candidate,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cocomelon-no-trade-context-prospective",
        description=(
            "Score a frozen skipped-context candidate only on post-freeze "
            "continuous-paper decisions"
        ),
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--freeze", required=True, type=Path)
    parser.add_argument("--selection-record", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = load_and_score_no_trade_context_candidate(
            forward_report_path=args.input,
            freeze_path=args.freeze,
            selection_record_path=args.selection_record,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(
            json.dumps(
                {"error": str(exc), "error_type": type(exc).__name__},
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 2

    print(
        json.dumps(
            {
                "command": "no-trade-context-prospective",
                **report.to_dict(),
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
