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
from cocomelon.research.learning_training_input import (
    build_learning_training_table,
    write_learning_training_bundle,
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
        prog="cocomelon-learning-training-bundle",
        description=(
            "Materialize an authenticated training bundle from a verified "
            "learning dataset and frozen challenger run manifest"
        ),
    )
    parser.add_argument("--source-bundle-dir", required=True, type=Path)
    parser.add_argument("--run-manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        source_bundle = load_verified_learning_dataset_bundle(
            output_dir=args.source_bundle_dir,
        )
        run_manifest = verify_learning_challenger_run_manifest(
            args.run_manifest,
            bundle=source_bundle,
        )
        table = build_learning_training_table(source_bundle, run_manifest)
        persisted = write_learning_training_bundle(
            table,
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
            "command": "learning-training-bundle",
            "run_id": table.run_id,
            "dataset_lineage_id": table.dataset_lineage_id,
            "table_id": table.table_id,
            "evidence_kind": table.evidence_kind,
            "target_name": table.target_name,
            "row_count": len(table.rows),
            "rows_sha256": table.rows_sha256,
            "manifest_sha256": persisted["manifest_sha256"],
            "rows_file_sha256": persisted["rows_file_sha256"],
            "output_dir": str(args.output_dir),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
