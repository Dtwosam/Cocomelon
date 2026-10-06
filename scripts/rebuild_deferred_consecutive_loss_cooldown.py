from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from cocomelon.research.deferred_consecutive_loss_cooldown import (
    write_deferred_consecutive_loss_cooldown,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Rebuild deferred consecutive-loss cooldown research after "
            "an upgrade handoff has already launched its successor."
        )
    )
    parser.add_argument("state_root", type=Path)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output = write_deferred_consecutive_loss_cooldown(
        args.state_root,
        output_path=args.output,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                "output": str(output),
                "candidate_id": payload["candidate_id"],
                "clean_cooldown_rejections": payload[
                    "clean_cooldown_rejections"
                ],
                "candidate_eligible_cooldown_rejections": payload[
                    "candidate_eligible_cooldown_rejections"
                ],
                "deferred_post_handoff_rebuild": payload[
                    "deferred_post_handoff_rebuild"
                ],
                "execution_authority": payload["execution_authority"],
                "changes_risk_limits": payload["changes_risk_limits"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
