from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from cocomelon.research.prospective_cutover_acceptance import (
    build_prospective_hype_cutover_acceptance,
    verify_prospective_hype_cutover_receipt,
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
        prog="cocomelon-prospective-hype-cutover",
        description=(
            "Build or verify the immutable redacted cutover acceptance receipt "
            "for the frozen prospective HYPE campaign"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build")
    build.add_argument("--monitor", required=True, type=Path)
    build.add_argument("--state-root", required=True, type=Path)
    build.add_argument("--state-artifact-id", required=True)
    build.add_argument("--state-audited-at-ms", required=True, type=int)
    build.add_argument("--audited-at-ms", required=True, type=int)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--receipt", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "build":
            receipt = build_prospective_hype_cutover_acceptance(
                args.monitor,
                args.state_root,
                state_artifact_id=args.state_artifact_id,
                state_audited_at_ms=args.state_audited_at_ms,
                audited_at_ms=args.audited_at_ms,
            )
        else:
            receipt = verify_prospective_hype_cutover_receipt(args.receipt)
    except (OSError, RuntimeError, ValueError) as exc:
        _emit(
            {"error": str(exc), "error_type": type(exc).__name__},
            stream=sys.stderr,
        )
        return 2

    _emit(receipt.to_dict())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
