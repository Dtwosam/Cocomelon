from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.strategy import Direction
from cocomelon.research.profit_lock_execution_shadow import (
    ProfitLockExecutionOutcome,
)
from cocomelon.research.prospective_breakeven_profit_lock import (
    RULE_ID as BREAKEVEN_RULE_ID,
)
from cocomelon.research.prospective_breakeven_profit_lock import (
    ProspectiveBreakevenProfitLockState,
)

ZERO: Final = Decimal("0")


class ProspectiveFullStackEntryExitError(RuntimeError):
    pass


def _required_int(raw: object, *, field: str) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ProspectiveFullStackEntryExitError(
            f"{field} must be an integer"
        )
    return raw


def _robustness(
    rows: tuple[
        tuple[TradeJournalEntry, Decimal, Decimal],
        ...,
    ],
) -> dict[str, object]:
    pnl_deltas = tuple(
        candidate_pnl - trade.net_pnl
        for trade, candidate_pnl, _candidate_r in rows
    )
    r_deltas = tuple(
        candidate_r - trade.net_r
        for trade, _candidate_pnl, candidate_r in rows
    )
    total_pnl = sum(pnl_deltas, ZERO)
    total_r = sum(r_deltas, ZERO)
    leave_trade_pnl = tuple(
        total_pnl - value for value in pnl_deltas
    )
    leave_trade_r = tuple(
        total_r - value for value in r_deltas
    )

    by_market_pnl: dict[str, Decimal] = {}
    by_market_r: dict[str, Decimal] = {}
    for (
        trade,
        candidate_pnl,
        candidate_r,
    ) in rows:
        market = trade.market.canonical
        by_market_pnl[market] = (
            by_market_pnl.get(market, ZERO)
            + candidate_pnl
            - trade.net_pnl
        )
        by_market_r[market] = (
            by_market_r.get(market, ZERO)
            + candidate_r
            - trade.net_r
        )
    leave_market_pnl = tuple(
        total_pnl - value for value in by_market_pnl.values()
    )
    leave_market_r = tuple(
        total_r - value for value in by_market_r.values()
    )

    return {
        "evaluated_trades": len(rows),
        "market_count": len(by_market_pnl),
        "delta_net_pnl": str(total_pnl),
        "delta_net_r": str(total_r),
        "leave_one_trade_out_min_delta_pnl": str(
            min(leave_trade_pnl, default=ZERO)
        ),
        "leave_one_trade_out_min_delta_r": str(
            min(leave_trade_r, default=ZERO)
        ),
        "positive_after_removing_any_one_trade": (
            len(rows) >= 2
            and min(leave_trade_pnl, default=ZERO) > ZERO
            and min(leave_trade_r, default=ZERO) > ZERO
        ),
        "leave_one_market_out_min_delta_pnl": str(
            min(leave_market_pnl, default=ZERO)
        ),
        "leave_one_market_out_min_delta_r": str(
            min(leave_market_r, default=ZERO)
        ),
        "positive_after_removing_any_one_market": (
            len(by_market_pnl) >= 2
            and min(leave_market_pnl, default=ZERO) > ZERO
            and min(leave_market_r, default=ZERO) > ZERO
        ),
    }


def _cohort_summary(
    rows: tuple[
        tuple[TradeJournalEntry, Decimal, Decimal],
        ...,
    ],
) -> dict[str, object]:
    actual_pnl = sum(
        (trade.net_pnl for trade, _pnl, _r in rows),
        ZERO,
    )
    actual_r = sum(
        (trade.net_r for trade, _pnl, _r in rows),
        ZERO,
    )
    candidate_pnl = sum(
        (pnl for _trade, pnl, _r in rows),
        ZERO,
    )
    candidate_r = sum(
        (net_r for _trade, _pnl, net_r in rows),
        ZERO,
    )
    return {
        "trades": len(rows),
        "actual_net_pnl": str(actual_pnl),
        "candidate_net_pnl": str(candidate_pnl),
        "delta_net_pnl": str(candidate_pnl - actual_pnl),
        "actual_net_r": str(actual_r),
        "candidate_net_r": str(candidate_r),
        "delta_net_r": str(candidate_r - actual_r),
    }



# A positive matched-trade screen is not a portfolio PnL backtest.
MIN_SCREEN_TRADES: Final = 40
MIN_SCREEN_DIRECTION_TRADES: Final = 10
MIN_SCREEN_MARKETS: Final = 4
MIN_SCREEN_ADMITTED_TRADES: Final = 20
MIN_SCREEN_BLOCKED_TRADES: Final = 5
SCREEN_TEMPORAL_BLOCKS: Final = 4
MIN_SCREEN_BLOCK_TRADES: Final = 10


def _full_stack_economic_screen(
    rows: tuple[tuple[TradeJournalEntry, Decimal, Decimal], ...],
    entry_rows: tuple[tuple[TradeJournalEntry, Decimal, Decimal], ...],
    *,
    integrity_clean: bool,
    entry_blocked: int,
    entry_admitted: int,
) -> dict[str, object]:
    # Exactly paired rows: blocked trade = zero contribution; admitted trade
    # = original entry for entry-only or independent fill-aware shadow exit.
    if len(rows) != len(entry_rows) or any(
        full[0].trade_id != entry[0].trade_id
        for full, entry in zip(rows, entry_rows, strict=True)
    ):
        raise ProspectiveFullStackEntryExitError(
            "full-stack economic screen has unpaired entry and exit rows"
        )
    ordered_pairs = tuple(sorted(
        zip(rows, entry_rows, strict=True),
        key=lambda pair: (
            pair[0][0].opened_at_ms,
            pair[0][0].closed_at_ms,
            pair[0][0].trade_id,
        ),
    ))
    actual_pnl = sum((full[0].net_pnl for full, _ in ordered_pairs), ZERO)
    actual_r = sum((full[0].net_r for full, _ in ordered_pairs), ZERO)
    full_pnl = sum((full[1] for full, _ in ordered_pairs), ZERO)
    full_r = sum((full[2] for full, _ in ordered_pairs), ZERO)
    entry_pnl = sum((entry[1] for _, entry in ordered_pairs), ZERO)
    entry_r = sum((entry[2] for _, entry in ordered_pairs), ZERO)

    rows_by_market: dict[str, list[
        tuple[tuple[TradeJournalEntry, Decimal, Decimal],
              tuple[TradeJournalEntry, Decimal, Decimal]]
    ]] = {}
    for pair in ordered_pairs:
        rows_by_market.setdefault(
            pair[0][0].market.canonical, []
        ).append(pair)
    by_market = tuple(
        tuple(value) for value in rows_by_market.values()
    )

    def leave_one_out_min(
        cohorts: tuple[tuple[
            tuple[tuple[TradeJournalEntry, Decimal, Decimal],
                  tuple[TradeJournalEntry, Decimal, Decimal]], ...
        ], ...],
        *,
        pnl: bool,
    ) -> tuple[Decimal | None, Decimal | None]:
        if len(cohorts) < 2:
            return None, None
        full = full_pnl if pnl else full_r
        delta = full - (actual_pnl if pnl else actual_r)
        index = 1 if pnl else 2
        removed_full = tuple(
            sum((pair[0][index] for pair in group), ZERO)
            for group in cohorts
        )
        removed_actual = tuple(
            sum((
                pair[0][0].net_pnl if pnl else pair[0][0].net_r
                for pair in group
            ), ZERO)
            for group in cohorts
        )
        return (
            min(full - amount for amount in removed_full),
            min(
                delta - (candidate - actual)
                for candidate, actual in zip(
                    removed_full, removed_actual, strict=True
                )
            ),
        )

    trade_cohorts = tuple((pair,) for pair in ordered_pairs)
    full_trade_min, delta_trade_min = leave_one_out_min(
        trade_cohorts, pnl=True
    )
    full_trade_r_min, delta_trade_r_min = leave_one_out_min(
        trade_cohorts, pnl=False
    )
    market_cohorts = by_market
    full_market_min, delta_market_min = leave_one_out_min(
        market_cohorts, pnl=True
    )
    full_market_r_min, delta_market_r_min = leave_one_out_min(
        market_cohorts, pnl=False
    )

    blocks: list[dict[str, object]] = []
    for block_index in range(SCREEN_TEMPORAL_BLOCKS):
        low = len(ordered_pairs) * block_index // SCREEN_TEMPORAL_BLOCKS
        high = len(ordered_pairs) * (block_index + 1) // SCREEN_TEMPORAL_BLOCKS
        portion = ordered_pairs[low:high]
        actual = sum((pair[0][0].net_pnl for pair in portion), ZERO)
        candidate = sum((pair[0][1] for pair in portion), ZERO)
        entry = sum((pair[1][1] for pair in portion), ZERO)
        actual_net_r = sum((pair[0][0].net_r for pair in portion), ZERO)
        candidate_net_r = sum((pair[0][2] for pair in portion), ZERO)
        passed = (
            len(portion) >= MIN_SCREEN_BLOCK_TRADES
            and candidate > ZERO
            and candidate_net_r > ZERO
            and candidate > actual
            and candidate_net_r > actual_net_r
        )
        blocks.append({
            "block_index": block_index,
            "evaluated_trades": len(portion),
            "first_opened_at_ms": (
                None if not portion else portion[0][0][0].opened_at_ms
            ),
            "last_opened_at_ms": (
                None if not portion else portion[-1][0][0].opened_at_ms
            ),
            "actual_net_pnl": str(actual),
            "entry_only_net_pnl": str(entry),
            "full_stack_net_pnl": str(candidate),
            "full_stack_delta_net_pnl": str(candidate - actual),
            "exit_incremental_net_pnl": str(candidate - entry),
            "passes_absolute_and_incremental": passed,
        })

    by_side = {
        side: {
            "evaluated_trades": len(cohort),
            "net_pnl": str(sum((row[1] for row in cohort), ZERO)),
            "net_r": str(sum((row[2] for row in cohort), ZERO)),
        }
        for side in ("long", "short")
        for cohort in (
            tuple(row for row in rows if row[0].direction.value == side),
        )
    }
    blocked_losers = sum(
        full[1] == ZERO and entry[1] == ZERO and full[0].net_pnl < ZERO
        for full, entry in ordered_pairs
    )
    blocked_winners = sum(
        full[1] == ZERO and entry[1] == ZERO and full[0].net_pnl > ZERO
        for full, entry in ordered_pairs
    )
    admitted_winners_preserved = sum(
        entry[1] > ZERO and full[1] > ZERO
        for full, entry in ordered_pairs
    )
    admitted_winners_lost = sum(
        entry[1] > ZERO and full[1] <= ZERO
        for full, entry in ordered_pairs
    )
    admitted_losers_recovered = sum(
        entry[1] <= ZERO and full[1] > ZERO
        for full, entry in ordered_pairs
    )

    sufficient = (
        len(rows) >= MIN_SCREEN_TRADES
        and len(by_market) >= MIN_SCREEN_MARKETS
        and all(
            cohort["evaluated_trades"] >= MIN_SCREEN_DIRECTION_TRADES
            for cohort in by_side.values()
        )
        and entry_admitted >= MIN_SCREEN_ADMITTED_TRADES
        and entry_blocked >= MIN_SCREEN_BLOCKED_TRADES
    )
    stable = all(
        block["passes_absolute_and_incremental"] is True
        for block in blocks
    )
    candidate_robust = all(
        value is not None and value > ZERO
        for value in (
            full_trade_min, full_trade_r_min,
            full_market_min, full_market_r_min,
        )
    )
    incremental_robust = all(
        value is not None and value > ZERO
        for value in (
            delta_trade_min, delta_trade_r_min,
            delta_market_min, delta_market_r_min,
        )
    )
    # This gate is diagnostic only: zeroed blocked trades omit replacement
    # entries, portfolio capacity, stop sequencing, and equity drawdown.
    passes = (
        integrity_clean
        and sufficient
        and full_pnl > ZERO
        and full_r > ZERO
        and full_pnl > actual_pnl
        and full_r > actual_r
        and stable
        and candidate_robust
        and incremental_robust
    )
    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "ready_for_review": False,
        "economic_screen_passes": passes,
        "portfolio_profitability_proven": False,
        "claim_scope": "matched_trade_contribution_only",
        "required_evaluated_trades": MIN_SCREEN_TRADES,
        "required_direction_trades": MIN_SCREEN_DIRECTION_TRADES,
        "required_markets": MIN_SCREEN_MARKETS,
        "required_admitted_trades": MIN_SCREEN_ADMITTED_TRADES,
        "required_blocked_trades": MIN_SCREEN_BLOCKED_TRADES,
        "minimum_temporal_block_trades": MIN_SCREEN_BLOCK_TRADES,
        "sample_sufficient": sufficient,
        "integrity_clean": integrity_clean,
        "absolute_candidate_profitable": full_pnl > ZERO and full_r > ZERO,
        "incremental_vs_actual_positive": (
            full_pnl > actual_pnl and full_r > actual_r
        ),
        "chronological_blocks_all_pass": stable,
        "candidate_leave_one_out_robust": candidate_robust,
        "incremental_leave_one_out_robust": incremental_robust,
        "evaluated_trades": len(rows),
        "observed_markets": len(by_market),
        "entry_blocked": entry_blocked,
        "entry_admitted": entry_admitted,
        "actual_net_pnl": str(actual_pnl),
        "entry_only_net_pnl": str(entry_pnl),
        "full_stack_net_pnl": str(full_pnl),
        "full_stack_delta_net_pnl": str(full_pnl - actual_pnl),
        "exit_incremental_net_pnl": str(full_pnl - entry_pnl),
        "blocked_losers": blocked_losers,
        "blocked_winners_forgone": blocked_winners,
        "admitted_winners_preserved": admitted_winners_preserved,
        "admitted_winners_lost_after_exit": admitted_winners_lost,
        "admitted_losers_recovered_after_exit": admitted_losers_recovered,
        "by_direction": by_side,
        "temporal_blocks": blocks,
        "leave_one_trade_min_candidate_pnl": (
            None if full_trade_min is None else str(full_trade_min)
        ),
        "leave_one_trade_min_candidate_r": (
            None if full_trade_r_min is None else str(full_trade_r_min)
        ),
        "leave_one_trade_min_delta_pnl": (
            None if delta_trade_min is None else str(delta_trade_min)
        ),
        "leave_one_trade_min_delta_r": (
            None if delta_trade_r_min is None else str(delta_trade_r_min)
        ),
        "leave_one_market_min_candidate_pnl": (
            None if full_market_min is None else str(full_market_min)
        ),
        "leave_one_market_min_candidate_r": (
            None if full_market_r_min is None else str(full_market_r_min)
        ),
        "leave_one_market_min_delta_pnl": (
            None if delta_market_min is None else str(delta_market_min)
        ),
        "leave_one_market_min_delta_r": (
            None if delta_market_r_min is None else str(delta_market_r_min)
        ),
        "warning": (
            "Do not treat positive matched-trade contributions as a "
            "profitable executable portfolio. Blocked positions have no "
            "replacement-entry, capacity reflow or drawdown simulation; "
            "forward fill-aware portfolio validation is required."
        ),
    }


def prospective_full_stack_entry_exit_summary(
    trades: Sequence[TradeJournalEntry],
    combined: Mapping[str, object],
    two_strike: Mapping[str, object],
    momentum: Mapping[str, object],
    execution_shadow_state: Mapping[str, object],
    breakeven_state: ProspectiveBreakevenProfitLockState,
) -> dict[str, object]:
    combined_start = _required_int(
        combined.get("started_at_ms"),
        field="combined started_at_ms",
    )
    two_start = _required_int(
        two_strike.get("started_at_ms"),
        field="two-strike started_at_ms",
    )
    momentum_start = _required_int(
        momentum.get("started_at_ms"),
        field="momentum started_at_ms",
    )
    overlap_start = max(
        combined_start,
        two_start,
        momentum_start,
        breakeven_state.started_at_ms,
    )

    combined_decisions = combined.get(
        "decision_block_reason_by_trade_id"
    )
    two_decisions = two_strike.get("decision_prior_strikes")
    momentum_details = momentum.get("decision_details")
    if not isinstance(combined_decisions, dict):
        raise ProspectiveFullStackEntryExitError(
            "combined decision map must be an object"
        )
    if not isinstance(two_decisions, dict):
        raise ProspectiveFullStackEntryExitError(
            "two-strike decision map must be an object"
        )
    if not isinstance(momentum_details, dict):
        raise ProspectiveFullStackEntryExitError(
            "momentum decision map must be an object"
        )

    raw_outcomes = execution_shadow_state.get("outcomes")
    if not isinstance(raw_outcomes, list):
        raise ProspectiveFullStackEntryExitError(
            "execution shadow outcomes must be a list"
        )
    outcomes = tuple(
        ProfitLockExecutionOutcome.from_payload(raw)
        for raw in raw_outcomes
    )
    selected = tuple(
        outcome
        for outcome in outcomes
        if outcome.rule_id == BREAKEVEN_RULE_ID
    )
    outcome_ids = tuple(outcome.trade_id for outcome in selected)
    if len(set(outcome_ids)) != len(outcome_ids):
        raise ProspectiveFullStackEntryExitError(
            "breakeven outcomes contain duplicate trade ids"
        )
    outcome_by_id = {
        outcome.trade_id: outcome for outcome in selected
    }

    prospective = tuple(
        sorted(
            (
                trade
                for trade in trades
                if trade.opened_at_ms >= overlap_start
            ),
            key=lambda trade: (
                trade.opened_at_ms,
                trade.closed_at_ms,
                trade.trade_id,
            ),
        )
    )
    trade_ids = tuple(trade.trade_id for trade in prospective)
    if len(set(trade_ids)) != len(trade_ids):
        raise ProspectiveFullStackEntryExitError(
            "prospective trades contain duplicate ids"
        )

    missing_combined = 0
    missing_two_strike = 0
    missing_momentum = 0
    entry_blocked = 0
    entry_admitted = 0
    missing_breakeven = 0
    unevaluable_breakeven = 0
    evaluated_rows: list[
        tuple[TradeJournalEntry, Decimal, Decimal]
    ] = []
    entry_only_rows: list[
        tuple[TradeJournalEntry, Decimal, Decimal]
    ] = []
    decision_by_trade_id: dict[str, dict[str, object]] = {}

    for trade in prospective:
        trade_id = trade.trade_id
        if trade_id not in combined_decisions:
            missing_combined += 1
            continue
        if trade_id not in two_decisions:
            missing_two_strike += 1
            continue
        if trade_id not in momentum_details:
            missing_momentum += 1
            continue

        combined_reason = combined_decisions[trade_id]
        if (
            combined_reason is not None
            and not isinstance(combined_reason, str)
        ):
            raise ProspectiveFullStackEntryExitError(
                "combined block reason must be a string or null"
            )
        prior_strikes = _required_int(
            two_decisions[trade_id],
            field="two-strike prior strikes",
        )
        detail = momentum_details[trade_id]
        if not isinstance(detail, dict):
            raise ProspectiveFullStackEntryExitError(
                "momentum decision detail must be an object"
            )
        momentum_decision = detail.get("decision")
        if momentum_decision not in {"ADMIT", "BLOCK"}:
            raise ProspectiveFullStackEntryExitError(
                "momentum decision must be ADMIT or BLOCK"
            )

        blocked = (
            combined_reason is not None
            or prior_strikes >= 2
            or momentum_decision == "BLOCK"
        )
        if blocked:
            entry_blocked += 1
            candidate_pnl = ZERO
            candidate_r = ZERO
            evaluated_rows.append(
                (trade, candidate_pnl, candidate_r)
            )
            entry_only_rows.append(
                (trade, candidate_pnl, candidate_r)
            )
            decision_by_trade_id[trade_id] = {
                "entry_decision": "BLOCK",
                "exit_evaluation": "NOT_APPLICABLE",
                "candidate_net_pnl": str(candidate_pnl),
                "candidate_net_r": str(candidate_r),
            }
            continue

        entry_admitted += 1
        outcome = outcome_by_id.get(trade_id)
        if outcome is None:
            missing_breakeven += 1
            decision_by_trade_id[trade_id] = {
                "entry_decision": "ADMIT",
                "exit_evaluation": "MISSING",
                "candidate_net_pnl": None,
                "candidate_net_r": None,
            }
            continue
        if (
            outcome.opening_plan_id != trade.opening_plan_id
            or outcome.market != trade.market.canonical
            or outcome.direction != trade.direction.value
            or outcome.actual_net_pnl != trade.net_pnl
            or outcome.actual_net_r != trade.net_r
        ):
            raise ProspectiveFullStackEntryExitError(
                "breakeven outcome journal drift"
            )
        if (
            outcome.candidate_net_pnl_estimate is None
            or outcome.candidate_net_r_estimate is None
        ):
            unevaluable_breakeven += 1
            decision_by_trade_id[trade_id] = {
                "entry_decision": "ADMIT",
                "exit_evaluation": "UNEVALUABLE",
                "candidate_net_pnl": None,
                "candidate_net_r": None,
            }
            continue

        candidate_pnl = outcome.candidate_net_pnl_estimate
        candidate_r = outcome.candidate_net_r_estimate
        evaluated_rows.append(
            (trade, candidate_pnl, candidate_r)
        )
        entry_only_rows.append(
            (trade, trade.net_pnl, trade.net_r)
        )
        decision_by_trade_id[trade_id] = {
            "entry_decision": "ADMIT",
            "exit_evaluation": "EVALUATED",
            "candidate_net_pnl": str(candidate_pnl),
            "candidate_net_r": str(candidate_r),
            "breakeven_activated": outcome.activated,
            "breakeven_triggered": outcome.triggered,
            "breakeven_source": outcome.candidate_source,
        }

    rows = tuple(evaluated_rows)
    entry_rows = tuple(entry_only_rows)
    actual_pnl = sum(
        (trade.net_pnl for trade, _pnl, _r in rows),
        ZERO,
    )
    actual_r = sum(
        (trade.net_r for trade, _pnl, _r in rows),
        ZERO,
    )
    entry_candidate_pnl = sum(
        (pnl for _trade, pnl, _r in entry_rows),
        ZERO,
    )
    entry_candidate_r = sum(
        (net_r for _trade, _pnl, net_r in entry_rows),
        ZERO,
    )
    full_candidate_pnl = sum(
        (pnl for _trade, pnl, _r in rows),
        ZERO,
    )
    full_candidate_r = sum(
        (net_r for _trade, _pnl, net_r in rows),
        ZERO,
    )

    by_direction = {
        direction.value: _cohort_summary(
            tuple(
                row
                for row in rows
                if row[0].direction is direction
            )
        )
        for direction in (Direction.LONG, Direction.SHORT)
    }
    by_market = {
        market: _cohort_summary(
            tuple(
                row
                for row in rows
                if row[0].market.canonical == market
            )
        )
        for market in sorted(
            {row[0].market.canonical for row in rows}
        )
    }

    integrity_clean = (
        missing_combined == 0
        and missing_two_strike == 0
        and missing_momentum == 0
        and missing_breakeven == 0
        and unevaluable_breakeven == 0
    )
    economic_screen = _full_stack_economic_screen(
        rows,
        entry_rows,
        integrity_clean=integrity_clean,
        entry_blocked=entry_blocked,
        entry_admitted=entry_admitted,
    )

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "descriptive_only": True,
        "changes_readiness_gate": False,
        "claim_scope": "matched_trade_contribution_only",
        "portfolio_counterfactual": False,
        "replacement_trades_modeled": False,
        "overlap_started_at_ms": overlap_start,
        "combined_started_at_ms": combined_start,
        "two_strike_started_at_ms": two_start,
        "momentum_started_at_ms": momentum_start,
        "breakeven_started_at_ms": breakeven_state.started_at_ms,
        "closed_trades_since_overlap_start": len(prospective),
        "economically_evaluated_trades": len(rows),
        "entry_blocked_trades": entry_blocked,
        "entry_admitted_trades": entry_admitted,
        "missing_combined_decisions": missing_combined,
        "missing_two_strike_decisions": missing_two_strike,
        "missing_momentum_decisions": missing_momentum,
        "missing_breakeven_outcomes": missing_breakeven,
        "unevaluable_breakeven_outcomes": unevaluable_breakeven,
        "integrity_clean": integrity_clean,
        "economic_viability_screen": economic_screen,
        "actual_net_pnl": str(actual_pnl),
        "actual_net_r": str(actual_r),
        "entry_stack_candidate_net_pnl": str(entry_candidate_pnl),
        "entry_stack_candidate_net_r": str(entry_candidate_r),
        "entry_stack_delta_net_pnl": str(
            entry_candidate_pnl - actual_pnl
        ),
        "entry_stack_delta_net_r": str(
            entry_candidate_r - actual_r
        ),
        "full_stack_candidate_net_pnl": str(full_candidate_pnl),
        "full_stack_candidate_net_r": str(full_candidate_r),
        "full_stack_delta_net_pnl": str(
            full_candidate_pnl - actual_pnl
        ),
        "full_stack_delta_net_r": str(
            full_candidate_r - actual_r
        ),
        "breakeven_incremental_net_pnl": str(
            full_candidate_pnl - entry_candidate_pnl
        ),
        "breakeven_incremental_net_r": str(
            full_candidate_r - entry_candidate_r
        ),
        "robustness": _robustness(rows),
        "by_direction": by_direction,
        "by_market": by_market,
        "decision_by_trade_id": {
            trade_id: decision_by_trade_id[trade_id]
            for trade_id in sorted(decision_by_trade_id)
        },
    }
