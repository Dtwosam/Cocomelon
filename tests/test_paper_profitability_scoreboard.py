"""Net losses must remain visible for every original executed paper trade."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
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
        "initial_risk_amount": "20",
        "chart_coverage_complete": chart,
        "exit_reason": "MARK_STOP_TRIGGERED",
        "chart_path_present": chart,
        "chart_mark_count": 2 if chart else 0,
        "chart_mark_samples": (
            [[opened, "10"], [closed, "9"]] if chart else []
        ),
        "chart_known_gap_duration_ms": 0 if chart else None,
        "chart_longest_unobserved_mark_ms": 10 if chart else None,
        "chart_unresolved_gap_starts_before_entry": 0,
        "chart_unresolved_gap_starts_during_position": 0,
        "chart_silent_gap_intervals_ms": [],
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
            "per-trade booked net",
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



def test_offsetting_trade_cashflow_corruption_cannot_hide_in_whole_net() -> None:
    """Opposite row-level forgeries preserve the signed total, not cohorts."""
    source = _audit()
    source["trades"][1]["net_pnl"] = "19"
    source["trades"][1]["entry_context"]["net_pnl"] = "19"
    source["trades"][2]["net_pnl"] = "-17"
    # Original whole-journal net, gross, fees, funding and declared residual
    # remain EXACTLY unchanged. The verified ETH row and unverified SOL row
    # falsely move $15 between strategy/rank cohorts.
    assert source["economics"]["overall"]["net_pnl"] == "-13.9"
    assert source["economics"]["overall"]["net_reconciliation_residual"] == "0.0"
    with pytest.raises(
        PaperProfitabilityScoreboardError, match="per-trade booked net"
    ):
        paper_profitability_scoreboard(source)


def test_forged_aggregate_booked_residual_cannot_authorize_bad_trade() -> None:
    source = _audit()
    row = source["trades"][1]
    row["net_pnl"] = "4.000001"
    row["entry_context"]["net_pnl"] = "4.000001"
    original = source["economics"]["overall"]
    original["net_pnl"] = "-13.899999"
    original["net_reconciliation_residual"] = "0.000001"
    with pytest.raises(
        PaperProfitabilityScoreboardError, match="per-trade booked net"
    ):
        paper_profitability_scoreboard(source)


def test_genuine_precision_scale_residuals_are_retained_not_erased() -> None:
    source = _audit()
    row = source["trades"][1]
    row["net_pnl"] = "4.000000000000000000000000005"
    row["entry_context"]["net_pnl"] = row["net_pnl"]
    # A genuine journal also books its risk-normalized R at the same
    # authoritative Decimal precision when its signed net cash changes.
    from cocomelon.domain.journal import AUTHORITATIVE_CONTEXT
    with localcontext(AUTHORITATIVE_CONTEXT):
        row["net_r"] = str(
            Decimal(str(row["net_pnl"])) / Decimal(str(row["initial_risk_amount"]))
        )
    original = source["economics"]["overall"]
    with localcontext(prec=96):
        original["net_pnl"] = str(
            Decimal(str(original["net_pnl"])) + Decimal("5E-27")
        )
    original["net_reconciliation_residual"] = "5E-27"
    result = paper_profitability_scoreboard(source)
    overall = result["overall"]
    assert overall["per_trade_nonzero_net_cash_residual_count"] == 1
    assert Decimal(overall["per_trade_max_abs_net_cash_residual"]) == Decimal("5E-27")
    assert Decimal(overall["per_trade_residual_precision_bound"]) == Decimal("1E-18")
    assert Decimal(overall["booked_net_cash_reconciliation_residual"]) == Decimal("5E-27")
    assert sum(
        cohort["per_trade_nonzero_net_cash_residual_count"]
        for cohort in result["strategy_cohorts"]
    ) == 1
    assert result["promotion_authority"] is False


def test_empty_original_journal_has_no_invented_booked_cash_residue() -> None:
    result = paper_profitability_scoreboard(_reconciled_audit_from_rows([]))
    assert result["overall"]["per_trade_nonzero_net_cash_residual_count"] == 0
    assert Decimal(result["overall"]["per_trade_max_abs_net_cash_residual"]) == 0



def test_original_chart_coverage_exposes_breakout_winners_only_in_missing_paths() -> None:
    """Chart-complete losses must not be masked by incomplete-path winners."""
    rows = [
        _trade(
            1, side="short", market="BTC", strategy="breakout",
            gross="101", chart=False,
        ),
        _trade(
            2, side="long", market="ETH", strategy="breakout",
            gross="-9", chart=True,
        ),
        _trade(
            3, side="short", market="OP", strategy="trend",
            gross="-4", chart=False,
        ),
        _trade(
            4, side="long", market="SOL", strategy=None,
            gross="-2", chart=False,
        ),
        _trade(
            5, side="short", market="ARB", strategy="breakout",
            gross="-3", chart=True,
        ),
    ]
    result = paper_profitability_scoreboard(_reconciled_audit_from_rows(rows))
    overall = result["original_chart_coverage_economics"]
    assert overall["whole_original_cohort"]["trades"] == 5
    assert overall["complete_observed_path_original_closes"]["trades"] == 2
    assert overall["incomplete_or_missing_path_original_closes"]["trades"] == 3
    assert overall["counterfactual_exit_cashflow_simulated"] is False
    assert overall["ready_for_strategy_promotion"] is False
    assert result["promotion_authority"] is False

    groups = result["strategy_chart_coverage_economics"]
    assert {row["lead_strategy"] for row in groups} == {
        "breakout", "trend", "UNVERIFIED_ENTRY_CONTEXT"
    }
    breakout = next(row for row in groups if row["lead_strategy"] == "breakout")
    assert breakout["whole_original_cohort"]["trades"] == 3
    assert Decimal(breakout["whole_original_cohort"]["net_pnl"]) == 86
    assert Decimal(
        breakout["complete_observed_path_original_closes"]["net_pnl"]
    ) == -14
    assert Decimal(
        breakout["incomplete_or_missing_path_original_closes"]["net_pnl"]
    ) == 100
    for row in (
        overall, *groups, *result["side_strategy_chart_coverage_economics"],
        *result["chronological_quartile_chart_coverage_economics"],
    ):
        whole = row["whole_original_cohort"]
        complete = row["complete_observed_path_original_closes"]
        incomplete = row["incomplete_or_missing_path_original_closes"]
        assert whole["trades"] == complete["trades"] + incomplete["trades"]
        for field in ("gross_realized_pnl", "fees", "funding_cash_pnl", "net_pnl", "net_r"):
            assert Decimal(whole[field]) == (
                Decimal(complete[field]) + Decimal(incomplete[field])
            )
    assert sum(
        row["whole_original_cohort"]["trades"]
        for row in result["chronological_quartile_chart_coverage_economics"]
    ) == 5
    assert sum(
        row["whole_original_cohort"]["trades"]
        for row in result["side_strategy_chart_coverage_economics"]
    ) == 5


def test_frozen_chart_economics_rejects_pre_embargo_winner_without_inventing_fill() -> None:
    from cocomelon.research.prospective_trend_outside_top10 import (
        ProspectiveTrendOutsideTop10State,
    )

    boundary = 6 * 3_600_000
    rows = [
        _move_trade_to_original_open_time(
            _trade(
                1, side="long", market="BTC", strategy="trend",
                rank="outside10", gross="200", chart=True,
            ), boundary - 1, closed_at_ms=boundary + 3,
        ),
        _move_trade_to_original_open_time(
            _trade(
                2, side="short", market="ETH", strategy="trend",
                rank="outside10", gross="11", chart=False,
            ), boundary, closed_at_ms=boundary + 4,
        ),
        _move_trade_to_original_open_time(
            _trade(
                3, side="long", market="OP", strategy="trend",
                rank="top10", gross="-8", chart=True,
            ), boundary + 1, closed_at_ms=boundary + 5,
        ),
        _move_trade_to_original_open_time(
            _trade(
                4, side="short", market="SOL", strategy="trend",
                rank="missing", gross="-6", chart=False,
            ), boundary + 2, closed_at_ms=boundary + 6,
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
    assert f["forward_trade_count"] == 3
    parts = (
        (
            "original_forward_hypothesis_context",
            "original_forward_hypothesis_chart_coverage_economics",
        ),
        (
            "preferred_rank_attributed_original_closes",
            "preferred_original_chart_coverage_economics",
        ),
        (
            "disfavored_rank_attributed_original_closes",
            "disfavored_original_chart_coverage_economics",
        ),
        ("unresolved_rank_original_closes", "unresolved_original_chart_coverage_economics"),
    )
    for original, key in parts:
        row = f[original]
        split = f[key]
        assert row["trades"] == split["whole_original_cohort"]["trades"]
        assert row["trades"] == (
            split["complete_observed_path_original_closes"]["trades"] +
            split["incomplete_or_missing_path_original_closes"]["trades"]
        )
        for field in ("gross_realized_pnl", "fees", "funding_cash_pnl", "net_pnl", "net_r"):
            assert Decimal(row[field]) == (
                Decimal(split["complete_observed_path_original_closes"][field]) +
                Decimal(split["incomplete_or_missing_path_original_closes"][field])
            )
    excluded = f["disfavored_original_chart_coverage_economics"]
    assert excluded["whole_original_cohort"]["trades"] == 1
    assert excluded["complete_observed_path_original_closes"]["trades"] == 0
    assert Decimal(excluded["incomplete_or_missing_path_original_closes"]["net_pnl"]) == 10
    assert f["unresolved_original_chart_coverage_economics"][
        "incomplete_or_missing_path_original_closes"
    ]["trades"] == 1
    assert f["candidate_skip_cashflow_simulated"] is False
    assert excluded["counterfactual_exit_cashflow_simulated"] is False
    assert f["promotion_authority"] is False


def test_empty_journal_chart_evidence_has_no_fabricated_account_edge() -> None:
    result = paper_profitability_scoreboard(_reconciled_audit_from_rows([]))
    split = result["original_chart_coverage_economics"]
    assert split["whole_original_cohort"]["trades"] == 0
    assert split["complete_observed_path_original_closes"]["trades"] == 0
    assert split["incomplete_or_missing_path_original_closes"]["trades"] == 0
    assert result["strategy_chart_coverage_economics"] == []
    assert len(result["chronological_quartile_chart_coverage_economics"]) == 4
    assert split["promotion_authority"] is False



@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ({"chart_path_present": False}, "claimed complete"),
        ({"chart_mark_count": 1}, "samples exceed recorded raw marks"),
        ({"chart_known_gap_duration_ms": 1}, "claimed complete"),
        ({"chart_known_gap_duration_ms": None}, "claimed complete"),
        ({"chart_longest_unobserved_mark_ms": 300_001}, "claimed complete"),
        ({"chart_longest_unobserved_mark_ms": None}, "claimed complete"),
        ({"chart_unresolved_gap_starts_before_entry": 1}, "claimed complete"),
        ({"chart_unresolved_gap_starts_during_position": 1}, "claimed complete"),
        ({"chart_silent_gap_intervals_ms": [[1_001, 1_010]]}, "claimed complete"),
        ({"chart_mark_count": True}, "chart mark count"),
        ({"chart_silent_gap_intervals_ms": [[1_010, 1_001]]}, "silent gap"),
    ],
)
def test_forged_chart_complete_label_fails_without_real_source_witnesses(
    mutation: dict[str, object], expected: str
) -> None:
    source = _audit()
    verified = source["trades"][1]
    assert verified["chart_coverage_complete"] is True
    verified.update(mutation)
    with pytest.raises(PaperProfitabilityScoreboardError, match=expected):
        paper_profitability_scoreboard(source)


def test_chart_absent_with_fabricated_mark_evidence_fails_closed() -> None:
    source = _audit()
    unverified = source["trades"][2]
    assert unverified["chart_path_present"] is False
    unverified["chart_mark_count"] = 2
    with pytest.raises(
        PaperProfitabilityScoreboardError, match="missing original price path"
    ):
        paper_profitability_scoreboard(source)


def test_valid_source_chart_claim_and_incomplete_groups_reconcile() -> None:
    source = _audit()
    source["trades"][0].update({
        "chart_path_present": True,
        "chart_mark_count": 81,
        "chart_known_gap_duration_ms": None,
        "chart_longest_unobserved_mark_ms": 1_000,
        "chart_unresolved_gap_starts_before_entry": 1,
        "chart_unresolved_gap_starts_during_position": 0,
        "chart_silent_gap_intervals_ms": [],
        "chart_coverage_complete": False,
    })
    report = paper_profitability_scoreboard(source)
    assert report["overall"]["trades"] == 4
    assert report["overall"]["incomplete_chart_trades"] == 3
    assert report["original_chart_coverage_economics"][
        "complete_observed_path_original_closes"
    ]["trades"] == 1
    assert report["original_chart_coverage_economics"][
        "incomplete_or_missing_path_original_closes"
    ]["trades"] == 3
    assert report["promotion_authority"] is False



@pytest.mark.parametrize(
    ("samples", "error"),
    [
        ([[2_010, "10"], [2_010, "9"]], "claimed complete"),
        ([[2_010, "10"]], "claimed complete"),
        ([[2_011, "10"], [2_010, "9"]], "chronology"),
        ([[True, "10"], [2_011, "9"]], "malformed"),
        ([[2_010, "10"], [2_011, "9"], [2_012, "9"]], "exceed"),
        ([[2_010, "10"], [2_011, None]], "malformed"),
    ],
)
def test_complete_original_chart_claim_needs_distinct_valid_mark_times(
    samples: list[list[object]], error: str
) -> None:
    source = _audit()
    trade = source["trades"][1]
    assert trade["chart_coverage_complete"] is True
    trade["chart_mark_samples"] = samples
    with pytest.raises(PaperProfitabilityScoreboardError, match=error):
        paper_profitability_scoreboard(source)


def test_incomplete_simultaneous_marks_preserve_booked_losing_trade() -> None:
    source = _audit()
    trade = source["trades"][0]
    trade.update({
        "chart_path_present": True,
        "chart_mark_count": 2,
        "chart_mark_samples": [[1_005, "100"], [1_005, "99"]],
        "chart_known_gap_duration_ms": 0,
        "chart_longest_unobserved_mark_ms": 15,
        "chart_coverage_complete": False,
    })
    result = paper_profitability_scoreboard(source)
    assert result["overall"]["trades"] == 4
    assert result["overall"]["net_pnl"] == "-13.9"
    assert result["original_chart_coverage_economics"][
        "complete_observed_path_original_closes"
    ]["trades"] == 1
    assert result["promotion_authority"] is False



def test_original_exit_mechanisms_reconcile_actual_cash_and_missing_context() -> None:
    """The book loses on stops; closing thesis wins elsewhere do not vanish."""
    rows = [
        _trade(
            1, side="short", market="BTC", strategy="trend",
            gross="-31", chart=True,
        ),
        _trade(
            2, side="short", market="ETH", strategy="breakout",
            gross="21", chart=False,
        ),
        _trade(
            3, side="long", market="SOL", strategy=None,
            gross="-8", chart=False,
        ),
        _trade(
            4, side="long", market="OP", strategy="trend",
            gross="-6", chart=True,
        ),
        _trade(
            5, side="short", market="ADA", strategy="trend",
            gross="50", chart=False,
        ),
    ]
    rows[1]["exit_reason"] = "OPPOSITE_FRESH_THESIS"
    rows[4]["exit_reason"] = "OPPOSITE_FRESH_THESIS"
    result = paper_profitability_scoreboard(_reconciled_audit_from_rows(rows))
    diag = result["original_booked_exit_mechanisms"]
    assert diag["suitable_as_entry_filter"] is False
    assert diag["counterfactual_exit_or_skip_account_simulated"] is False
    assert diag["exit_reason_known_only_after_original_entry"] is True
    assert diag["promotion_authority"] is False
    assert diag["whole_original_cohort"]["trades"] == 5
    assert diag["whole_original_cohort"]["net_pnl"] == "21.0"
    for key in (
        "by_exit_reason", "by_side_and_exit_reason",
        "by_strategy_and_exit_reason", "by_side_strategy_and_exit_reason",
    ):
        groups = diag[key]
        assert sum(group["trades"] for group in groups) == 5
        for field in ("gross_realized_pnl", "fees", "funding_cash_pnl", "net_pnl", "net_r"):
            assert sum(Decimal(group[field]) for group in groups) == Decimal(
                diag["whole_original_cohort"][field]
            )
    stops = next(
        group for group in diag["by_exit_reason"]
        if group["cohort"]["exit_reason"] == "MARK_STOP_TRIGGERED"
    )
    thesis = next(
        group for group in diag["by_exit_reason"]
        if group["cohort"]["exit_reason"] == "OPPOSITE_FRESH_THESIS"
    )
    assert stops["trades"] == 3
    assert Decimal(stops["net_pnl"]) == -48
    assert thesis["trades"] == 2
    assert Decimal(thesis["net_pnl"]) == 69
    assert sum(
        group["trades"] for group in diag["by_strategy_and_exit_reason"]
        if group["cohort"]["lead_strategy"] == "UNVERIFIED_ENTRY_CONTEXT"
    ) == 1
    charts = diag["by_exit_reason_with_original_chart_coverage"]
    assert sum(
        row["complete_observed_path_original_closes"]["trades"] for row in charts
    ) == 2
    assert sum(
        row["incomplete_or_missing_path_original_closes"]["trades"] for row in charts
    ) == 3
    assert result["ready_for_strategy_promotion"] is False


def test_original_exit_mechanism_missing_reason_is_not_imputed() -> None:
    audit = _audit()
    audit["trades"][0].pop("exit_reason")
    with pytest.raises(PaperProfitabilityScoreboardError, match="exit reason"):
        paper_profitability_scoreboard(audit)


def test_frozen_exit_reason_attribution_excludes_pre_embargo_openings() -> None:
    from cocomelon.research.prospective_trend_outside_top10 import (
        ProspectiveTrendOutsideTop10State,
    )

    cutoff = 6 * 3_600_000
    rows = [
        _move_trade_to_original_open_time(
            _trade(
                1, side="short", market="BTC", strategy="trend",
                rank="outside10", gross="150",
            ), cutoff - 1, closed_at_ms=cutoff + 8,
        ),
        _move_trade_to_original_open_time(
            _trade(
                2, side="long", market="ETH", strategy="trend",
                rank="outside10", gross="-10",
            ), cutoff, closed_at_ms=cutoff + 9,
        ),
        _move_trade_to_original_open_time(
            _trade(
                3, side="short", market="SOL", strategy="trend",
                rank="top10", gross="30",
            ), cutoff + 1, closed_at_ms=cutoff + 10,
        ),
        _move_trade_to_original_open_time(
            _trade(
                4, side="long", market="OP", strategy="trend",
                rank="missing", gross="-4",
            ), cutoff + 2, closed_at_ms=cutoff + 11,
        ),
    ]
    rows[0]["exit_reason"] = "OPPOSITE_FRESH_THESIS"
    rows[2]["exit_reason"] = "OPPOSITE_FRESH_THESIS"
    result = paper_profitability_scoreboard(
        _reconciled_audit_from_rows(rows),
        trend_outside_freeze=ProspectiveTrendOutsideTop10State(
            frozen_at_ms=0
        ).payload(),
    )
    frozen = result["frozen_hypotheses_original_forward_economics"]["hypotheses"][
        "trend_outside_top10_both_sides_skip"
    ]
    assert frozen["forward_trade_count"] == 3
    for expected, key in (
        ("original_forward_whole_journal", "original_forward_whole_exit_mechanisms"),
        ("original_forward_hypothesis_context", "original_forward_hypothesis_exit_mechanisms"),
        ("preferred_rank_attributed_original_closes", "preferred_original_exit_mechanisms"),
        ("disfavored_rank_attributed_original_closes", "disfavored_original_exit_mechanisms"),
        ("unresolved_rank_original_closes", "unresolved_original_exit_mechanisms"),
    ):
        original = frozen[expected]
        split = frozen[key]
        assert split["whole_original_cohort"]["trades"] == original["trades"]
        assert sum(row["trades"] for row in split["by_exit_reason"]) == original["trades"]
        for field in ("gross_realized_pnl", "fees", "funding_cash_pnl", "net_pnl", "net_r"):
            assert sum(Decimal(row[field]) for row in split["by_exit_reason"]) == Decimal(
                original[field]
            )
        assert split["promotion_authority"] is False
    preferred = frozen["preferred_original_exit_mechanisms"]
    assert preferred["whole_original_cohort"]["trades"] == 1
    assert Decimal(preferred["by_exit_reason"][0]["net_pnl"]) == 29
    # The huge prior-to-freeze +$149 thesis winner was NOT counted forward.
    assert Decimal(
        frozen["original_forward_hypothesis_context"]["net_pnl"]
    ) == 13
    assert frozen["candidate_skip_cashflow_simulated"] is False


def test_empty_exit_book_is_not_a_profitable_exit_strategy() -> None:
    report = paper_profitability_scoreboard(_reconciled_audit_from_rows([]))
    diag = report["original_booked_exit_mechanisms"]
    assert diag["whole_original_cohort"]["trades"] == 0
    assert diag["by_exit_reason"] == []
    assert diag["by_exit_reason_with_original_chart_coverage"] == []
    assert diag["promotion_authority"] is False



def test_booked_original_net_r_cannot_be_forged_without_changing_cash() -> None:
    source = _audit()
    first = source["trades"][0]
    assert Decimal(str(first["net_pnl"])) < 0
    first["net_r"] = "100"
    with pytest.raises(
        PaperProfitabilityScoreboardError,
        match="net-R contradicts booked cash",
    ):
        paper_profitability_scoreboard(source)


def test_offsetting_r_forgery_cannot_hide_in_whole_account_total() -> None:
    source = _audit()
    first, second = source["trades"][:2]
    first["net_r"] = str(Decimal(str(first["net_r"])) + Decimal("4"))
    second["net_r"] = str(Decimal(str(second["net_r"])) - Decimal("4"))
    assert sum(
        Decimal(str(row["net_r"])) for row in source["trades"]
    ) == sum(
        Decimal(str(row["net_pnl"])) / Decimal("20")
        for row in source["trades"]
    )
    with pytest.raises(
        PaperProfitabilityScoreboardError,
        match="net-R contradicts booked cash",
    ):
        paper_profitability_scoreboard(source)


@pytest.mark.parametrize(
    "risk",
    [None, "0", "-10", "21", "not-a-number", "Infinity", True],
)
def test_original_immutable_r_denominator_missing_or_changed_fails_closed(
    risk: object,
) -> None:
    audit = _audit()
    audit["trades"][1]["initial_risk_amount"] = risk
    with pytest.raises(PaperProfitabilityScoreboardError):
        paper_profitability_scoreboard(audit)


def test_original_journal_decimal_r_rounding_is_not_false_tamper() -> None:
    from cocomelon.domain.journal import AUTHORITATIVE_CONTEXT

    trade = _trade(
        1, side="short", market="BTC", strategy="breakout",
        gross="4", entry_fee="0", exit_fee="0",
    )
    trade["initial_risk_amount"] = "3"
    with localcontext(AUTHORITATIVE_CONTEXT):
        trade["net_r"] = str(Decimal("4") / Decimal("3"))
    report = paper_profitability_scoreboard(
        _reconciled_audit_from_rows([trade])
    )
    assert report["overall"]["net_pnl"] == "4"
    assert report["overall"]["net_r"] == trade["net_r"]
    assert report["promotion_authority"] is False


def test_original_risk_guard_blocks_frozen_forward_rank_r_inflation() -> None:
    from cocomelon.research.prospective_short_breakout_rank import (
        ProspectiveShortBreakoutRankState,
    )

    boundary = 6 * 3_600_000
    past = _move_trade_to_original_open_time(
        _trade(
            1, side="short", market="BTC", strategy="breakout",
            gross="90", rank="top3",
        ), boundary - 1, closed_at_ms=boundary + 5
    )
    future = _move_trade_to_original_open_time(
        _trade(
            2, side="short", market="ETH", strategy="breakout",
            gross="-6", rank="outside10",
        ), boundary, closed_at_ms=boundary + 5
    )
    audit = _reconciled_audit_from_rows([past, future])
    future["net_r"] = "10000"
    with pytest.raises(
        PaperProfitabilityScoreboardError,
        match="net-R contradicts booked cash",
    ):
        paper_profitability_scoreboard(
            audit,
            short_rank_freeze=ProspectiveShortBreakoutRankState(
                frozen_at_ms=0
            ).payload(),
        )



def _add_original_opportunity_to_scoreboard_trade(
    row: dict[str, object], *, lead: str,
) -> None:
    """Preserve genuine row identity in the synthetic first-seen fixture."""
    ident = str(row["trade_id"])
    row["strategy_decision_id"] = "strategy-" + ident
    row["feature_snapshot_id"] = "feature-" + ident
    row["risk_decision_id"] = "risk-" + ident
    row["original_first_seen_opportunity"] = {
        "status": "matched",
        "source_phase": "original_paper_opening_opportunity_after_risk_evaluation",
        "independently_archived_before_trade": False,
        "online_filter_state_certified": False,
        "promotion_authority": False,
        "strategy_decision_id": row["strategy_decision_id"],
        "feature_snapshot_id": row["feature_snapshot_id"],
        "risk_decision_id": row["risk_decision_id"],
        "market": row["market"],
        "direction": row["side"],
        "lead_strategy": lead,
        "opportunity_timestamp_ms": int(row["opened_at_ms"]) - 1,
        "baseline_risk_approved": True,
    }


def test_mean_reversion_abstention_excludes_all_discovery_rows() -> None:
    from cocomelon.research.paper_profitability_scoreboard import (
        MEAN_REVERSION_FORWARD_START_MS,
    )

    report = paper_profitability_scoreboard(_audit())
    trial = report["prospective_mean_reversion_abstention_contributions"]
    assert trial["fixed_discovery_freeze_ms"] == 1_791_720_000_000
    assert trial["forward_started_at_ms"] == MEAN_REVERSION_FORWARD_START_MS
    assert trial["forward_original_closed_trades"] == 0
    assert trial["verified_mean_reversion_avoided"]["trades"] == 0
    assert Decimal(trial["naive_zero_replacement_delta_net_cash"]) == Decimal("0")
    assert trial["arithmetic_candidate_positive_both_cash_and_r"] is False
    assert trial["descriptive_sample_floor_met_not_promotion"] is False
    assert trial["research_readiness_grant"] is False
    assert trial["promotion_authority"] is False
    assert report["overall"]["trades"] == 4


def test_mean_reversion_forward_abstention_retains_unknowns_and_winners() -> None:
    """Post-embargo new losers/winners count, but none buys back risk capacity."""
    from cocomelon.research.paper_profitability_scoreboard import (
        MEAN_REVERSION_FORWARD_START_MS as start,
    )

    args = (
        # A historically opened losing MR trade closed after the clean
        # start is DISCOVERY and must never count as avoided.
        (1, "BTC", "mean_reversion", "-100", start - 1, start + 100),
        (2, "BTC", "mean_reversion", "-9", start, start + 101),
        (3, "ETH", "trend", "8", start + 1, start + 102),
        # Even a forward MR *winner* is hypothetically skipped: no cherry-pick.
        (4, "CRV", "mean_reversion", "3", start + 2, start + 103),
        (5, "SOL", None, "-2", start + 3, start + 104),
        (6, "BTC", "mean_reversion", "-3", start + 4, start + 105),
    )
    rows = [
        _move_trade_to_original_open_time(
            _trade(n, side="long", market=market, strategy=strategy, gross=gross),
            opened, closed_at_ms=closed,
        )
        for n, market, strategy, gross, opened, closed in args
    ]
    for row in rows:
        context = row["entry_context"]
        if isinstance(context, dict):
            _add_original_opportunity_to_scoreboard_trade(
                row, lead=str(context["lead_strategy"]),
            )
    report = paper_profitability_scoreboard(
        _reconciled_audit_from_rows(rows)
    )
    trial = report["prospective_mean_reversion_abstention_contributions"]
    assert report["overall"]["trades"] == 6
    assert trial["forward_original_closed_trades"] == 5
    assert trial["verified_mean_reversion_avoided"]["trades"] == 3
    assert trial["verified_mean_reversion_avoided"]["wins"] == 1
    assert trial["forward_unverified_entry_contexts_retained"] == 1
    assert Decimal(trial["original_forward_net_cash"]) == Decimal("-8")
    assert Decimal(trial["verified_mean_reversion_avoided"]["net_pnl"]) == Decimal("-12")
    assert Decimal(trial["retained_original_closes"]["net_pnl"]) == Decimal("4")
    assert Decimal(trial["naive_zero_replacement_candidate_net_cash"]) == Decimal("4")
    assert Decimal(trial["naive_zero_replacement_delta_net_cash"]) == Decimal("12")
    assert Decimal(trial["naive_zero_replacement_delta_net_r"]) == Decimal("0.6")
    assert Decimal(trial["leave_one_avoided_trade_min_delta_cash"]) == Decimal("2")
    assert Decimal(trial["leave_one_avoided_market_min_delta_cash"]) == Decimal("-2")
    assert trial["avoided_market_count"] == 2
    assert trial["chronological_forward_halves_avoided"][0]["avoided"]["trades"] == 1
    assert trial["chronological_forward_halves_avoided"][1]["avoided"]["trades"] == 2
    assert trial["arithmetic_candidate_positive_both_cash_and_r"] is True
    assert trial["arithmetic_improvement_positive_both_cash_and_r"] is True
    assert trial["independent_online_filter_state_certified"] is False
    assert trial["trading_replacements_modeled"] is False
    assert trial["full_account_trial"] is False
    assert trial["ready_for_strategy_promotion"] is False
    assert trial["execution_authority"] is False


def test_mean_reversion_abstention_never_credits_missing_original_context() -> None:
    from cocomelon.research.paper_profitability_scoreboard import (
        MEAN_REVERSION_FORWARD_START_MS as start,
    )

    old = _move_trade_to_original_open_time(
        _trade(
            1, side="short", market="XPL", strategy="mean_reversion",
            gross="-200",
        ), start - 1, closed_at_ms=start + 50,
    )
    unknown = _move_trade_to_original_open_time(
        _trade(
            2, side="short", market="ETH", strategy=None,
            gross="-100",
        ), start, closed_at_ms=start + 51,
    )
    winning = _move_trade_to_original_open_time(
        _trade(
            3, side="long", market="CRV", strategy="mean_reversion",
            gross="5",
        ), start + 1, closed_at_ms=start + 52,
    )
    _add_original_opportunity_to_scoreboard_trade(
        winning, lead="mean_reversion",
    )
    out = paper_profitability_scoreboard(
        _reconciled_audit_from_rows([old, unknown, winning])
    )["prospective_mean_reversion_abstention_contributions"]
    assert out["forward_original_closed_trades"] == 2
    assert out["verified_mean_reversion_avoided"]["trades"] == 1
    assert Decimal(out["verified_mean_reversion_avoided"]["net_pnl"]) == Decimal("4")
    assert Decimal(out["naive_zero_replacement_delta_net_cash"]) == Decimal("-4")
    assert Decimal(out["retained_original_closes"]["net_pnl"]) == Decimal("-101")
    assert out["arithmetic_improvement_positive_both_cash_and_r"] is False
    assert out["descriptive_sample_floor_met_not_promotion"] is False
    assert out["research_readiness_grant"] is False


def test_unmatched_first_seen_mean_reversion_stays_in_actual_original_cash() -> None:
    from cocomelon.research.paper_profitability_scoreboard import (
        MEAN_REVERSION_FORWARD_START_MS as start,
    )
    row = _move_trade_to_original_open_time(
        _trade(1, side="long", market="SOL", strategy="mean_reversion",
               gross="-9"),
        start, closed_at_ms=start + 60_000,
    )
    report = paper_profitability_scoreboard(
        _reconciled_audit_from_rows([row])
    )
    trial = report["prospective_mean_reversion_abstention_contributions"]
    assert trial["forward_original_closed_trades"] == 1
    assert trial["forward_mean_reversion_without_first_seen_match_retained"] == 1
    assert trial["verified_mean_reversion_avoided"]["trades"] == 0
    assert Decimal(trial["naive_zero_replacement_delta_net_cash"]) == 0
    assert Decimal(trial["original_forward_net_cash"]) == Decimal("-10")


@pytest.mark.parametrize("bad", [
    ("lead_strategy", "trend"),
    ("market", "BTC"),
    ("direction", "short"),
    ("strategy_decision_id", "forged-decision"),
    ("feature_snapshot_id", "forged-feature"),
    ("risk_decision_id", "forged-risk"),
    ("baseline_risk_approved", False),
    ("opportunity_timestamp_ms", 0),
    ("independently_archived_before_trade", True),
    ("online_filter_state_certified", True),
])
def test_first_seen_opportunity_must_match_original_and_cannot_claim_authority(
    bad: tuple[str, object],
) -> None:
    from cocomelon.research.paper_profitability_scoreboard import (
        MEAN_REVERSION_FORWARD_START_MS as start,
    )
    row = _move_trade_to_original_open_time(
        _trade(1, side="long", market="SOL", strategy="mean_reversion",
               gross="-9"),
        start, closed_at_ms=start + 50,
    )
    _add_original_opportunity_to_scoreboard_trade(row, lead="mean_reversion")
    source = row["original_first_seen_opportunity"]
    assert isinstance(source, dict)
    field, value = bad
    source[field] = value
    with pytest.raises(
        PaperProfitabilityScoreboardError, match="original|first-seen"
    ):
        paper_profitability_scoreboard(
            _reconciled_audit_from_rows([row])
        )


def test_first_seen_uncertain_source_cannot_claim_matching_fields() -> None:
    from cocomelon.research.paper_profitability_scoreboard import (
        MEAN_REVERSION_FORWARD_START_MS as start,
    )
    row = _move_trade_to_original_open_time(
        _trade(1, side="short", market="SOL",
               strategy="mean_reversion", gross="-5"),
        start, closed_at_ms=start + 50,
    )
    _add_original_opportunity_to_scoreboard_trade(row, lead="mean_reversion")
    source = row["original_first_seen_opportunity"]
    assert isinstance(source, dict)
    source["status"] = "missing"
    with pytest.raises(PaperProfitabilityScoreboardError, match="uncertain"):
        paper_profitability_scoreboard(
            _reconciled_audit_from_rows([row])
        )


def test_forward_fixed_opening_day_windows_never_follow_close_order() -> None:
    """Long-lived day-0 loser closes after a day-1 winner; fixed bins do not flip."""
    from cocomelon.research.paper_profitability_scoreboard import (
        MEAN_REVERSION_FIXED_OPENING_DAY_MS as day,
    )
    from cocomelon.research.paper_profitability_scoreboard import (
        MEAN_REVERSION_FORWARD_START_MS as start,
    )

    original_day0 = _move_trade_to_original_open_time(
        _trade(1, side="long", market="BTC", strategy="mean_reversion",
               gross="-9"),
        start + 1, closed_at_ms=start + 2 * day + 10,
    )
    original_day1 = _move_trade_to_original_open_time(
        _trade(2, side="short", market="ETH", strategy="mean_reversion",
               gross="5"),
        start + day + 1, closed_at_ms=start + day + 20,
    )
    _add_original_opportunity_to_scoreboard_trade(
        original_day0, lead="mean_reversion",
    )
    _add_original_opportunity_to_scoreboard_trade(
        original_day1, lead="mean_reversion",
    )
    chronological_closes = [original_day1, original_day0]
    audit = _reconciled_audit_from_rows(chronological_closes)
    audit["source_handoff_ended_at_ms"] = start + 3 * day
    audit["source_handoff_open_positions"] = 0
    report = paper_profitability_scoreboard(audit)
    trial = report["prospective_mean_reversion_abstention_contributions"]
    blocks = trial["fixed_24h_original_opening_windows"]
    assert [b["opening_day_index"] for b in blocks] == [0, 1]
    assert all(b["source_observation_window_mature"] for b in blocks)
    assert blocks[0]["observed_original_closed_trades"] == 1
    assert Decimal(blocks[0]["naive_skip_delta_cash"]) == Decimal("10")
    assert Decimal(blocks[1]["naive_skip_delta_cash"]) == Decimal("-4")
    assert Decimal(blocks[0]["zero_replacement_net_cash"]) == 0
    assert Decimal(blocks[1]["zero_replacement_net_cash"]) == 0
    assert trial["chronological_forward_halves_avoided"][0]["avoided"]["trades"] == 1
    assert trial["chronological_forward_halves_avoided"][1]["avoided"]["trades"] == 1
    assert trial["first_two_fixed_24h_windows_have_mature_sample"] is False
    assert trial["first_two_fixed_24h_naive_skip_improves_cash_and_r"] is False
    assert trial["promotion_authority"] is False


@pytest.mark.parametrize("open_positions,expected", [
    (None, False),
    (1, False),
    (0, True),
])
def test_forward_window_maturity_requires_authenticated_zero_open_exposure(
    open_positions: int | None,
    expected: bool,
) -> None:
    from cocomelon.research.paper_profitability_scoreboard import (
        MEAN_REVERSION_FIXED_OPENING_DAY_MS as day,
    )
    from cocomelon.research.paper_profitability_scoreboard import (
        MEAN_REVERSION_FORWARD_START_MS as start,
    )

    row = _move_trade_to_original_open_time(
        _trade(1, side="long", market="SOL", strategy="mean_reversion",
               gross="-9"),
        start + 1, closed_at_ms=start + 100,
    )
    _add_original_opportunity_to_scoreboard_trade(
        row, lead="mean_reversion",
    )
    audit = _reconciled_audit_from_rows([row])
    audit["source_handoff_ended_at_ms"] = start + 2 * day
    audit["source_handoff_open_positions"] = open_positions
    trial = paper_profitability_scoreboard(audit)[
        "prospective_mean_reversion_abstention_contributions"
    ]
    block0, block1 = trial["fixed_24h_original_opening_windows"]
    assert block0["source_observation_window_mature"] is expected
    assert block1["source_observation_window_mature"] is expected
    assert trial["source_handoff_exposure_zero_and_end_known"] is expected
    assert trial["descriptive_sample_floor_met_not_promotion"] is False
    assert trial["research_readiness_grant"] is False


def test_forward_window_current_incomplete_day_never_matures() -> None:
    from cocomelon.research.paper_profitability_scoreboard import (
        MEAN_REVERSION_FIXED_OPENING_DAY_MS as day,
    )
    from cocomelon.research.paper_profitability_scoreboard import (
        MEAN_REVERSION_FORWARD_START_MS as start,
    )
    row = _move_trade_to_original_open_time(
        _trade(1, side="long", market="SOL", strategy="mean_reversion",
               gross="-9"),
        start + 1, closed_at_ms=start + 100,
    )
    _add_original_opportunity_to_scoreboard_trade(
        row, lead="mean_reversion",
    )
    audit = _reconciled_audit_from_rows([row])
    audit["source_handoff_ended_at_ms"] = start + day - 1
    audit["source_handoff_open_positions"] = 0
    block = paper_profitability_scoreboard(audit)[
        "prospective_mean_reversion_abstention_contributions"
    ]["fixed_24h_original_opening_windows"][0]
    assert block["source_observation_window_mature"] is False


@pytest.mark.parametrize("field,value", [
    ("source_handoff_ended_at_ms", True),
    ("source_handoff_ended_at_ms", -1),
    ("source_handoff_open_positions", False),
    ("source_handoff_open_positions", -1),
])
def test_forward_source_handoff_censor_fields_fail_closed(
    field: str, value: object,
) -> None:
    audit = _audit()
    audit[field] = value
    with pytest.raises(
        PaperProfitabilityScoreboardError, match="source handoff"
    ):
        paper_profitability_scoreboard(audit)


def test_forward_original_close_cannot_postdate_completed_source_handoff() -> None:
    audit = _audit()
    audit["source_handoff_ended_at_ms"] = 0
    audit["source_handoff_open_positions"] = 0
    with pytest.raises(
        PaperProfitabilityScoreboardError, match="exceeds source handoff"
    ):
        paper_profitability_scoreboard(audit)


def test_sparse_mean_reversion_uses_first_two_fixed_weeks_not_daily_floor() -> None:
    from cocomelon.research.paper_profitability_scoreboard import (
        MEAN_REVERSION_FIXED_OPENING_DAY_MS as day,
    )
    from cocomelon.research.paper_profitability_scoreboard import (
        MEAN_REVERSION_FORWARD_START_MS as start,
    )

    # Three outcomes per calendar week, but only one in any 24h block.
    days = (0, 1, 2, 7, 8, 9)
    markets = ("BTC", "ETH", "SOL", "ADA", "CRV", "HYPE")
    rows: list[dict[str, object]] = []
    for i, (d, market) in enumerate(zip(days, markets, strict=True)):
        opened = start + d * day + 1
        row = _move_trade_to_original_open_time(
            _trade(
                i + 1, side="long", market=market,
                strategy="mean_reversion", gross="-9",
            ),
            opened, closed_at_ms=opened + 100,
        )
        _add_original_opportunity_to_scoreboard_trade(
            row, lead="mean_reversion",
        )
        rows.append(row)
    audit = _reconciled_audit_from_rows(rows)
    audit["source_handoff_ended_at_ms"] = start + 14 * day
    audit["source_handoff_open_positions"] = 0
    trial = paper_profitability_scoreboard(audit)[
        "prospective_mean_reversion_abstention_contributions"
    ]
    weeks = trial["fixed_7d_original_opening_windows"]
    assert [w["opening_week_index"] for w in weeks] == [0, 1]
    assert trial["fixed_stability_window_ms"] == 7 * day
    assert [w["avoided_verified_mean_reversion"]["trades"] for w in weeks] == [
        3, 3,
    ]
    assert all(w["source_observation_window_mature"] for w in weeks)
    assert trial["first_two_fixed_7d_windows_have_mature_sample"] is True
    assert trial["first_two_fixed_7d_naive_skip_improves_cash_and_r"] is True
    # Weekly reporting must never shadow or reset whole-forward original cash/R.
    assert Decimal(trial["original_forward_net_cash"]) == Decimal("-60")
    assert Decimal(trial["original_forward_net_r"]) == Decimal("-3")
    assert sum(
        (Decimal(w["original_booked_net_cash"]) for w in weeks), Decimal(0)
    ) == Decimal(trial["original_forward_net_cash"])
    assert sum(
        (Decimal(w["original_booked_net_r"]) for w in weeks), Decimal(0)
    ) == Decimal(trial["original_forward_net_r"])
    assert trial["first_two_fixed_24h_windows_have_mature_sample"] is False
    assert trial["descriptive_sample_floor_met_not_promotion"] is False
    assert trial["promotion_authority"] is False

    # The second week is not mature one millisecond before its exclusive end.
    audit["source_handoff_ended_at_ms"] = start + 14 * day - 1
    trial_early = paper_profitability_scoreboard(audit)[
        "prospective_mean_reversion_abstention_contributions"
    ]
    assert trial_early["fixed_7d_original_opening_windows"][0][
        "source_observation_window_mature"
    ] is True
    assert trial_early["fixed_7d_original_opening_windows"][1][
        "source_observation_window_mature"
    ] is False
    assert trial_early["first_two_fixed_7d_windows_have_mature_sample"] is False


def test_unwitnessed_mean_reversion_selection_bounds_keep_all_original_cash() -> None:
    from cocomelon.research.paper_profitability_scoreboard import (
        MEAN_REVERSION_FORWARD_START_MS as start,
    )
    cases = [
        (1, "BTC", "mean_reversion", "-9", True),
        (2, "ETH", "mean_reversion", "-6", False),
        (3, "SOL", "mean_reversion", "5", False),
        (4, "ADA", "trend", "2", False),
        (5, "JUP", None, "-3", False),
    ]
    rows: list[dict[str, object]] = []
    for n, market, strategy, gross, witnessed in cases:
        row = _move_trade_to_original_open_time(
            _trade(n, side="long", market=market, strategy=strategy,
                   gross=gross),
            start + n, closed_at_ms=start + 100 + n,
        )
        if witnessed:
            _add_original_opportunity_to_scoreboard_trade(
                row, lead="mean_reversion",
            )
        rows.append(row)
    report = paper_profitability_scoreboard(_reconciled_audit_from_rows(rows))
    coverage = report["original_first_seen_decision_coverage_economics"]
    assert coverage["whole_original"]["trades"] == 5
    assert coverage["first_seen_matched"]["trades"] == 1
    assert coverage["first_seen_unmatched"]["trades"] == 4
    assert Decimal(coverage["whole_original"]["net_pnl"]) == -16
    assert Decimal(coverage["first_seen_matched"]["net_pnl"]) == -10
    assert Decimal(coverage["first_seen_unmatched"]["net_pnl"]) == -6
    mr = next(x for x in coverage["by_original_verified_lead_strategy"]
              if x["lead_strategy"] == "mean_reversion")
    assert mr["matched_first_seen"]["trades"] == 1
    assert mr["unmatched_first_seen"]["trades"] == 2
    assert coverage["independent_archive_receipt_certified"] is False

    trial = report["prospective_mean_reversion_abstention_contributions"]
    assert trial["verified_mean_reversion_avoided"]["trades"] == 1
    assert Decimal(trial["original_forward_net_cash"]) == -16
    assert Decimal(trial["naive_zero_replacement_delta_net_cash"]) == 10
    assert Decimal(trial["naive_zero_replacement_candidate_net_cash"]) == -6
    bound = trial["unproven_mean_reversion_posttrade_classification"]
    assert bound["original_retained_booked"]["trades"] == 2
    assert bound["unwitnessed_original_loss_count"] == 1
    assert bound["unwitnessed_original_win_count"] == 1
    assert Decimal(
        bound["naive_skip_delta_cash_lower_if_unverified_winners_eligible"]
    ) == 6
    assert Decimal(
        bound["naive_skip_delta_cash_upper_if_unverified_losers_eligible"]
    ) == 17
    assert Decimal(bound["zero_replacement_cash_lower"]) == -10
    assert Decimal(bound["zero_replacement_cash_upper"]) == 1
    assert bound["unproven_skips_credited_to_candidate"] == 0
    assert bound["interval_is_not_statistical_confidence"] is True
    assert bound["nominal_skip_cash_positive_at_worst_eligibility"] is True
    assert bound["research_readiness_grant"] is False
    assert trial["promotion_authority"] is False


def test_missing_source_bounds_cannot_borrow_pre_embargo_or_unknown_lead() -> None:
    from cocomelon.research.paper_profitability_scoreboard import (
        MEAN_REVERSION_FORWARD_START_MS as start,
    )
    rows = [
        _move_trade_to_original_open_time(
            _trade(1, side="short", market="BTC",
                   strategy="mean_reversion", gross="-500"),
            start - 1, closed_at_ms=start + 900,
        ),
        _move_trade_to_original_open_time(
            _trade(2, side="short", market="ETH",
                   strategy=None, gross="-50"),
            start, closed_at_ms=start + 901,
        ),
        _move_trade_to_original_open_time(
            _trade(3, side="short", market="SOL",
                   strategy="trend", gross="-9"),
            start + 1, closed_at_ms=start + 902,
        ),
    ]
    r = paper_profitability_scoreboard(_reconciled_audit_from_rows(rows))
    trial = r["prospective_mean_reversion_abstention_contributions"]
    assert trial["forward_original_closed_trades"] == 2
    assert trial["forward_mean_reversion_without_first_seen_match_retained"] == 0
    b = trial["unproven_mean_reversion_posttrade_classification"]
    assert b["original_retained_booked"]["trades"] == 0
    assert Decimal(
        b["naive_skip_delta_cash_lower_if_unverified_winners_eligible"]
    ) == 0
    assert Decimal(
        b["naive_skip_delta_cash_upper_if_unverified_losers_eligible"]
    ) == 0
    assert b["nominal_skip_cash_positive_at_worst_eligibility"] is False
    assert b["even_best_eligibility_cannot_make_original_forward_cash_and_r_positive"] is True
    assert trial["verified_mean_reversion_avoided"]["trades"] == 0
    assert Decimal(trial["original_forward_net_cash"]) == -61
    assert r["overall"]["trades"] == 3


def test_frozen_long_trend_volatility_only_counts_genuine_forward_opening() -> None:
    from cocomelon.research.paper_profitability_scoreboard import (
        LONG_TREND_VOLATILITY_FORWARD_MS as start,
    )
    assert start == 1_791_763_200_000  # Oct 12 at 00:00 UTC
    args = (
        # A loss opened inside the six-hour embargo (after discovery freeze)
        # and closed inside the trial is excluded from BOTH cohorts.
        (1, "BTC", "long", "trend", "low", "-100", start - 1, False),
        (2, "ETH", "long", "trend", "low", "-9", start, True),
        # A winning high-volatility trend must ALSO be skipped.
        (3, "SOL", "long", "trend", "high", "5", start + 1, True),
        # Original normal-volatility LONG loss must remain in candidate.
        (4, "ADA", "long", "trend", "normal", "-7", start + 2, True),
        # Unwitnessed original low-volatility LONG loser is never credited.
        (5, "JUP", "long", "trend", "low", "-3", start + 3, False),
        # Even extreme volatility cannot skip an original short.
        (6, "CRV", "short", "trend", "low", "-20", start + 4, True),
    )
    rows: list[dict[str, object]] = []
    for n, market, side, strategy, vol, gross, opened, matched in args:
        row = _move_trade_to_original_open_time(
            _trade(n, side=side, market=market, strategy=strategy,
                   gross=gross),
            opened, closed_at_ms=start + 200 + n,
        )
        context = row["entry_context"]
        assert isinstance(context, dict)
        context["volatility_regime"] = vol
        if matched:
            _add_original_opportunity_to_scoreboard_trade(row, lead=strategy)
        rows.append(row)
    report = paper_profitability_scoreboard(_reconciled_audit_from_rows(rows))
    study = report["prospective_long_trend_volatility_abstention_contributions"]
    assert study["frozen_at_ms"] == 1_791_741_600_000
    assert study["forward_started_at_ms"] == start
    assert report["overall"]["trades"] == 6
    assert study["original_forward_closed_trades"] == 5
    assert next(
        c for c in study["discovery_only_long_trend_volatility_cohorts"]
        if c["original_entry_volatility"] == "low"
    )["original_booked"]["trades"] == 0
    assert study["verified_low_or_high_volatility_avoided"]["trades"] == 2
    assert study["verified_low_or_high_volatility_avoided"]["wins"] == 1
    assert Decimal(study["original_forward_booked_net_cash"]) == -39
    assert Decimal(study["verified_low_or_high_volatility_avoided"]["net_pnl"]) == -6
    assert Decimal(study["zero_replacement_candidate_cash"]) == -33
    assert Decimal(study["zero_replacement_delta_cash"]) == 6
    assert study["unwitnessed_volatility_originals_retained"]["trades"] == 1
    assert Decimal(study["unwitnessed_context_cash_delta_lower"]) == 6
    assert Decimal(study["unwitnessed_context_cash_delta_upper"]) == 10
    assert study["unwitnessed_original_cannot_earn_skip_credit"] is True
    assert study["risk_matched_full_account_trial"] is False
    assert study["descriptive_sample_floor_met_not_promotion"] is False
    assert study["execution_authority"] is False
    assert study["promotion_authority"] is False
    assert study["changes_strategy"] is False
    assert study["changes_risk_limits"] is False
    assert study["independent_online_filter_state_certified"] is False
    weeks = study["weekly_open_time_windows"]
    assert [w["week_index"] for w in weeks] == [0, 1]
    assert Decimal(weeks[0]["original_booked_net_cash"]) == -39
    assert Decimal(weeks[1]["original_booked_net_cash"]) == 0
    assert sum((Decimal(w["original_booked_net_cash"]) for w in weeks),
               Decimal(0)) == Decimal(study["original_forward_booked_net_cash"])


def test_frozen_long_trend_volatility_discovery_never_counts_as_forward() -> None:
    report = paper_profitability_scoreboard(_audit())
    study = report["prospective_long_trend_volatility_abstention_contributions"]
    assert study["original_forward_closed_trades"] == 0
    assert study["verified_low_or_high_volatility_avoided"]["trades"] == 0
    assert Decimal(study["zero_replacement_delta_cash"]) == 0
    assert study["weekly_open_time_windows"][0]["source_window_mature"] is False
    assert study["research_readiness_grant"] is False
    assert study["ready_for_strategy_promotion"] is False
    assert report["overall"]["trades"] == 4
    assert study["discovery_never_forward"] is True
    assert sum(
        v["original_booked"]["trades"]
        for v in study["discovery_only_long_trend_volatility_cohorts"]
    ) == 1
    # The original historical fixture has one LONG trend with no
    # independently witnessed volatility label; never infer normal/low.
    assert next(
        v for v in study["discovery_only_long_trend_volatility_cohorts"]
        if v["original_entry_volatility"] == "UNVERIFIED_ENTRY_CONTEXT"
    )["original_booked"]["trades"] == 1


def test_frozen_long_trend_volatility_week_zero_cannot_move_after_closes() -> None:
    from cocomelon.research.paper_profitability_scoreboard import (
        LONG_TREND_VOLATILITY_FORWARD_MS as start,
    )
    day = 86_400_000
    one = _move_trade_to_original_open_time(
        _trade(1, side="long", market="BTC",
               strategy="trend", gross="-9"),
        start + 1, closed_at_ms=start + 8 * day + 500,
    )
    two = _move_trade_to_original_open_time(
        _trade(2, side="long", market="ETH",
               strategy="trend", gross="5"),
        start + 7 * day + 1, closed_at_ms=start + 8 * day,
    )
    for row, regime in ((one, "low"), (two, "high")):
        context = row["entry_context"]
        assert isinstance(context, dict)
        context["volatility_regime"] = regime
        _add_original_opportunity_to_scoreboard_trade(row, lead="trend")
    audit = _reconciled_audit_from_rows([two, one])
    audit["source_handoff_ended_at_ms"] = start + 14 * day
    audit["source_handoff_open_positions"] = 0
    study = paper_profitability_scoreboard(audit)[
        "prospective_long_trend_volatility_abstention_contributions"
    ]
    windows = study["weekly_open_time_windows"]
    assert [w["week_index"] for w in windows] == [0, 1]
    assert [w["verified_abstention_closes"]["trades"] for w in windows] == [1, 1]
    assert all(w["source_window_mature"] for w in windows)
    assert Decimal(windows[0]["naive_skip_delta_cash"]) == 10
    assert Decimal(windows[1]["naive_skip_delta_cash"]) == -4
    assert study["fixed_first_two_weeks_mature_sample"] is False
    assert study["promotion_authority"] is False

    audit["source_handoff_ended_at_ms"] = start + 14 * day - 1
    early = paper_profitability_scoreboard(audit)[
        "prospective_long_trend_volatility_abstention_contributions"
    ]
    assert early["weekly_open_time_windows"][0]["source_window_mature"] is True
    assert early["weekly_open_time_windows"][1]["source_window_mature"] is False
    audit["source_handoff_ended_at_ms"] = start + 14 * day
    audit["source_handoff_open_positions"] = 1
    open_end = paper_profitability_scoreboard(audit)[
        "prospective_long_trend_volatility_abstention_contributions"
    ]
    assert all(
        w["source_window_mature"] is False
        for w in open_end["weekly_open_time_windows"]
    )


def test_same_millisecond_original_decision_never_earns_mean_reversion_skip() -> None:
    from cocomelon.research.paper_profitability_scoreboard import (
        MEAN_REVERSION_FORWARD_START_MS as start,
    )
    tied = _move_trade_to_original_open_time(
        _trade(1, side="long", market="ETH",
               strategy="mean_reversion", gross="-9"),
        start, closed_at_ms=start + 900,
    )
    earlier = _move_trade_to_original_open_time(
        _trade(2, side="short", market="SOL",
               strategy="mean_reversion", gross="5"),
        start + 10, closed_at_ms=start + 901,
    )
    _add_original_opportunity_to_scoreboard_trade(
        tied, lead="mean_reversion",
    )
    _add_original_opportunity_to_scoreboard_trade(
        earlier, lead="mean_reversion",
    )
    original = tied["original_first_seen_opportunity"]
    assert isinstance(original, dict)
    original["opportunity_timestamp_ms"] = start
    result = paper_profitability_scoreboard(
        _reconciled_audit_from_rows([tied, earlier])
    )
    coverage = result["original_first_seen_decision_coverage_economics"]
    assert coverage["whole_original"]["trades"] == 2
    assert coverage["first_seen_matched"]["trades"] == 1
    assert coverage["first_seen_unmatched"]["trades"] == 1
    assert (
        coverage["first_seen_same_millisecond_not_provably_preopen"]["trades"]
        == 1
    )
    assert coverage["same_millisecond_opening_decisions_never_qualify"] is True
    assert Decimal(coverage["whole_original"]["net_pnl"]) == -6
    assert Decimal(coverage["first_seen_unmatched"]["net_pnl"]) == -10
    trial = result["prospective_mean_reversion_abstention_contributions"]
    assert trial["forward_original_decision_matches"] == 1
    assert trial["forward_same_millisecond_decisions_unproven"] == 1
    assert trial["verified_mean_reversion_avoided"]["trades"] == 1
    assert Decimal(trial["original_forward_net_cash"]) == -6
    # Only the originally witnessed, causally earlier WINNER is skipped.
    assert Decimal(trial["naive_zero_replacement_delta_net_cash"]) == -4
    assert Decimal(trial["naive_zero_replacement_candidate_net_cash"]) == -10
    assert trial["forward_mean_reversion_without_first_seen_match_retained"] == 1
    uncertain = trial["unproven_mean_reversion_posttrade_classification"]
    assert uncertain["original_retained_booked"]["trades"] == 1
    assert Decimal(
        uncertain["naive_skip_delta_cash_upper_if_unverified_losers_eligible"]
    ) == 6
    assert uncertain["unproven_skips_credited_to_candidate"] == 0
    assert trial["promotion_authority"] is False


def test_same_millisecond_original_long_trend_regime_never_earns_skip() -> None:
    from cocomelon.research.paper_profitability_scoreboard import (
        LONG_TREND_VOLATILITY_FORWARD_MS as start,
    )
    tied = _move_trade_to_original_open_time(
        _trade(1, side="long", market="ETH",
               strategy="trend", gross="-9"),
        start, closed_at_ms=start + 900,
    )
    earlier = _move_trade_to_original_open_time(
        _trade(2, side="long", market="SOL",
               strategy="trend", gross="-9"),
        start + 10, closed_at_ms=start + 901,
    )
    for row, regime in ((tied, "low"), (earlier, "high")):
        context = row["entry_context"]
        assert isinstance(context, dict)
        context["volatility_regime"] = regime
        _add_original_opportunity_to_scoreboard_trade(row, lead="trend")
    original = tied["original_first_seen_opportunity"]
    assert isinstance(original, dict)
    original["opportunity_timestamp_ms"] = start
    result = paper_profitability_scoreboard(
        _reconciled_audit_from_rows([tied, earlier])
    )
    trial = result["prospective_long_trend_volatility_abstention_contributions"]
    assert trial["original_forward_closed_trades"] == 2
    assert trial["forward_same_millisecond_decisions_unproven"] == 1
    assert trial["verified_low_or_high_volatility_avoided"]["trades"] == 1
    assert trial["unwitnessed_volatility_originals_retained"]["trades"] == 1
    assert Decimal(trial["original_forward_booked_net_cash"]) == -20
    assert Decimal(trial["zero_replacement_candidate_cash"]) == -10
    assert Decimal(trial["zero_replacement_delta_cash"]) == 10
    assert Decimal(trial["unwitnessed_context_cash_delta_upper"]) == 20
    assert trial["unwitnessed_original_cannot_earn_skip_credit"] is True
    assert trial["execution_authority"] is False
    assert trial["promotion_authority"] is False


def test_future_dated_original_opening_source_still_rejected() -> None:
    from cocomelon.research.paper_profitability_scoreboard import (
        MEAN_REVERSION_FORWARD_START_MS as start,
    )
    row = _move_trade_to_original_open_time(
        _trade(1, side="long", market="ETH",
               strategy="mean_reversion", gross="-9"),
        start, closed_at_ms=start + 200,
    )
    _add_original_opportunity_to_scoreboard_trade(row, lead="mean_reversion")
    original = row["original_first_seen_opportunity"]
    assert isinstance(original, dict)
    original["opportunity_timestamp_ms"] = start + 1
    with pytest.raises(
        PaperProfitabilityScoreboardError,
        match="approval or decision clock mismatch",
    ):
        paper_profitability_scoreboard(_reconciled_audit_from_rows([row]))


def _week_time(day: int, hour: int = 0) -> int:
    return int(datetime(2026, 10, day, hour, tzinfo=UTC).timestamp() * 1000)


def test_fixed_original_opening_weeks_preserve_loss_and_costs_when_closed_out_of_order(
) -> None:
    first = _move_trade_to_original_open_time(
        _trade(
            1, side="short", market="MEGA", strategy="trend",
            gross="-10", entry_fee="1", exit_fee="1",
        ),
        _week_time(12, 1), closed_at_ms=_week_time(20, 1),
    )
    second = _move_trade_to_original_open_time(
        _trade(
            2, side="long", market="ALGO", strategy="breakout",
            gross="6", entry_fee="1", exit_fee="2",
        ),
        _week_time(19, 9), closed_at_ms=_week_time(19, 10),
    )
    # Original journal is ordered by CLOSING, not by opening.
    rows = [second, first]
    audit = _reconciled_audit_from_rows(rows)
    audit["source_handoff_ended_at_ms"] = _week_time(27, 1)
    audit["source_handoff_open_positions"] = 0
    result = paper_profitability_scoreboard(audit)
    weekly = result["original_fixed_utc_opening_week_economics"]
    periods = weekly["weeks"]
    assert weekly["week_anchor_epoch_ms_utc"] == 345_600_000
    assert weekly["week_duration_ms"] == 604_800_000
    assert weekly["time_assignment"] == (
        "actual_original_entry_timestamp_not_exit_timestamp"
    )
    assert weekly["all_original_closed_trade_counts_cash_and_net_r_reconciled"] is True
    assert [w["week_start_ms_utc"] for w in periods] == [
        _week_time(12), _week_time(19),
    ]
    assert [w["original_booked_week"]["net_pnl"] for w in periods] == [
        "-12", "3",
    ]
    assert [w["original_booked_week"]["fees"] for w in periods] == [
        "2", "3",
    ]
    assert [w["original_booked_week"]["trades"] for w in periods] == [1, 1]
    assert periods[0]["by_side"][0]["cohort"] == {"side": "short"}
    assert periods[1]["by_lead_strategy"][0]["cohort"] == {
        "lead_strategy": "breakout",
    }
    assert all(
        w["week_original_booked_outcome_mature_at_handoff"] for w in periods
    )
    assert weekly["closed_only_not_capital_matched_account_pnl"] is True
    assert weekly["forward_full_account_after_cost_expectancy_proven"] is False
    assert weekly["promotion_authority"] is False
    assert weekly["execution_authority"] is False


def test_fixed_original_opening_weeks_cannot_rebalance_earlier_losing_periods(
) -> None:
    first = _move_trade_to_original_open_time(
        _trade(
            1, side="short", market="A", strategy="trend",
            gross="-8", entry_fee="2", exit_fee="1",
        ),
        _week_time(12), closed_at_ms=_week_time(12, 1),
    )
    later = _move_trade_to_original_open_time(
        _trade(
            2, side="long", market="B", strategy="breakout",
            gross="50", entry_fee="1", exit_fee="1",
        ),
        _week_time(26), closed_at_ms=_week_time(26, 1),
    )
    initial = _reconciled_audit_from_rows([first])
    amended = _reconciled_audit_from_rows([first, later])
    a = paper_profitability_scoreboard(initial)[
        "original_fixed_utc_opening_week_economics"
    ]
    b = paper_profitability_scoreboard(amended)[
        "original_fixed_utc_opening_week_economics"
    ]
    assert a["weeks"][0] == b["weeks"][0]
    assert len(b["weeks"]) == 3
    assert b["weeks"][1]["contains_no_original_closed_trades"] is True
    assert b["weeks"][1]["original_booked_week"]["trades"] == 0
    assert b["weeks"][0]["original_booked_week"]["net_pnl"] == "-11"
    assert b["weeks"][2]["original_booked_week"]["net_pnl"] == "48"
    assert b["weeks"][0]["week_original_booked_outcome_mature_at_handoff"] is False
    assert b["weeks"][2]["week_original_booked_outcome_mature_at_handoff"] is False
    assert b["calendar_boundaries_never_rebalanced_by_future_closes"] is True


def test_fixed_original_opening_week_maturity_requires_flat_original_handoff() -> None:
    source = _reconciled_audit_from_rows([
        _move_trade_to_original_open_time(
            _trade(1, side="long", market="BTC", strategy=None, gross="-20"),
            _week_time(12), closed_at_ms=_week_time(12, 1),
        )
    ])
    source["source_handoff_ended_at_ms"] = _week_time(26)
    source["source_handoff_open_positions"] = 1
    result = paper_profitability_scoreboard(source)
    week = result["original_fixed_utc_opening_week_economics"]["weeks"][0]
    assert week["original_booked_week"]["net_pnl"] == "-21.0"
    assert week["original_booked_week"]["unverified_entry_context_trades"] == 1
    assert week["week_original_booked_outcome_mature_at_handoff"] is False
    source["source_handoff_open_positions"] = 0
    result = paper_profitability_scoreboard(source)
    assert result["original_fixed_utc_opening_week_economics"]["weeks"][0][
        "week_original_booked_outcome_mature_at_handoff"
    ] is True
    source["source_handoff_ended_at_ms"] = _week_time(13)
    result = paper_profitability_scoreboard(source)
    assert result["original_fixed_utc_opening_week_economics"]["weeks"][0][
        "week_original_booked_outcome_mature_at_handoff"
    ] is False


def test_fixed_original_opening_weeks_do_not_erase_exact_net_r_when_empty() -> None:
    original = _reconciled_audit_from_rows([])
    result = paper_profitability_scoreboard(original)
    weekly = result["original_fixed_utc_opening_week_economics"]
    assert weekly["weeks"] == []
    assert weekly["all_original_closed_trade_counts_cash_and_net_r_reconciled"] is True
    assert result["overall"]["trades"] == 0
    assert result["overall"]["net_pnl"] == "0"
    assert result["promotion_authority"] is False


def _original_with_gap_witness(
    n: int, *, kind: str, gross: str, market: str,
    strategy: str | None = "trend",
) -> dict[str, object]:
    """Create one booked original trade; gap evidence never changes its cash."""
    row = _trade(
        n, side="long" if n % 2 else "short", market=market,
        strategy=strategy, gross=gross, chart=True,
    )
    if kind == "complete_observed_original_mark_path":
        return row
    row["chart_coverage_complete"] = False
    row["chart_path_present"] = True
    row["chart_known_gap_duration_ms"] = 0
    row["chart_unresolved_gap_starts_before_entry"] = 0
    row["chart_unresolved_gap_starts_during_position"] = 0
    if kind == "unresolved_before_entry_and_during_position":
        row["chart_known_gap_duration_ms"] = None
        row["chart_unresolved_gap_starts_before_entry"] = 1
        row["chart_unresolved_gap_starts_during_position"] = 1
    elif kind == "unresolved_before_entry":
        row["chart_known_gap_duration_ms"] = None
        row["chart_unresolved_gap_starts_before_entry"] = 1
    elif kind == "unresolved_during_position":
        row["chart_known_gap_duration_ms"] = None
        row["chart_unresolved_gap_starts_during_position"] = 1
    elif kind == "recorded_closed_market_data_gap":
        row["chart_known_gap_duration_ms"] = 15
    elif kind == "silent_unobserved_mark_interval":
        opened = row["opened_at_ms"]
        assert isinstance(opened, int)
        row["chart_silent_gap_intervals_ms"] = [[opened, opened + 20]]
    elif kind == "missing_original_mark_path":
        row["chart_path_present"] = False
        row["chart_mark_count"] = 0
        row["chart_mark_samples"] = []
        row["chart_known_gap_duration_ms"] = None
        row["chart_longest_unobserved_mark_ms"] = None
    elif kind != "other_incomplete_original_mark_path":
        raise AssertionError(f"unrecognized test witness class: {kind}")
    return row


def test_original_feed_gap_economics_partition_keeps_every_loss_fee_and_net_r() -> None:
    classes = (
        "complete_observed_original_mark_path",
        "unresolved_before_entry",
        "unresolved_during_position",
        "unresolved_before_entry_and_during_position",
        "recorded_closed_market_data_gap",
        "silent_unobserved_mark_interval",
        "missing_original_mark_path",
        "other_incomplete_original_mark_path",
    )
    source = _reconciled_audit_from_rows([
        _original_with_gap_witness(
            index, kind=kind, gross=("-11" if index % 2 else "8"),
            market="MEGA" if index % 2 else "ALGO",
            strategy=None if index == 7 else "trend",
        )
        for index, kind in enumerate(classes, start=1)
    ])
    report = paper_profitability_scoreboard(source)
    debt = report["original_chart_gap_witness_loss_attribution"]
    all_group = debt["whole_original_booked_journal"]
    buckets = debt["mutually_exclusive_evidence_classes"]
    assert len(buckets) == len(classes)
    assert {
        b["cohort"]["chart_gap_witness_class"]: b["trades"] for b in buckets
    } == dict.fromkeys(classes, 1)
    assert all_group["trades"] == 8
    assert all_group["net_pnl"] == report["overall"]["net_pnl"]
    assert all_group["fees"] == report["overall"]["fees"]
    assert all_group["net_r"] == report["overall"]["net_r"]
    assert debt["incomplete_or_missing_original_evidence"]["trades"] == 7
    assert debt["incomplete_or_missing_original_evidence"]["losses"] == 4
    assert debt[
        "all_original_closed_trades_and_booked_dollars_and_net_r_reconciled"
    ] is True
    assert debt["observed_gap_causation_of_booked_losses_proven"] is False
    assert debt["feed_event_gap_history_independently_recovered"] is False
    assert debt["execution_authority"] is False
    assert debt["promotion_authority"] is False
    markets = debt["incomplete_by_market"]
    assert sum(v["trades"] for v in markets) == 7
    assert sum(Decimal(v["net_pnl"]) for v in markets) == Decimal(
        debt["incomplete_or_missing_original_evidence"]["net_pnl"]
    )
    assert report["promotion_authority"] is False
    assert source["trades"] == source["trades"]


def test_original_gap_exposure_never_turns_unresolved_gap_into_clean_chart() -> None:
    unsafe = _original_with_gap_witness(
        1, kind="unresolved_before_entry", gross="25", market="MEGA",
    )
    unsafe["chart_coverage_complete"] = True
    source = _reconciled_audit_from_rows([unsafe])
    with pytest.raises(
        PaperProfitabilityScoreboardError, match="claimed complete original price path"
    ):
        paper_profitability_scoreboard(source)


def test_original_gap_exposure_uses_booked_actual_cash_not_synthetic_skip() -> None:
    missing = _original_with_gap_witness(
        1, kind="missing_original_mark_path", gross="-12",
        market="MEGA", strategy=None,
    )
    valid = _original_with_gap_witness(
        2, kind="complete_observed_original_mark_path", gross="3",
        market="ALGO",
    )
    report = paper_profitability_scoreboard(
        _reconciled_audit_from_rows([missing, valid])
    )
    gap = report["original_chart_gap_witness_loss_attribution"]
    assert gap["whole_original_booked_journal"]["net_pnl"] == "-11.0"
    assert gap["incomplete_or_missing_original_evidence"]["net_pnl"] == "-13.0"
    assert gap["incomplete_or_missing_original_evidence"]["unverified_entry_context_trades"] == 1
    assert gap["original_closed_trades_not_signed_full_account_equity"] is True
    assert gap["no_counterfactual_exit_or_abstention_executed"] is True
    assert gap["observed_gap_causation_of_booked_losses_proven"] is False


def test_profitability_cli_surfaces_original_gap_loss_evidence_without_execution(
    tmp_path: Path,
) -> None:
    source = _reconciled_audit_from_rows([
        _original_with_gap_witness(
            1, kind="unresolved_before_entry", gross="-12", market="MEGA",
        ),
    ])
    raw = tmp_path / "source.json"
    out = tmp_path / "research.json"
    raw.write_text(json.dumps(source), encoding="utf-8")
    subprocess.run(
        [
            sys.executable, "-m", "scripts.report_paper_profitability_scoreboard",
            str(raw), "--json-out", str(out),
        ],
        check=True, capture_output=True, text=True,
    )
    result = json.loads(out.read_text(encoding="utf-8"))
    debt = result["original_chart_gap_witness_loss_attribution"]
    assert debt["whole_original_booked_journal"]["net_pnl"] == "-13.0"
    assert debt["mutually_exclusive_evidence_classes"][0][
        "cohort"
    ]["chart_gap_witness_class"] == "unresolved_before_entry"
    assert debt["promotion_authority"] is False
