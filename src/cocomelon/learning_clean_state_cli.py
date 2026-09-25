from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from cocomelon.research.learning_clean_state import (
    build_learning_clean_state,
    verify_learning_clean_state,
    write_learning_clean_state,
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
        prog="cocomelon-learning-clean-state",
        description=(
            "Build and verify economically blind operational state for one "
            "prospective learning clean-validation candidate"
        ),
    )
    parser.add_argument("--package-root", required=True, type=Path)
    parser.add_argument("--validation-spec", required=True, type=Path)
    parser.add_argument("--evidence-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--as-of-ms", required=True, type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        state = build_learning_clean_state(
            package_root=args.package_root,
            validation_spec_path=args.validation_spec,
            evidence_root=args.evidence_root,
            as_of_ms=args.as_of_ms,
        )
        path = write_learning_clean_state(args.output_root, state)
        verified = verify_learning_clean_state(
            path,
            package_root=args.package_root,
            validation_spec_path=args.validation_spec,
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
            "command": "learning-clean-state",
            "path": str(path),
            **verified.to_dict(),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
