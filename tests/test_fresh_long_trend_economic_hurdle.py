"""Exact money-first v3 trial arithmetic, without invented trading improvement."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, localcontext

import pytest

from cocomelon.research.fresh_long_trend_economic_hurdle import (
    V3EconomicHurdleError,
    fresh_long_trend_economic_hurdle,
)


def _lane(
    gross: str, fees: str, funding: str, open_mark: str, *,
    start: str = "10000", count: int = 1,
) -> dict[str, object]:
    with localcontext() as ctx:
        ctx.prec = 96
        realized = Decimal(gross) - Decimal(fees) + Decimal(funding)
        marked = realized + Decimal(open_mark)
        return {
            "starting_cash_usd": start,
            "equity_usd": str(Decimal(start) + marked),
            "gross_realized_pnl_usd": gross,
            "fill_fees_usd": fees,
            "funding_cash_usd": funding,
            "unrealized_pnl_usd": open_mark,
            "realized_after_cost_usd": str(realized),
            "marked_after_cost_usd": str(marked),
            "open_position_count": count,
        }


def _audit(
    base: dict[str, object] | None = None,
    candidate: dict[str, object] | None = None,
) -> dict[str, object]:
    base = base or _lane("-50", "20", "-2", "5")
    candidate = candidate or _lane("15", "10", "-1", "-5")
    bn = Decimal(str(base["marked_after_cost_usd"]))
    cn = Decimal(str(candidate["marked_after_cost_usd"]))
    return {
        "schema": "v3-readonly-original-paired-sqlite-cash-audit-v1",
        "local_checkpoint_self_digest_and_exact_accounts_reconciled": True,
        "baseline": base,
        "candidate": candidate,
        "candidate_minus_baseline_marked_after_cost_usd": str(cn - bn),
        "baseline_marked_account_positive": bn > 0,
        "candidate_marked_account_positive": cn > 0,
        "both_accounts_positive": bn > 0 and cn > 0,
        "relative_candidate_advantage_positive": cn > bn,
        "original_source_venue_completeness_authenticated": False,
        "external_checkpoint_signature_verified": False,
        "72h_forward_profitability_certified": False,
        "study_promotable": False,
        "paper_only": True,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
    }


def test_relative_winner_can_still_lose_absolute_after_cost() -> None:
    report = fresh_long_trend_economic_hurdle(_audit())
    assert report["baseline"]["marked_after_all_costs_usd"] == "-67"
    assert report["candidate"]["marked_after_all_costs_usd"] == "-1"
    assert report["candidate_minus_baseline_after_cost_usd"] == "66"
    assert report["delta_gross_realized_usd"] == "65"
    assert report["delta_fee_savings_usd"] == "10"
    assert report["delta_funding_cash_usd"] == "1"
    assert report["delta_unrealized_pnl_usd"] == "-10"
    assert report["baseline"]["same_fills_all_fees_refunded_net_usd"] == "-47"
    assert report["baseline"]["even_fee_free_same_fills_still_negative"]
    assert report["baseline"]["additional_gross_to_reach_zero_after_all_fee_refunds_usd"] == "47"
    assert report["candidate"]["same_fills_all_fees_refunded_net_usd"] == "9"
    assert report["candidate"]["additional_net_to_reach_zero_usd"] == "1"
    assert report["candidate"]["absolute_after_cost_positive"] is False
    assert report["positive_absolute_baseline_and_candidate_and_delta"] is False
    assert report["baseline"]["booked_fee_coverage_by_non_fee_marked_pnl_ratio"] == "-2.35"
    assert report["baseline"]["fraction_of_booked_fees_to_refund_for_zero"] == "3.35"
    assert report["baseline"]["even_full_fee_refund_cannot_make_strict_profit"]
    assert report["candidate"]["booked_fee_coverage_by_non_fee_marked_pnl_ratio"] == "0.9"
    assert report["candidate"]["fraction_of_booked_fees_to_refund_for_zero"] == "0.1"
    assert not report["candidate"]["even_full_fee_refund_cannot_make_strict_profit"]
    scenarios = report["paired_same_fills_fee_refund_sensitivity"]
    assert [x["booked_fee_refund_fraction"] for x in scenarios] == [
        "0", "0.25", "0.50", "0.75", "1"
    ]
    assert [x["candidate_minus_baseline_usd"] for x in scenarios] == [
        "66", "63.50", "61.00", "58.50", "56"
    ]
    assert scenarios[0]["baseline_same_fills_marked_net_usd"] == "-67"
    assert scenarios[0]["candidate_same_fills_marked_net_usd"] == "-1"
    assert scenarios[1]["candidate_same_fills_marked_net_usd"] == "1.50"
    assert scenarios[-1]["baseline_same_fills_marked_net_usd"] == "-47"
    assert scenarios[-1]["candidate_same_fills_marked_net_usd"] == "9"
    assert all(not row["both_accounts_strictly_positive"] for row in scenarios)
    assert all(row["candidate_strictly_ahead"] for row in scenarios)
    assert all(
        row["research_only"] and not row["execution_authority"]
        and not row["promotion_authority"]
        for row in scenarios
    )
    assert report["open_exposure_valuation_can_change"] is True
    assert report["whole_account_positive_forward_edge_certified"] is False
    assert report["promotion_authority"] is False
    assert report["execution_authority"] is False


def test_only_local_descriptive_positive_screen_when_both_accounts_win() -> None:
    data = _audit(
        _lane("30", "5", "0", "0", count=0),
        _lane("60", "10", "0", "0", count=0),
    )
    report = fresh_long_trend_economic_hurdle(data)
    assert report["positive_absolute_baseline_and_candidate_and_delta"] is True
    assert report["candidate_minus_baseline_after_cost_usd"] == "25"
    assert report["open_exposure_valuation_can_change"] is False
    # Even the best synthetic test never proves original exchange coverage.
    assert report["original_feed_source_authentication_certified"] is False
    assert report["minimum_72h_source_and_equity_stability_certified"] is False
    assert report["whole_account_positive_forward_edge_certified"] is False


@pytest.mark.parametrize(("field", "value", "message"), [
    ("equity_usd", "9998", "cash mismatch"),
    ("realized_after_cost_usd", "10", "cash mismatch"),
    ("fill_fees_usd", "-1", "cash, fees"),
    ("gross_realized_pnl_usd", "NaN", "nonfinite"),
    ("open_position_count", True, "cash, fees"),
])
def test_contradictory_account_or_forged_fee_fails_closed(
    field: str, value: object, message: str,
) -> None:
    audit = _audit()
    broken = deepcopy(audit)
    broken["candidate"][field] = value
    with pytest.raises(V3EconomicHurdleError, match=message):
        fresh_long_trend_economic_hurdle(broken)


@pytest.mark.parametrize(("field", "value"), [
    ("candidate_minus_baseline_marked_after_cost_usd", "1"),
    ("candidate_marked_account_positive", True),
    ("both_accounts_positive", True),
    ("local_checkpoint_self_digest_and_exact_accounts_reconciled", False),
    ("original_source_venue_completeness_authenticated", True),
    ("72h_forward_profitability_certified", True),
    ("promotion_authority", True),
])
def test_untrusted_audit_authority_or_pnl_is_rejected(
    field: str, value: object,
) -> None:
    audit = _audit()
    audit[field] = value
    with pytest.raises(V3EconomicHurdleError):
        fresh_long_trend_economic_hurdle(audit)


def test_identical_zero_profit_is_not_a_winning_trial() -> None:
    same = _lane("0", "0", "0", "0", count=0)
    report = fresh_long_trend_economic_hurdle(_audit(same, same))
    assert report["candidate_minus_baseline_after_cost_usd"] == "0"
    assert report["positive_absolute_baseline_and_candidate_and_delta"] is False
    assert report["candidate"]["additional_net_to_reach_zero_usd"] == "0"
    assert report["candidate"]["absolute_after_cost_positive"] is False


def test_paid_fee_discount_threshold_is_not_forward_profit() -> None:
    base = _lane("20", "10", "0", "0", count=0)
    challenger = _lane("18", "3", "0", "0", count=0)
    report = fresh_long_trend_economic_hurdle(_audit(base, challenger))
    assert report["candidate_minus_baseline_after_cost_usd"] == "5"
    assert report["delta_gross_realized_usd"] == "-2"
    assert report["delta_fee_savings_usd"] == "7"
    scenarios = report["paired_same_fills_fee_refund_sensitivity"]
    assert scenarios[0]["candidate_minus_baseline_usd"] == "5"
    assert scenarios[-1]["candidate_minus_baseline_usd"] == "-2"
    assert report["positive_absolute_baseline_and_candidate_and_delta"] is True
    assert report["promotion_authority"] is False


def test_no_fees_and_fee_free_breakeven_do_not_synthesize_an_edge() -> None:
    base = _lane("-1", "0", "0", "0", count=0)
    challenger = _lane("2", "2", "0", "0", count=0)
    report = fresh_long_trend_economic_hurdle(_audit(base, challenger))
    assert report["baseline"]["fraction_of_booked_fees_to_refund_for_zero"] is None
    assert report["baseline"]["booked_fee_coverage_by_non_fee_marked_pnl_ratio"] is None
    assert report["baseline"]["even_full_fee_refund_cannot_make_strict_profit"]
    assert report["candidate"]["fraction_of_booked_fees_to_refund_for_zero"] == "0"
    assert report["candidate"]["even_full_fee_refund_cannot_make_strict_profit"] is False
    assert report["candidate"]["absolute_after_cost_positive"] is False
    assert not report["paired_same_fills_fee_refund_sensitivity"][0][
        "both_accounts_strictly_positive"
    ]
    assert report["whole_account_positive_forward_edge_certified"] is False
