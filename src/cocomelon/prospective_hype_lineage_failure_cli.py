from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import TextIO

from cocomelon.research.prospective_lineage_failure import (
    build_prospective_lineage_failure,
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


def _optional_artifact_id(value: str | None) -> str | None:
    if value is None or value in {"", "none"}:
        return None
    if not value.isdigit():
        raise argparse.ArgumentTypeError("artifact ids must be numeric when present")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cocomelon-prospective-hype-lineage-failure",
        description="Build a redacted immutable lineage-audit failure receipt",
    )
    parser.add_argument("--audited-at-ms", required=True, type=int)
    parser.add_argument(
        "--stage",
        required=True,
        choices=("discovery", "download", "state", "verify", "upload"),
    )
    parser.add_argument("--reason-code", required=True)
    parser.add_argument("--previous-artifact-id", type=_optional_artifact_id)
    parser.add_argument("--current-artifact-id", type=_optional_artifact_id)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        receipt = build_prospective_lineage_failure(
            audited_at_ms=args.audited_at_ms,
            stage=args.stage,
            reason_code=args.reason_code,
            previous_artifact_id=args.previous_artifact_id,
            current_artifact_id=args.current_artifact_id,
        )
    except ValueError as exc:
        _emit(
            {"error": str(exc), "error_type": type(exc).__name__},
            stream=sys.stderr,
        )
        return 2

    _emit(receipt.to_dict())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
