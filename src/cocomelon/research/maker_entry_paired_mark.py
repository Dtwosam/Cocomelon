"""Capital-matched isolated entry-mark PAPER accounts, never profit certification.

Replays an original approved IOC and a conditional strict-through maker
candidate into separate, fresh, in-memory PAPER ledgers. The candidate uses
transient clearly labeled hypothetical fills solely to reuse the canonical
accounting engine. The accounts are NOT durable, venue-confirmed, exit-complete
or independently source-authenticated and have no promotion authority.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Final

from cocomelon.domain.execution import (
    ExecutionResult,
    InstrumentExecutionSpec,
    PaperExecutionConfig,
    PaperFill,
    PaperOrderPlan,
)
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.execution.accounting import (
    PaperAccountState,
    apply_opening_fills,
    empty_account,
    mark_to_market,
)
from cocomelon.execution.ioc import simulate_ioc
from cocomelon.research.maker_entry_feasibility import (
    MakerEntryQuoteWitness,
    MakerEntryWitnessError,
)
from cocomelon.research.maker_entry_paper_shadow import (
    simulate_strict_through_maker_entry,
)

ZERO: Final = Decimal("0")
SCHEMA: Final = "paired-maker-vs-ioc-entry-mark-account-v1"
MAKER_ATTEMPT_PREFIX: Final = "RESEARCH-ONLY-CONDITIONAL-MAKER-NOT-VENUE"


def _ms(event: StreamEvent) -> int:
    return int(event.receive_time.timestamp() * 1000)


def _account_summary(account: PaperAccountState) -> dict[str, object]:
    return {
        "starting_cash_usd": str(account.starting_cash),
        "cash_usd": str(account.cash),
        "marked_equity_usd": str(account.equity),
        "marked_pnl_vs_start_usd": str(account.equity - account.starting_cash),
        "cumulative_fees_usd": str(account.cumulative_fees),
        "unrealized_pnl_usd": str(account.unrealized_pnl),
        "realized_gross_pnl_usd": str(account.realized_gross_pnl),
        "funding_usd": str(account.cumulative_funding),
        "position_count": len(account.positions),
        "position_quantity": (
            "0" if not account.positions else str(account.positions[0].quantity)
        ),
        "position_entry_price": (
            None if not account.positions
            else str(account.positions[0].average_entry_price)
        ),
        "accounting_library": "cocomelon.execution.accounting",
        "separately_funded_fresh_in_memory_paper_account": True,
    }


def _conditional_paper_fills(
    shadow: dict[str, object],
    original_plan: PaperOrderPlan,
    maker_rate: Decimal,
) -> tuple[PaperFill, ...]:
    """Never persist or return the constructed PaperFill objects.

    The shared PaperFill.taker_fee legacy name is a generic charged fee
    in the PAPER ledger; here its value is explicitly the maker model fee,
    not a claim that these are real exchange or IOC fills.
    """
    rows = shadow.get("conditional_modelled_trade_events")
    if not isinstance(rows, list):
        raise MakerEntryWitnessError("maker shadow conditional fill rows absent")
    result: list[PaperFill] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("venue_acknowledged") is not False:
            raise MakerEntryWitnessError("conditional maker fill has venue claim")
        if type(row.get("original_trade_event_key")) is not str:
            raise MakerEntryWitnessError("conditional maker trade identity absent")
        try:
            quantity = Decimal(str(row["conditional_fill_quantity"]))
            price = Decimal(str(row["conditional_fill_price"]))
            fee = Decimal(str(row["conditional_entry_fee_usd"]))
        except (KeyError, ValueError, ArithmeticError) as exc:
            raise MakerEntryWitnessError("conditional maker fill malformed") from exc
        if (
            not quantity.is_finite()
            or quantity <= ZERO
            or not price.is_finite()
            or price <= ZERO
            or not fee.is_finite()
            or fee != price * quantity * maker_rate
            or type(row.get("received_at_ms")) is not int
        ):
            raise MakerEntryWitnessError("conditional maker fee or fill malformed")
        result.append(PaperFill(
            plan_id=original_plan.plan_id,
            attempt_id=f"{MAKER_ATTEMPT_PREFIX}:{original_plan.plan_id}",
            market=original_plan.market,
            side=original_plan.side,
            price=price,
            quantity=quantity,
            notional=price * quantity,
            taker_fee=fee,
            source_event_key=(
                f"{MAKER_ATTEMPT_PREFIX}:{row['original_trade_event_key']}"
            ),
            timestamp_ms=row["received_at_ms"],
        ))
    return tuple(result)


def paired_maker_vs_ioc_entry_mark(
    *,
    original_plan: PaperOrderPlan,
    original_book: StreamEvent,
    original_trades: Sequence[StreamEvent],
    original_mark: StreamEvent,
    maker_witness: MakerEntryQuoteWitness,
    instrument: InstrumentExecutionSpec,
    execution_config: PaperExecutionConfig,
    start_cash: Decimal,
    mark_at_ms: int,
    source_integrity_passed: bool,
) -> dict[str, object]:
    """Return a marked ENTRY-PERIOD hypothetical pair with no exit/profit gate.

    Strictly require the SAME original plan, market book, trade tape and
    exact future mark for both lanes; independent initial cash and positions.
    No borrowed baseline fills in the conditional maker lane.
    """
    if type(start_cash) is not Decimal or not start_cash.is_finite() or start_cash <= ZERO:
        raise MakerEntryWitnessError("paired entry account start cash invalid")
    if source_integrity_passed is not True:
        raise MakerEntryWitnessError("paired entry original source not continuous")
    if (
        original_mark.kind is not StreamKind.ACTIVE_ASSET_CTX
        or original_mark.market != original_plan.market
        or original_mark.source != original_book.source
        or type(mark_at_ms) is not int
        or mark_at_ms < maker_witness.expire_at_ms
        or mark_at_ms < original_plan.created_at_ms
    ):
        raise MakerEntryWitnessError("paired entry mark market or chronology invalid")
    for event in original_trades:
        if event.source != original_book.source:
            raise MakerEntryWitnessError("paired entry original trade source mismatch")
    received = _ms(original_mark)
    if (
        received < maker_witness.expire_at_ms
        or not 0 <= mark_at_ms - received <= execution_config.max_asset_ctx_age_ms
        or (
            original_mark.exchange_time_ms is not None
            and original_mark.exchange_time_ms > received
        )
        or original_mark.event_key == original_book.event_key
        or any(original_mark.event_key == t.event_key for t in original_trades)
    ):
        raise MakerEntryWitnessError("paired entry original mark stale or future")
    mark = original_mark.payload.get("mark_px")
    if type(mark) is not Decimal or not mark.is_finite() or mark <= ZERO:
        raise MakerEntryWitnessError("paired entry original mark invalid")

    shadow = simulate_strict_through_maker_entry(
        maker_witness,
        original_plan=original_plan,
        original_book=original_book,
        instrument=instrument,
        execution_config=execution_config,
        original_events=original_trades,
        observation_end_ms=maker_witness.expire_at_ms,
        source_integrity_passed=True,
    )
    baseline_execution = simulate_ioc(
        original_plan,
        original_book,
        instrument,
        execution_config,
        attempt_timestamp_ms=maker_witness.quote_at_ms,
    )
    if baseline_execution.attempt.result is ExecutionResult.REJECTED:
        raise MakerEntryWitnessError(
            "original IOC entry rejected; comparison cannot silently continue"
        )
    # Never allow an original IOC lane that breaches approved risk/metadata.
    baseline = empty_account(start_cash, original_plan.created_at_ms)
    candidate = empty_account(start_cash, original_plan.created_at_ms)
    if baseline_execution.fills:
        baseline = apply_opening_fills(
            baseline, original_plan, baseline_execution.fills,
            venue_max_leverage=instrument.venue_max_leverage,
        )
    provisional_maker_fills = _conditional_paper_fills(
        shadow, original_plan, maker_witness.hypothetical_maker_fee_rate
    )
    if provisional_maker_fills:
        candidate = apply_opening_fills(
            candidate, original_plan, provisional_maker_fills,
            venue_max_leverage=instrument.venue_max_leverage,
        )
    # Both enter the same original marked time and canonical account math.
    marks = {original_plan.market: mark}
    baseline = mark_to_market(
        baseline, marks, mark_at_ms,
        paper_max_gross_leverage=execution_config.paper_max_gross_leverage,
    )
    candidate = mark_to_market(
        candidate, marks, mark_at_ms,
        paper_max_gross_leverage=execution_config.paper_max_gross_leverage,
    )
    if (
        baseline.starting_cash != candidate.starting_cash
        or baseline.updated_at_ms != candidate.updated_at_ms
        or baseline.cumulative_funding != ZERO
        or candidate.cumulative_funding != ZERO
    ):
        raise MakerEntryWitnessError("paired entry cash or mark parity broken")
    return {
        "schema": SCHEMA,
        "original_opening_plan_id": original_plan.plan_id,
        "original_book_event_key": original_book.event_key,
        "original_mark_event_key": original_mark.event_key,
        "original_mark_received_ms": received,
        "mark_at_ms": mark_at_ms,
        "original_mark_price": str(mark),
        "baseline_ioc_result": baseline_execution.attempt.result.value,
        "baseline_ioc_quantity": str(baseline_execution.attempt.filled_quantity),
        "maker_shadow_modelled_entry_status": shadow["modelled_entry_status"],
        "maker_shadow_modelled_entry_quantity": (
            shadow["conditional_modelled_entry_quantity"]
        ),
        "maker_original_venue_fills_confirmed": False,
        "baseline_original_ioc_execution_is_paper_simulated": True,
        "baseline_entry_account": _account_summary(baseline),
        "conditional_maker_entry_account": _account_summary(candidate),
        "conditional_entry_period_marked_delta_usd": str(
            candidate.equity - baseline.equity
        ),
        "both_lanes_open_positions_exit_complete": False,
        "candidate_trade_funding_and_exit_costs_modeled": False,
        "whole_account_positive_edge_verified": False,
        "independent_source_continuity_authenticated": False,
        "no_live_or_broker_calls": True,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
    }
