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




def test_report_cli_uses_exact_frozen_states_or_marks_absence(
    tmp_path: Path,
) -> None:
    from cocomelon.research.prospective_short_breakout_rank import (
        ProspectiveShortBreakoutRankState,
    )
    from cocomelon.research.prospective_trend_outside_top10 import (
        ProspectiveTrendOutsideTop10State,
    )

    source = tmp_path / "original-complete-trades.json"
    output = tmp_path / "separate-economic-readout.json"
    short = tmp_path / "frozen-short-breakout.json"
    trend = tmp_path / "frozen-trend-rank.json"
    source.write_text(json.dumps(_audit()), encoding="utf-8")
    short.write_text(
        json.dumps(ProspectiveShortBreakoutRankState(frozen_at_ms=0).payload()),
        encoding="utf-8",
    )
    trend.write_text(
        json.dumps(ProspectiveTrendOutsideTop10State(frozen_at_ms=0).payload()),
        encoding="utf-8",
    )
    cmd = [
        sys.executable,
        "scripts/report_paper_profitability_scoreboard.py",
        str(source),
        "--short-rank-freeze", str(short),
        "--trend-outside-freeze", str(trend),
        "--json-out", str(output),
    ]
    result = subprocess.run(
        cmd, check=False, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    forward = payload["frozen_hypotheses_original_forward_economics"]
    assert forward["hypotheses"][
        "short_breakout_rank4plus_skip"
    ]["frozen_state_verified"] is True
    assert forward["hypotheses"][
        "trend_outside_top10_both_sides_skip"
    ]["forward_trade_count"] == 0
    assert payload["overall"]["trades"] == 4
    assert payload["execution_authority"] is False
    assert source.read_text(encoding="utf-8") == json.dumps(_audit())
    assert short.is_file() and trend.is_file()
    bad = json.loads(short.read_text(encoding="utf-8"))
    bad["frozen_at_ms"] = 123
    short.write_text(json.dumps(bad), encoding="utf-8")
    broken = subprocess.run(
        cmd, check=False, capture_output=True, text=True
    )
    assert broken.returncode != 0
    assert "drift" in broken.stderr
    # Failure cannot rewrite a previously successful original output.
    assert json.loads(output.read_text(encoding="utf-8")) == payload


def test_real_paper_workflow_supplies_both_frozen_state_paths_to_report() -> None:
    workflow = Path(".github/workflows/continuous-paper.yml").read_text(
        encoding="utf-8"
    )
    start = workflow.index(
        "- name: Reconcile original paper after-cost profitability cohorts"
    )
    end = workflow.index(
        "- name: Upload original paper after-cost profitability scoreboard"
    )
    report = workflow[start:end]
    assert (
        '--short-rank-freeze "$STATE_ROOT/prospective-short-breakout-rank-state.json"'
        in report
    )
    assert (
        '--trend-outside-freeze "$STATE_ROOT/prospective-trend-outside-top10-state.json"'
        in report
    )
    assert "frozen_hypotheses_original_forward_economics" in report

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


def _move_trade_to_original_open_time(
    row: dict[str, object], opened_at_ms: int, *, closed_at_ms: int
) -> dict[str, object]:
    result = dict(row)
    result["opened_at_ms"] = opened_at_ms
    result["closed_at_ms"] = closed_at_ms
    context = result["entry_context"]
    if isinstance(context, dict):
        revised = dict(context)
        revised["opened_at_ms"] = opened_at_ms
        revised["closed_at_ms"] = closed_at_ms
        result["entry_context"] = revised
    return result


def test_frozen_hypotheses_only_count_openings_after_actual_six_hour_embargo() -> None:
    from cocomelon.research.prospective_short_breakout_rank import (
        ProspectiveShortBreakoutRankState,
    )
    from cocomelon.research.prospective_trend_outside_top10 import (
        ProspectiveTrendOutsideTop10State,
    )

    boundary = 6 * 3_600_000
    data = [
        _move_trade_to_original_open_time(
            _trade(
                1, side="short", market="BTC", strategy="breakout",
                gross="100", rank="outside10",
            ),
            boundary - 1, closed_at_ms=boundary + 1,
        ),
        _move_trade_to_original_open_time(
            _trade(
                2, side="short", market="ADA", strategy="breakout",
                gross="10", rank="top3",
            ),
            boundary, closed_at_ms=boundary + 5,
        ),
        _move_trade_to_original_open_time(
            _trade(
                3, side="short", market="CRV", strategy="breakout",
                gross="-9", rank="outside10",
            ),
            boundary + 5, closed_at_ms=boundary + 15,
        ),
        _move_trade_to_original_open_time(
            _trade(
                4, side="short", market="XPL", strategy="trend",
                gross="-4", rank="outside10",
            ),
            boundary + 17, closed_at_ms=boundary + 22,
        ),
        _move_trade_to_original_open_time(
            _trade(
                5, side="long", market="ETH", strategy="trend",
                gross="-5", rank="top10",
            ),
            boundary + 23, closed_at_ms=boundary + 28,
        ),
        _move_trade_to_original_open_time(
            _trade(
                6, side="long", market="ENA", strategy=None,
                gross="-2",
            ),
            boundary + 29, closed_at_ms=boundary + 35,
        ),
    ]
    audit = _reconciled_audit_from_rows(data)
    original_before_freeze = paper_profitability_scoreboard(audit)
    absent = original_before_freeze[
        "frozen_hypotheses_original_forward_economics"
    ]
    assert all(
        item["source_status"] == "missing_frozen_state"
        and item["forward_trade_count"] == 0
        for item in absent["hypotheses"].values()
    )
    report = paper_profitability_scoreboard(
        audit,
        short_rank_freeze=(
            ProspectiveShortBreakoutRankState(frozen_at_ms=0).payload()
        ),
        trend_outside_freeze=(
            ProspectiveTrendOutsideTop10State(frozen_at_ms=0).payload()
        ),
    )
    forward = report["frozen_hypotheses_original_forward_economics"]
    assert forward["original_whole_journal_trades"] == 6
    assert forward["original_whole_journal_net_pnl"] == "84.0"
    short = forward["hypotheses"]["short_breakout_rank4plus_skip"]
    trend = forward["hypotheses"]["trend_outside_top10_both_sides_skip"]
    assert short["source_status"] == "immutable_freeze_verified"
    assert short["forward_trade_count"] == 5
    assert short["post_embargo_started_at_ms"] == boundary
    assert len(short["frozen_state_sha256"]) == 64
    assert short["original_forward_whole_journal"]["trades"] == 5
    assert short["original_forward_hypothesis_context"]["trades"] == 2
    assert short["preferred_rank_attributed_original_closes"]["trades"] == 1
    assert short["disfavored_rank_attributed_original_closes"]["trades"] == 1
    assert short["original_forward_unverified_entry_context_count"] == 1
    preferred_stress = short["original_forward_preferred_rank_robustness"]
    assert preferred_stress["cohort_original_closes"] == 1
    assert preferred_stress["distinct_original_markets"] == 1
    assert preferred_stress["global_forward_first_half"]["trades"] == 1
    assert preferred_stress["global_forward_second_half"]["trades"] == 0
    assert preferred_stress["min_net_pnl_leaving_one_trade_out"] is None
    assert preferred_stress["min_net_r_leaving_one_market_out"] is None
    assert preferred_stress["promotion_authority"] is False
    assert short["original_forward_disfavored_rank_robustness"][
        "global_forward_first_half"
    ]["trades"] == 1
    assert short["candidate_skip_cashflow_simulated"] is False
    assert short["ready_for_review"] is False
    assert trend["forward_trade_count"] == 5
    assert trend["original_forward_hypothesis_context"]["trades"] == 2
    assert trend["disfavored_rank_attributed_original_closes"]["trades"] == 1
    assert trend["preferred_rank_attributed_original_closes"]["trades"] == 1
    assert trend["execution_authority"] is False
    assert forward["promotion_authority"] is False
    assert forward["no_claim_of_counterfactual_account_returns"] is True


def test_mutated_frozen_state_fails_closed_without_reporting_a_forward_edge() -> None:
    from cocomelon.research.prospective_short_breakout_rank import (
        ProspectiveShortBreakoutRankError,
        ProspectiveShortBreakoutRankState,
    )

    frozen = ProspectiveShortBreakoutRankState(frozen_at_ms=0).payload()
    frozen["started_at_ms"] = 0
    with pytest.raises(ProspectiveShortBreakoutRankError, match="drift"):
        paper_profitability_scoreboard(_audit(), short_rank_freeze=frozen)


def test_no_new_original_forward_closes_is_not_profitable_evidence() -> None:
    from cocomelon.research.prospective_short_breakout_rank import (
        ProspectiveShortBreakoutRankState,
    )

    frozen = ProspectiveShortBreakoutRankState(frozen_at_ms=1_000_000_000)
    report = paper_profitability_scoreboard(
        _audit(), short_rank_freeze=frozen.payload()
    )
    forward = report["frozen_hypotheses_original_forward_economics"]
    study = forward["hypotheses"]["short_breakout_rank4plus_skip"]
    assert study["frozen_state_verified"] is True
    assert study["forward_trade_count"] == 0
    assert study["original_forward_hypothesis_context"]["net_pnl"] == "0"
    assert study["original_forward_unverified_entry_context_count"] == 0
    assert study["sufficient_original_forward_trade_count"] is False
    assert study["ready_for_review"] is False
    assert study["promotion_authority"] is False


def test_post_embargo_rank_stress_exposes_concentrated_winners_and_net_r() -> None:
    from cocomelon.research.prospective_short_breakout_rank import (
        ProspectiveShortBreakoutRankState,
    )

    boundary = 6 * 3_600_000
    rows = [
        _move_trade_to_original_open_time(
            _trade(
                1, side="short", market="BTC", strategy="breakout",
                rank="top3", gross="21",
            ),
            boundary + 10, closed_at_ms=boundary + 11,
        ),
        _move_trade_to_original_open_time(
            _trade(
                2, side="short", market="ADA", strategy="breakout",
                rank="top3", gross="-3",
            ),
            boundary + 20, closed_at_ms=boundary + 21,
        ),
        _move_trade_to_original_open_time(
            _trade(
                3, side="short", market="CRV", strategy="breakout",
                rank="outside10", gross="-5",
            ),
            boundary + 30, closed_at_ms=boundary + 31,
        ),
        _move_trade_to_original_open_time(
            _trade(
                4, side="short", market="ENA", strategy=None,
                gross="-9",
            ),
            boundary + 40, closed_at_ms=boundary + 41,
        ),
    ]
    report = paper_profitability_scoreboard(
        _reconciled_audit_from_rows(rows),
        short_rank_freeze=ProspectiveShortBreakoutRankState(
            frozen_at_ms=0
        ).payload(),
    )
    study = report["frozen_hypotheses_original_forward_economics"][
        "hypotheses"
    ]["short_breakout_rank4plus_skip"]
    assert study["forward_trade_count"] == 4
    assert Decimal(study["original_forward_whole_journal"]["net_pnl"]) == 0
    preferred = study["original_forward_preferred_rank_robustness"]
    assert Decimal(study["preferred_rank_attributed_original_closes"]["net_pnl"]) == 16
    assert preferred["distinct_original_markets"] == 2
    assert Decimal(preferred["min_net_pnl_leaving_one_trade_out"]) == -4
    assert Decimal(preferred["min_net_r_leaving_one_trade_out"]) == Decimal("-0.2")
    assert Decimal(preferred["min_net_pnl_leaving_one_market_out"]) == -4
    assert Decimal(preferred["min_net_r_leaving_one_market_out"]) == Decimal("-0.2")
    assert preferred["largest_winner_share_of_positive_net"] == "1"
    assert preferred["global_forward_first_half"]["trades"] == 2
    assert preferred["global_forward_second_half"]["trades"] == 0
    assert preferred["global_forward_second_half"]["net_pnl"] == "0"
    assert preferred["independent_forward_edge_verified"] is False
    assert study["unresolved_rank_original_closes"]["trades"] == 0
    assert report["promotion_authority"] is False


def test_empty_frozen_rank_stress_has_no_invented_profitability() -> None:
    from cocomelon.research.prospective_trend_outside_top10 import (
        ProspectiveTrendOutsideTop10State,
    )

    result = paper_profitability_scoreboard(
        _audit(),
        trend_outside_freeze=ProspectiveTrendOutsideTop10State(
            frozen_at_ms=1_000_000_000
        ).payload(),
    )
    study = result["frozen_hypotheses_original_forward_economics"][
        "hypotheses"
    ]["trend_outside_top10_both_sides_skip"]
    preferred = study["original_forward_preferred_rank_robustness"]
    assert preferred["cohort_original_closes"] == 0
    assert preferred["min_net_pnl_leaving_one_trade_out"] is None
    assert preferred["min_net_r_leaving_one_market_out"] is None
    assert preferred["largest_winner_share_of_positive_net"] is None
    assert preferred["global_forward_first_half"]["trades"] == 0
    assert preferred["global_forward_second_half"]["trades"] == 0
    assert preferred["independent_forward_edge_verified"] is False



def test_whole_original_journal_booked_friction_flips_are_exact() -> None:
    """Separate observed fee/funding erosion from raw trade-direction losses."""
    rows = [
        _trade(
            1, side="short", market="BTC", strategy="breakout",
            gross="0.4",
        ),
        _trade(
            2, side="short", market="ETH", strategy="breakout",
            gross="2",
        ),
        _trade(
            3, side="long", market="SOL", strategy="trend",
            gross="-1", funding="3",
        ),
        _trade(
            4, side="long", market="OP", strategy=None,
            gross="0", funding="1",
        ),
        _trade(
            5, side="long", market="ARB", strategy="trend",
            gross="-9",
        ),
    ]
    source = _reconciled_audit_from_rows(rows)
    report = paper_profitability_scoreboard(source)
    overall = report["overall"]
    assert overall["trades"] == 5
    assert Decimal(overall["gross_realized_pnl"]) == Decimal("-7.6")
    assert Decimal(overall["fees"]) == 5
    assert Decimal(overall["funding_cash_pnl"]) == 4
    assert Decimal(overall["net_pnl"]) == Decimal("-8.6")
    assert Decimal(overall["recorded_fees_minus_funding_cash"]) == 1
    assert Decimal(overall["gross_minus_booked_net_pnl"]) == 1
    assert Decimal(overall["booked_net_cash_reconciliation_residual"]) == 0
    assert overall["gross_positive_trades"] == 2
    assert overall["gross_positive_net_nonpositive_trades"] == 1
    assert overall["gross_positive_net_negative_trades"] == 1
    assert overall["gross_nonpositive_net_positive_trades"] == 1
    assert Decimal(overall["gross_positive_flipped_booked_gross_pnl"]) == Decimal("0.4")
    assert Decimal(overall["gross_positive_flipped_booked_net_pnl"]) == Decimal("-0.6")
    assert Decimal(overall["gross_positive_flipped_recorded_fees"]) == 1
    assert Decimal(overall["gross_positive_flipped_funding_cash_pnl"]) == 0
    assert sum(x["gross_positive_net_nonpositive_trades"] for x in report["side_cohorts"]) == 1
    assert sum(x["gross_positive_net_nonpositive_trades"] for x in report["strategy_cohorts"]) == 1
    assert source["trades"] == rows
    assert report["promotion_authority"] is False


def test_frozen_forward_friction_excludes_pre_embargo_winning_trades() -> None:
    from cocomelon.research.prospective_short_breakout_rank import (
        ProspectiveShortBreakoutRankState,
    )

    boundary = 6 * 3_600_000
    rows = [
        _move_trade_to_original_open_time(
            _trade(
                1, side="short", market="BTC", strategy="breakout",
                gross="2", rank="outside10",
            ),
            boundary - 1, closed_at_ms=boundary + 1,
        ),
        _move_trade_to_original_open_time(
            _trade(
                2, side="short", market="ETH", strategy="breakout",
                gross="0.25", rank="top3",
            ),
            boundary, closed_at_ms=boundary + 2,
        ),
        _move_trade_to_original_open_time(
            _trade(
                3, side="short", market="SOL", strategy="breakout",
                gross="-2", rank="outside10",
            ),
            boundary + 10, closed_at_ms=boundary + 12,
        ),
    ]
    report = paper_profitability_scoreboard(
        _reconciled_audit_from_rows(rows),
        short_rank_freeze=ProspectiveShortBreakoutRankState(
            frozen_at_ms=0
        ).payload(),
    )
    hypothesis = report["frozen_hypotheses_original_forward_economics"][
        "hypotheses"
    ]["short_breakout_rank4plus_skip"]
    assert hypothesis["forward_trade_count"] == 2
    assert hypothesis["original_forward_whole_journal"]["gross_positive_trades"] == 1
    preferred = hypothesis["preferred_rank_attributed_original_closes"]
    assert preferred["gross_positive_net_negative_trades"] == 1
    assert Decimal(preferred["gross_positive_flipped_booked_gross_pnl"]) == Decimal("0.25")
    assert Decimal(preferred["gross_positive_flipped_booked_net_pnl"]) == Decimal("-0.75")
    assert hypothesis["disfavored_rank_attributed_original_closes"][
        "gross_positive_net_nonpositive_trades"
    ] == 0
    assert report["overall"]["gross_positive_trades"] == 2
    assert hypothesis["promotion_authority"] is False


def test_subcent_booked_residual_stays_visible_in_friction_diagnostics() -> None:
    source = _audit()
    row = source["trades"][1]
    assert isinstance(row, dict)
    row["net_pnl"] = "4.000000000000000000000000001"
    context = row["entry_context"]
    assert isinstance(context, dict)
    context["net_pnl"] = row["net_pnl"]
    original = source["economics"]["overall"]
    assert isinstance(original, dict)
    with localcontext(prec=96):
        original["net_pnl"] = str(
            Decimal(str(original["net_pnl"])) +
            Decimal("0.000000000000000000000000001")
        )
    original["net_reconciliation_residual"] = "0.000000000000000000000000001"
    metrics = paper_profitability_scoreboard(source)["overall"]
    assert Decimal(
        metrics["booked_net_cash_reconciliation_residual"]
    ) == Decimal("0.000000000000000000000000001")
    assert Decimal(metrics["gross_minus_booked_net_pnl"]) != Decimal(
        metrics["recorded_fees_minus_funding_cash"]
    )



def test_forward_trend_both_sides_exposes_loss_hidden_by_net_pooling() -> None:
    from cocomelon.research.prospective_trend_outside_top10 import (
        ProspectiveTrendOutsideTop10State,
    )

    boundary = 6 * 3_600_000
    rows = [
        _move_trade_to_original_open_time(
            _trade(
                1, side="long", market="BTC", strategy="trend",
                rank="top3", gross="31", funding="-1",
            ),
            boundary - 1, closed_at_ms=boundary + 1,
        ),
        _move_trade_to_original_open_time(
            _trade(
                2, side="long", market="ETH", strategy="trend",
                rank="top10", gross="22", funding="-1",
            ),
            boundary + 1, closed_at_ms=boundary + 2,
        ),
        _move_trade_to_original_open_time(
            _trade(
                3, side="short", market="OP", strategy="trend",
                rank="top3", gross="-10",
            ),
            boundary + 3, closed_at_ms=boundary + 4,
        ),
        _move_trade_to_original_open_time(
            _trade(
                4, side="short", market="ADA", strategy="trend",
                rank="outside10", gross="-7",
            ),
            boundary + 5, closed_at_ms=boundary + 6,
        ),
        _move_trade_to_original_open_time(
            _trade(
                5, side="long", market="SOL", strategy="trend",
                rank="missing", gross="-4",
            ),
            boundary + 7, closed_at_ms=boundary + 8,
        ),
        _move_trade_to_original_open_time(
            _trade(
                6, side="short", market="ARB", strategy=None,
                gross="-3",
            ),
            boundary + 9, closed_at_ms=boundary + 10,
        ),
    ]
    result = paper_profitability_scoreboard(
        _reconciled_audit_from_rows(rows),
        trend_outside_freeze=ProspectiveTrendOutsideTop10State(
            frozen_at_ms=0
        ).payload(),
    )
    f = result["frozen_hypotheses_original_forward_economics"]["hypotheses"][
        "trend_outside_top10_both_sides_skip"
    ]
    assert f["forward_trade_count"] == 5
    preferred = f["preferred_rank_attributed_original_closes"]
    by_side = f["preferred_rank_attributed_original_closes_by_side"]
    assert preferred["trades"] == 2
    assert Decimal(preferred["net_pnl"]) == 9
    assert Decimal(by_side["long"]["net_pnl"]) == 20
    assert Decimal(by_side["short"]["net_pnl"]) == -11
    assert by_side["long"]["trades"] == 1
    assert by_side["short"]["trades"] == 1
    for name, side_key in (
        ("original_forward_hypothesis_context", "original_forward_hypothesis_context_by_side"),
        (
            "preferred_rank_attributed_original_closes",
            "preferred_rank_attributed_original_closes_by_side",
        ),
        (
            "disfavored_rank_attributed_original_closes",
            "disfavored_rank_attributed_original_closes_by_side",
        ),
        ("unresolved_rank_original_closes", "unresolved_rank_original_closes_by_side"),
    ):
        overall = f[name]
        split = f[side_key]
        assert overall["trades"] == split["long"]["trades"] + split["short"]["trades"]
        for field in ("gross_realized_pnl", "fees", "funding_cash_pnl", "net_pnl", "net_r"):
            assert Decimal(overall[field]) == (
                Decimal(split["long"][field]) + Decimal(split["short"][field])
            )
    assert f["disfavored_rank_attributed_original_closes_by_side"][
        "short"
    ]["trades"] == 1
    assert f["unresolved_rank_original_closes_by_side"]["long"]["trades"] == 1
    assert f["unresolved_rank_original_closes_by_side"]["short"]["trades"] == 0
    assert f["candidate_skip_cashflow_simulated"] is False
    assert f["promotion_authority"] is False


def test_short_only_forward_hypothesis_reports_zero_long_closes() -> None:
    from cocomelon.research.prospective_short_breakout_rank import (
        ProspectiveShortBreakoutRankState,
    )

    result = paper_profitability_scoreboard(
        _audit(),
        short_rank_freeze=ProspectiveShortBreakoutRankState(
            frozen_at_ms=0
        ).payload(),
    )
    hypothesis = result["frozen_hypotheses_original_forward_economics"][
        "hypotheses"
    ]["short_breakout_rank4plus_skip"]
    for name in (
        "original_forward_hypothesis_context_by_side",
        "preferred_rank_attributed_original_closes_by_side",
        "disfavored_rank_attributed_original_closes_by_side",
        "unresolved_rank_original_closes_by_side",
    ):
        assert hypothesis[name]["long"]["trades"] == 0
        assert Decimal(hypothesis[name]["long"]["net_pnl"]) == 0
        assert hypothesis[name]["short"]["trades"] == 0
    assert hypothesis["ready_for_review"] is False



def test_fee_only_cannot_rescue_actual_negative_gross_original_journal() -> None:
    """Even removing every booked fee can leave the observed account red."""
    source = _reconciled_audit_from_rows([
        _trade(
            1, side="long", market="BTC", strategy="trend", gross="-10",
            entry_fee="1", exit_fee="1", funding="1",
        ),
        _trade(
            2, side="short", market="ETH", strategy="breakout", gross="4",
            entry_fee="0.5", exit_fee="0.5", funding="-0.5",
        ),
    ])
    result = paper_profitability_scoreboard(source)
    metrics = result["overall"]
    assert Decimal(metrics["gross_realized_pnl"]) == -6
    assert Decimal(metrics["fees"]) == 3
    assert Decimal(metrics["funding_cash_pnl"]) == Decimal("0.5")
    assert Decimal(metrics["net_pnl"]) == Decimal("-8.5")
    assert Decimal(metrics["same_fill_all_recorded_fees_refunded_net_pnl"]) == (
        Decimal("-5.5")
    )
    with localcontext(prec=96):
        assert Decimal(
            metrics["same_fill_fee_refund_fraction_needed_for_zero_net"]
        ) == Decimal("8.5") / 3
    assert metrics["same_fill_all_fee_refund_still_net_negative"] is True
    assert Decimal(
        metrics["same_fill_additional_gross_needed_even_after_full_fee_refund"]
    ) == Decimal("5.5")
    assert metrics["fee_refund_bound_semantics"] == (
        "arithmetic_same_original_fills_not_executable_or_new_equity"
    )
    assert result["execution_authority"] is False
    assert result["ready_for_strategy_promotion"] is False


def test_fee_only_bound_can_rescue_a_losing_single_original_close() -> None:
    source = _reconciled_audit_from_rows([
        _trade(
            1, side="long", market="BTC", strategy="trend",
            gross="0.5", entry_fee="0.4", exit_fee="0.6",
        ),
    ])
    metrics = paper_profitability_scoreboard(source)["overall"]
    assert Decimal(metrics["net_pnl"]) == Decimal("-0.5")
    assert Decimal(metrics["same_fill_all_recorded_fees_refunded_net_pnl"]) == (
        Decimal("0.5")
    )
    assert Decimal(
        metrics["same_fill_fee_refund_fraction_needed_for_zero_net"]
    ) == Decimal("0.5")
    assert metrics["same_fill_all_fee_refund_still_net_negative"] is False
    assert Decimal(
        metrics["same_fill_additional_gross_needed_even_after_full_fee_refund"]
    ) == 0


def test_fee_refund_fraction_null_when_no_booked_fees_or_trades() -> None:
    source = _reconciled_audit_from_rows([
        _trade(
            1, side="long", market="BTC", strategy="trend",
            gross="-3", entry_fee="0", exit_fee="0",
        ),
    ])
    report = paper_profitability_scoreboard(source)
    assert report["overall"][
        "same_fill_fee_refund_fraction_needed_for_zero_net"
    ] is None
    assert report["overall"]["same_fill_all_fee_refund_still_net_negative"] is True
    assert Decimal(
        report["overall"]["same_fill_additional_gross_needed_even_after_full_fee_refund"]
    ) == 3
    empty = paper_profitability_scoreboard(_reconciled_audit_from_rows([]))
    assert empty["overall"]["same_fill_all_fee_refund_still_net_negative"] is None
    assert empty["overall"]["same_fill_fee_refund_fraction_needed_for_zero_net"] is None
    assert Decimal(empty["overall"]["same_fill_all_recorded_fees_refunded_net_pnl"]) == 0


def test_frozen_fee_only_bound_preserves_original_open_time_embargo() -> None:
    from cocomelon.research.prospective_trend_outside_top10 import (
        ProspectiveTrendOutsideTop10State,
    )

    boundary = 6 * 3_600_000
    rows = [
        _move_trade_to_original_open_time(
            _trade(
                1, side="short", market="BTC", strategy="trend",
                gross="400", rank="outside10",
            ),
            boundary - 1, closed_at_ms=boundary + 10,
        ),
        _move_trade_to_original_open_time(
            _trade(
                2, side="short", market="SOL", strategy="trend",
                gross="-5", rank="outside10",
            ),
            boundary, closed_at_ms=boundary + 20,
        ),
        _move_trade_to_original_open_time(
            _trade(
                3, side="long", market="OP", strategy="trend",
                gross="0.25", rank="top10",
            ),
            boundary + 1, closed_at_ms=boundary + 30,
        ),
    ]
    report = paper_profitability_scoreboard(
        _reconciled_audit_from_rows(rows),
        trend_outside_freeze=ProspectiveTrendOutsideTop10State(
            frozen_at_ms=0
        ).payload(),
    )
    f = report["frozen_hypotheses_original_forward_economics"][
        "hypotheses"
    ]["trend_outside_top10_both_sides_skip"]
    disfavored = f["disfavored_rank_attributed_original_closes"]
    assert disfavored["trades"] == 1
    assert Decimal(disfavored["net_pnl"]) == -6
    assert Decimal(
        disfavored["same_fill_all_recorded_fees_refunded_net_pnl"]
    ) == -5
    assert disfavored["same_fill_all_fee_refund_still_net_negative"] is True
    assert Decimal(
        f["original_forward_hypothesis_context_by_side"]["short"][
            "same_fill_all_recorded_fees_refunded_net_pnl"
        ]
    ) == -5
    assert Decimal(report["overall"]["gross_realized_pnl"]) > 390
    assert f["candidate_skip_cashflow_simulated"] is False
    assert f["promotion_authority"] is False


def test_fee_only_bound_preserves_actual_subcent_booked_residual() -> None:
    source = _audit()
    row = source["trades"][1]
    assert isinstance(row, dict)
    row["net_pnl"] = "4.000000000000000000000000001"
    context = row["entry_context"]
    assert isinstance(context, dict)
    context["net_pnl"] = row["net_pnl"]
    overall = source["economics"]["overall"]
    assert isinstance(overall, dict)
    with localcontext(prec=96):
        overall["net_pnl"] = str(
            Decimal(str(overall["net_pnl"])) +
            Decimal("0.000000000000000000000000001")
        )
    overall["net_reconciliation_residual"] = "0.000000000000000000000000001"
    result = paper_profitability_scoreboard(source)["overall"]
    with localcontext(prec=96):
        assert Decimal(
            result["same_fill_all_recorded_fees_refunded_net_pnl"]
        ) == Decimal(result["net_pnl"]) + Decimal(result["fees"])
        assert Decimal(result["booked_net_cash_reconciliation_residual"]) == (
            Decimal("0.000000000000000000000000001")
        )
