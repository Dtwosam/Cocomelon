from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from cocomelon.research.deferred_long_entry_loss_attribution import (
    LongEntryLossAttributionError,
    assess_long_entry_loss_attribution,
    write_long_entry_loss_attribution,
)


def _trade(
    ident: str, side: str, gross: str, net: str, mfe: str | None,
    complete: bool, *, context: bool = True, market: str = "SOL",
) -> dict[str, object]:
    opened = 1000 * int(ident[-1])
    entry = (
        {
            "trade_id": ident,
            "market": market,
            "direction": side,
            "opened_at_ms": opened,
            "closed_at_ms": opened + 500,
            "net_pnl": net,
            "net_r": str(float(net) / 10),
            "lead_strategy": "trend",
            "rank_band": "outside10",
        } if context else None
    )
    return {
        "trade_id": ident, "market": market, "side": side,
        "opened_at_ms": opened, "closed_at_ms": opened + 500,
        "net_pnl": net, "net_r": str(float(net) / 10),
        "gross_realized_pnl": gross, "entry_fees": "0.3",
        "exit_fees": "0.2", "funding_cash_pnl": "0",
        "chart_path_present": complete,
        "chart_coverage_complete": complete,
        "chart_mark_count": 3 if complete else 0,
        "chart_known_gap_duration_ms": 0 if complete else None,
        "chart_longest_unobserved_mark_ms": 100 if complete else None,
        "mfe_r": mfe, "entry_context": entry,
    }


def _source() -> dict[str, object]:
    rows = [
        _trade("t1", "long", "-2", "-2.5", "0.1", True),
        _trade("t2", "long", "-2", "-2.5", "0.8", True),
        _trade("t3", "long", "0.2", "-0.3", None, False),
        _trade("t4", "long", "-2", "-2.5", "1.2", False, context=False),
        _trade("t5", "short", "4", "3.5", "1.1", True, market="BTC"),
    ]
    return {
        "definition": (
            "entire_closed_paper_journal_with_observed_in_position_mark_charts_v1"
        ),
        "research_only": True, "execution_authority": False,
        "promotion_authority": False,
        "total_journal_trades": 5, "trades_included_in_economics": 5,
        "trades": rows,
        "economics": {"overall": {"trades": 5, "net_pnl": "-4.3"}},
        "verified_entry_exit_context": {
            "trade_count": 5,
            "entry_context_verified_trades": 4,
            "entry_context_unresolved_trades": 1,
            "overall": {"net_pnl": "-4.3"},
        },
    }


def test_reconciled_full_sample_and_side_separated_loss_taxonomy() -> None:
    report = assess_long_entry_loss_attribution(_source())
    assert report["source_trades"] == 5
    assert report["total_realized_closed_net_pnl"] == "-4.3"
    assert report["by_side"]["long"]["net_pnl"] == "-7.8"
    assert report["by_side"]["short"]["net_pnl"] == "3.5"
    assert report["by_side"]["long"]["losers"] == 4
    assert report["missing_entry_context_trades"] == 1
    reasons = report["loss_reasons_by_side"]["long"]
    for key in (
        "loss_without_0_25r_favorable_move",
        "loss_after_0_5r_favorable_move",
        "gross_winner_flipped_negative_after_costs",
        "unknown_favorable_path_or_incomplete_chart",
    ):
        assert reasons[key]["trades"] == 1
    assert reasons["unknown_favorable_path_or_incomplete_chart"]["net_pnl"] == "-2.5"
    assert report["by_entry_strategy_and_rank"][
        "long | unverified_entry_context | unverified_entry_context"
    ]["trades"] == 1
    assert report["can_select_entry_filter"] is False
    assert report["execution_authority"] is False
    assert report["ready_for_review"] is False
    assert report["chronological_blocks_are_global"] is True


@pytest.mark.parametrize("corrupt", [
    "drop_trade", "duplicate_trade", "change_fee", "swap_side",
    "invent_context", "pretend_complete", "total_drift", "direction_drift",
])
def test_evidence_tampering_fails_closed(corrupt: str) -> None:
    source = _source()
    rows = source["trades"]
    if corrupt == "drop_trade":
        rows.pop()
    elif corrupt == "duplicate_trade":
        rows[1]["trade_id"] = rows[0]["trade_id"]
    elif corrupt == "change_fee":
        rows[1]["exit_fees"] = "100"
    elif corrupt == "swap_side":
        rows[1]["side"] = "short"
    elif corrupt == "invent_context":
        rows[0]["entry_context"]["opened_at_ms"] += 1
    elif corrupt == "pretend_complete":
        rows[3]["chart_coverage_complete"] = True
    elif corrupt == "total_drift":
        source["economics"]["overall"]["net_pnl"] = "99"
    elif corrupt == "direction_drift":
        rows[0]["side"] = "neither"
    with pytest.raises(LongEntryLossAttributionError):
        assess_long_entry_loss_attribution(source)


def test_favorable_extrema_from_gapped_chart_does_not_claim_exit_opportunity() -> None:
    source = _source()
    source["trades"][3]["mfe_r"] = "15"
    report = assess_long_entry_loss_attribution(source)
    assert report["loss_reasons_by_side"]["long"][
        "unknown_favorable_path_or_incomplete_chart"
    ]["trades"] == 1


def test_paper_handoff_guard_and_file_output(tmp_path: Path) -> None:
    src = _source()
    (tmp_path / "all-paper-trade-chart-audit.json").write_text(
        json.dumps(src), encoding="utf-8"
    )
    (tmp_path / "session-summary.json").write_text(
        json.dumps({"exit_reason": "crashed"}), encoding="utf-8"
    )
    with pytest.raises(LongEntryLossAttributionError, match="handoff"):
        write_long_entry_loss_attribution(tmp_path)
    (tmp_path / "session-summary.json").write_text(
        json.dumps({"exit_reason": "duration_elapsed"}), encoding="utf-8"
    )
    file = write_long_entry_loss_attribution(tmp_path)
    report = json.loads(file.read_text(encoding="utf-8"))
    assert report["total_realized_closed_net_pnl"] == "-4.3"
    assert report["source_exit_reason"] == "duration_elapsed"


def test_refuses_promotional_or_partial_source() -> None:
    for key, value in (("research_only", False), ("promotion_authority", True)):
        source = copy.deepcopy(_source())
        source[key] = value
        with pytest.raises(LongEntryLossAttributionError):
            assess_long_entry_loss_attribution(source)
