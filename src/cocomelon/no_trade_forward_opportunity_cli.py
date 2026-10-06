from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from cocomelon.research.continuous_paper_decision_facts import (
    ContinuousPaperDecisionFactStore,
)
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotStore,
)
from cocomelon.research.no_trade_forward_opportunity import (
    build_no_trade_forward_opportunity_report,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cocomelon-no-trade-forward-opportunity",
        description=(
            "Build research-only forward market outcomes for continuous-paper "
            "NO_TRADE decisions"
        ),
    )
    parser.add_argument("--decision-store-dir", required=True, type=Path)
    parser.add_argument("--feature-store-dir", required=True, type=Path)
    parser.add_argument("--as-of-ms", required=True, type=int)
    parser.add_argument("--min-group-rows", type=int, default=20)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = build_no_trade_forward_opportunity_report(
            ContinuousPaperDecisionFactStore(args.decision_store_dir),
            LearningFeatureSnapshotStore(args.feature_store_dir),
            as_of_ms=args.as_of_ms,
            min_group_rows=args.min_group_rows,
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
                "command": "no-trade-forward-opportunity",
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
