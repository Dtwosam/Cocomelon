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
    verified = report["verified_entry_exit_context"]
    print(json.dumps({
        "report": str(report_path),
        "charts": str(chart_path),
        "all_journal_trades": report["total_journal_trades"],
        "verified_entry_contexts": verified["entry_context_verified_trades"],
        "unresolved_entry_contexts": verified["entry_context_unresolved_trades"],
        "stopped_losing_trades": verified["overall"]["mark_stop_losing_exits"],
        "losses_with_favorable_0_5r": (
            verified["overall"]["losses_after_0_5r_favorable_move"]
        ),
        "losses_no_favorable_0_25r": (
            verified["overall"]["losses_no_0_25r_favorable_move"]
        ),
        "verified_trades": report["trades_included_in_economics"],
        "realized_net_pnl": overall["net_pnl"],
        "fees": overall["fees"],
        "gross_realized_pnl": overall["gross_realized_pnl"],
        "path_complete": report["complete_chart_paths"],
        "path_missing": len(report["missing_chart_path_trade_ids"]),
        "bad_or_gapped_paths": report["incomplete_or_gapped_chart_paths"],
        "unresolved_open_gap_paths": report["unresolved_open_gap_affected_trades"],
        "unresolved_pre_entry_gap_paths": (
            report["unresolved_gap_before_entry_affected_trades"]
        ),
        "unresolved_during_position_gap_paths": (
            report["unresolved_gap_during_position_affected_trades"]
        ),
        "clean_mark_cadence_but_unresolved_gap_paths": (
            report["clean_mark_cadence_but_unresolved_gap_trades"]
        ),
        "chronological_chart_coverage_quartiles": (
            report["chronological_chart_coverage_quartiles"]
        ),
        "execution_authority": report["execution_authority"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
