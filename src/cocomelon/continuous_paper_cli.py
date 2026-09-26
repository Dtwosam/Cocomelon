from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from pathlib import Path

from cocomelon.continuous_paper import ContinuousPaperConfig, run_continuous_paper_session


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cocomelon-continuous-paper")
    parser.add_argument("--state-root", required=True, type=Path)
    parser.add_argument("--duration-seconds", type=int, default=19_800)
    parser.add_argument("--deep-limit", type=int, default=20)
    parser.add_argument("--context-poll-seconds", type=int, default=60)
    parser.add_argument("--selection-refresh-seconds", type=int, default=300)
    parser.add_argument("--checkpoint-seconds", type=int, default=30)
    parser.add_argument("--stop-file", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    config = ContinuousPaperConfig(
        duration_seconds=args.duration_seconds,
        deep_limit=args.deep_limit,
        context_poll_seconds=args.context_poll_seconds,
        selection_refresh_seconds=args.selection_refresh_seconds,
        checkpoint_seconds=args.checkpoint_seconds,
    )
    summary = asyncio.run(
        run_continuous_paper_session(
            args.state_root,
            config,
            stop_file=args.stop_file,
        )
    )
    print(json.dumps(summary.payload(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
