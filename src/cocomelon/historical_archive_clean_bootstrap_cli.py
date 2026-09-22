from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TextIO

from cocomelon.research.historical_archive_clean_bootstrap import (
    bootstrap_archive_clean_state,
)
from cocomelon.research.historical_archive_clean_runtime import (
    load_pinned_archive_clean_runtime,
)
from cocomelon.util.time import utc_now_ms


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
        prog="cocomelon-historical-archive-clean-bootstrap",
        description=(
            "Create or verify pre-cutover PAPER-only archive clean bootstrap state"
        ),
    )
    parser.add_argument("--runtime-root", required=True, type=Path)
    parser.add_argument("--pin-id", required=True)
    parser.add_argument("--state-root", required=True, type=Path)
    parser.add_argument("--frozen-revision", required=True)
    parser.add_argument("--runtime-artifact-id", required=True)
    return parser


def archive_clean_bootstrap_payload(
    *,
    runtime_root: Path,
    pin_id: str,
    state_root: Path,
    frozen_revision: str,
    runtime_artifact_id: str,
    clock_ms: Callable[[], int] = utc_now_ms,
) -> dict[str, object]:
    pinned = load_pinned_archive_clean_runtime(
        runtime_root,
        expected_pin_id=pin_id,
    )
    receipt = bootstrap_archive_clean_state(
        pinned,
        state_root=state_root,
        frozen_revision=frozen_revision,
        runtime_artifact_id=runtime_artifact_id,
        as_of_ms=clock_ms(),
    )
    return {
        "command": "historical-archive-clean-bootstrap",
        **receipt.to_dict(),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = archive_clean_bootstrap_payload(
            runtime_root=args.runtime_root,
            pin_id=args.pin_id,
            state_root=args.state_root,
            frozen_revision=args.frozen_revision,
            runtime_artifact_id=args.runtime_artifact_id,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        _emit(
            {"error": str(exc), "error_type": type(exc).__name__},
            stream=sys.stderr,
        )
        return 2
    _emit(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
