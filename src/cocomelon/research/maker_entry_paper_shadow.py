"""Strict-through maker-first PAPER shadow: hypothetical entries, not venue fills.

No broker integration, no PaperFill/ExecutionAttempt objects, no account
mutations. Original plan risk limits are hard ceilings. Every modeled fill
is explicitly conditional on unobserved maker placement and queue priority.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_DOWN, Decimal, localcontext
from typing import Final

from cocomelon.domain.execution import (
    InstrumentExecutionSpec,
    OrderSide,
    PaperExecutionConfig,
    PaperOrderPlan,
)
from cocomelon.domain.stream import StreamEvent
from cocomelon.research.maker_entry_feasibility import (
    MAX_WAIT_MS,
    MakerEntryQuoteWitness,
    MakerEntryWitnessError,
    quote_research_only_maker_entry,
    review_original_trade_through,
)

ZERO: Final = Decimal("0")
ONE: Final = Decimal("1")
BPS: Final = Decimal("10000")
MAX_SOURCE_EVENTS: Final = 50_000
SCHEMA: Final = "strict-through-maker-entry-paper-shadow-v1"


def _finite_positive(value: object, field: str) -> Decimal:
    if type(value) is not Decimal or not value.is_finite() or value <= ZERO:
        raise MakerEntryWitnessError(f"maker shadow invalid {field}")
    return value


def _floor(value: Decimal, quantum: Decimal) -> Decimal:
    if value <= ZERO:
        return ZERO
    return value.quantize(quantum, rounding=ROUND_DOWN)


def _validate_envelope(
    witness: MakerEntryQuoteWitness,
    plan: PaperOrderPlan,
    instrument: InstrumentExecutionSpec,
    config: PaperExecutionConfig,
) -> tuple[Decimal, Decimal]:
    if (
        plan.reduce_only
        or witness.opening_plan_id != plan.plan_id
        or witness.market != plan.market.canonical
        or witness.side != plan.side.value
        or plan.execution_config_version != config.config_version
        or instrument.market != plan.market
        or instrument.metadata_received_at_ms != plan.instrument_metadata_received_at_ms
        or not instrument.execution_supported
        or witness.baseline_taker_fee_rate != config.taker_fee_rate
        or type(witness.quote_at_ms) is not int
        or witness.quote_at_ms < 0
        or plan.earliest_execution_ms > witness.quote_at_ms
        or witness.quote_at_ms < plan.created_at_ms
        or type(witness.expire_at_ms) is not int
        or not 0 < witness.expire_at_ms - witness.quote_at_ms <= MAX_WAIT_MS
    ):
        raise MakerEntryWitnessError(
            "maker shadow original plan or market lineage drift"
        )
    quote = _finite_positive(witness.quote_price, "price")
    requested = _finite_positive(witness.requested_quantity, "quantity")
    _finite_positive(witness.displayed_best_level_quantity, "queue depth")
    _finite_positive(config.taker_fee_rate, "taker fee")
    if (
        type(witness.hypothetical_maker_fee_rate) is not Decimal
        or not witness.hypothetical_maker_fee_rate.is_finite()
        or not ZERO < witness.hypothetical_maker_fee_rate < config.taker_fee_rate
        or requested != plan.requested_quantity
        or plan.approved_risk_amount_ceiling is None
        or plan.stop_price is None
        or plan.cost_buffer_fraction is None
    ):
        raise MakerEntryWitnessError("maker shadow fee, size or risk envelope invalid")
    # Never change the original IOC signal, risk, stop, notional or config.
    max_slippage = min(plan.max_slippage_bps, config.max_ioc_slippage_bps) / BPS
    if (
        plan.side is OrderSide.BUY
        and (
            quote > plan.execution_reference_price * (ONE + max_slippage)
            or quote <= plan.stop_price
        )
    ) or (
        plan.side is OrderSide.SELL
        and (
            quote < plan.execution_reference_price * (ONE - max_slippage)
            or quote >= plan.stop_price
        )
    ):
        raise MakerEntryWitnessError(
            "maker shadow quote violates original stop/slippage"
        )
    quantum = instrument.size_quantum
    if requested != _floor(requested, quantum):
        raise MakerEntryWitnessError("maker shadow quantity violates instrument step")
    minimum = max(instrument.minimum_order_notional, config.native_perp_min_notional)
    if quote * requested < minimum:
        raise MakerEntryWitnessError("maker shadow quote below venue min notional")
    if witness.book_event_key == "":
        raise MakerEntryWitnessError("maker shadow source book identity absent")
    with localcontext() as ctx:
        ctx.prec = 64
        buffer = plan.cost_buffer_fraction
        per_unit_risk = (
            quote * (ONE + buffer) - plan.stop_price
            if plan.side is OrderSide.BUY
            else plan.stop_price - quote * (ONE - buffer)
        )
        if not per_unit_risk.is_finite() or per_unit_risk <= ZERO:
            raise MakerEntryWitnessError("maker shadow nonpositive unit stop risk")
        allowed_qty = _floor(
            min(
                requested,
                plan.approved_notional_ceiling / quote,
                plan.approved_risk_amount_ceiling / per_unit_risk,
            ),
            quantum,
        )
        if allowed_qty <= ZERO or quote * allowed_qty < minimum:
            raise MakerEntryWitnessError(
                "maker shadow risk budgets permit no venue-sized order"
            )
        return allowed_qty, per_unit_risk


def simulate_strict_through_maker_entry(
    witness: MakerEntryQuoteWitness,
    *,
    original_plan: PaperOrderPlan,
    original_book: StreamEvent,
    instrument: InstrumentExecutionSpec,
    execution_config: PaperExecutionConfig,
    original_events: Sequence[StreamEvent],
    observation_end_ms: int,
    source_integrity_passed: bool,
) -> dict[str, object]:
    """Conservative simplified FIFO candidate, not matching-engine evidence.

    One visible best-level queue is put ahead of the hypothetical entry.
    At-touch prints can exhaust queue ahead but NEVER trigger maker fills.
    Only strictly THROUGH prints can create modeled maker quantities.
    Original order and all events are immutable; no taker fallback or exits.
    """
    if len(original_events) > MAX_SOURCE_EVENTS:
        raise MakerEntryWitnessError("maker shadow original event budget exceeded")
    allowed, per_unit_risk = _validate_envelope(
        witness, original_plan, instrument, execution_config
    )
    # Independently reconstruct the quote from the supplied original L2.
    # A stale, wrong-side or forged quote/queue/fee cannot drive paper fills.
    rebuilt = quote_research_only_maker_entry(
        original_plan=original_plan,
        original_book=original_book,
        execution=execution_config,
        maker_fee_rate=witness.hypothetical_maker_fee_rate,
        quote_at_ms=witness.quote_at_ms,
        wait_ms=witness.expire_at_ms - witness.quote_at_ms,
    )
    if witness != rebuilt:
        raise MakerEntryWitnessError(
            "maker shadow original book/witness lineage mismatch"
        )
    # First reuse original strict all-market/clock/expiry/duplicates validator.
    review = review_original_trade_through(
        witness,
        original_events=original_events,
        observation_end_ms=observation_end_ms,
        source_integrity_passed=source_integrity_passed,
    )
    queue_remaining = witness.displayed_best_level_quantity
    modelled_qty = ZERO
    modelled_fee = ZERO
    modelled_notional = ZERO
    leftover_fractional_volume = ZERO
    at_touch_prints = 0
    through_prints = 0
    modelled_events: list[dict[str, object]] = []
    quantum = instrument.size_quantum

    with localcontext() as ctx:
        ctx.prec = 64
        for event in original_events:
            received = int(event.receive_time.timestamp() * 1000)
            if (
                event.exchange_time_ms is not None
                and event.exchange_time_ms > received
            ):
                raise MakerEntryWitnessError(
                    "maker shadow original exchange/receipt clock reversed"
                )
            if received <= witness.quote_at_ms or received > witness.expire_at_ms:
                continue
            aggressor = event.payload.get("side")
            price = event.payload.get("price")
            volume = event.payload.get("size")
            if (
                aggressor not in {"A", "B"}
                or type(price) is not Decimal
                or type(volume) is not Decimal
                or not price.is_finite()
                or not volume.is_finite()
                or price <= ZERO
                or volume <= ZERO
            ):
                raise MakerEntryWitnessError("maker shadow malformed trade print")
            if (
                aggressor != ("A" if witness.side == "buy" else "B")
            ):
                continue
            touch = price == witness.quote_price
            through = (
                price < witness.quote_price
                if witness.side == "buy"
                else price > witness.quote_price
            )
            if not touch and not through:
                continue
            if touch:
                at_touch_prints += 1
            else:
                through_prints += 1
            consumed_queue = min(queue_remaining, volume)
            queue_remaining -= consumed_queue
            # To avoid awarding unproved at-touch executions, ALL residual
            # touch volume is discarded. Through volume alone can be modeled.
            if not through or modelled_qty >= allowed:
                continue
            eligible = volume - consumed_queue
            leftover_fractional_volume += eligible
            fill = _floor(
                min(leftover_fractional_volume, allowed - modelled_qty),
                quantum,
            )
            if fill <= ZERO:
                continue
            # Do not carry volume once the candidate's maximum size is filled.
            leftover_fractional_volume -= fill
            fee = fill * witness.quote_price * witness.hypothetical_maker_fee_rate
            modelled_events.append({
                "original_trade_event_key": event.event_key,
                "received_at_ms": received,
                "conditional_fill_quantity": str(fill),
                "conditional_fill_price": str(witness.quote_price),
                "conditional_entry_fee_usd": str(fee),
                "venue_acknowledged": False,
            })
            modelled_qty += fill
            modelled_fee += fee
            modelled_notional += fill * witness.quote_price
        return {
            "schema": SCHEMA,
            "original_plan_id": original_plan.plan_id,
            "market": original_plan.market.canonical,
            "side": original_plan.side.value,
            "original_source_rows": len(original_events),
            "original_trade_through_receipt": review["schema"],
            "quote_at_ms": witness.quote_at_ms,
            "expired_at_ms": witness.expire_at_ms,
            "strictly_through_only": True,
            "visible_queue_ahead_multiplier": "1",
            "initial_visible_queue_ahead_quantity": str(
                witness.displayed_best_level_quantity
            ),
            "remaining_assumed_queue_ahead_quantity": str(queue_remaining),
            "at_touch_trade_prints": at_touch_prints,
            "strictly_through_trade_prints": through_prints,
            "original_requested_quantity": str(original_plan.requested_quantity),
            "original_risk_capped_max_quantity": str(allowed),
            "original_per_unit_stop_risk_usd": str(per_unit_risk),
            "conditional_modelled_entry_quantity": str(modelled_qty),
            "conditional_modelled_unfilled_quantity": str(
                original_plan.requested_quantity - modelled_qty
            ),
            "conditional_modelled_entry_notional_usd": str(modelled_notional),
            "conditional_modelled_entry_fee_usd": str(modelled_fee),
            "conditional_modelled_trade_events": modelled_events,
            "modelled_entry_status": (
                "no_fill" if modelled_qty == ZERO
                else "full" if modelled_qty == original_plan.requested_quantity
                else "partial"
            ),
            "no_automatic_taker_fallback": True,
            "modelled_position_exits_or_funding": False,
            "maker_order_submitted_or_confirmed_by_venue": False,
            "guaranteed_real_entry_fill_quantity": "0",
            "realized_fee_savings_usd": None,
            "whole_account_after_cost_pnl_usd": None,
            "independent_original_source_authenticated": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
        }
