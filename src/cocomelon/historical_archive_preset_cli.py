from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TextIO

from cocomelon.config import ExecutionMode, Settings
from cocomelon.hyperliquid.client import InfoClient
from cocomelon.research.historical_archive_acquisition import plan_archive_shards
from cocomelon.research.historical_archive_presets import (
    PRESET_NAME,
    get_archive_experiment_preset,
    run_archive_experiment_preset,
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


def _clock(received_at_ms: int | None) -> Callable[[], int]:
    if received_at_ms is None:
        return lambda: time.time_ns() // 1_000_000
    if received_at_ms < 0:
        raise ValueError("received_at_ms must be non-negative")
    return lambda: received_at_ms


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cocomelon-historical-archive-preset",
        description="Inspect or run a frozen touched archive research preset",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    show = subparsers.add_parser("show")
    show.add_argument("--preset", default=PRESET_NAME)

    keys = subparsers.add_parser("keys")
    keys.add_argument("--preset", default=PRESET_NAME)

    run = subparsers.add_parser("run")
    run.add_argument("--preset", default=PRESET_NAME)
    run.add_argument("--archive-root", required=True, type=Path)
    run.add_argument("--source-root", required=True, type=Path)
    run.add_argument("--output-root", required=True, type=Path)
    run.add_argument("--received-at-ms", type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        preset = get_archive_experiment_preset(args.preset)
        if args.command == "show":
            _emit(
                {
                    "command": "show",
                    "paid_request_performed": False,
                    **preset.to_dict(),
                }
            )
            return 0
        if args.command == "keys":
            shards = plan_archive_shards(
                start_ms=preset.start_ms,
                end_ms=preset.end_ms,
            )
            _emit(
                {
                    "command": "keys",
                    "preset": preset.name,
                    "preset_id": preset.preset_id,
                    "paid_request_performed": False,
                    "shard_count": len(shards),
                    "keys": tuple(item.key for item in shards),
                }
            )
            return 0

        settings = Settings.from_env()
        if settings.execution_mode is not ExecutionMode.PAPER:
            raise ValueError("historical archive presets require paper execution mode")
        result = run_archive_experiment_preset(
            InfoClient(settings),
            preset=preset,
            archive_root=args.archive_root,
            source_root=args.source_root,
            output_root=args.output_root,
            clock_ms=_clock(args.received_at_ms),
        )
    except (OSError, RuntimeError, ValueError) as exc:
        _emit(
            {"error": str(exc), "error_type": type(exc).__name__},
            stream=sys.stderr,
        )
        return 2

    _emit(
        {
            "command": "run",
            "preset": preset.name,
            "preset_id": preset.preset_id,
            "evidence_class": preset.evidence_class,
            "archive_manifest_id": result.archive.manifest_id,
            "archive_shard_count": result.archive.shard_count,
            "archive_total_byte_count": result.archive.total_byte_count,
            "overlap_report_id": result.overlap.report_id,
            "overlap_compared_count": result.overlap.compared_count,
            "dataset_id": result.dataset_id,
            "report_id": result.report_id,
            "row_count": result.comparison.dataset_row_count,
            "fold_count": len(result.comparison.baseline_folds),
            "output_root": str(args.output_root),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
