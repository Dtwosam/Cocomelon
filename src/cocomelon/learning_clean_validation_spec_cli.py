from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from cocomelon.research.learning_clean_validation_spec import (
    build_learning_clean_validation_spec,
    verify_learning_clean_validation_spec,
    write_learning_clean_validation_spec,
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
        prog="cocomelon-learning-clean-validation-spec",
        description=(
            "Freeze the prospective clean-validation protocol for a verified "
            "learning candidate package"
        ),
    )
    parser.add_argument("--package-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        spec = build_learning_clean_validation_spec(args.package_root)
        path = write_learning_clean_validation_spec(args.output_root, spec)
        verified = verify_learning_clean_validation_spec(
            path,
            package_root=args.package_root,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        _emit(
            {"error": str(exc), "error_type": type(exc).__name__},
            stream=sys.stderr,
        )
        return 2

    _emit(
        {
            "command": "learning-clean-validation-spec",
            "path": str(path),
            **verified.to_dict(),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
