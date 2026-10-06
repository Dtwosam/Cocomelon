from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.research.continuous_paper_decision_export import (
    export_continuous_paper_decision_facts,
)
from cocomelon.research.continuous_paper_decision_facts import (
    ContinuousPaperDecisionFactStore,
)
from cocomelon.research.continuous_paper_learning import (
    CONTINUOUS_PAPER_REPLAY_RUN_ID,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cocomelon-continuous-paper-decision-export",
        description=(
            "Export compact immutable decision facts from the durable "
            "continuous-paper fact database"
        ),
    )
    parser.add_argument("--facts", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--replay-run-id",
        default=CONTINUOUS_PAPER_REPLAY_RUN_ID,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    facts = EvaluationFactStore(args.facts)
    try:
        report = export_continuous_paper_decision_facts(
            facts,
            ContinuousPaperDecisionFactStore(args.output_dir),
            replay_run_id=args.replay_run_id,
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
    finally:
        facts.close()

    print(
        json.dumps(
            {
                "command": "continuous-paper-decision-export",
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
