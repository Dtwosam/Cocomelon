from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace

import pytest

from cocomelon.research.deferred_early_exit_chart_integrity import (
    DeferredEarlyExitChartIntegrityError,
    assess_early_exit_chart_integrity,
)
from cocomelon.research.prospective_early_vs_late_trailing import (
    _economics,
)


def _sources() -> tuple[dict[str, object], dict[str, object]]:
    rows = [
        {
            "trade_id": "long-1",
            "side": "long",
            "opened_at_ms": 1100,
            "closed_at_ms": 1900,
            "net_pnl": "1.5",
            "net_r": "0.15",
            "chart_path_present": True,
            "chart_coverage_complete": True,
            "chart_mark_count": 12,
            "chart_known_gap_duration_ms": 0,
        },
        {
            "trade_id": "short-1",
            "side": "short",
            "opened_at_ms": 1200,
            "closed_at_ms": 2000,
            "net_pnl": "-2",
            "net_r": "-0.2",
            "chart_path_present": True,
            "chart_coverage_complete": True,
            "chart_mark_count": 18,
            "chart_known_gap_duration_ms": 0,
        },
    ]
    exit_report: dict[str, object] = {
        "definition": (
            "frozen_plus_0_5r_early_vs_plus_1r_late_visible_book_ioc"
        ),
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "economic_screen_passes": True,
        "matched_trade_count": 2,
        "matched_trade_ids": ["long-1", "short-1"],
        "future_original_closed_trades": 2,
        "common_scoring_start_ms": 1000,
        "overall": {
            "matched_trades": 2,
            "original_net_pnl": "-0.5",
            "original_net_r": "-0.05",
        },
        "by_direction": {
            "long": {
                "matched_trades": 1,
                "original_net_pnl": "1.5",
                "original_net_r": "0.15",
            },
            "short": {
                "matched_trades": 1,
                "original_net_pnl": "-2",
                "original_net_r": "-0.2",
            },
        },
    }
    charts: dict[str, object] = {
        "definition": (
            "entire_closed_paper_journal_with_observed_in_position_mark_charts_v1"
        ),
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "total_journal_trades": 2,
        "trades_included_in_economics": 2,
        "trades": rows,
        "economics": {"overall": {"net_pnl": "-0.5"}},
    }
    return exit_report, charts


def test_all_clean_forward_trades_reconcile_original_cashflow_and_r() -> None:
    exits, charts = _sources()
    result = assess_early_exit_chart_integrity(exits, charts)
    assert result["matched_forward_trades"] == 2
    assert result["total_original_forward_trades"] == 2
    assert result["unmatched_original_forward_trade_ids"] == []
    assert result["verified_clean_chart_trades"] == 2
    assert result["chart_integrity_complete"] is True
    assert result["economic_screen_with_chart_integrity"] is True
    assert result["unfiltered_original_net_pnl"] == "-0.5"
    assert result["unfiltered_original_net_r"] == "-0.05"
    assert result["execution_authority"] is False
    assert result["ready_for_review"] is False


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("chart_path_present", False, "missing_chart_trade_ids"),
        ("chart_coverage_complete", False, "incomplete_chart_trade_ids"),
        ("chart_mark_count", 1, "incomplete_chart_trade_ids"),
        ("chart_known_gap_duration_ms", 55, "known_data_gap_trade_ids"),
        ("chart_known_gap_duration_ms", None, "known_data_gap_trade_ids"),
    ],
)
def test_missing_incomplete_and_gapped_charts_never_make_exit_ready(
    field: str,
    value: object,
    expected: str,
) -> None:
    exits, charts = _sources()
    rows = charts["trades"]
    assert isinstance(rows, list)
    rows[1][field] = value
    result = assess_early_exit_chart_integrity(exits, charts)
    assert result["economic_screen_with_chart_integrity"] is False
    assert result["chart_integrity_complete"] is False
    assert result[expected] == ["short-1"]
    assert result["matched_forward_trades"] == 2
    assert result["unfiltered_original_net_pnl"] == "-0.5"



def test_exit_chart_gate_rejects_cherry_picked_clean_simulated_subset() -> None:
    exits, charts = _sources()
    # Only the winning original received an executable complete IOC outcome.
    # The losing original still belongs in the untouched journal denominator.
    exits["matched_trade_ids"] = ["long-1"]
    exits["matched_trade_count"] = 1
    original = exits["overall"]
    by_side = exits["by_direction"]
    assert isinstance(original, dict)
    assert isinstance(by_side, dict)
    original["matched_trades"] = 1
    original["original_net_pnl"] = "1.5"
    original["original_net_r"] = "0.15"
    short = by_side["short"]
    assert isinstance(short, dict)
    short["matched_trades"] = 0
    short["original_net_pnl"] = "0"
    short["original_net_r"] = "0"
    report = assess_early_exit_chart_integrity(exits, charts)
    assert report["total_original_forward_trades"] == 2
    assert report["matched_forward_trades"] == 1
    assert report["unmatched_original_forward_trade_ids"] == ["short-1"]
    assert report["verified_clean_chart_trades"] == 1
    assert report["chart_integrity_complete"] is False
    assert report["economic_screen_with_chart_integrity"] is False
    assert report["unfiltered_original_net_pnl"] == "-0.5"
    assert report["unfiltered_original_net_r"] == "-0.05"
    assert report["matched_original_net_pnl"] == "1.5"


def test_exit_chart_gate_rejects_forged_full_forward_denominator() -> None:
    exits, charts = _sources()
    exits["future_original_closed_trades"] = 1
    with pytest.raises(
        DeferredEarlyExitChartIntegrityError,
        match="forward original sample does not reconcile",
    ):
        assess_early_exit_chart_integrity(exits, charts)


def test_empty_forward_sample_cannot_be_claimed_all_clean() -> None:
    exits, charts = _sources()
    exits["common_scoring_start_ms"] = 3000
    exits["future_original_closed_trades"] = 0
    exits["matched_trade_ids"] = []
    exits["matched_trade_count"] = 0
    overall = exits["overall"]
    sides = exits["by_direction"]
    assert isinstance(overall, dict)
    assert isinstance(sides, dict)
    overall.update({
        "matched_trades": 0,
        "original_net_pnl": "0",
        "original_net_r": "0",
    })
    for key in ("long", "short"):
        side = sides[key]
        assert isinstance(side, dict)
        side.update({
            "matched_trades": 0,
            "original_net_pnl": "0",
            "original_net_r": "0",
        })
    report = assess_early_exit_chart_integrity(exits, charts)
    assert report["total_original_forward_trades"] == 0
    assert report["chart_integrity_complete"] is False
    assert report["economic_screen_with_chart_integrity"] is False



def test_original_r_reconciliation_blocks_false_profit_claim() -> None:
    exits, charts = _sources()
    overall = exits["overall"]
    assert isinstance(overall, dict)
    overall["original_net_r"] = "1.5"
    with pytest.raises(
        DeferredEarlyExitChartIntegrityError,
        match="economics contradict",
    ):
        assess_early_exit_chart_integrity(exits, charts)


def test_original_side_profit_reconciliation_blocks_swap() -> None:
    exits, charts = _sources()
    by_side = exits["by_direction"]
    assert isinstance(by_side, dict)
    side = by_side["short"]
    assert isinstance(side, dict)
    side["original_net_pnl"] = "5"
    with pytest.raises(
        DeferredEarlyExitChartIntegrityError,
        match="short paired exit",
    ):
        assess_early_exit_chart_integrity(exits, charts)


def test_cannot_select_only_winning_charts_or_unknown_trades() -> None:
    exits, charts = _sources()
    rows = charts["trades"]
    assert isinstance(rows, list)
    rows.pop()
    with pytest.raises(
        DeferredEarlyExitChartIntegrityError,
        match="sample is incomplete",
    ):
        assess_early_exit_chart_integrity(exits, charts)

    exits, charts = _sources()
    ids = exits["matched_trade_ids"]
    assert isinstance(ids, list)
    ids[1] = "not-a-closed-trade"
    with pytest.raises(
        DeferredEarlyExitChartIntegrityError,
        match="outside closed journal",
    ):
        assess_early_exit_chart_integrity(exits, charts)


def test_reject_duplicate_or_pre_frozen_original_sample() -> None:
    exits, charts = _sources()
    ids = exits["matched_trade_ids"]
    assert isinstance(ids, list)
    ids[1] = ids[0]
    with pytest.raises(
        DeferredEarlyExitChartIntegrityError, match="duplicated"
    ):
        assess_early_exit_chart_integrity(exits, charts)

    exits, charts = _sources()
    exits["common_scoring_start_ms"] = 1400
    with pytest.raises(
        DeferredEarlyExitChartIntegrityError,
        match="forward original sample does not reconcile",
    ):
        assess_early_exit_chart_integrity(exits, charts)


def test_zero_early_vs_late_advantage_fails_screen_with_clean_chart() -> None:
    exits, charts = _sources()
    exits["economic_screen_passes"] = False
    result = assess_early_exit_chart_integrity(exits, charts)
    assert result["chart_integrity_complete"] is True
    assert result["economic_screen_with_chart_integrity"] is False


def test_early_exit_must_beat_original_after_cost_r_not_only_dollars() -> None:
    trade = SimpleNamespace(net_pnl=Decimal("1"), net_r=Decimal("2"))
    early = SimpleNamespace(
        candidate_net_pnl_estimate=Decimal("3"),
        candidate_net_r_estimate=Decimal("1"),
    )
    late = SimpleNamespace(
        candidate_net_pnl_estimate=Decimal("2"),
        candidate_net_r_estimate=Decimal("0.5"),
    )
    outcome = _economics(((trade, early, late),))
    assert outcome["early_vs_original_net_pnl"] == "2"
    assert outcome["early_vs_original_net_r"] == "-1"
    assert outcome["early_beats_late_and_original"] is False

    # Increasing original R alone must never make the early policy
    # attractive. Keep identical closed original identities in all cases.
    more_orig = deepcopy(trade)
    more_orig.net_r = Decimal("0.5")
    improved = _economics(((more_orig, early, late),))
    assert improved["early_beats_late_and_original"] is True
