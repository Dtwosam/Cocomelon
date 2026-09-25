from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from cocomelon.research.learning_clean_review_queue import (
    build_learning_clean_review_queue,
    render_learning_clean_review_markdown,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cocomelon-learning-clean-review-queue",
        description=(
            "Render a non-economic review queue for verified learned "
            "clean-validation lineages"
        ),
    )
    parser.add_argument(
        "--state-root",
        action="append",
        required=True,
        type=Path,
        dest="state_roots",
    )
    parser.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="json",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        queue = build_learning_clean_review_queue(args.state_roots)
    except (OSError, RuntimeError, ValueError) as exc:
        print(
            json.dumps(
                {"error": str(exc), "error_type": type(exc).__name__},
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 2

    if args.format == "markdown":
        print(render_learning_clean_review_markdown(queue), end="")
    else:
        print(
            json.dumps(
                queue,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
