from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from decimal import Decimal
from typing import Final, cast

from cocomelon.research.prospective_full_stack_reflow_exact_ledger import (
    validate_full_stack_reflow_exact_ledger,
)

ZERO: Final = Decimal("0")
MIN_SELECTED_OPTIONS: Final = 20
MIN_SELECTED_PER_DIRECTION: Final = 5
MIN_SELECTED_MARKETS: Final = 4
TEMPORAL_BLOCKS: Final = 4
MIN_BLOCK_OPTIONS: Final = 5
FROZEN_CALENDAR_WEEK_MS: Final = 7 * 24 * 60 * 60 * 1000


class FullStackReflowCapacityReviewError(RuntimeError):
    pass


def _decimal(row: dict[str, object], field: str) -> Decimal:
    return Decimal(cast(str, row[field]))


def _economics(rows: Sequence[dict[str, object]]) -> dict[str, object]:
    total_pnl = sum((_decimal(row, "exact_realized_pnl") for row in rows), ZERO)
    total_return = sum(
        (_decimal(row, "exact_realized_return_fraction") for row in rows),
        ZERO,
    )
    return {
        "exact_options": len(rows),
        "net_pnl": str(total_pnl),
        "net_normalized_return_sum": str(total_return),
        "positive": len(rows) > 0 and total_pnl > ZERO and total_return > ZERO,
    }



def _fixed_calendar_opening_windows(
    selected: tuple[dict[str, object], ...],
    *,
    anchor_ms: int,
) -> tuple[dict[str, object], ...]:
    """Compare fixed entry-time windows, not moving completed-trade quartiles.

    This terminal exact-exit ledger has NO independently verified
    observation-end or live open-position census. Never label the windows
    fully matured or treat them as a capital-constrained paired account.
    """
    windows: dict[int, list[dict[str, object]]] = {}
    for row in selected:
        index = (
            cast(int, row["entry_attempt_timestamp_ms"]) - anchor_ms
        ) // FROZEN_CALENDAR_WEEK_MS
        windows.setdefault(index, []).append(row)
    output: list[dict[str, object]] = []
    for index in sorted(set(windows).union({0, 1})):
        rows = tuple(windows.get(index, []))
        economics = _economics(rows)
        start_ms = anchor_ms + index * FROZEN_CALENDAR_WEEK_MS
        output.append({
            "opening_week_index": index,
            "entry_attempt_ms_ge": start_ms,
            "entry_attempt_ms_lt": start_ms + FROZEN_CALENDAR_WEEK_MS,
            "selected_exact_one_slot_options": len(rows),
            "selected_fixed_horizon_economics": economics,
            "arithmetic_sample_and_sign_positive": (
                len(rows) >= MIN_BLOCK_OPTIONS
                and economics["positive"] is True
            ),
            "original_source_observation_end_verified": False,
            "original_open_exposure_cleared_for_week": False,
            "mature_complete_calendar_week_certified": False,
            "full_account_paired_comparison_certified": False,
            "promotion_authority": False,
        })
    if (
        sum((w["selected_exact_one_slot_options"] for w in output), 0)
        != len(selected)
        or sum((
            Decimal(cast(dict[str, object],
                         w["selected_fixed_horizon_economics"])["net_pnl"])
            for w in output
        ), ZERO) != sum((
            _decimal(row, "exact_realized_pnl") for row in selected
        ), ZERO)
        or sum((
            Decimal(cast(dict[str, object],
                         w["selected_fixed_horizon_economics"])[
                         "net_normalized_return_sum"])
            for w in output
        ), ZERO) != sum((
            _decimal(row, "exact_realized_return_fraction")
            for row in selected
        ), ZERO)
    ):
        raise FullStackReflowCapacityReviewError(
            "fixed calendar entry windows do not reconcile one-slot economics"
        )
    return tuple(output)


def _horizon_review(
    rows: tuple[dict[str, object], ...],
    *,
    horizon_ms: int,
    source_pending: int,
    overlap_started_at_ms: int,
) -> dict[str, object]:
    if any(row["horizon_ms"] != horizon_ms for row in rows):
        raise FullStackReflowCapacityReviewError(
            "horizon comparison must not include a different exit horizon"
        )
    # Do not choose whichever of several candidate releases turns out to
    # have the best realized exit. An ambiguous opportunity contributes
    # nothing to the conservative one-position experiment.
    counts = Counter(
        cast(str, row["opportunity_id"]) for row in rows
    )
    ambiguous_ids = {
        opportunity_id
        for opportunity_id, count in counts.items()
        if count != 1
    }
    eligible = tuple(
        sorted(
            (
                row
                for row in rows
                if row["opportunity_id"] not in ambiguous_ids
            ),
            key=lambda row: (
                cast(int, row["entry_attempt_timestamp_ms"]),
                cast(int, row["opportunity_timestamp_ms"]),
                cast(str, row["option_id"]),
            ),
        )
    )
    selected: list[dict[str, object]] = []
    invalid_clock = 0
    overlap_excluded = 0
    capacity_available_at_ms = 0
    for row in eligible:
        opened = cast(int, row["opportunity_timestamp_ms"])
        entered = cast(int, row["entry_attempt_timestamp_ms"])
        scheduled_end = opened + horizon_ms
        # These are conservative scheduled windows, NOT verified actual
        # position closing timestamps. A late fill is never presumed.
        if entered < opened or entered >= scheduled_end:
            invalid_clock += 1
            continue
        if entered < capacity_available_at_ms:
            overlap_excluded += 1
            continue
        selected.append(row)
        capacity_available_at_ms = scheduled_end

    chosen = tuple(selected)
    pre_campaign_entries = sum(
        cast(int, row["entry_attempt_timestamp_ms"])
        < overlap_started_at_ms
        for row in chosen
    )
    fixed_windows = _fixed_calendar_opening_windows(
        chosen, anchor_ms=overlap_started_at_ms,
    )
    directions = {
        direction: _economics(tuple(
            row for row in chosen
            if row["opportunity_direction"] == direction
        ))
        for direction in ("long", "short")
    }
    markets = {
        cast(str, row["opportunity_market"])
        for row in chosen
    }
    pnl = sum((_decimal(row, "exact_realized_pnl") for row in chosen), ZERO)
    normalized = sum(
        (_decimal(row, "exact_realized_return_fraction") for row in chosen),
        ZERO,
    )
    trade_leave_out = (
        len(chosen) >= 2
        and all(
            pnl - _decimal(row, "exact_realized_pnl") > ZERO
            and normalized
            - _decimal(row, "exact_realized_return_fraction") > ZERO
            for row in chosen
        )
    )
    market_leave_out = (
        len(markets) >= 2
        and all(
            pnl - sum((
                _decimal(row, "exact_realized_pnl")
                for row in chosen if row["opportunity_market"] == market
            ), ZERO) > ZERO
            and normalized - sum((
                _decimal(row, "exact_realized_return_fraction")
                for row in chosen if row["opportunity_market"] == market
            ), ZERO) > ZERO
            for market in markets
        )
    )
    blocks: list[dict[str, object]] = []
    for block_index in range(TEMPORAL_BLOCKS):
        low = len(chosen) * block_index // TEMPORAL_BLOCKS
        high = len(chosen) * (block_index + 1) // TEMPORAL_BLOCKS
        block = chosen[low:high]
        economics = _economics(block)
        blocks.append({
            "index": block_index,
            "start_entry_timestamp_ms": (
                None if not block else block[0]["entry_attempt_timestamp_ms"]
            ),
            "end_entry_timestamp_ms": (
                None if not block else block[-1]["entry_attempt_timestamp_ms"]
            ),
            **economics,
            "passes": (
                len(block) >= MIN_BLOCK_OPTIONS
                and economics["positive"] is True
            ),
        })

    sample_complete = (
        len(chosen) >= MIN_SELECTED_OPTIONS
        and len(markets) >= MIN_SELECTED_MARKETS
        and all(
            cast(int, value["exact_options"])
            >= MIN_SELECTED_PER_DIRECTION
            for value in directions.values()
        )
    )
    structural_clean = (
        not ambiguous_ids
        and invalid_clock == 0
        and pre_campaign_entries == 0
        and source_pending == 0
    )
    both_directions_profitable = all(
        value["positive"] is True for value in directions.values()
    )
    chronologically_profitable = all(block["passes"] for block in blocks)
    screen = (
        structural_clean
        and sample_complete
        and pnl > ZERO
        and normalized > ZERO
        and both_directions_profitable
        and chronologically_profitable
        and trade_leave_out
        and market_leave_out
    )
    return {
        "horizon_ms": horizon_ms,
        "source_exact_options": len(rows),
        "source_unique_opportunities": len(counts),
        "source_pending_option_horizons": source_pending,
        "ambiguous_opportunity_count": len(ambiguous_ids),
        "ambiguous_opportunity_option_rows": sum(
            counts[opportunity_id] for opportunity_id in ambiguous_ids
        ),
        "invalid_entry_window_rows": invalid_clock,
        "pre_campaign_selected_entry_rows": pre_campaign_entries,
        "skipped_for_one_position_capacity": overlap_excluded,
        "selected_exact_options": len(chosen),
        "selected_distinct_markets": len(markets),
        "selected_option_ids": [
            cast(str, row["option_id"]) for row in chosen
        ],
        "raw_exact_opportunity_economics": _economics(rows),
        "one_slot_selected_economics": _economics(chosen),
        "by_direction": directions,
        "chronological_blocks": blocks,
        "count_quartiles_move_as_new_closes_arrive": True,
        "count_quartiles_are_not_fixed_temporal_validation": True,
        "fixed_calendar_week_ms": FROZEN_CALENDAR_WEEK_MS,
        "fixed_calendar_entry_week_windows": fixed_windows,
        "first_two_frozen_weeks_sampled_and_arithmetically_positive": (
            all(
                item["arithmetic_sample_and_sign_positive"] is True
                for item in fixed_windows
                if item["opening_week_index"] in (0, 1)
            )
        ),
        "calendar_week_observation_maturity_verified": False,
        "fixed_calendar_temporal_stability_validated": False,
        "source_structurally_complete": structural_clean,
        "sample_complete": sample_complete,
        "both_directions_profitable": both_directions_profitable,
        "chronologically_profitable": chronologically_profitable,
        "positive_after_leave_one_option": trade_leave_out,
        "positive_after_leave_one_market": market_leave_out,
        "economic_screen_passes": screen,
        "ready_for_review": False,
        "portfolio_profitability_proven": False,
    }


def review_full_stack_reflow_capacity(
    raw_ledger: object,
) -> dict[str, object]:
    """Review exact replacements without selecting the best horizon or PnL."""
    ledger = validate_full_stack_reflow_exact_ledger(raw_ledger)
    raw_rows = ledger["rows"]
    if not isinstance(raw_rows, tuple):
        raise FullStackReflowCapacityReviewError(
            "validated exact rows must be canonical tuple"
        )
    rows = cast(tuple[dict[str, object], ...], raw_rows)
    horizons = ledger["horizons_ms"]
    pending = ledger["pending_option_horizons"]
    if not isinstance(horizons, list) or not all(
        type(item) is int and item > 0 for item in horizons
    ):
        raise FullStackReflowCapacityReviewError(
            "fixed horizon metadata is invalid"
        )
    if type(pending) is not int or pending < 0:
        raise FullStackReflowCapacityReviewError(
            "pending exit count is invalid"
        )
    anchor = ledger["overlap_started_at_ms"]
    if type(anchor) is not int or anchor < 0:
        raise FullStackReflowCapacityReviewError(
            "original campaign overlap anchor is invalid"
        )
    by_horizon = {
        str(horizon): _horizon_review(
            tuple(row for row in rows if row["horizon_ms"] == horizon),
            horizon_ms=horizon,
            source_pending=pending,
            overlap_started_at_ms=anchor,
        )
        for horizon in horizons
    }
    return {
        "schema_version": 1,
        "source_ledger_sha256": ledger["ledger_sha256"],
        "source_rows_sha256": ledger["rows_sha256"],
        "source_row_count": ledger["row_count"],
        "original_campaign_overlap_started_at_ms": anchor,
        "fixed_calendar_blocks_use_immutable_campaign_anchor": True,
        "research_only": True,
        "descriptive_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "portfolio_profitability_proven": False,
        "ready_for_review": False,
        "cross_horizon_economics_aggregated": False,
        "horizon_chosen_by_future_pnl": False,
        "maximum_simultaneous_replacement_positions": 1,
        "capacity_window_model": (
            "entry_attempt_to_opportunity_timestamp_plus_fixed_horizon"
        ),
        "by_horizon": by_horizon,
        "warning": (
            "A deterministic one-slot subset of completed exact IOC "
            "options is not a runnable account portfolio. Unfilled "
            "opportunities, counterfactual skipped entry candidates, "
            "actual exit completion times, unverified calendar-window "
            "observation maturity, moving count quartiles, incumbent "
            "overlapping trades, "
            "available margin, correlation buckets and drawdown still "
            "require prospective account-level replication. Neither "
            "the raw option sum nor the one-slot subset authorizes "
            "execution, profit claims or promotion."
        ),
    }
