"""Net losses must remain visible for every original executed paper trade."""

from __future__ import annotations

import json
import subprocess
import sys
from decimal import Decimal, localcontext
from pathlib import Path

import pytest

from cocomelon.research.paper_profitability_scoreboard import (
    PaperProfitabilityScoreboardError,
    paper_profitability_scoreboard,
)


def _trade(
    n: int,
    *,
    side: str,
    market: str,
    strategy: str | None,
    rank: str = "top3",
    gross: str = "-9",
    entry_fee: str = "0.4",
    exit_fee: str = "0.6",
    funding: str = "0",
    chart: bool = False,
) -> dict[str, object]:
    with localcontext(prec=96):
        net = (
            Decimal(gross)
            - Decimal(entry_fee)
            - Decimal(exit_fee)
            + Decimal(funding)
        )
    opened = n * 1000
    closed = opened + 20
    trade: dict[str, object] = {
        "trade_id": f"original-{n}",
        "market": market,
        "side": side,
        "opened_at_ms": opened,
        "closed_at_ms": closed,
        "gross_realized_pnl": gross,
        "entry_fees": entry_fee,
        "exit_fees": exit_fee,
        "funding_cash_pnl": funding,
        "net_pnl": str(net),
        "net_r": str(net / Decimal("20")),
        "chart_coverage_complete": chart,
        "entry_context": None,
    }
    if strategy is not None:
        trade["entry_context"] = {
            "trade_id": trade["trade_id"],
            "market": market,
            "direction": side,
            "opened_at_ms": opened,
            "closed_at_ms": closed,
            "net_pnl": str(net),
            "lead_strategy": strategy,
            "rank_band": rank,
        }
    return trade


def _audit() -> dict[str, object]:
    rows = [
        _trade(1, side="short", market="BTC", strategy="trend"),
        _trade(
            2, side="long", market="ETH", strategy="breakout",
            gross="5", chart=True,
        ),
        _trade(
            3, side="short", market="SOL", strategy=None,
            gross="-1",
        ),
        _trade(
            4, side="long", market="BTC", strategy="trend",
            gross="-5", funding="0.1",
        ),
    ]
    with localcontext(prec=96):
        gross = sum((Decimal(str(r["gross_realized_pnl"])) for r in rows), Decimal(0))
        fees = sum(
            (
                Decimal(str(r["entry_fees"]))
                + Decimal(str(r["exit_fees"]))
                for r in rows
            ),
            Decimal(0),
        )
        funding = sum(
            (Decimal(str(r["funding_cash_pnl"])) for r in rows), Decimal(0)
        )
        net = sum((Decimal(str(r["net_pnl"])) for r in rows), Decimal(0))
    return {
        "definition": (
            "entire_closed_paper_journal_with_observed_in_position_mark_charts_v1"
        ),
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_strategy": False,
        "changes_risk_limits": False,
        "deferred_after_successor_dispatch": True,
        "source_exit_reason": "upgrade_requested",
        "total_journal_trades": len(rows),
        "trades_included_in_economics": len(rows),
        "economics": {
            "overall": {
                "trades": len(rows),
                "gross_realized_pnl": str(gross),
                "fees": str(fees),
                "funding_cash_pnl": str(funding),
                "net_pnl": str(net),
                "net_reconciliation_residual": str(
                    net - gross + fees - funding
                ),
            }
        },
        "verified_entry_exit_context": {
            "entry_context_verified_trades": 3,
            "entry_context_unresolved_trades": 1,
        },
        "trades": rows,
    }


def test_all_original_trades_and_net_losses_are_retained() -> None:
    source = _audit()
    report = paper_profitability_scoreboard(source)
    assert report["kind"] == "entire-original-paper-profitability-attribution"
    assert report["overall"]["trades"] == 4
    assert report["overall"]["net_pnl"] == "-13.9"
    assert report["overall"]["fees"] == "4.0"
    assert report["overall"]["funding_cash_pnl"] == "0.1"
    assert report["overall"]["unverified_entry_context_trades"] == 1
    assert report["overall"]["incomplete_chart_trades"] == 3
    assert report["execution_authority"] is False
    assert report["promotion_authority"] is False
    assert report["ready_for_strategy_promotion"] is False
    assert sum(x["trades"] for x in report["side_cohorts"]) == 4
    assert sum(x["trades"] for x in report["strategy_cohorts"]) == 4
    assert sum(x["trades"] for x in report["market_cohorts"]) == 4
    assert [x["trades"] for x in report["chronological_quartiles"]] == [1] * 4
    unknown = next(
        row for row in report["strategy_cohorts"]
        if row["cohort"]["lead_strategy"] == "UNVERIFIED_ENTRY_CONTEXT"
    )
    assert unknown["trades"] == 1
    assert unknown["net_pnl"] == "-2.0"
    assert unknown["unverified_entry_context_trades"] == 1
    short_trend = next(
        x for x in report["side_strategy_rank_cohorts"]
        if x["cohort"] == {
            "side": "short", "lead_strategy": "trend", "rank_band": "top3",
        }
    )
    assert short_trend["net_pnl"] == "-10.0"
    assert source["trades"][2]["entry_context"] is None


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        (lambda d: d.update(total_journal_trades=3), "exclude"),
        (lambda d: d["trades"].pop(), "exclude"),
        (lambda d: d["trades"][2].update(trade_id="original-1"), "duplicate"),
        (lambda d: d["trades"][1].update(side="both"), "side"),
        (
            lambda d: d["trades"][1].update(entry_fees="-2"),
            "negative execution fee",
        ),
        (
            lambda d: d["trades"][2].update(net_pnl="100"),
            "whole-journal net_pnl",
        ),
        (
            lambda d: d["trades"][1]["entry_context"].update(trade_id="forged"),
            "lineage",
        ),
        (
            lambda d: d["trades"][1]["entry_context"].update(net_pnl="-100"),
            "context net PnL",
        ),
        (
            lambda d: d["economics"]["overall"].update(fees="0"),
            "fees does not reconcile",
        ),
        (
            lambda d: d["economics"]["overall"].update(
                net_reconciliation_residual="0.1"
            ),
            "residue mismatch",
        ),
        (lambda d: d.update(execution_authority=True), "untrusted"),
        (lambda d: d.update(source_exit_reason="unknown"), "handoff"),
        (
            lambda d: d["verified_entry_exit_context"].update(
                entry_context_unresolved_trades=0
            ),
            "counts do not reconcile",
        ),
    ],
)
def test_corrupt_or_cherry_picked_source_fails_closed(
    mutation: object, error: str
) -> None:
    source = _audit()
    mutation(source)
    with pytest.raises(PaperProfitabilityScoreboardError, match=error):
        paper_profitability_scoreboard(source)


def test_unbooked_sub_cent_differences_must_match_declared_residual() -> None:
    source = _audit()
    original = source["trades"][1]
    assert isinstance(original, dict)
    original["net_pnl"] = "4.000000000000000000000000001"
    context = original["entry_context"]
    assert isinstance(context, dict)
    context["net_pnl"] = original["net_pnl"]
    with localcontext(prec=96):
        value = Decimal(str(source["economics"]["overall"]["net_pnl"]))
        value += Decimal("0.000000000000000000000000001")
        overall = source["economics"]["overall"]
        overall["net_pnl"] = str(value)
        overall["net_reconciliation_residual"] = "0.000000000000000000000000001"
    result = paper_profitability_scoreboard(source)
    assert result["overall"]["net_pnl"] == str(value)


def test_report_command_writes_separate_research_only_result(tmp_path: Path) -> None:
    audit_path = tmp_path / "all-paper-trade-chart-audit.json"
    out = tmp_path / "profitability-scoreboard.json"
    audit_path.write_text(json.dumps(_audit()), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "scripts/report_paper_profitability_scoreboard.py",
            str(audit_path),
            "--json-out", str(out),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(out.read_text(encoding="utf-8"))["overall"]["trades"] == 4
    assert audit_path.read_text(encoding="utf-8") == json.dumps(_audit())
    assert json.loads(result.stdout)["closed_net_pnl"] == "-13.9"


def test_worker_publishes_scoreboard_only_after_full_journal_audit() -> None:
    workflow = Path(".github/workflows/continuous-paper.yml").read_text(
        encoding="utf-8"
    )
    audit = workflow.index("- name: Audit all closed paper trades")
    upload = workflow.index("- name: Upload all closed paper-trade economics")
    scoreboard = workflow.index(
        "- name: Reconcile original paper after-cost profitability cohorts"
    )
    score_upload = workflow.index(
        "- name: Upload original paper after-cost profitability scoreboard"
    )
    assert audit < upload < scoreboard < score_upload
    block = workflow[scoreboard:score_upload]
    assert "steps.deferred_all_trade_chart_audit.outcome == 'success'" in block
    assert "continue-on-error: true" in block
    assert "timeout-minutes: 5" in block
    assert "all-paper-trade-chart-audit.json" in block
    assert "report_paper_profitability_scoreboard.py" in block
    artifact = workflow[score_upload:]
    assert "steps.paper_profitability_scoreboard.outcome == 'success'" in artifact
    assert "continuous-paper-profitability-scoreboard-" in artifact


def _reconciled_audit_from_rows(
    rows: list[dict[str, object]],
) -> dict[str, object]:
    """Use the same strict signed-journal totals, never delete bad entries."""
    audit = _audit()
    with localcontext(prec=96):
        gross = sum(
            (Decimal(str(row["gross_realized_pnl"])) for row in rows),
            Decimal(0),
        )
        fees = sum(
            (
                Decimal(str(row["entry_fees"])) +
                Decimal(str(row["exit_fees"]))
                for row in rows
            ),
            Decimal(0),
        )
        funding = sum(
            (Decimal(str(row["funding_cash_pnl"])) for row in rows),
            Decimal(0),
        )
        net = sum(
            (Decimal(str(row["net_pnl"])) for row in rows),
            Decimal(0),
        )
    audit["trades"] = rows
    audit["total_journal_trades"] = len(rows)
    audit["trades_included_in_economics"] = len(rows)
    audit["verified_entry_exit_context"] = {
        "entry_context_verified_trades": sum(
            row["entry_context"] is not None for row in rows
        ),
        "entry_context_unresolved_trades": sum(
            row["entry_context"] is None for row in rows
        ),
    }
    audit["economics"] = {
        "overall": {
            "trades": len(rows),
            "gross_realized_pnl": str(gross),
            "fees": str(fees),
            "funding_cash_pnl": str(funding),
            "net_pnl": str(net),
            "net_reconciliation_residual": str(net - gross + fees - funding),
        }
    }
    return audit


def test_short_breakout_top3_survives_outlier_omission_but_is_not_forward_edge() -> None:
    rows = [
        _trade(1, side="short", market="XPL", strategy="breakout", gross="0"),
        _trade(2, side="short", market="NIL", strategy="breakout",
               rank="top10", gross="-10"),
        _trade(3, side="short", market="HBAR", strategy="breakout", gross="50"),
        _trade(4, side="long", market="ADA", strategy="trend", gross="-100"),
        _trade(5, side="short", market="CRV", strategy="breakout",
               rank="outside10", gross="-5"),
        _trade(6, side="short", market="CASHCAT", strategy="breakout", gross="40"),
        _trade(7, side="short", market="AERO", strategy="breakout",
               rank="missing", gross="13"),
        _trade(8, side="short", market="STRK", strategy="breakout", gross="0"),
        _trade(9, side="long", market="ETH", strategy=None, gross="-20"),
    ]
    result = paper_profitability_scoreboard(_reconciled_audit_from_rows(rows))
    study = result["short_breakout_top3_robustness"]
    assert result["overall"]["trades"] == 9
    assert Decimal(result["overall"]["net_pnl"]) < 0
    assert study["short_breakout_top3"]["trades"] == 4
    assert study["short_breakout_top3"]["wins"] == 2
    assert study["short_breakout_top3"]["net_pnl"] == "86.0"
    assert study["short_breakout_other_bands_including_missing"]["trades"] == 3
    assert study["short_breakout_other_rank_missing_trades"] == 1
    assert study["short_breakout_all_rank_bands"]["trades"] == 7
    assert study["top3_distinct_markets"] == 4
    assert study["top3_min_net_after_leaving_one_trade_out"] == "37.0"
    assert study["top3_min_net_after_leaving_one_market_out"] == "37.0"
    assert study["top3_global_chronological_first_half"]["trades"] == 2
    assert study["top3_global_chronological_second_half"]["trades"] == 2
    assert study["meets_descriptive_sample_floor"] is False
    assert study["counterfactual_account_pnl_estimated"] is False
    assert study["ready_for_strategy_promotion"] is False
    assert study["forward_net_edge_verified"] is False
    assert study["execution_authority"] is False


def test_profitable_gross_short_breakout_can_still_lose_after_costs() -> None:
    rows = [
        _trade(
            1, side="short", market="ADA", strategy="breakout",
            gross="2", entry_fee="2", exit_fee="2",
        ),
        _trade(
            2, side="short", market="ARB", strategy="breakout",
            gross="2", entry_fee="2", exit_fee="2",
        ),
    ]
    result = paper_profitability_scoreboard(_reconciled_audit_from_rows(rows))
    study = result["short_breakout_top3_robustness"]
    assert study["short_breakout_top3"]["gross_realized_pnl"] == "4"
    assert study["short_breakout_top3"]["net_pnl"] == "-4"
    assert study["top3_min_net_after_leaving_one_trade_out"] == "-2"
    assert study["meets_descriptive_sample_floor"] is False
    assert study["forward_net_edge_verified"] is False


def test_empty_short_breakout_cohort_does_not_invent_a_trading_edge() -> None:
    result = paper_profitability_scoreboard(_audit())
    study = result["short_breakout_top3_robustness"]
    assert study["whole_journal_trades"] == 4
    assert study["short_breakout_top3"]["trades"] == 0
    assert study["top3_min_net_after_leaving_one_trade_out"] is None
    assert study["top3_min_net_after_leaving_one_market_out"] is None
    assert study["top3_largest_winner_share_of_positive_net"] is None
    assert study["meets_descriptive_sample_floor"] is False
    assert study["ready_for_strategy_promotion"] is False
