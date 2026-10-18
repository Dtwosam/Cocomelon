"""Exact-dollar, research-only profitability hurdle for fresh LONG-trend v3.

Consume ONLY the locally reconciled independent SQLite PAPER account audit.
A favorable arithmetic result is NOT a clean source, 72h trial, prospective
edge, or permission to modify trading.
"""
from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Context, Decimal, InvalidOperation, localcontext
from typing import Any, cast

ZERO = Decimal("0")
BOOKING_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)
# Source accounts book at precision 28; tiny cross-expression differences are
# not a dollar-denominated edge. Reject material drift without rounding PnL.
MAX_CASH_RESIDUAL = Decimal("1E-18")


class V3EconomicHurdleError(ValueError):
    pass


def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(type(key) is not str for key in value):
        raise V3EconomicHurdleError(f"{name} must be an object")
    return cast(dict[str, Any], value)


def _amount(row: dict[str, Any], key: str, lane: str) -> Decimal:
    raw = row.get(key)
    if type(raw) is not str:
        raise V3EconomicHurdleError(f"{lane} {key} must be exact decimal text")
    try:
        amount = Decimal(raw)
    except InvalidOperation as exc:
        raise V3EconomicHurdleError(f"{lane} {key} invalid decimal") from exc
    if not amount.is_finite():
        raise V3EconomicHurdleError(f"{lane} {key} nonfinite")
    return amount


def _lane(row: dict[str, Any], name: str) -> dict[str, Decimal | int]:
    fields = (
        "starting_cash_usd",
        "equity_usd",
        "gross_realized_pnl_usd",
        "fill_fees_usd",
        "funding_cash_usd",
        "unrealized_pnl_usd",
        "realized_after_cost_usd",
        "marked_after_cost_usd",
    )
    values = {field: _amount(row, field, name) for field in fields}
    start = values["starting_cash_usd"]
    fees = values["fill_fees_usd"]
    gross = values["gross_realized_pnl_usd"]
    funding = values["funding_cash_usd"]
    unrealized = values["unrealized_pnl_usd"]
    realized = values["realized_after_cost_usd"]
    marked = values["marked_after_cost_usd"]
    equity = values["equity_usd"]
    open_positions = row.get("open_position_count")
    if (
        start <= ZERO
        or fees < ZERO
        or type(open_positions) is not int
        or open_positions < 0
    ):
        raise V3EconomicHurdleError(f"{name} cash, fees or open count invalid")
    with localcontext(BOOKING_CONTEXT):
        if (
            abs(realized - (gross - fees + funding)) > MAX_CASH_RESIDUAL
            or abs(marked - (realized + unrealized)) > MAX_CASH_RESIDUAL
            or abs(equity - (start + marked)) > MAX_CASH_RESIDUAL
        ):
            raise V3EconomicHurdleError(f"{name} after-cost account cash mismatch")
    return {**values, "open_position_count": open_positions}


def fresh_long_trend_economic_hurdle(
    local_audit: dict[str, object],
) -> dict[str, object]:
    """Classify paired whole-account economics; cannot certify profitability."""
    audit = _mapping(local_audit, "local v3 SQLite audit")
    if (
        audit.get("schema") != "v3-readonly-original-paired-sqlite-cash-audit-v1"
        or audit.get("local_checkpoint_self_digest_and_exact_accounts_reconciled")
        is not True
        or audit.get("original_source_venue_completeness_authenticated") is not False
        or audit.get("external_checkpoint_signature_verified") is not False
        or audit.get("72h_forward_profitability_certified") is not False
        or audit.get("study_promotable") is not False
        or audit.get("paper_only") is not True
        or audit.get("research_only") is not True
        or audit.get("execution_authority") is not False
        or audit.get("promotion_authority") is not False
    ):
        raise V3EconomicHurdleError("unverified v3 study authority or parity")
    baseline = _lane(_mapping(audit.get("baseline"), "baseline"), "baseline")
    candidate = _lane(_mapping(audit.get("candidate"), "candidate"), "candidate")
    if candidate["starting_cash_usd"] != baseline["starting_cash_usd"]:
        raise V3EconomicHurdleError("paired starting cash differs")

    with localcontext() as ctx:
        ctx.prec = 96
        base_net = cast(Decimal, baseline["marked_after_cost_usd"])
        candidate_net = cast(Decimal, candidate["marked_after_cost_usd"])
        delta = candidate_net - base_net
        gross_delta = (
            candidate["gross_realized_pnl_usd"] - baseline["gross_realized_pnl_usd"]
        )
        fee_savings = baseline["fill_fees_usd"] - candidate["fill_fees_usd"]
        funding_delta = (
            candidate["funding_cash_usd"] - baseline["funding_cash_usd"]
        )
        unrealized_delta = (
            candidate["unrealized_pnl_usd"] - baseline["unrealized_pnl_usd"]
        )
        if abs(delta - (gross_delta + fee_savings + funding_delta + unrealized_delta)) > MAX_CASH_RESIDUAL:
            raise V3EconomicHurdleError("paired marked PnL decomposition differs")
        if _amount(
            audit, "candidate_minus_baseline_marked_after_cost_usd", "audit"
        ) - delta > MAX_CASH_RESIDUAL or delta - _amount(
            audit, "candidate_minus_baseline_marked_after_cost_usd", "audit"
        ) > MAX_CASH_RESIDUAL:
            raise V3EconomicHurdleError("audited candidate advantage mismatch")
        if (
            audit.get("candidate_marked_account_positive") is not (candidate_net > ZERO)
            or audit.get("baseline_marked_account_positive") is not (base_net > ZERO)
            or audit.get("both_accounts_positive")
            is not (candidate_net > ZERO and base_net > ZERO)
            or audit.get("relative_candidate_advantage_positive") is not (delta > ZERO)
        ):
            raise V3EconomicHurdleError("audited profitability flags mismatch")

        def target(lane: dict[str, Decimal | int]) -> dict[str, object]:
            net = cast(Decimal, lane["marked_after_cost_usd"])
            fees = cast(Decimal, lane["fill_fees_usd"])
            no_fee = net + fees
            return {
                "marked_after_all_costs_usd": str(net),
                "gross_realized_usd": str(lane["gross_realized_pnl_usd"]),
                "fees_paid_usd": str(fees),
                "funding_cash_usd": str(lane["funding_cash_usd"]),
                "unrealized_pnl_usd": str(lane["unrealized_pnl_usd"]),
                "starting_cash_usd": str(lane["starting_cash_usd"]),
                "equity_usd": str(lane["equity_usd"]),
                "open_positions": lane["open_position_count"],
                "additional_net_to_reach_zero_usd": str(max(-net, ZERO)),
                "same_fills_all_fees_refunded_net_usd": str(no_fee),
                "even_fee_free_same_fills_still_negative": no_fee < ZERO,
                "additional_gross_to_reach_zero_after_all_fee_refunds_usd": str(
                    max(-no_fee, ZERO)
                ),
                "absolute_after_cost_positive": net > ZERO,
            }

        return {
            "schema": "fresh-long-trend-v3-local-net-profit-hurdle-v1",
            "baseline": target(baseline),
            "candidate": target(candidate),
            "candidate_minus_baseline_after_cost_usd": str(delta),
            "delta_gross_realized_usd": str(gross_delta),
            "delta_fee_savings_usd": str(fee_savings),
            "delta_funding_cash_usd": str(funding_delta),
            "delta_unrealized_pnl_usd": str(unrealized_delta),
            "positive_absolute_baseline_and_candidate_and_delta": (
                base_net > ZERO and candidate_net > ZERO and delta > ZERO
            ),
            "scope": (
                "locally_reconciled_paper_accounts_marked_net_"
                "not_72h_source_authenticated_not_strategy_promotion"
            ),
            "open_exposure_valuation_can_change": bool(
                baseline["open_position_count"] or candidate["open_position_count"]
            ),
            "original_feed_source_authentication_certified": False,
            "signed_interworker_account_continuity_certified": False,
            "minimum_72h_source_and_equity_stability_certified": False,
            "whole_account_positive_forward_edge_certified": False,
            "execution_authority": False,
            "promotion_authority": False,
            "paper_only": True,
            "research_only": True,
        }
