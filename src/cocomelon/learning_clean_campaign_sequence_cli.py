from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from cocomelon.research.learning_clean_campaign_sequence import (
    build_learning_clean_campaign_sequence_status,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cocomelon-learning-clean-sequence",
        description=(
            "Check whether one authenticated paper campaign is the next "
            "contiguous campaign required by a durable learned clean-state lineage"
        ),
    )
    parser.add_argument("--state-root", required=True, type=Path)
    parser.add_argument("--campaign-history", required=True, type=Path)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--current-run-id", type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        status = build_learning_clean_campaign_sequence_status(
            state_root=args.state_root,
            campaign_history_path=args.campaign_history,
            repository=args.repository,
            current_run_id=args.current_run_id,
        )
    except (OSError, RuntimeError, ValueError) as exc:
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
            status.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
