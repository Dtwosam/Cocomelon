from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence

from cocomelon.research.prospective_liveness import (
    ProspectiveLivenessError,
    evaluate_prospective_observer_liveness,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cocomelon-prospective-hype-liveness",
        description="Audit observer artifact freshness without touching campaign state",
    )
    parser.add_argument("--artifact-id", required=True)
    parser.add_argument("--artifact-created-at-ms", required=True, type=int)
    parser.add_argument("--as-of-ms", type=int)
    parser.add_argument("--max-artifact-age-ms", type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    audited_at_ms = (
        time.time_ns() // 1_000_000
        if args.as_of_ms is None
        else args.as_of_ms
    )
    try:
        if args.max_artifact_age_ms is None:
            receipt = evaluate_prospective_observer_liveness(
                artifact_id=args.artifact_id,
                artifact_created_at_ms=args.artifact_created_at_ms,
                audited_at_ms=audited_at_ms,
            )
        else:
            receipt = evaluate_prospective_observer_liveness(
                artifact_id=args.artifact_id,
                artifact_created_at_ms=args.artifact_created_at_ms,
                audited_at_ms=audited_at_ms,
                max_artifact_age_ms=args.max_artifact_age_ms,
            )
    except (ValueError, ProspectiveLivenessError) as exc:
        print(
            json.dumps(
                {"error": str(exc), "error_type": type(exc).__name__},
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(receipt.to_dict(), sort_keys=True, separators=(",", ":")))
    return 3 if receipt.alert_required else 0


if __name__ == "__main__":
    raise SystemExit(main())
