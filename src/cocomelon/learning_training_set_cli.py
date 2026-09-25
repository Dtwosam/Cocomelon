from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from cocomelon.research.learning_challenger_run import (
    verify_learning_challenger_run_manifest,
)
from cocomelon.research.learning_dataset_bundle import (
    load_verified_learning_dataset_bundle,
)
from cocomelon.research.learning_training_bundle import (
    write_learning_training_bundle,
)
from cocomelon.research.learning_training_rows import build_learning_training_set


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
        prog="cocomelon-learning-training-set",
        description=(
            "Materialize a target-isolated training bundle from an authenticated "
            "learning dataset and frozen challenger run manifest"
        ),
    )
    parser.add_argument("--bundle-dir", required=True, type=Path)
    parser.add_argument("--run-manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        bundle = load_verified_learning_dataset_bundle(
            output_dir=args.bundle_dir,
        )
        manifest = verify_learning_challenger_run_manifest(
            args.run_manifest,
            bundle=bundle,
        )
        training_set = build_learning_training_set(bundle, manifest)
        written = write_learning_training_bundle(
            training_set,
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
            "command": "learning-training-set",
            "run_id": training_set.run_id,
            "dataset_id": training_set.dataset_id,
            "dataset_lineage_id": training_set.dataset_lineage_id,
            "training_set_id": training_set.training_set_id,
            "evidence_kind": training_set.evidence_kind,
            "target_name": training_set.target_name,
            "row_count": len(training_set.rows),
            "rows_sha256": written["rows_sha256"],
            "manifest_sha256": written["manifest_sha256"],
            "output_dir": str(args.output_dir),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
