from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from cocomelon.research.loss_context_prospective import (
    score_loss_context_candidate_state,
)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    encoded = (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cocomelon-loss-context-prospective",
        description=(
            "Score a frozen recurring loss context only on post-embargo "
            "realized continuous-paper trades"
        ),
    )
    parser.add_argument("--state-root", required=True, type=Path)
    parser.add_argument("--freeze", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = score_loss_context_candidate_state(
            state_root=args.state_root,
            freeze_path=args.freeze,
        )
        payload = {
            "command": "loss-context-prospective",
            **report.to_dict(),
        }
        _write_json(args.output, payload)
    except (OSError, json.JSONDecodeError, RuntimeError, ValueError) as exc:
        print(
            json.dumps(
                {"error": str(exc), "error_type": type(exc).__name__},
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 2

    print(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
