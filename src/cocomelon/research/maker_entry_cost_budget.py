"""Closed-journal maker-entry cost budget; never a maker execution PnL claim.

This is a same-original-fill, same-original-exit fee-only stress test.
It does NOT model maker queue, actual resting orders, changed entry prices,
altered capital availability, partial fills, stops or missing profitable
trades as observed outcomes. Open-position marks are not in a closed journal.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation, localcontext
from typing import Final, cast

from cocomelon.domain.journal import TradeJournalEntry

ZERO: Final = Decimal("0")
ONE: Final = Decimal("1")
CASH_TOLERANCE: Final = Decimal("1E-18")
MAX_TRADES: Final = 100_000


class MakerEntryCostBudgetError(ValueError):
    pass


def _amount(raw: object, name: str, *, positive: bool = False) -> Decimal:
    if type(raw) is not str:
        raise MakerEntryCostBudgetError(f"{name} must be exact decimal text")
    try:
        amount = Decimal(raw)
    except InvalidOperation as exc:
        raise MakerEntryCostBudgetError(f"{name} decimal invalid") from exc
    if (
        not amount.is_finite()
        or amount < ZERO
        or (positive and amount <= ZERO)
    ):
        raise MakerEntryCostBudgetError(f"{name} must be finite nonnegative")
    return amount


def _cash_text(value: Decimal) -> str:
    # Canonical cash string without precision-context trailing zeros.
    return format(value.normalize(), "f")


def _validate_review(
    trade: TradeJournalEntry,
    raw: Mapping[str, object],
    *,
    taker_rate: Decimal,
    maker_rate: Decimal,
) -> Decimal:
    quote_raw = raw.get("quote")
    if not isinstance(quote_raw, dict):
        raise MakerEntryCostBudgetError("maker review missing original quote")
    quote = cast(dict[str, object], quote_raw)
    side = "buy" if trade.direction.value == "long" else "sell"
    if (
        raw.get("schema") != "original-post-only-entry-feasibility-v1"
        or raw.get("research_only") is not True
        or raw.get("execution_authority") is not False
        or raw.get("promotion_authority") is not False
        or raw.get("maker_fill_certified") is not False
        or raw.get("source_external_authentication_certified") is not False
        or raw.get("quote_fully_observed_to_expiry") is not True
        or raw.get("guaranteed_entry_fill_quantity") != "0"
        or raw.get("maker_fee_savings_realized_usd") is not None
        or raw.get("candidate_after_cost_pnl_usd") is not None
        or quote.get("resting_order_submitted") is not False
        or quote.get("maker_fill_certified") is not False
        or quote.get("execution_authority") is not False
        or quote.get("promotion_authority") is not False
        or quote.get("opening_plan_id") != trade.opening_plan_id
        or quote.get("market") != trade.market.canonical
        or quote.get("side") != side
        or quote.get("baseline_taker_fee_rate") != str(taker_rate)
        or quote.get("hypothetical_maker_fee_rate") != str(maker_rate)
    ):
        raise MakerEntryCostBudgetError(
            "maker research receipt identity or authority drift"
        )
    quote_time = quote.get("quote_at_ms")
    expiry = quote.get("expire_at_ms")
    if (
        type(quote_time) is not int
        or type(expiry) is not int
        or not 0 <= quote_time < expiry
        or quote_time > trade.opened_at_ms
        or expiry > trade.closed_at_ms
    ):
        raise MakerEntryCostBudgetError(
            "maker quote chronology cannot retain original exit"
        )
    requested = _amount(
        quote.get("requested_quantity"), "maker requested quantity", positive=True
    )
    observed_upper = _amount(
        raw.get("possible_entry_fill_quantity_upper_bound"),
        "maker possible crossing quantity",
    )
    quoted_price = _amount(
        quote.get("quote_price"), "maker quoted price", positive=True
    )
    conditional_savings = _amount(
        quote.get("fee_savings_if_entire_entry_filled_same_notional"),
        "maker conditional saving",
    )
    expected_savings = requested * quoted_price * (taker_rate - maker_rate)
    if (
        requested < trade.filled_quantity
        or observed_upper > requested
        or abs(expected_savings - conditional_savings) > CASH_TOLERANCE
    ):
        raise MakerEntryCostBudgetError("maker quoted size, crossing or fee mismatch")
    return observed_upper


def maker_entry_closed_trade_cost_budget(
    trades: Sequence[TradeJournalEntry],
    reviews_by_opening_plan: Mapping[str, Mapping[str, object]],
    *,
    taker_fee_rate: Decimal,
    maker_fee_rate: Decimal,
) -> dict[str, object]:
    """Fail-closed descriptive cash budget for original completed trades only.

    Upper-fee savings assume ALL original entries inexplicably fill at the
    original IOC price, then the exact same actual exit/funding is booked.
    Witness crossing quantities cannot certify even one such fill.
    """
    if (
        type(taker_fee_rate) is not Decimal
        or type(maker_fee_rate) is not Decimal
        or not taker_fee_rate.is_finite()
        or not maker_fee_rate.is_finite()
        or not ZERO < taker_fee_rate < Decimal("0.1")
        or not ZERO <= maker_fee_rate < taker_fee_rate
    ):
        raise MakerEntryCostBudgetError("maker and taker fee schedule invalid")
    items = tuple(trades)
    if not items or len(items) > MAX_TRADES:
        raise MakerEntryCostBudgetError("nonempty bounded closed cohort required")
    if (
        len({trade.trade_id for trade in items}) != len(items)
        or len({trade.opening_plan_id for trade in items}) != len(items)
    ):
        raise MakerEntryCostBudgetError("duplicate closed trade or opening plan")
    expected_plans = {trade.opening_plan_id for trade in items}
    if set(reviews_by_opening_plan) != expected_plans:
        raise MakerEntryCostBudgetError("unpaired maker reviews or missing originals")

    with localcontext() as ctx:
        ctx.prec = 96
        fee_discount_fraction = ONE - maker_fee_rate / taker_fee_rate
        original_net = ZERO
        gross = ZERO
        entry_fees = ZERO
        exit_fees = ZERO
        funding = ZERO
        discount = ZERO
        individual_same_fill_nets: list[Decimal] = []
        print_full_size_not_ruled_out = 0
        print_full_size_ruled_out = 0
        zero_possible_prints = 0
        for trade in items:
            possible_qty = _validate_review(
                trade,
                reviews_by_opening_plan[trade.opening_plan_id],
                taker_rate=taker_fee_rate,
                maker_rate=maker_fee_rate,
            )
            if possible_qty >= trade.filled_quantity:
                print_full_size_not_ruled_out += 1
            else:
                print_full_size_ruled_out += 1
            if possible_qty == ZERO:
                zero_possible_prints += 1
            if (
                not trade.net_pnl.is_finite()
                or not trade.entry_fees.is_finite()
                or not trade.exit_fees.is_finite()
                or not trade.gross_realized_pnl.is_finite()
                or not trade.funding_cash_pnl.is_finite()
                or trade.entry_fees < ZERO
                or trade.exit_fees < ZERO
                or abs(
                    trade.gross_realized_pnl
                    - trade.entry_fees
                    - trade.exit_fees
                    + trade.funding_cash_pnl
                    - trade.net_pnl
                ) > CASH_TOLERANCE
            ):
                raise MakerEntryCostBudgetError(
                    "original trade cash fails reconciliation"
                )
            # Compute dollars from the fee-ratio division last. Using a
            # rounded repeating discount fraction (e.g. two thirds) can
            # create false sub-cent residuals even for exact booked fees.
            fee_savings = (
                trade.entry_fees
                - (trade.entry_fees * maker_fee_rate / taker_fee_rate)
            )
            original_net += trade.net_pnl
            gross += trade.gross_realized_pnl
            entry_fees += trade.entry_fees
            exit_fees += trade.exit_fees
            funding += trade.funding_cash_pnl
            discount += fee_savings
            individual_same_fill_nets.append(trade.net_pnl + fee_savings)

        if (
            abs(gross - entry_fees - exit_fees + funding - original_net)
            > CASH_TOLERANCE
        ):
            raise MakerEntryCostBudgetError("cohort exact cost decomposition mismatch")

        same_fill_net = original_net + discount
        # These are adversarial STATIC NO-REPLACEMENT missed-trade probes,
        # NOT a prediction that real resting orders miss precisely winners.
        winning_contributions = sorted(
            (net for net in individual_same_fill_nets if net > ZERO),
            reverse=True,
        )
        def missed_winners(n: int) -> Decimal:
            return same_fill_net - sum(winning_contributions[:n], ZERO)

        entry_refund_fraction_to_zero = (
            str(max(-original_net, ZERO) / entry_fees)
            if entry_fees > ZERO
            else "0" if original_net >= ZERO else None
        )
        return {
            "schema": "maker-entry-original-closed-journal-cost-budget-v1",
            "closed_trades": len(items),
            "scope": "booked_closed_journal_only_not_whole_marked_paper_account",
            "original_booked_gross_usd": _cash_text(gross),
            "original_booked_entry_fees_usd": _cash_text(entry_fees),
            "original_booked_exit_fees_usd": _cash_text(exit_fees),
            "original_booked_funding_usd": _cash_text(funding),
            "original_booked_net_usd": _cash_text(original_net),
            "exact_entry_fee_discount_fraction": str(fee_discount_fraction),
            "entry_fee_refund_fraction_needed_for_zero": entry_refund_fraction_to_zero,
            "all_original_entries_same_fill_fee_only_saving_usd": _cash_text(discount),
            "all_original_entries_same_fill_net_usd": _cash_text(same_fill_net),
            "all_entry_fee_discount_still_nonpositive": same_fill_net <= ZERO,
            "additional_non_fee_gross_needed_to_reach_zero_usd": _cash_text(
                max(-same_fill_net, ZERO)
            ),
            "hypothetical_surplus_to_absorb_missed_winner_usd": _cash_text(
                max(same_fill_net, ZERO)
            ),
            "hypothetical_net_if_largest_positive_trade_missed_usd": _cash_text(
                missed_winners(1)
            ),
            "hypothetical_net_if_top_three_positive_trades_missed_usd": _cash_text(
                missed_winners(3)
            ),
            "positive_hypothetical_trade_contributions": len(winning_contributions),
            "original_tape_could_support_full_size_count_not_certified": (
                print_full_size_not_ruled_out
            ),
            "original_tape_rules_out_full_size_count": print_full_size_ruled_out,
            "original_tape_zero_crossing_qty_count": zero_possible_prints,
            "guaranteed_maker_fills": 0,
            "realized_maker_fee_savings_usd": None,
            "maker_strategy_whole_account_net_usd": None,
            "changed_entry_prices_modeled": False,
            "partial_fills_or_margin_reallocation_modeled": False,
            "original_market_source_externally_authenticated": False,
            "independent_paired_account_positive_edge_proven": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
        }
