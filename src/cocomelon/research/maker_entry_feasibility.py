"""Research-only post-only (ALO) entry feasibility from original PAPER observations.

A best-bid/ask resting quote is not a fill. Trade-through observations only
bound *possible* executed quantity, never prove queue priority, that a paper
quote actually rested, or positive after-cost PnL. No orders are submitted.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from cocomelon.domain.execution import (
    OrderSide,
    PaperExecutionConfig,
    PaperOrderPlan,
)
from cocomelon.domain.stream import StreamEvent, StreamKind

ZERO: Final = Decimal("0")
MAX_TAPE_EVENTS: Final = 50_000
MAX_WAIT_MS: Final = 300_000


class MakerEntryWitnessError(ValueError):
    pass


def _received_ms(event: StreamEvent) -> int:
    return int(event.receive_time.timestamp() * 1000)


def _positive_decimal(value: object, name: str) -> Decimal:
    if type(value) is not Decimal or not value.is_finite() or value <= ZERO:
        raise MakerEntryWitnessError(f"{name} must be a positive Decimal")
    return value


def _first_level(raw: object, name: str) -> tuple[Decimal, Decimal]:
    if (
        not isinstance(raw, (tuple, list))
        or not raw
        or not isinstance(raw[0], Mapping)
    ):
        raise MakerEntryWitnessError(f"{name} book level absent")
    level = raw[0]
    return (
        _positive_decimal(level.get("px"), f"{name} price"),
        _positive_decimal(level.get("sz"), f"{name} size"),
    )


@dataclass(frozen=True, slots=True)
class MakerEntryQuoteWitness:
    opening_plan_id: str
    market: str
    side: str
    quote_price: Decimal
    requested_quantity: Decimal
    displayed_best_level_quantity: Decimal
    quote_at_ms: int
    expire_at_ms: int
    baseline_taker_fee_rate: Decimal
    hypothetical_maker_fee_rate: Decimal
    fee_savings_if_entire_entry_filled_same_notional: Decimal
    book_event_key: str

    def payload(self) -> dict[str, object]:
        return {
            "opening_plan_id": self.opening_plan_id,
            "market": self.market,
            "side": self.side,
            "quote_price": str(self.quote_price),
            "requested_quantity": str(self.requested_quantity),
            "displayed_best_level_quantity": str(self.displayed_best_level_quantity),
            "quote_at_ms": self.quote_at_ms,
            "expire_at_ms": self.expire_at_ms,
            "baseline_taker_fee_rate": str(self.baseline_taker_fee_rate),
            "hypothetical_maker_fee_rate": str(self.hypothetical_maker_fee_rate),
            "fee_savings_if_entire_entry_filled_same_notional": str(
                self.fee_savings_if_entire_entry_filled_same_notional
            ),
            "book_event_key": self.book_event_key,
            "resting_order_submitted": False,
            "maker_fill_certified": False,
            "execution_authority": False,
            "promotion_authority": False,
        }


def quote_research_only_maker_entry(
    *,
    original_plan: PaperOrderPlan,
    original_book: StreamEvent,
    execution: PaperExecutionConfig,
    maker_fee_rate: Decimal,
    quote_at_ms: int,
    wait_ms: int = 60_000,
) -> MakerEntryQuoteWitness:
    """Quote at the captured touch, with no artificial maker fill."""
    if original_plan.reduce_only or original_book.kind is not StreamKind.L2_BOOK:
        raise MakerEntryWitnessError("maker research needs opening plan and L2")
    if (
        original_plan.market != original_book.market
        or original_plan.execution_config_version != execution.config_version
    ):
        raise MakerEntryWitnessError("original book/plan/config lineage mismatch")
    if (
        type(quote_at_ms) is not int
        or quote_at_ms < original_plan.earliest_execution_ms
        or type(wait_ms) is not int
        or not 0 < wait_ms <= MAX_WAIT_MS
    ):
        raise MakerEntryWitnessError("quote time or bounded wait invalid")
    book_ms = _received_ms(original_book)
    if not 0 <= quote_at_ms - book_ms <= execution.max_book_age_ms:
        raise MakerEntryWitnessError("missing, stale or future original book")
    if (
        original_book.exchange_time_ms is not None
        and original_book.exchange_time_ms > quote_at_ms
    ):
        raise MakerEntryWitnessError("future exchange book cannot price quote")
    rate = _positive_decimal(maker_fee_rate, "maker fee rate")
    if rate >= execution.taker_fee_rate:
        raise MakerEntryWitnessError("maker rate must save fee versus actual taker")
    bid_px, bid_qty = _first_level(original_book.payload.get("bids"), "bid")
    ask_px, ask_qty = _first_level(original_book.payload.get("asks"), "ask")
    if bid_px >= ask_px:
        raise MakerEntryWitnessError("crossed or locked original L2")
    price, level_qty = (
        (bid_px, bid_qty)
        if original_plan.side is OrderSide.BUY
        else (ask_px, ask_qty)
    )
    quantity = _positive_decimal(original_plan.requested_quantity, "plan size")
    savings = quantity * price * (execution.taker_fee_rate - rate)
    return MakerEntryQuoteWitness(
        opening_plan_id=original_plan.plan_id,
        market=original_plan.market.canonical,
        side=original_plan.side.value,
        quote_price=price,
        requested_quantity=quantity,
        displayed_best_level_quantity=level_qty,
        quote_at_ms=quote_at_ms,
        expire_at_ms=quote_at_ms + wait_ms,
        baseline_taker_fee_rate=execution.taker_fee_rate,
        hypothetical_maker_fee_rate=rate,
        fee_savings_if_entire_entry_filled_same_notional=savings,
        book_event_key=original_book.event_key,
    )


def review_original_trade_through(
    witness: MakerEntryQuoteWitness,
    *,
    original_events: Sequence[StreamEvent],
    observation_end_ms: int,
    source_integrity_passed: bool,
) -> dict[str, object]:
    """A conservative *possible* trade-through bound, never a maker fill.

    Prints after our hypothetical bid/ask are not queue-verified. Even
    positive crossing volume may all belong to other resting orders.
    """
    if source_integrity_passed is not True:
        raise MakerEntryWitnessError("original stream gaps or clock not clean")
    if (
        type(observation_end_ms) is not int
        or observation_end_ms < witness.expire_at_ms
    ):
        raise MakerEntryWitnessError("maker quote not fully observed to expiry")
    if len(original_events) > MAX_TAPE_EVENTS:
        raise MakerEntryWitnessError("maker original event tape exceeds bound")
    seen: set[str] = set()
    previous_received = witness.quote_at_ms
    possible_volume = ZERO
    crossing_count = 0
    for event in original_events:
        if (
            event.kind is not StreamKind.TRADE
            or event.market.canonical != witness.market
        ):
            raise MakerEntryWitnessError("maker quote tape needs exact-market trades")
        received_ms = _received_ms(event)
        if (
            event.event_key in seen
            or received_ms < previous_received
            or received_ms > observation_end_ms
        ):
            raise MakerEntryWitnessError("duplicate, reversed or future original tape")
        seen.add(event.event_key)
        previous_received = received_ms
        # Equal-millisecond original ordering is unverified here. Never
        # count an ambiguous event as evidence of a post-quote crossing.
        if received_ms <= witness.quote_at_ms or received_ms > witness.expire_at_ms:
            continue
        side = event.payload.get("side")
        if type(side) is not str or side not in {"A", "B"}:
            raise MakerEntryWitnessError("original aggressor direction missing")
        price = _positive_decimal(event.payload.get("price"), "trade price")
        size = _positive_decimal(event.payload.get("size"), "trade size")
        crossed = (
            side == "A" and price <= witness.quote_price
            if witness.side == "buy"
            else side == "B" and price >= witness.quote_price
        )
        if crossed:
            possible_volume += size
            crossing_count += 1
    possible_qty = min(witness.requested_quantity, possible_volume)
    return {
        "schema": "original-post-only-entry-feasibility-v1",
        "quote": witness.payload(),
        "original_trade_rows_examined": len(original_events),
        "crossing_original_trade_count": crossing_count,
        "crossing_print_quantity": str(possible_volume),
        "possible_entry_fill_quantity_upper_bound": str(possible_qty),
        "guaranteed_entry_fill_quantity": "0",
        "quote_fully_observed_to_expiry": True,
        "maker_fill_certified": False,
        "maker_fee_savings_realized_usd": None,
        "candidate_after_cost_pnl_usd": None,
        "missed_fill_and_adverse_selection_risk_unmeasured": True,
        "source_external_authentication_certified": False,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
    }
