from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from cocomelon.research.learning_challenger_run import (
    load_learning_challenger_run_manifest,
)
from cocomelon.research.learning_training_bundle import (
    verify_learning_training_bundle,
)
from cocomelon.research.learning_tree import (
    evaluate_learning_tree,
    write_learning_tree_evaluation,
)


def _emit(payload: dict[str, object], *, stream: TextIO | None = None) -> None:
    target = sys.stdout if stream is None else stream
    print(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ),
        file=target,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cocomelon-learning-tree",
        description=(
            "Evaluate a frozen shallow nonlinear learning filter on an "
            "authenticated chronological holdout"
        ),
    )
    parser.add_argument("--training-bundle-dir", required=True, type=Path)
    parser.add_argument("--run-manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest = load_learning_challenger_run_manifest(args.run_manifest)
        training_bundle = verify_learning_training_bundle(
            output_dir=args.training_bundle_dir,
            manifest=manifest,
        )
        evaluation = evaluate_learning_tree(training_bundle, manifest)
        write_learning_tree_evaluation(args.output, evaluation)
    except (OSError, RuntimeError, ValueError) as exc:
        _emit(
            {"error": str(exc), "error_type": type(exc).__name__},
            stream=sys.stderr,
        )
        return 2

    _emit(
        {
            "command": "learning-tree",
            "evaluation_id": evaluation.evaluation_id,
            "run_id": evaluation.run_id,
            "training_bundle_id": evaluation.training_bundle_id,
            "train_row_count": evaluation.train_row_count,
            "validation_row_count": evaluation.validation_row_count,
            "overlap_excluded_count": evaluation.overlap_excluded_count,
            "validation_trade_count": evaluation.overall.trade_count,
            "validation_no_trade_count": evaluation.overall.no_trade_count,
            "validation_mean_target": (
                None
                if evaluation.overall.mean_target is None
                else str(evaluation.overall.mean_target)
            ),
            "prediction_sha256": evaluation.prediction_sha256,
            "qualifies_development": evaluation.qualifies_development,
            "research_only": evaluation.research_only,
            "promotion_eligible": evaluation.promotion_eligible,
            "execution_ready": evaluation.execution_ready,
            "output": str(args.output),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
