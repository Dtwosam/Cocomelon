from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from cocomelon.research.learning_cycle import run_learning_cycle


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
        prog="cocomelon-learning-cycle",
        description=(
            "Run the frozen research-only baseline and shallow-tree learning cycle "
            "only after authenticated cumulative evidence is structurally and "
            "chronologically ready"
        ),
    )
    parser.add_argument("--learning-root", required=True, type=Path)
    parser.add_argument("--feature-store-dir", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--as-of-ms", required=True, type=int)
    parser.add_argument("--implementation-commit-sha", required=True)
    parser.add_argument("--expected-learning-state-digest", required=True)
    parser.add_argument("--expected-feature-state-digest", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run_learning_cycle(
            learning_root=args.learning_root,
            feature_store_dir=args.feature_store_dir,
            output_root=args.output_root,
            as_of_ms=args.as_of_ms,
            implementation_commit_sha=args.implementation_commit_sha,
            expected_learning_state_digest=args.expected_learning_state_digest,
            expected_feature_state_digest=args.expected_feature_state_digest,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        _emit(
            {"error": str(exc), "error_type": type(exc).__name__},
            stream=sys.stderr,
        )
        return 2

    _emit(
        {
            "command": "learning-cycle",
            **result.to_dict(),
        }
    )
    return 0 if result.status == "completed" else 3


if __name__ == "__main__":
    raise SystemExit(main())
