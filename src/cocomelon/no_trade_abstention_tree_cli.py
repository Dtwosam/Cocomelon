from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

from cocomelon.research.continuous_paper_decision_facts import (
    ContinuousPaperDecisionFactStore,
)
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotStore,
)
from cocomelon.research.no_trade_abstention_tree import (
    build_no_trade_abstention_tree_report,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cocomelon-no-trade-abstention-tree",
        description=(
            "Evaluate a fixed shallow tree on genuine strategy-abstention "
            "forward returns using chronological holdout"
        ),
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--decision-store-dir", required=True, type=Path)
    parser.add_argument("--feature-store-dir", required=True, type=Path)
    parser.add_argument("--split-fraction", default="0.70")
    parser.add_argument("--min-training-rows", type=int, default=500)
    parser.add_argument("--min-validation-rows", type=int, default=300)
    parser.add_argument("--validation-blocks", type=int, default=4)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        forward_report = json.loads(args.input.read_text(encoding="utf-8"))
        if not isinstance(forward_report, dict):
            raise ValueError("input must contain a JSON object")
        report = build_no_trade_abstention_tree_report(
            forward_report,
            ContinuousPaperDecisionFactStore(args.decision_store_dir),
            LearningFeatureSnapshotStore(args.feature_store_dir),
            split_fraction=Decimal(args.split_fraction),
            min_training_rows=args.min_training_rows,
            min_validation_rows=args.min_validation_rows,
            validation_blocks=args.validation_blocks,
        )
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
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
                "command": "no-trade-abstention-tree",
                **report,
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
