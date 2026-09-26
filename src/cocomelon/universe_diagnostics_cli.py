from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from cocomelon.universe_diagnostics import (
    collect_universe_opportunity_diagnostics,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cocomelon-universe-diagnostics")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--deep-limit", type=int, default=20)
    parser.add_argument("--top-hip3-limit", type=int, default=10)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    report = collect_universe_opportunity_diagnostics(
        deep_limit=args.deep_limit,
        top_hip3_limit=args.top_hip3_limit,
    )
    encoded = json.dumps(
        report.payload(),
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    ) + "\n"
    if args.output is None:
        print(encoded, end="")
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(encoded, encoding="utf-8")


if __name__ == "__main__":
    main()
