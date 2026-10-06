from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from cocomelon.research.deferred_full_stack_forward_markout import (
    write_deferred_full_stack_forward_markout,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Rebuild deferred full-stack forward-markout research after "
            "an upgrade handoff has already launched its successor."
        )
    )
    parser.add_argument("state_root", type=Path)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output = write_deferred_full_stack_forward_markout(
        args.state_root,
        output_path=args.output,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                "output": str(output),
                "risk_rejected_stack_evaluated": payload[
                    "risk_rejected_stack_evaluated"
                ],
                "risk_rejected_integrity_clean": payload[
                    "risk_rejected_integrity_clean"
                ],
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
