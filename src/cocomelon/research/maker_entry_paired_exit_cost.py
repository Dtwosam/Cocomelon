"""After-entry exit-cost sensitivity on two independent PAPER cash accounts.

Not a complete prospective portfolio or real maker execution.
Hourly funding must be witnessed for EVERY crossed boundary, never inferred.
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
from cocomelon.domain.market import FundingRate
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.execution.accounting import (
    PaperAccountState,
    apply_funding_accrual,
    apply_opening_fills,
    apply_reduce_only_fills,
    empty_account,
    mark_to_market,
    roll_account_day,
)
from cocomelon.execution.funding import (
    FUNDING_INTERVAL_MS,
    FundingAccrual,
    reconcile_funding_boundary,
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


def _fund_one_lane(
    account: PaperAccountState,
    *,
    boundary_ms: int,
    oracle_ctx: StreamEvent,
    rate: FundingRate,
    config: PaperExecutionConfig,
) -> PaperAccountState:
    # A no-entry lane pays nothing, and a late-entry lane never inherits
    # a funding bill for a boundary it did not hold a position through.
    if not account.positions or account.positions[0].opened_at_ms >= boundary_ms:
        return account
    if len(account.positions) != 1:
        raise MakerEntryWitnessError("paired funding requires one open position")
    cash_event = reconcile_funding_boundary(
        account.positions[0],
        boundary_ms,
        oracle_ctx,
        rate,
        now_ms=rate.received_at_ms,
        config=config,
    )
    if not isinstance(cash_event, FundingAccrual):
        raise MakerEntryWitnessError(
            f"paired funding original source gap: {cash_event.reason}"
        )
    account = roll_account_day(account, rate.received_at_ms)
    return apply_funding_accrual(account, cash_event, rate.received_at_ms)


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
    original_funding_oracle: StreamEvent | None = None,
    original_funding_rate: FundingRate | None = None,
    original_hourly_funding: tuple[tuple[StreamEvent, FundingRate], ...] = (),
) -> dict[str, object]:
    """Pair an unchanged original exit *plan* with conditional maker entries.

    The exit plan must pre-exist the exit book, not be synthesized from later
    prices. This is a SINGLE original trade path, with no future signals,
    capital reallocation or multi-trade portfolio execution, and cannot certify profit.
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
    # Use actual PAPER IOC entry time, not signal time or a hindsight
    # rounded trade time. Every crossed source hour costs BOTH independent
    # cash lanes, including the baseline when a maker order never filled.
    baseline_opened_at = baseline.positions[0].opened_at_ms
    first_boundary = (
        (baseline_opened_at // FUNDING_INTERVAL_MS) + 1
    ) * FUNDING_INTERVAL_MS
    boundaries = range(first_boundary, exit_at_ms + 1, FUNDING_INTERVAL_MS)
    # apply_opening_fills aggregates conditional maker prints into one
    # position whose opened_at_ms is the LAST fill. If some quantity was
    # already open before a boundary and more fills arrived afterwards,
    # that timestamp would erase funding owed/earned by the earlier lot.
    # A genuine lot-by-lot chronology/accounting engine is still missing:
    # reject the uncostable path rather than silently charge zero.
    if conditional_fills and boundaries:
        first_maker_fill_ms = min(fill.timestamp_ms for fill in conditional_fills)
        last_maker_fill_ms = max(fill.timestamp_ms for fill in conditional_fills)
        if any(
            first_maker_fill_ms < boundary_ms <= last_maker_fill_ms
            for boundary_ms in boundaries
        ):
            raise MakerEntryWitnessError(
                "paired maker fills straddle funding boundary; "
                "lot-level original funding accounting required"
            )
    # Legacy one-boundary input remains valid. The explicit tuple is required
    # for multi-hour original positions; never mix the two evidence formats.
    if type(original_hourly_funding) is not tuple:
        raise MakerEntryWitnessError("paired funding witness must be a tuple")
    if original_hourly_funding:
        if original_funding_oracle is not None or original_funding_rate is not None:
            raise MakerEntryWitnessError("paired funding evidence formats conflict")
        funding_rows = original_hourly_funding
    elif original_funding_oracle is not None or original_funding_rate is not None:
        if original_funding_oracle is None or original_funding_rate is None:
            raise MakerEntryWitnessError(
                "paired funding boundary lacks complete original evidence"
            )
        funding_rows = ((original_funding_oracle, original_funding_rate),)
    else:
        funding_rows = ()
    if not boundaries and funding_rows:
        raise MakerEntryWitnessError(
            "paired funding input without crossed original boundary"
        )
    if len(funding_rows) != len(boundaries):
        raise MakerEntryWitnessError(
            "paired funding boundary lacks complete original evidence"
        )

    seen_oracle_keys = {
        original_open_book.event_key,
        original_exit_book.event_key,
        original_after_exit_mark.event_key,
    }
    previous_rate_received_ms = -1
    previous_oracle_received_ms = -1
    oracle_keys: list[str] = []
    funding_received_ms: list[int] = []
    for boundary_ms, row in zip(boundaries, funding_rows, strict=True):
        if (
            type(row) is not tuple
            or len(row) != 2
            or not isinstance(row[0], StreamEvent)
            or not isinstance(row[1], FundingRate)
        ):
            raise MakerEntryWitnessError(
                "paired funding boundary lacks complete original evidence"
            )
        oracle_ctx, rate = row
        oracle_received_ms = _ms(oracle_ctx)
        if (
            oracle_ctx.source != original_open_book.source
            or oracle_ctx.market != original_opening_plan.market
            or oracle_ctx.event_key in seen_oracle_keys
            or oracle_received_ms <= previous_oracle_received_ms
            or rate.market != original_opening_plan.market
            or rate.source != "hyperliquid-mainnet-info"
            or not (
                boundary_ms <= rate.received_at_ms
                < boundary_ms + FUNDING_INTERVAL_MS
            )
            or rate.received_at_ms > exit_at_ms
            or rate.received_at_ms <= previous_rate_received_ms
        ):
            raise MakerEntryWitnessError(
                "paired funding boundary lacks complete original evidence"
            )
        # reconcile_funding_boundary checks oracle kind/age/time, exact
        # canonical hour, rate validity, and the position held at that hour.
        baseline = _fund_one_lane(
            baseline, boundary_ms=boundary_ms, oracle_ctx=oracle_ctx,
            rate=rate, config=execution_config,
        )
        candidate = _fund_one_lane(
            candidate, boundary_ms=boundary_ms, oracle_ctx=oracle_ctx,
            rate=rate, config=execution_config,
        )
        seen_oracle_keys.add(oracle_ctx.event_key)
        previous_oracle_received_ms = oracle_received_ms
        previous_rate_received_ms = rate.received_at_ms
        oracle_keys.append(oracle_ctx.event_key)
        funding_received_ms.append(rate.received_at_ms)
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
        "single_funding_boundary_costed": len(boundaries) == 1,
        "original_funding_boundary_ms": (
            first_boundary if len(boundaries) == 1 else None
        ),
        "original_funding_oracle_event_key": (
            oracle_keys[0] if len(oracle_keys) == 1 else None
        ),
        "original_hourly_funding_boundaries_ms": list(boundaries),
        "original_hourly_funding_oracle_event_keys": oracle_keys,
        "original_hourly_funding_received_at_ms": funding_received_ms,
        "complete_original_hourly_funding_boundaries_costed": len(boundaries),
        "multiple_hour_funding_boundaries_costed": len(boundaries) > 1,
        "funding_boundaries_and_multi_trade_capacity_modeled": False,
        "whole_account_profitable_edge_proven": False,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
    }
