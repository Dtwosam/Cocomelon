from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from cocomelon.research.prospective_comparison_ledger import (
    load_comparison_ledger,
)
from cocomelon.research.prospective_prediction_ledger import (
    load_prediction_ledger,
)
from cocomelon.research.prospective_timing_ledger import load_timing_ledger
from cocomelon.research.prospective_trade_quality_readiness import (
    ProspectiveTradeQualityReadinessError,
    prospective_trade_quality_readiness,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="evaluate-prospective-trade-quality-readiness",
        description=(
            "Join immutable cadence and timing ledgers into a fail-closed "
            "research readiness manifest."
        ),
    )
    parser.add_argument("prediction_ledger", type=Path)
    parser.add_argument("comparison_ledger", type=Path)
    parser.add_argument("timing_ledger", type=Path)
    parser.add_argument("--json-out", type=Path)
    return parser


def evaluate_paths(
    prediction_path: Path,
    comparison_path: Path,
    timing_path: Path,
) -> dict[str, object]:
    try:
        prediction = load_prediction_ledger(prediction_path)
        comparison = load_comparison_ledger(comparison_path)
        timing = load_timing_ledger(timing_path)
        return prospective_trade_quality_readiness(
            prediction,
            comparison,
            timing,
        )
    except RuntimeError as exc:
        raise ProspectiveTradeQualityReadinessError(str(exc)) from exc


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = evaluate_paths(
            args.prediction_ledger,
            args.comparison_ledger,
            args.timing_ledger,
        )
    except ProspectiveTradeQualityReadinessError as exc:
        raise SystemExit(str(exc)) from exc
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
