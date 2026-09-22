from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from cocomelon.research.prospective_blind_monitor import (
    build_prospective_hype_blind_monitor,
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
        prog="cocomelon-prospective-hype-blind-monitor",
        description=(
            "Build a redacted operational health receipt for the frozen HYPE "
            "prospective campaign"
        ),
    )
    parser.add_argument("--health", required=True, type=Path)
    parser.add_argument("--lineage", required=True, type=Path)
    parser.add_argument("--state-artifact-id", required=True)
    parser.add_argument("--audited-at-ms", required=True, type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        monitor = build_prospective_hype_blind_monitor(
            args.health,
            args.lineage,
            expected_state_artifact_id=args.state_artifact_id,
            audited_at_ms=args.audited_at_ms,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        _emit(
            {"error": str(exc), "error_type": type(exc).__name__},
            stream=sys.stderr,
        )
        return 2

    _emit(monitor.to_dict())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
