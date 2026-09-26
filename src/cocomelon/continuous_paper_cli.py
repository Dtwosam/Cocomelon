from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from pathlib import Path

from cocomelon.continuous_paper import ContinuousPaperConfig, run_continuous_paper_session
from cocomelon.research.continuous_paper_learning import ContinuousPaperRuntimeIdentity


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cocomelon-continuous-paper")
    parser.add_argument("--state-root", required=True, type=Path)
    parser.add_argument("--duration-seconds", type=int, default=19_800)
    parser.add_argument("--deep-limit", type=int, default=20)
    parser.add_argument("--context-poll-seconds", type=int, default=60)
    parser.add_argument("--selection-refresh-seconds", type=int, default=300)
    parser.add_argument("--checkpoint-seconds", type=int, default=30)
    parser.add_argument("--stop-file", type=Path)
    parser.add_argument("--worker-run-id", type=int)
    parser.add_argument("--worker-run-attempt", type=int)
    parser.add_argument("--worker-head-sha")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = ContinuousPaperConfig(
        duration_seconds=args.duration_seconds,
        deep_limit=args.deep_limit,
        context_poll_seconds=args.context_poll_seconds,
        selection_refresh_seconds=args.selection_refresh_seconds,
        checkpoint_seconds=args.checkpoint_seconds,
    )
    identity_values = (
        args.worker_run_id,
        args.worker_run_attempt,
        args.worker_head_sha,
    )
    if any(value is not None for value in identity_values) and not all(
        value is not None for value in identity_values
    ):
        parser.error(
            "worker-run-id, worker-run-attempt, and worker-head-sha "
            "must be provided together"
        )
    runtime_identity = (
        None
        if args.worker_run_id is None
        else ContinuousPaperRuntimeIdentity(
            worker_run_id=args.worker_run_id,
            worker_run_attempt=args.worker_run_attempt,
            worker_head_sha=args.worker_head_sha,
        )
    )
    summary = asyncio.run(
        run_continuous_paper_session(
            args.state_root,
            config,
            stop_file=args.stop_file,
            runtime_identity=runtime_identity,
        )
    )
    print(json.dumps(summary.payload(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
