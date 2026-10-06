from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from cocomelon.research.deferred_full_stack_capacity_reflow import (
    write_deferred_full_stack_capacity_reflow,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Rebuild deferred full-stack capacity-reflow economics after "
            "an upgrade handoff has already launched its successor."
        )
    )
    parser.add_argument("state_root", type=Path)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output = write_deferred_full_stack_capacity_reflow(
        args.state_root,
        output_path=args.output,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    realized = payload["realized_pnl"]
    if not isinstance(realized, dict):
        raise RuntimeError("realized_pnl must be an object")
    print(
        json.dumps(
            {
                "output": str(output),
                "baseline_capacity_rejections": payload[
                    "baseline_capacity_rejections"
                ],
                "candidate_capacity_release_opportunities": payload[
                    "candidate_capacity_release_opportunities"
                ],
                "integrity_clean": payload["integrity_clean"],
                "exact_realized_pnl_available": payload[
                    "exact_realized_pnl_available"
                ],
                "pnl_modeled": payload["pnl_modeled"],
                "realized_pnl_enabled": realized["enabled"],
                "deferred_post_handoff_rebuild": payload[
                    "deferred_post_handoff_rebuild"
                ],
                "execution_authority": payload["execution_authority"],
                "promotion_authority": payload["promotion_authority"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
