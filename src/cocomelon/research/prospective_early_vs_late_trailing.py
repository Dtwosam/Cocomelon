from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.research.profit_lock_execution_shadow import (
    ProfitLockExecutionOutcome,
)
from cocomelon.research.prospective_profit_target_one_r_comparison import (
    EARLY_RESERVED_TRAILING_RULE_ID,
    MIN_BLOCK_TRADES,
    MIN_DIRECTION_TRADES,
    MIN_MARKETS,
    MIN_PAIRED_TRADES,
    NET_RESERVED_TRAILING_RULE_ID,
    ProspectiveProfitTargetComparisonError,
    _verified_outcomes,
    _verify_trade_exit_cashflow,
)

ZERO: Final = Decimal("0")
BLOCKS: Final = 4


class EarlyVsLateTrailingError(RuntimeError):
    pass


def _valid_complete_exit(
    trade: TradeJournalEntry,
    outcome: ProfitLockExecutionOutcome,
) -> bool:
    if (
        outcome.opening_plan_id != trade.opening_plan_id
        or outcome.market != trade.market.canonical
        or outcome.direction != trade.direction.value
        or outcome.actual_net_pnl != trade.net_pnl
        or outcome.actual_net_r != trade.net_r
    ):
        raise EarlyVsLateTrailingError("exit observer and journal identity mismatch")
    _verify_trade_exit_cashflow(trade, outcome)
    if (
        outcome.candidate_net_pnl_estimate is None
        or outcome.candidate_net_r_estimate is None
    ):
        return False
    if not outcome.triggered:
        if outcome.candidate_source != "actual_close":
            raise EarlyVsLateTrailingError("untriggered exit cannot claim filled cashflow")
        if (
            outcome.candidate_net_pnl_estimate != trade.net_pnl
            or outcome.candidate_net_r_estimate != trade.net_r
        ):
            raise EarlyVsLateTrailingError("untriggered exit must equal original close")
        return True
    return (
        outcome.simulated_close_complete
        and outcome.candidate_source == "visible_book_ioc"
        and outcome.simulated_filled_quantity == trade.filled_quantity
        and outcome.simulated_average_exit_price is not None
        and outcome.attempt_count > 0
        and outcome.trigger_timestamp_ms is not None
        and outcome.completion_timestamp_ms is not None
        and trade.opened_at_ms
        <= outcome.trigger_timestamp_ms
        <= outcome.completion_timestamp_ms
        <= trade.closed_at_ms
    )


def _economics(
    rows: Sequence[
        tuple[TradeJournalEntry, ProfitLockExecutionOutcome, ProfitLockExecutionOutcome]
    ],
) -> dict[str, object]:
    actual = sum((trade.net_pnl for trade, _, _ in rows), ZERO)
    early = sum((e.candidate_net_pnl_estimate for _, e, _ in rows
                 if e.candidate_net_pnl_estimate is not None), ZERO)
    late = sum((l.candidate_net_pnl_estimate for _, _, l in rows
                if l.candidate_net_pnl_estimate is not None), ZERO)
    early_r = sum((e.candidate_net_r_estimate for _, e, _ in rows
                   if e.candidate_net_r_estimate is not None), ZERO)
    late_r = sum((l.candidate_net_r_estimate for _, _, l in rows
                  if l.candidate_net_r_estimate is not None), ZERO)
    return {
        "matched_trades": len(rows),
        "original_net_pnl": str(actual),
        "early_net_pnl": str(early),
        "late_net_pnl": str(late),
        "early_vs_late_net_pnl": str(early - late),
        "early_vs_original_net_pnl": str(early - actual),
        "late_vs_original_net_pnl": str(late - actual),
        "early_net_r": str(early_r),
        "late_net_r": str(late_r),
        "early_vs_late_net_r": str(early_r - late_r),
        "early_is_profitable": bool(rows) and early > ZERO and early_r > ZERO,
        "early_beats_late_and_original": (
            bool(rows)
            and early > late
            and early > actual
            and early_r > late_r
        ),
        "original_winners_reduced": sum(
            trade.net_pnl > ZERO
            and e.candidate_net_pnl_estimate is not None
            and e.candidate_net_pnl_estimate < trade.net_pnl
            for trade, e, _ in rows
        ),
        "original_losers_rescued": sum(
            trade.net_pnl <= ZERO
            and e.candidate_net_pnl_estimate is not None
            and e.candidate_net_pnl_estimate > ZERO
            for trade, e, _ in rows
        ),
        "late_winners_reduced": sum(
            l.candidate_net_pnl_estimate is not None
            and l.candidate_net_pnl_estimate > ZERO
            and e.candidate_net_pnl_estimate is not None
            and e.candidate_net_pnl_estimate < l.candidate_net_pnl_estimate
            for _, e, l in rows
        ),
    }


def prospective_early_vs_late_trailing(
    trades: Sequence[TradeJournalEntry],
    early_shadow_state: object,
    late_shadow_state: object,
) -> dict[str, object]:
    """Compare *identical future trades* under two precommitted IOC exit rules.

    Not an independent full-account trial. Exits that fail IOC execution
    cannot receive favorable mark-to-market profits.
    """
    early_start, early_outcomes, early_meta = _verified_outcomes(
        early_shadow_state, rule_id=EARLY_RESERVED_TRAILING_RULE_ID
    )
    late_start, late_outcomes, late_meta = _verified_outcomes(
        late_shadow_state, rule_id=NET_RESERVED_TRAILING_RULE_ID
    )
    if early_meta["execution_config"] != late_meta["execution_config"]:
        raise EarlyVsLateTrailingError("paired exit cost/configuration drift")
    start = max(early_start, late_start)
    all_trades = tuple(trades)
    trade_by_id = {trade.trade_id: trade for trade in all_trades}
    if len(trade_by_id) != len(all_trades):
        raise EarlyVsLateTrailingError("duplicate journal trade ID")

    forward = tuple(sorted(
        (t for t in all_trades if t.opened_at_ms >= start),
        key=lambda t: (t.opened_at_ms, t.closed_at_ms, t.trade_id),
    ))
    forward_ids = {t.trade_id for t in forward}
    missing_early = sorted(forward_ids - early_outcomes.keys())
    missing_late = sorted(forward_ids - late_outcomes.keys())
    orphan_early = sorted(early_outcomes.keys() - trade_by_id.keys())
    orphan_late = sorted(late_outcomes.keys() - trade_by_id.keys())
    incomplete: list[str] = []
    matched: list[
        tuple[TradeJournalEntry, ProfitLockExecutionOutcome, ProfitLockExecutionOutcome]
    ] = []
    for trade in forward:
        early = early_outcomes.get(trade.trade_id)
        late = late_outcomes.get(trade.trade_id)
        if early is None or late is None:
            continue
        if not (_valid_complete_exit(trade, early) and _valid_complete_exit(trade, late)):
            incomplete.append(trade.trade_id)
            continue
        matched.append((trade, early, late))

    total = _economics(matched)
    side = {
        direction: _economics(tuple(
            item for item in matched if item[0].direction.value == direction
        ))
        for direction in ("long", "short")
    }
    markets = sorted({item[0].market.canonical for item in matched})
    blocks: list[dict[str, object]] = []
    for idx in range(BLOCKS):
        segment = matched[len(matched) * idx // BLOCKS:len(matched) * (idx + 1) // BLOCKS]
        block = _economics(segment)
        blocks.append({
            "block": idx + 1,
            **block,
            "passes": (
                len(segment) >= MIN_BLOCK_TRADES
                and block["early_is_profitable"] is True
                and block["early_beats_late_and_original"] is True
            ),
        })
    leave_market_out = {
        market: _economics(tuple(
            item for item in matched if item[0].market.canonical != market
        ))
        for market in markets
    }
    largest = (
        None if not matched else max(
            matched,
            key=lambda p: (
                p[1].candidate_net_pnl_estimate or ZERO,
                p[0].trade_id,
            ),
        )[0].trade_id
    )
    leave_best_out = _economics(tuple(
        item for item in matched if item[0].trade_id != largest
    ))
    invalid_counters = {
        name: (early_meta[name], late_meta[name])
        for name in ("lineage_mismatch_closed_trades", "orphaned_restored_positions")
    }
    integrity_clean = (
        not missing_early and not missing_late
        and not orphan_early and not orphan_late and not incomplete
        and all(early_count == 0 and late_count == 0
                for early_count, late_count in invalid_counters.values())
    )
    sample_complete = (
        len(matched) >= MIN_PAIRED_TRADES
        and len(markets) >= MIN_MARKETS
        and all(
            side[direction]["matched_trades"] >= MIN_DIRECTION_TRADES
            for direction in ("long", "short")
        )
        and sum(e.triggered for _, e, _ in matched) >= 10
        and sum(l.triggered for _, _, l in matched) >= 5
    )
    robust = (
        bool(markets)
        and leave_best_out["early_is_profitable"] is True
        and leave_best_out["early_beats_late_and_original"] is True
        and all(
            outcome["early_is_profitable"] is True
            and outcome["early_beats_late_and_original"] is True
            for outcome in leave_market_out.values()
        )
    )
    economic_screen = (
        integrity_clean and sample_complete and robust
        and total["early_is_profitable"] is True
        and total["early_beats_late_and_original"] is True
        and all(
            v["early_is_profitable"] is True
            and v["early_beats_late_and_original"] is True
            for v in side.values()
        )
        and all(b["passes"] is True for b in blocks)
    )
    return {
        "definition": "frozen_plus_0_5r_early_vs_plus_1r_late_visible_book_ioc",
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_strategy": False,
        "changes_risk_limits": False,
        "ready_for_review": False,
        "independent_portfolio_trial": False,
        "candidate": EARLY_RESERVED_TRAILING_RULE_ID,
        "comparator": NET_RESERVED_TRAILING_RULE_ID,
        "common_scoring_start_ms": start,
        "future_original_closed_trades": len(forward),
        "matched_trade_count": len(matched),
        "matched_trade_ids": [t.trade_id for t, _, _ in matched],
        "missing_early_trade_ids": missing_early,
        "missing_late_trade_ids": missing_late,
        "orphan_early_trade_ids": orphan_early,
        "orphan_late_trade_ids": orphan_late,
        "incomplete_ioc_trade_ids": incomplete,
        "observer_integrity_counters": invalid_counters,
        "integrity_clean": integrity_clean,
        "sample_complete": sample_complete,
        "economic_screen_passes": economic_screen,
        "overall": total,
        "by_direction": side,
        "chronological_blocks": blocks,
        "by_market_leave_one_out": leave_market_out,
        "leave_best_early_winner_out": leave_best_out,
        "reason_not_promotable": (
            "Per-trade exit counterfactuals do not reproduce changed capital "
            "availability, subsequent entries, and portfolio risk. Requires "
            "new independent prospective full-account paired trial."
        ),
    }
