from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from cocomelon.research.cooldown_context_selection import (
    build_cooldown_context_selection_record,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cocomelon-cooldown-context-selection",
        description=(
            "Build an immutable research-only selection record from "
            "cooldown context stability evidence"
        ),
    )
    parser.add_argument("--cooldown", required=True, type=Path)
    parser.add_argument("--stability", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cooldown = json.loads(args.cooldown.read_text(encoding="utf-8"))
        stability = json.loads(args.stability.read_text(encoding="utf-8"))
        if not isinstance(cooldown, dict) or not isinstance(stability, dict):
            raise ValueError("selection inputs must be objects")
        payload = build_cooldown_context_selection_record(
            cooldown,
            stability,
        ).to_dict()
        encoded = (_canonical_json(payload) + "\n").encode("utf-8")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_name(f".{args.output.name}.tmp")
        try:
            with temporary.open("wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, args.output)
        finally:
            temporary.unlink(missing_ok=True)
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
            {
                "output": str(args.output),
                "source_record_id": payload["source_record_id"],
                "stable_candidate_count": payload["stable_candidate_count"],
                "selected_candidate": payload["selected_candidate"],
                "execution_authority": payload["execution_authority"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
