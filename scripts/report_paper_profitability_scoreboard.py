"""Report original executed paper-trade dollars, costs, and loss cohorts."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from decimal import Decimal
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
    weekly = report["original_fixed_utc_opening_week_economics"]
    assert isinstance(weekly, dict)
    periods = weekly["weeks"]
    assert isinstance(periods, list)
    original_week_rows = [
        {
            "week_start_ms_utc": period["week_start_ms_utc"],
            "booked_net_pnl": period["original_booked_week"]["net_pnl"],
            "booked_gross_pnl": period["original_booked_week"]["gross_realized_pnl"],
            "booked_fees": period["original_booked_week"]["fees"],
            "booked_funding_pnl": period["original_booked_week"]["funding_cash_pnl"],
            "closed_trade_count": period["original_booked_week"]["trades"],
            "fully_observed_at_original_flat_handoff": (
                period["week_original_booked_outcome_mature_at_handoff"]
            ),
        }
        for period in periods
    ]
    worst_booked_week = (
        min(original_week_rows, key=lambda row: (
            Decimal(str(row["booked_net_pnl"])),
            row["week_start_ms_utc"],
        )) if original_week_rows else None
    )
    gap = report["original_chart_gap_witness_loss_attribution"]
    assert isinstance(gap, dict)
    gap_classes = gap["mutually_exclusive_evidence_classes"]
    assert isinstance(gap_classes, list)
    headline = {
        "original_gap_evidence_loss_cohorts": [
            {
                "class": item["cohort"]["chart_gap_witness_class"],
                "original_closed_trades": item["trades"],
                "booked_gross_pnl": item["gross_realized_pnl"],
                "booked_fees": item["fees"],
                "booked_funding": item["funding_cash_pnl"],
                "booked_net_pnl": item["net_pnl"],
                "booked_net_r": item["net_r"],
            }
            for item in gap_classes
        ],
        "original_incomplete_evidence_market_loss_cohorts": [
            {
                "market": item["cohort"]["market"],
                "original_closed_trades": item["trades"],
                "booked_net_pnl": item["net_pnl"],
                "booked_fees": item["fees"],
            }
            for item in gap["incomplete_by_market"][:10]
        ],
        "gap_causation_or_recovered_market_feed_proven": False,
        "fixed_opening_week_count_including_empty": len(original_week_rows),
        "fixed_opening_week_mature_count": sum(
            row["fully_observed_at_original_flat_handoff"]
            for row in original_week_rows
        ),
        "original_worst_booked_opening_week": worst_booked_week,
        "original_recent_booked_opening_week": (
            original_week_rows[-1] if original_week_rows else None
        ),
        "fixed_opening_week_source": (
            "historical_original_closed_trades_not_full_account_expectancy"
        ),
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
