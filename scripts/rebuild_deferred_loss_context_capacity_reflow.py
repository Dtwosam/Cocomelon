from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from cocomelon.research.deferred_loss_context_capacity_reflow import (
    write_deferred_loss_context_capacity_reflow,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Rebuild loss-context capacity-release sensitivity after a "
            "clean paper handoff has already launched its successor."
        )
    )
    parser.add_argument("state_root", type=Path)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output = write_deferred_loss_context_capacity_reflow(
        args.state_root,
        output_path=args.output,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                "output": str(output),
                "enabled": payload["enabled"],
                "gate_open": payload["gate_open"],
                "candidate_capacity_release_opportunities": payload.get(
                    "candidate_capacity_release_opportunities",
                    0,
                ),
                "integrity_clean": payload.get("integrity_clean"),
                "ready_for_replacement_fill_investigation": payload.get(
                    "ready_for_replacement_fill_investigation",
                    False,
                ),
                "replacement_entries_modeled": payload[
                    "replacement_entries_modeled"
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
