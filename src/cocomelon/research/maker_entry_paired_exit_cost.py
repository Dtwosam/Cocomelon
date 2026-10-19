"""After-entry exit-cost sensitivity on two independent PAPER cash accounts.

Not a complete prospective portfolio, funding ledger or real maker execution.
One original predetermined exit decision is applied to both conditional lanes;
no cherry-picked deletion of losing baseline trades or invented maker fills.
"""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from cocomelon.domain.execution import (
    ExecutionResult,
    InstrumentExecutionSpec,
    OrderSide,
    PaperExecutionConfig,
    PaperOrderPlan,
)
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.execution.accounting import (
    PaperAccountState,
    apply_opening_fills,
    apply_reduce_only_fills,
    empty_account,
    mark_to_market,
)
from cocomelon.execution.ioc import simulate_ioc
from cocomelon.research.maker_entry_feasibility import (
    MakerEntryQuoteWitness,
    MakerEntryWitnessError,
)
from cocomelon.research.maker_entry_paired_mark import (
    _account_summary,
    _conditional_paper_fills,
    _ms,
)
from cocomelon.research.maker_entry_paper_shadow import (
    simulate_strict_through_maker_entry,
)

ZERO = Decimal("0")


def _exit_lane(
    account: PaperAccountState,
    exit_plan: PaperOrderPlan,
    exit_book: StreamEvent,
    instrument: InstrumentExecutionSpec,
    config: PaperExecutionConfig,
    exit_at_ms: int,
) -> tuple[PaperAccountState, str, Decimal]:
    if not account.positions:
        return account, "no_entry", ZERO
    if len(account.positions) != 1:
        raise MakerEntryWitnessError("paired exit expected one source position")
    position = account.positions[0]
    lane_plan = replace(exit_plan, requested_quantity=position.quantity)
    if (
        lane_plan.market != position.market
        or (lane_plan.side is OrderSide.BUY) == (
            position.side.value == "long"
        )
    ):
        raise MakerEntryWitnessError("paired exit reduces wrong source position")
    sim = simulate_ioc(
        lane_plan, exit_book, instrument, config,
        attempt_timestamp_ms=exit_at_ms,
    )
    if sim.attempt.result is ExecutionResult.REJECTED:
        raise MakerEntryWitnessError(
            "paired exit IOC rejected; never treat as free closure"
        )
    if sim.fills:
        account = apply_reduce_only_fills(
            account, exit_plan.market, sim.fills, exit_at_ms
        )
    return account, sim.attempt.result.value, sim.attempt.filled_quantity


def paired_maker_vs_ioc_exit_cost_probe(
    *,
    original_opening_plan: PaperOrderPlan,
    original_exit_plan: PaperOrderPlan,
    original_open_book: StreamEvent,
    original_trades_to_maker_expiry: tuple[StreamEvent, ...],
    original_exit_book: StreamEvent,
    original_after_exit_mark: StreamEvent,
    maker_witness: MakerEntryQuoteWitness,
    instrument: InstrumentExecutionSpec,
    execution_config: PaperExecutionConfig,
    start_cash: Decimal,
    exit_at_ms: int,
    mark_at_ms: int,
    source_integrity_passed: bool,
) -> dict[str, object]:
    """Pair an unchanged original exit *plan* with conditional maker entries.

    The exit plan must pre-exist the exit book, not be synthesized from later
    prices. This is a SINGLE original trade path, with no future signals,
    capital reallocation or funding, and cannot certify whole-account profit.
    """
    if (
        type(start_cash) is not Decimal
        or not start_cash.is_finite()
        or start_cash <= ZERO
    ):
        raise MakerEntryWitnessError("paired exit original cash invalid")
    if source_integrity_passed is not True:
        raise MakerEntryWitnessError("paired exit original source failed")
    if (
        original_opening_plan.reduce_only
        or not original_exit_plan.reduce_only
        or original_exit_plan.market != original_opening_plan.market
        or original_exit_plan.side is original_opening_plan.side
        or instrument.market != original_opening_plan.market
        or original_exit_plan.execution_config_version
        != original_opening_plan.execution_config_version
        or original_exit_plan.instrument_metadata_received_at_ms
        != original_opening_plan.instrument_metadata_received_at_ms
        or original_exit_plan.earliest_execution_ms > exit_at_ms
        or original_exit_plan.created_at_ms < maker_witness.expire_at_ms
        or type(exit_at_ms) is not int
        or type(mark_at_ms) is not int
        or not maker_witness.expire_at_ms < exit_at_ms <= mark_at_ms
    ):
        raise MakerEntryWitnessError("paired exit plan/clock/source lineage invalid")
    if (
        original_open_book.kind is not StreamKind.L2_BOOK
        or original_exit_book.kind is not StreamKind.L2_BOOK
        or original_after_exit_mark.kind is not StreamKind.ACTIVE_ASSET_CTX
        or any(
            event.market != original_opening_plan.market
            or event.source != original_open_book.source
            for event in (original_exit_book, original_after_exit_mark)
        )
        or len({original_open_book.event_key, original_exit_book.event_key,
                original_after_exit_mark.event_key}) != 3
        or _ms(original_exit_book) != exit_at_ms
        or not exit_at_ms <= _ms(original_after_exit_mark) <= mark_at_ms
        or mark_at_ms - _ms(original_after_exit_mark)
        > execution_config.max_asset_ctx_age_ms
        or (
            original_exit_book.exchange_time_ms is not None
            and original_exit_book.exchange_time_ms > exit_at_ms
        )
        or (
            original_after_exit_mark.exchange_time_ms is not None
            and original_after_exit_mark.exchange_time_ms
            > _ms(original_after_exit_mark)
        )
    ):
        raise MakerEntryWitnessError("paired exit market book or mark untrusted")
    mark = original_after_exit_mark.payload.get("mark_px")
    if type(mark) is not Decimal or not mark.is_finite() or mark <= ZERO:
        raise MakerEntryWitnessError("paired exit mark invalid")
    if (
        original_exit_plan.requested_quantity
        != original_opening_plan.requested_quantity
    ):
        # No hindsight adaptation to original IOC size at this interface.
        # A different approved original exit plan needs its own later study.
        raise MakerEntryWitnessError("paired exit plan original amount drift")

    shadow = simulate_strict_through_maker_entry(
        maker_witness,
        original_plan=original_opening_plan,
        original_book=original_open_book,
        instrument=instrument,
        execution_config=execution_config,
        original_events=original_trades_to_maker_expiry,
        observation_end_ms=maker_witness.expire_at_ms,
        source_integrity_passed=True,
    )
    entry = simulate_ioc(
        original_opening_plan, original_open_book, instrument,
        execution_config,
        attempt_timestamp_ms=maker_witness.quote_at_ms,
    )
    if entry.attempt.result is ExecutionResult.REJECTED or not entry.fills:
        raise MakerEntryWitnessError("paired exit baseline opening not executable")
    baseline = apply_opening_fills(
        empty_account(start_cash, original_opening_plan.created_at_ms),
        original_opening_plan, entry.fills,
        venue_max_leverage=instrument.venue_max_leverage,
    )
    candidate = empty_account(start_cash, original_opening_plan.created_at_ms)
    conditional_fills = _conditional_paper_fills(
        shadow, original_opening_plan,
        maker_witness.hypothetical_maker_fee_rate,
    )
    if conditional_fills:
        candidate = apply_opening_fills(
            candidate, original_opening_plan, conditional_fills,
            venue_max_leverage=instrument.venue_max_leverage,
        )
    # Fail rather than silently retrofit a full original exit with less
    # original baseline quantity or an unknown earlier risk decision.
    if (
        len(baseline.positions) != 1
        or baseline.positions[0].quantity != original_exit_plan.requested_quantity
    ):
        raise MakerEntryWitnessError("paired exit baseline/plan size mismatch")
    baseline, baseline_status, baseline_exit_qty = _exit_lane(
        baseline, original_exit_plan, original_exit_book,
        instrument, execution_config, exit_at_ms,
    )
    candidate, maker_status, maker_exit_qty = _exit_lane(
        candidate, original_exit_plan, original_exit_book,
        instrument, execution_config, exit_at_ms,
    )
    marks = {original_opening_plan.market: mark}
    baseline = mark_to_market(
        baseline, marks, mark_at_ms,
        paper_max_gross_leverage=execution_config.paper_max_gross_leverage,
    )
    candidate = mark_to_market(
        candidate, marks, mark_at_ms,
        paper_max_gross_leverage=execution_config.paper_max_gross_leverage,
    )
    return {
        "schema": "paired-maker-vs-ioc-single-exit-cost-probe-v1",
        "original_opening_plan_id": original_opening_plan.plan_id,
        "original_exit_plan_id": original_exit_plan.plan_id,
        "original_exit_book_event_key": original_exit_book.event_key,
        "original_after_exit_mark_event_key": original_after_exit_mark.event_key,
        "baseline_ioc_exit_result": baseline_status,
        "conditional_maker_exit_result": maker_status,
        "baseline_ioc_exit_quantity": str(baseline_exit_qty),
        "conditional_maker_exit_quantity": str(maker_exit_qty),
        "baseline_account": _account_summary(baseline),
        "conditional_maker_account": _account_summary(candidate),
        "single_path_after_exit_marked_delta_usd": str(
            candidate.equity - baseline.equity
        ),
        "both_lanes_flat_after_original_exit": (
            not baseline.positions and not candidate.positions
        ),
        "original_source_independently_authenticated": False,
        "real_maker_fills_confirmed": False,
        "funding_boundaries_and_multi_trade_capacity_modeled": False,
        "whole_account_profitable_edge_proven": False,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
    }
