from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path

from cocomelon.research.no_trade_context_stability import (
    DEFAULT_MATERIAL_THRESHOLDS_BPS,
    build_no_trade_context_stability_report,
)


def _decimal(value: str) -> Decimal:
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError("must be a decimal") from exc
    if not result.is_finite():
        raise argparse.ArgumentTypeError("must be finite")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cocomelon-no-trade-context-stability",
        description=(
            "Require skipped-opportunity context patterns to survive a "
            "chronological holdout before treating them as research candidates"
        ),
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--split-fraction", type=_decimal, default=Decimal("0.70"))
    parser.add_argument(
        "--threshold-bps",
        action="append",
        type=int,
        dest="thresholds",
        help="Material absolute move threshold in basis points; may be repeated.",
    )
    parser.add_argument("--min-discovery-rows", type=int, default=40)
    parser.add_argument("--min-validation-rows", type=int, default=20)
    parser.add_argument(
        "--min-discovery-direction-share",
        type=_decimal,
        default=Decimal("0.60"),
    )
    parser.add_argument(
        "--min-validation-direction-share",
        type=_decimal,
        default=Decimal("0.55"),
    )
    parser.add_argument(
        "--min-validation-lift",
        type=_decimal,
        default=Decimal("0.05"),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("input report must be an object")
        thresholds = (
            tuple(args.thresholds)
            if args.thresholds is not None
            else DEFAULT_MATERIAL_THRESHOLDS_BPS
        )
        report = build_no_trade_context_stability_report(
            payload,
            split_fraction=args.split_fraction,
            material_thresholds_bps=thresholds,
            min_discovery_rows=args.min_discovery_rows,
            min_validation_rows=args.min_validation_rows,
            min_discovery_direction_share=args.min_discovery_direction_share,
            min_validation_direction_share=args.min_validation_direction_share,
            min_validation_lift=args.min_validation_lift,
        )
    except (
        OSError,
        json.JSONDecodeError,
        RuntimeError,
        ValueError,
    ) as exc:
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
                "command": "no-trade-context-stability",
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
