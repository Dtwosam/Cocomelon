from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from cocomelon.research.learning_candidate_package import (
    materialize_learning_candidate_package,
    verify_learning_candidate_package,
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
        prog="cocomelon-learning-candidate-package",
        description=(
            "Materialize and verify a self-contained prospective-only "
            "learning candidate package"
        ),
    )
    parser.add_argument("--experiment-root", required=True, type=Path)
    parser.add_argument("--candidate-freeze", required=True, type=Path)
    parser.add_argument("--package-root", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        path = materialize_learning_candidate_package(
            experiment_root=args.experiment_root,
            candidate_freeze_path=args.candidate_freeze,
            package_root=args.package_root,
        )
        package = verify_learning_candidate_package(args.package_root)
    except (OSError, RuntimeError, ValueError) as exc:
        _emit(
            {"error": str(exc), "error_type": type(exc).__name__},
            stream=sys.stderr,
        )
        return 2

    _emit(
        {
            "command": "learning-candidate-package",
            "path": str(path),
            **package.to_dict(),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
