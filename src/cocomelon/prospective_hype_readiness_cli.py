from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from cocomelon.research.prospective_campaign_readiness import (
    ProspectiveCampaignReadinessError,
    verify_prospective_hype_campaign_readiness_file,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cocomelon-prospective-hype-readiness",
        description="Audit the frozen prospective HYPE campaign without mutating it",
    )
    parser.add_argument("--workflow", required=True, type=Path)
    parser.add_argument("--as-of-ms", type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    as_of_ms = (
        time.time_ns() // 1_000_000
        if args.as_of_ms is None
        else args.as_of_ms
    )
    try:
        receipt = verify_prospective_hype_campaign_readiness_file(
            args.workflow,
            audited_at_ms=as_of_ms,
        )
    except (OSError, ValueError, ProspectiveCampaignReadinessError) as exc:
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
            receipt.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
