from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from cocomelon.research.learning_experiment import verify_learning_experiment


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
        prog="cocomelon-learning-experiment-verify",
        description=(
            "Verify the complete lineage and research-only authority of a "
            "materialized learning experiment"
        ),
    )
    parser.add_argument("--output-root", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = verify_learning_experiment(output_root=args.output_root)
    except (OSError, RuntimeError, ValueError) as exc:
        _emit(
            {"error": str(exc), "error_type": type(exc).__name__},
            stream=sys.stderr,
        )
        return 2

    _emit(
        {
            "command": "learning-experiment-verify",
            **result.to_dict(),
            "verified": True,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
