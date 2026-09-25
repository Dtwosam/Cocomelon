from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from cocomelon.research.learning_clean_finalization import (
    build_learning_clean_finalization,
    verify_learning_clean_finalization,
    write_learning_clean_finalization,
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
        prog="cocomelon-learning-clean-finalize",
        description=(
            "Finalize a verified learned clean-validation score into a "
            "research-only candidate-review verdict"
        ),
    )
    parser.add_argument("--package-root", required=True, type=Path)
    parser.add_argument("--validation-spec", required=True, type=Path)
    parser.add_argument("--validation-score", required=True, type=Path)
    parser.add_argument("--evidence-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--finalized-at-ms", required=True, type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        finalization = build_learning_clean_finalization(
            package_root=args.package_root,
            validation_spec_path=args.validation_spec,
            validation_score_path=args.validation_score,
            evidence_root=args.evidence_root,
            finalized_at_ms=args.finalized_at_ms,
        )
        path = write_learning_clean_finalization(
            args.output_root,
            finalization,
        )
        verified = verify_learning_clean_finalization(
            path,
            package_root=args.package_root,
            validation_spec_path=args.validation_spec,
            validation_score_path=args.validation_score,
            evidence_root=args.evidence_root,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        _emit(
            {"error": str(exc), "error_type": type(exc).__name__},
            stream=sys.stderr,
        )
        return 2

    _emit(
        {
            "command": "learning-clean-finalize",
            "path": str(path),
            **verified.to_dict(),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
