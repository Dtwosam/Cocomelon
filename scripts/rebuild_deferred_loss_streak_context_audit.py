from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from cocomelon.research.deferred_loss_streak_context_audit import (
    write_deferred_loss_streak_context_audit,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Rebuild descriptive loss-streak context evidence after the "
            "successor paper worker is already running."
        )
    )
    parser.add_argument("state_root", type=Path)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output = write_deferred_loss_streak_context_audit(
        args.state_root,
        output_path=args.output,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    latest = payload.get("latest_qualifying_streak")
    latest_length = (
        None
        if not isinstance(latest, dict)
        else latest.get("length")
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "trade_count": payload["trade_count"],
                "qualifying_loss_streak_count": payload[
                    "qualifying_loss_streak_count"
                ],
                "current_consecutive_losses": payload[
                    "current_consecutive_losses"
                ],
                "latest_qualifying_streak_length": latest_length,
                "recurring_pattern_count": len(
                    payload["recurring_dominant_patterns"]
                ),
                "baseline_resolved_trade_count": payload[
                    "baseline_resolved_trade_count"
                ],
                "baseline_unresolved_trade_count": payload[
                    "baseline_unresolved_trade_count"
                ],
                "baseline_normalization_complete": payload[
                    "baseline_normalization_complete"
                ],
                "non_loss_control_trade_count": payload[
                    "non_loss_control_trade_count"
                ],
                "qualifying_loss_trade_count": payload[
                    "qualifying_loss_trade_count"
                ],
                "complete_qualifying_loss_streak_count": payload[
                    "complete_qualifying_loss_streak_count"
                ],
                "incomplete_qualifying_loss_streak_count": payload[
                    "incomplete_qualifying_loss_streak_count"
                ],
                "qualifying_loss_unresolved_trade_count": payload[
                    "qualifying_loss_unresolved_trade_count"
                ],
                "qualifying_loss_unresolved_reason_counts": payload[
                    "qualifying_loss_unresolved_reason_counts"
                ],
                "execution_authority": payload[
                    "execution_authority"
                ],
                "changes_strategy": payload["changes_strategy"],
                "changes_risk_limits": payload[
                    "changes_risk_limits"
                ],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
