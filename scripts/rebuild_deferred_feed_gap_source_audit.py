from __future__ import annotations

import argparse
import json
from pathlib import Path

from cocomelon.research.deferred_feed_gap_source_audit import (
    write_deferred_feed_gap_source_audit,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Diagnose unresolved per-market and shared market-data feed "
            "sources after the paper trader's safe successor handoff."
        )
    )
    parser.add_argument("state_root", type=Path)
    args = parser.parse_args()
    report_path = write_deferred_feed_gap_source_audit(args.state_root)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    print(json.dumps({
        "report": str(report_path),
        "closed_trades": report["chart_total_journal_trades"],
        "complete_charts": report["chart_complete_paths"],
        "unresolved_pre_entry_charts": (
            report["chart_unresolved_pre_entry_gap_paths"]
        ),
        "unresolved_source_gap_starts": (
            report["total_unresolved_source_gap_starts"]
        ),
        "sources_with_unresolved_gaps": (
            report["sources_with_unresolved_gaps"]
        ),
        "open_gaps_by_scope": report["open_gap_count_by_scope"],
        "research_only": True,
        "execution_authority": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
