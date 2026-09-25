from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from cocomelon.research.learning_experiment import (
    materialize_learning_experiment,
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
        prog="cocomelon-learning-experiment",
        description=(
            "Materialize one self-contained authenticated learning experiment "
            "from a verified dataset and frozen challenger run"
        ),
    )
    parser.add_argument("--dataset-bundle-dir", required=True, type=Path)
    parser.add_argument("--run-manifest", required=True, type=Path)
    parser.add_argument("--feature-store-dir", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest = materialize_learning_experiment(
            dataset_bundle_dir=args.dataset_bundle_dir,
            run_manifest_path=args.run_manifest,
            feature_store_dir=args.feature_store_dir,
            output_dir=args.output_dir,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        _emit(
            {"error": str(exc), "error_type": type(exc).__name__},
            stream=sys.stderr,
        )
        return 2

    _emit(
        {
            "command": "learning-experiment",
            "experiment_id": manifest.experiment_id,
            "dataset_id": manifest.dataset_id,
            "dataset_lineage_id": manifest.dataset_lineage_id,
            "run_id": manifest.run_id,
            "training_set_id": manifest.training_set_id,
            "training_bundle_id": manifest.training_bundle_id,
            "model_family": manifest.model_family,
            "evaluation_id": manifest.evaluation_id,
            "feature_snapshot_count": manifest.feature_snapshot_count,
            "research_only": manifest.research_only,
            "promotion_eligible": manifest.promotion_eligible,
            "execution_ready": manifest.execution_ready,
            "output_dir": str(args.output_dir),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
