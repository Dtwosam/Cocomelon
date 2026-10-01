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
        "integrity_clean": (
            missing_combined == 0
            and missing_two_strike == 0
            and missing_momentum == 0
            and missing_breakeven == 0
            and unevaluable_breakeven == 0
        ),
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
