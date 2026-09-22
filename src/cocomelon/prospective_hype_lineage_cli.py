from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from cocomelon.research.prospective_artifact_lineage import (
    ProspectiveArtifactLineageError,
    verify_prospective_hype_artifact_lineage,
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
        prog="cocomelon-prospective-hype-lineage",
        description=(
            "Verify append-only lineage between two cumulative frozen HYPE "
            "prospective campaign artifacts"
        ),
    )
    parser.add_argument("--previous-root", required=True, type=Path)
    parser.add_argument("--current-root", required=True, type=Path)
    parser.add_argument("--previous-artifact-id", required=True)
    parser.add_argument("--current-artifact-id", required=True)
    parser.add_argument("--previous-audited-at-ms", required=True, type=int)
    parser.add_argument("--current-audited-at-ms", required=True, type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        receipt = verify_prospective_hype_artifact_lineage(
            args.previous_root,
            args.current_root,
            previous_artifact_id=args.previous_artifact_id,
            current_artifact_id=args.current_artifact_id,
            previous_audited_at_ms=args.previous_audited_at_ms,
            current_audited_at_ms=args.current_audited_at_ms,
        )
    except (OSError, RuntimeError, ValueError, ProspectiveArtifactLineageError) as exc:
        _emit(
            {"error": str(exc), "error_type": type(exc).__name__},
            stream=sys.stderr,
        )
        return 2

    _emit(receipt.to_dict())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
