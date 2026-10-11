from __future__ import annotations

from decimal import Decimal

import pytest

from cocomelon.research.prospective_short_rank_utc_window import (
    UTC_DAY_MS,
    PairedAccountUtcWindowLedger,
    PairedAccountWindowError,
)

D = Decimal


def _ledger() -> PairedAccountUtcWindowLedger:
    return PairedAccountUtcWindowLedger(
        started_at_ms=UTC_DAY_MS - 4_000,
        starting_cash=D("10000"),
    )


def _record(
    ledger: PairedAccountUtcWindowLedger,
    at_ms: int,
    b_equity: str,
    b_cash: str,
    c_equity: str,
    c_cash: str,
) -> None:
    ledger.record(
        at_ms=at_ms,
        baseline_equity=D(b_equity),
        baseline_realized=D(b_cash),
        candidate_equity=D(c_equity),
        candidate_realized=D(c_cash),
    )


def _receipt(
    ledger: PairedAccountUtcWindowLedger,
    b_equity: str, b_cash: str,
    c_equity: str, c_cash: str,
) -> dict[str, object]:
    return ledger.reconciled_payload(
        baseline_equity=D(b_equity),
        baseline_realized=D(b_cash),
        candidate_equity=D(c_equity),
        candidate_realized=D(c_cash),
    )


def test_all_four_signed_cash_series_reconcile_even_with_losses(
) -> None:
    ledger = _ledger()
    _record(ledger, UTC_DAY_MS - 2_000, "9991", "-11", "9999", "-3")
    # This change spans midnight; no one can truthfully attribute it to
    # either observed day. It contains an extra challenger loss.
    _record(ledger, UTC_DAY_MS + 100, "9986", "-14", "9980", "-23")
    _record(ledger, UTC_DAY_MS + 200, "9981", "-19", "9977", "-25")

    result = _receipt(ledger, "9981", "-19", "9977", "-25")
    previous = result["by_fixed_utc_day"]
    assert isinstance(previous, dict)
    assert previous["1970-01-01"]["baseline_marked"] == "-9"
    assert previous["1970-01-01"]["candidate_realized"] == "-3"
    assert previous["1970-01-02"]["baseline_marked"] == "-5"
    assert previous["1970-01-02"]["candidate_realized"] == "-2"
    unallocated = result["unallocated_cross_day"]
    assert isinstance(unallocated, dict)
    assert unallocated == {
        "baseline_marked": "-5",
        "baseline_realized": "-3",
        "candidate_marked": "-19",
        "candidate_realized": "-20",
        "candidate_minus_baseline_marked": "-14",
        "candidate_minus_baseline_realized": "-17",
    }
    total = result["full_account_change"]
    assert isinstance(total, dict)
    assert total["baseline_marked"] == "-19"
    assert total["baseline_realized"] == "-19"
    assert total["candidate_marked"] == "-23"
    assert total["candidate_realized"] == "-25"
    assert total["candidate_minus_baseline_marked"] == "-4"
    assert total["candidate_minus_baseline_realized"] == "-6"
    assert result["midnight_crossing_interval_count"] == 1
    assert result["all_four_account_metrics_reconciled"] is True
    assert result["execution_authority"] is False


def test_missing_terminal_equity_or_cash_cannot_publish_reconciled_report() -> None:
    ledger = _ledger()
    _record(ledger, UTC_DAY_MS - 2_000, "9991", "-11", "9999", "-3")
    with pytest.raises(PairedAccountWindowError, match="diverges"):
        _receipt(ledger, "9991", "-11", "9999", "-4")
    with pytest.raises(PairedAccountWindowError, match="diverges"):
        _receipt(ledger, "9990", "-11", "9999", "-3")


def test_off_day_change_does_not_get_relabelled_as_daily_profit() -> None:
    ledger = _ledger()
    _record(ledger, UTC_DAY_MS + 100, "9980", "-20", "9990", "-10")
    result = _receipt(ledger, "9980", "-20", "9990", "-10")
    assert result["by_fixed_utc_day"] == {}
    unallocated = result["unallocated_cross_day"]
    assert isinstance(unallocated, dict)
    assert unallocated["baseline_realized"] == "-20"
    assert unallocated["candidate_realized"] == "-10"
    assert unallocated["candidate_minus_baseline_realized"] == "10"


def test_bad_checkpoint_types_regressions_and_nonfinite_balances_rejected() -> None:
    with pytest.raises(PairedAccountWindowError, match="starting cash"):
        PairedAccountUtcWindowLedger(started_at_ms=1, starting_cash=D("NaN"))
    ledger = _ledger()
    with pytest.raises(PairedAccountWindowError, match="chronological"):
        _record(ledger, UTC_DAY_MS - 5_000, "10000", "0", "10000", "0")
    with pytest.raises(PairedAccountWindowError, match="nonfinite"):
        _record(ledger, UTC_DAY_MS - 1, "NaN", "0", "10000", "0")
    assert ledger.checkpoint_count == 0


def test_zero_market_movement_and_zero_cashflow_stay_reconciled() -> None:
    ledger = _ledger()
    _record(ledger, UTC_DAY_MS - 1_000, "10000", "0", "10000", "0")
    result = _receipt(ledger, "10000", "0", "10000", "0")
    allocated = result["allocated_sum"]
    assert isinstance(allocated, dict)
    assert allocated["candidate_minus_baseline_marked"] == "0"
    assert result["checkpoint_count"] == 1
    assert result["research_only"] is True
