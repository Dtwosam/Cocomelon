from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from cocomelon.research.learning_dataset import build_learning_dataset_snapshot
from cocomelon.research.outcome_learning import LearningEvidenceLedger
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
        prog="cocomelon-learning-dataset",
        description="Build a leakage-safe snapshot of research-eligible learning evidence",
    )
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--as-of-ms", type=int)
    return parser


def learning_dataset_payload(
    *,
    root: Path,
    as_of_ms: int | None = None,
) -> dict[str, object]:
    resolved_as_of_ms = utc_now_ms() if as_of_ms is None else as_of_ms
    ledger = LearningEvidenceLedger(root)
    snapshot = build_learning_dataset_snapshot(
        ledger,
        as_of_ms=resolved_as_of_ms,
    )
    return {
        "command": "learning-dataset",
        **snapshot.manifest.to_dict(),
        "root": str(root),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = learning_dataset_payload(
            root=args.root,
            as_of_ms=args.as_of_ms,
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
