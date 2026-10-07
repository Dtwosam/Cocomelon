from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from cocomelon.research.loss_context_candidate import (
    write_loss_context_candidate_freeze,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cocomelon-loss-context-freeze",
        description=(
            "Freeze the first stable recurring loss context for untouched "
            "future paper evaluation"
        ),
    )
    parser.add_argument("--audit", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--frozen-at-ms", required=True, type=int)
    parser.add_argument("--source-paper-run-id", required=True, type=int)
    parser.add_argument("--source-paper-run-attempt", required=True, type=int)
    parser.add_argument("--source-paper-head-sha", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        raw = json.loads(args.audit.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("loss-context audit must be an object")
        freeze, created = write_loss_context_candidate_freeze(
            raw,
            output_path=args.output,
            frozen_at_ms=args.frozen_at_ms,
            source_paper_run_id=args.source_paper_run_id,
            source_paper_run_attempt=args.source_paper_run_attempt,
            source_paper_head_sha=args.source_paper_head_sha,
        )
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

    payload: dict[str, object] = {
        "command": "loss-context-freeze",
        "created": created,
        "selected_candidate": freeze is not None,
    }
    if freeze is not None:
        payload.update(freeze.to_dict())
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
