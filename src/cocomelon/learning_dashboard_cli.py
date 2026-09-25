from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from cocomelon.research.learning_dashboard import (
    build_learning_operations_status,
    render_learning_operations_markdown,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cocomelon-learning-ops-status",
        description=(
            "Render provenance-safe continuous-learning operations status without "
            "economic performance or execution authority"
        ),
    )
    parser.add_argument("--state-root", required=True, type=Path)
    parser.add_argument("--cycle-root", type=Path)
    parser.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="json",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        status = build_learning_operations_status(
            args.state_root,
            cycle_root=args.cycle_root,
        )
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
        print(render_learning_operations_markdown(status), end="")
    else:
        print(
            json.dumps(
                status,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
