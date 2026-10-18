"""PAPER profitability is measured on the entire marked account, after costs."""
from __future__ import annotations

from scripts.render_continuous_paper_live_status import _account_breakeven_lines


def _account(**edits: object) -> dict[str, object]:
    # Values are the actual authenticated 2026-10-18 14:46 UTC PAPER
    # status, not a synthetic winning or source-certified strategy.
    result: dict[str, object] = {
        "starting_cash": "10000",
        "equity": "9736.877904323346178200000001",
        "total_account_pnl": "-263.122095676653821799999999",
        "realized_gross_pnl": "-33.75662000000000000000000317",
        "cumulative_fees": "227.00025559890",
        "cumulative_funding": "-2.3652200777538218",
        "unrealized_pnl": "0",
    }
    result.update(edits)
    return result


def test_actual_whole_paper_account_still_loses_even_without_fees() -> None:
    lines = "\n".join(_account_breakeven_lines(_account()))
    assert "263.122095676653821799999999" in lines
    assert "-36.12184007775382180000000317" in lines
    assert "true / 36.12184007775382180000000317" in lines
    assert "absolute marked PAPER after-cost positive: `false`" in lines
    assert "NOT CERTIFIED / NOT CERTIFIED / DISABLED" in lines


def test_open_mark_is_included_and_no_fee_replay_does_not_invent_fills() -> None:
    lines = "\n".join(_account_breakeven_lines({
        "starting_cash": "10000",
        "equity": "10008",
        "total_account_pnl": "8",
        "realized_gross_pnl": "0",
        "cumulative_fees": "2",
        "cumulative_funding": "0",
        "unrealized_pnl": "10",
    }))
    assert "dollars to zero (not profit): `0`" in lines
    assert "funding/marks unchanged): `10`" in lines
    assert "false / 0" in lines
    assert "absolute marked PAPER after-cost positive: `true`" in lines
    assert "NOT CERTIFIED / NOT CERTIFIED / DISABLED" in lines


def test_break_even_zero_not_labeled_profitable() -> None:
    lines = "\n".join(_account_breakeven_lines({
        "starting_cash": "10000",
        "equity": "10000",
        "total_account_pnl": "0",
        "realized_gross_pnl": "2",
        "cumulative_fees": "2",
        "cumulative_funding": "0",
        "unrealized_pnl": "0",
    }))
    assert "dollars to zero (not profit): `0`" in lines
    assert "absolute marked PAPER after-cost positive: `false`" in lines


def test_corrupt_components_never_produce_false_profitability() -> None:
    cases: tuple[dict[str, object], ...] = (
        {"equity": "10001"},
        {"total_account_pnl": "999"},
        {"starting_cash": "0"},
        {"cumulative_fees": "-1"},
        {"unrealized_pnl": "NaN"},
        {"unrealized_pnl": "Infinity"},
        {"total_account_pnl": True},
        {"realized_gross_pnl": 4},
        {"cumulative_funding": ""},
    )
    for changed in cases:
        lines = _account_breakeven_lines(_account(**changed))
        assert len(lines) == 1
        assert "UNAVAILABLE" in lines[0]
        assert "NOT CERTIFIED" not in lines[0]


def test_missing_components_fail_closed_without_crashing_status() -> None:
    assert "UNAVAILABLE" in _account_breakeven_lines({})[0]
    value = _account()
    del value["total_account_pnl"]
    assert "UNAVAILABLE" in _account_breakeven_lines(value)[0]


def test_booking_precision_differences_do_not_hide_true_loss() -> None:
    lines = _account_breakeven_lines(_account(
        total_account_pnl="-263.122095676653821799999999",
    ))
    assert any("dollars to zero" in line for line in lines)
