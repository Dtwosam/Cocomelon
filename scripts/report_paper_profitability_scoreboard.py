"""Report original executed paper-trade dollars, costs, and loss cohorts."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from pathlib import Path

from cocomelon.research.paper_profitability_scoreboard import (
    paper_profitability_scoreboard,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audit_path", type=Path)
    parser.add_argument("--json-out", required=True, type=Path)
    parser.add_argument("--short-rank-freeze", type=Path)
    parser.add_argument("--trend-outside-freeze", type=Path)
    args = parser.parse_args(argv)
    sources = (
        args.audit_path,
        args.short_rank_freeze,
        args.trend_outside_freeze,
    )
    if any(
        source is not None and source.resolve() == args.json_out.resolve()
        for source in sources
    ):
        raise ValueError("scoreboard cannot replace authoritative input")
    audit = json.loads(args.audit_path.read_text(encoding="utf-8"))

    def read_frozen(path: Path | None) -> object | None:
        if path is None or not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    report = paper_profitability_scoreboard(
        audit,
        short_rank_freeze=read_frozen(args.short_rank_freeze),
        trend_outside_freeze=read_frozen(args.trend_outside_freeze),
    )
    target: Path = args.json_out
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(
                report, sort_keys=True, separators=(",", ":"), allow_nan=False
            ) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    overall = report["overall"]
    assert isinstance(overall, dict)
    side = report["side_cohorts"]
    assert isinstance(side, list)
    headline = {
        "report": str(target),
        "trades": overall["trades"],
        "closed_net_pnl": overall["net_pnl"],
        "recorded_fees": overall["fees"],
        "recorded_funding_cash_pnl": overall["funding_cash_pnl"],
        "unverified_entry_context_trades": overall[
            "unverified_entry_context_trades"
        ],
        "incomplete_chart_trades": overall["incomplete_chart_trades"],
        "side_cohorts": side,
        "frozen_hypotheses": report[
            "frozen_hypotheses_original_forward_economics"
        ],
        "execution_authority": False,
        "promotion_authority": False,
    }
    print(json.dumps(headline, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
