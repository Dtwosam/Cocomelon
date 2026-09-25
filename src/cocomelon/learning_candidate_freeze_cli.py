from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from cocomelon.research.learning_candidate_freeze import (
    build_learning_candidate_freeze,
    verify_learning_candidate_freeze,
    write_learning_candidate_freeze,
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
        prog="cocomelon-learning-candidate-freeze",
        description=(
            "Freeze a development-qualified authenticated learning experiment "
            "into a prospective-only research candidate"
        ),
    )
    parser.add_argument("--experiment-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--frozen-at-ms", required=True, type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        freeze = build_learning_candidate_freeze(
            experiment_root=args.experiment_root,
            frozen_at_ms=args.frozen_at_ms,
        )
        path = write_learning_candidate_freeze(args.output_root, freeze)
        verified = verify_learning_candidate_freeze(
            path,
            experiment_root=args.experiment_root,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        _emit(
            {"error": str(exc), "error_type": type(exc).__name__},
            stream=sys.stderr,
        )
        return 2

    _emit(
        {
            "command": "learning-candidate-freeze",
            "path": str(path),
            **verified.to_dict(),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
