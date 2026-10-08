from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from cocomelon.research.deferred_all_trade_chart_audit import (
    write_deferred_trade_charts,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rebuild all paper-trade economics and observed chart paths after handoff"
    )
    parser.add_argument("state_root", type=Path)
    args = parser.parse_args(argv)
    report_path, chart_path, report = write_deferred_trade_charts(args.state_root)
    economics = report["economics"]
    overall = economics["overall"]
    print(json.dumps({
        "report": str(report_path),
        "charts": str(chart_path),
        "all_journal_trades": report["total_journal_trades"],
        "verified_trades": report["trades_included_in_economics"],
        "realized_net_pnl": overall["net_pnl"],
        "fees": overall["fees"],
        "gross_realized_pnl": overall["gross_realized_pnl"],
        "path_complete": report["complete_chart_paths"],
        "path_missing": len(report["missing_chart_path_trade_ids"]),
        "bad_or_gapped_paths": report["incomplete_or_gapped_chart_paths"],
        "execution_authority": report["execution_authority"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
