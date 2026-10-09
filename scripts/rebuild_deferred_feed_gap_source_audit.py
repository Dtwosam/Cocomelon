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
        "legacy_unattributable_open_gap_count": (
            report["legacy_unattributable_open_gap_count"]
        ),
        "legacy_lineage_blocks_chart_source_certification": (
            report["legacy_lineage_blocks_chart_source_certification"]
        ),
        "named_unresolved_source_count": report["named_unresolved_source_count"],
        "current_selection_witness_present": (
            report["current_selection_witness_present"]
        ),
        "current_selected_market_count": (
            report["current_selected_market_count"]
        ),
        "named_unresolved_sources_on_selected_markets": (
            report["named_unresolved_sources_on_selected_markets"]
        ),
        "named_unresolved_sources_outside_selected_markets": (
            report["named_unresolved_sources_outside_selected_markets"]
        ),
        "named_unresolved_sources_without_selection_attribution": (
            report["named_unresolved_sources_without_selection_attribution"]
        ),
        "named_unresolved_gap_starts_on_selected_markets": (
            report["named_unresolved_gap_starts_on_selected_markets"]
        ),
        "named_unresolved_gap_starts_outside_selected_markets": (
            report["named_unresolved_gap_starts_outside_selected_markets"]
        ),
        "named_unresolved_gap_starts_without_selection_attribution": (
            report["named_unresolved_gap_starts_without_selection_attribution"]
        ),
        "top_selected_market_repair_sources": [
            {
                "stream_id": item["stream_id"],
                "open_gap_count": item["open_gap_count"],
                "incomplete_charts": (
                    item["incomplete_charts_overlapping_unresolved_source_gap"]
                ),
            }
            for item in report["top_selected_market_repair_sources"]
        ],
        "named_recovery_witness_ledger_present": (
            report["named_recovery_witness_ledger_present"]
        ),
        "named_recovery_checkpoint_confirmed": (
            report["named_recovery_checkpoint_confirmed"]
        ),
        "named_recovery_witness_sources": (
            report["named_recovery_witness_sources"]
        ),
        "top_named_repair_sources": [
            {
                "scope": item["scope"],
                "stream_id": item["stream_id"],
                "incomplete_charts": (
                    item["incomplete_charts_overlapping_unresolved_source_gap"]
                ),
                "original_trades_overlapping_unresolved": (
                    item["original_trades_overlapping_unresolved_source_gap"]
                ),
            }
            for item in report["named_source_repair_priority"][:5]
        ],
        "top_incomplete_chart_sources": [
            {
                "scope": item["scope"],
                "stream_id": item["stream_id"],
                "incomplete_charts": (
                    item["incomplete_charts_overlapping_unresolved_source_gap"]
                ),
                "original_trades_overlapping_unresolved": (
                    item["original_trades_overlapping_unresolved_source_gap"]
                ),
            }
            for item in report["by_source"][:5]
        ],
        "research_only": True,
        "execution_authority": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
