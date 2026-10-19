"""Queue-ahead sensitivity for *possible* post-only entry fills.

All conclusions are conditional stress scenarios: original trade prints are
not matching-engine acknowledgements, and the hypothetical order did not
join the exchange queue. No accounting or position mutation is possible.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal, localcontext
from typing import Final

from cocomelon.domain.stream import StreamEvent
from cocomelon.research.maker_entry_feasibility import (
    MakerEntryQuoteWitness,
    MakerEntryWitnessError,
    review_original_trade_through,
)

ZERO: Final = Decimal("0")
ONE: Final = Decimal("1")
QUEUE_AHEAD_MULTIPLIERS: Final = (
    ZERO,
    ONE,
    Decimal("2"),
)


def _positive(value: Decimal, name: str) -> None:
    if type(value) is not Decimal or not value.is_finite() or value <= ZERO:
        raise MakerEntryWitnessError(f"invalid original maker {name}")


def maker_entry_queue_ahead_sensitivity(
    witness: MakerEntryQuoteWitness,
    *,
    original_events: Sequence[StreamEvent],
    observation_end_ms: int,
    source_integrity_passed: bool,
) -> dict[str, object]:
    """Report queue-size scenarios, not certified or expected fills.

    In a frozen-book simplified FIFO model, prints at the quote first
    consume a hypothetical queue-ahead. Prints strictly through the quote
    add potential executable volume. Actual ahead cancellations, reorders,
    hidden size, fees, liquidity and price impact are all UNKNOWN.
    """
    if witness.side not in {"buy", "sell"}:
        raise MakerEntryWitnessError("invalid original maker side")
    for field in ("quote_price", "requested_quantity", "displayed_best_level_quantity"):
        _positive(getattr(witness, field), field)
    _positive(witness.baseline_taker_fee_rate, "taker fee")
    if (
        type(witness.hypothetical_maker_fee_rate) is not Decimal
        or not witness.hypothetical_maker_fee_rate.is_finite()
        or witness.hypothetical_maker_fee_rate < ZERO
        or witness.hypothetical_maker_fee_rate >= witness.baseline_taker_fee_rate
    ):
        raise MakerEntryWitnessError("invalid original maker fee")
    if (
        type(witness.quote_at_ms) is not int
        or type(witness.expire_at_ms) is not int
        or witness.quote_at_ms >= witness.expire_at_ms
    ):
        raise MakerEntryWitnessError("invalid original maker quote period")

    # Reuse strict receipt, clock, duplicate, original-market and expiry checks
    # before a single potential scenario is reported. A caller-provided clean
    # bool is not an independently authenticated venue-source certificate.
    crossing = review_original_trade_through(
        witness,
        original_events=original_events,
        observation_end_ms=observation_end_ms,
        source_integrity_passed=source_integrity_passed,
    )
    at_quote_qty = ZERO
    strictly_through_qty = ZERO
    at_quote_count = 0
    strictly_through_count = 0
    for event in original_events:
        ms = int(event.receive_time.timestamp() * 1000)
        if ms <= witness.quote_at_ms or ms > witness.expire_at_ms:
            continue
        if (
            event.exchange_time_ms is not None
            and event.exchange_time_ms > ms
        ):
            raise MakerEntryWitnessError(
                "maker trade exchange clock exceeds receipt clock"
            )
        side = event.payload["side"]
        # The upstream validated receipt already checks side/price/size.
        price = event.payload["price"]
        quantity = event.payload["size"]
        assert isinstance(side, str)
        assert isinstance(price, Decimal)
        assert isinstance(quantity, Decimal)
        opposite_aggressor = (
            side == "A" if witness.side == "buy" else side == "B"
        )
        if not opposite_aggressor:
            continue
        if price == witness.quote_price:
            at_quote_qty += quantity
            at_quote_count += 1
        elif (
            price < witness.quote_price
            if witness.side == "buy" else price > witness.quote_price
        ):
            strictly_through_qty += quantity
            strictly_through_count += 1

    with localcontext() as ctx:
        ctx.prec = 96
        scenarios: list[dict[str, object]] = []
        for multiplier in QUEUE_AHEAD_MULTIPLIERS:
            assumed_queue = multiplier * witness.displayed_best_level_quantity
            theoretical_at_quote_after_queue = max(
                ZERO, at_quote_qty - assumed_queue
            )
            # Scenario volume is NOT an unconditional upper bound on live
            # maker fills. Real queue cancellations can help; hidden size,
            # adverse selection and original market-impact can hurt.
            possible_qty = min(
                witness.requested_quantity,
                theoretical_at_quote_after_queue + strictly_through_qty,
            )
            nominal_fee_discount = (
                possible_qty
                * witness.quote_price
                * (
                    witness.baseline_taker_fee_rate
                    - witness.hypothetical_maker_fee_rate
                )
            )
            scenarios.append({
                "initial_visible_queue_ahead_multiple": str(multiplier),
                "hypothetical_queue_ahead_quantity": str(assumed_queue),
                "conditional_possible_quantity": str(possible_qty),
                "conditional_single_entry_fee_discount_usd": str(
                    nominal_fee_discount.normalize()
                ),
                "full_requested_size_possible_in_scenario": (
                    possible_qty >= witness.requested_quantity
                ),
                "research_only": True,
                "fill_certified": False,
                "promotion_authority": False,
            })

    return {
        "schema": "maker-entry-queue-ahead-sensitivity-v1",
        "opening_plan_id": witness.opening_plan_id,
        "market": witness.market,
        "side": witness.side,
        "quote_at_ms": witness.quote_at_ms,
        "expire_at_ms": witness.expire_at_ms,
        "initial_visible_quantity_at_quote": str(
            witness.displayed_best_level_quantity
        ),
        "opposite_aggressor_at_quote_prints": at_quote_count,
        "opposite_aggressor_strictly_through_prints": strictly_through_count,
        "at_quote_print_quantity": str(at_quote_qty),
        "strictly_through_print_quantity": str(strictly_through_qty),
        "original_simple_crossing_upper_bound": crossing[
            "possible_entry_fill_quantity_upper_bound"
        ],
        "queue_ahead_stress_scenarios": scenarios,
        "queue_cancellations_and_hidden_liquidity_observed": False,
        "maker_quote_actually_resting": False,
        "guaranteed_filled_quantity": "0",
        "realized_maker_fee_savings_usd": None,
        "maker_candidate_after_cost_equity_usd": None,
        "original_source_independently_authenticated": False,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "warning": (
            "Displayed queue-ahead stress is a conditional scenario, not "
            "a venue-order fill, probability, unbiased upper/lower bound, "
            "booked fee saving or profit. The original no-order tape can "
            "differ from a venue tape after posting a real order."
        ),
    }
