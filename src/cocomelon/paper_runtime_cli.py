from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

from cocomelon.config import Settings
from cocomelon.paper_runtime import (
    DEFAULT_DEEP_LIMIT,
    DEFAULT_DURATION_SECONDS,
    DEFAULT_FUNDING_POLL_SECONDS,
    DEFAULT_REFRESH_SECONDS,
    PaperRuntimeConfig,
    run_continuous_paper_runtime,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cocomelon-paper-runtime")
    parser.add_argument("--state-root", required=True, type=Path)
    parser.add_argument(
        "--duration-seconds",
        type=int,
        default=DEFAULT_DURATION_SECONDS,
    )
    parser.add_argument(
        "--refresh-seconds",
        type=int,
        default=DEFAULT_REFRESH_SECONDS,
    )
    parser.add_argument(
        "--funding-poll-seconds",
        type=int,
        default=DEFAULT_FUNDING_POLL_SECONDS,
    )
    parser.add_argument("--deep-limit", type=int, default=DEFAULT_DEEP_LIMIT)
    parser.add_argument("--starting-cash", type=Decimal, default=Decimal("10000"))
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    config = PaperRuntimeConfig(
        state_root=args.state_root,
        duration_seconds=args.duration_seconds,
        refresh_seconds=args.refresh_seconds,
        funding_poll_seconds=args.funding_poll_seconds,
        deep_limit=args.deep_limit,
        starting_cash=args.starting_cash,
    )
    summary = asyncio.run(
        run_continuous_paper_runtime(
            Settings.from_env(),
            config,
        )
    )
    print(
        json.dumps(
            {
                "runtime_id": summary.runtime_id,
                "selected_markets": list(summary.selected_markets),
                "open_positions": summary.open_positions,
                "closed_trades": summary.closed_trades,
                "equity": str(summary.equity),
                "realized_gross_pnl": str(summary.realized_gross_pnl),
                "cumulative_fees": str(summary.cumulative_fees),
                "cumulative_funding": str(summary.cumulative_funding),
                "started_at_ms": summary.started_at_ms,
                "finished_at_ms": summary.finished_at_ms,
                "cycles": summary.cycles,
                "network_access": summary.network_access,
                "paper_only": summary.paper_only,
                "live_orders": summary.live_orders,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
