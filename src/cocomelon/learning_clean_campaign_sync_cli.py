from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from cocomelon.research.learning_clean_campaign_sync import (
    sync_learning_clean_research_campaign,
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
        prog="cocomelon-learning-clean-campaign-sync",
        description=(
            "Append authenticated post-embargo research paper trades to one "
            "frozen learning candidate's clean evidence store"
        ),
    )
    parser.add_argument("--campaign-root", required=True, type=Path)
    parser.add_argument("--package-root", required=True, type=Path)
    parser.add_argument("--validation-spec", required=True, type=Path)
    parser.add_argument("--evidence-root", required=True, type=Path)
    parser.add_argument("--upstream-run-id", required=True, type=int)
    parser.add_argument("--upstream-run-attempt", required=True, type=int)
    parser.add_argument("--upstream-head-sha", required=True)
    parser.add_argument("--upstream-artifact-id", required=True, type=int)
    parser.add_argument("--upstream-artifact-digest", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = sync_learning_clean_research_campaign(
            campaign_root=args.campaign_root,
            package_root=args.package_root,
            validation_spec_path=args.validation_spec,
            evidence_root=args.evidence_root,
            upstream_run_id=args.upstream_run_id,
            upstream_run_attempt=args.upstream_run_attempt,
            upstream_head_sha=args.upstream_head_sha,
            upstream_artifact_id=args.upstream_artifact_id,
            upstream_artifact_digest=args.upstream_artifact_digest,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        _emit(
            {"error": str(exc), "error_type": type(exc).__name__},
            stream=sys.stderr,
        )
        return 2

    _emit(
        {
            "command": "learning-clean-campaign-sync",
            **result.to_dict(),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
