from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from cocomelon.research.deferred_correlation_bucket_priority import (
    write_deferred_correlation_bucket_priority,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Rebuild descriptive correlation-bucket priority evidence after "
            "the successor paper worker is already running."
        )
    )
    parser.add_argument("state_root", type=Path)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output = write_deferred_correlation_bucket_priority(
        args.state_root,
        output_path=args.output,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                "output": str(output),
                "stack_admitted_correlation_rejections": payload[
                    "stack_admitted_correlation_rejections"
                ],
                "releasable_holder_options": payload[
                    "releasable_holder_options"
                ],
                "opportunities_outranking_any_releasable_holder": payload[
                    "opportunities_outranking_any_releasable_holder"
                ],
                "execution_authority": payload["execution_authority"],
                "changes_risk_limits": payload["changes_risk_limits"],
                "changes_entry_priority": payload["changes_entry_priority"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
