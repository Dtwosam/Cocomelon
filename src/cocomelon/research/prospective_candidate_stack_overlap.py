from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.strategy import Direction
from cocomelon.research.prospective_filter_robustness import (
    prospective_filter_robustness,
)

ZERO: Final = Decimal("0")


class ProspectiveCandidateStackOverlapError(RuntimeError):
    pass


def _summary(
    trades: tuple[TradeJournalEntry, ...],
) -> dict[str, object]:
    pnl = sum((trade.net_pnl for trade in trades), ZERO)
    net_r = sum((trade.net_r for trade in trades), ZERO)
    return {
        "trades": len(trades),
        "wins": sum(1 for trade in trades if trade.net_pnl > ZERO),
        "losses": sum(1 for trade in trades if trade.net_pnl < ZERO),
        "breakeven": sum(
            1 for trade in trades if trade.net_pnl == ZERO
        ),
        "net_pnl": str(pnl),
        "net_r": str(net_r),
        "mean_net_r": (
            None
            if not trades
            else str(net_r / Decimal(len(trades)))
        ),
    }


def _required_int(raw: object, *, field: str) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ProspectiveCandidateStackOverlapError(
            f"{field} must be an integer"
        )
    return raw


def prospective_candidate_stack_overlap_summary(
    trades: Sequence[TradeJournalEntry],
    combined: dict[str, object],
    two_strike: dict[str, object],
) -> dict[str, object]:
    combined_start = _required_int(
        combined.get("started_at_ms"),
        field="combined started_at_ms",
    )
    two_start = _required_int(
        two_strike.get("started_at_ms"),
        field="two-strike started_at_ms",
    )
    overlap_start = max(combined_start, two_start)

    combined_decisions = combined.get(
        "decision_block_reason_by_trade_id"
    )
    two_decisions = two_strike.get("decision_prior_strikes")
    if not isinstance(combined_decisions, dict):
        raise ProspectiveCandidateStackOverlapError(
            "combined decision map must be an object"
        )
    if not isinstance(two_decisions, dict):
        raise ProspectiveCandidateStackOverlapError(
            "two-strike decision map must be an object"
        )

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
    ids = tuple(trade.trade_id for trade in prospective)
    if len(set(ids)) != len(ids):
        raise ProspectiveCandidateStackOverlapError(
            "overlap trades contain duplicate ids"
        )

    buckets: dict[str, list[TradeJournalEntry]] = {
        "both_block": [],
        "combined_only": [],
        "two_strike_only": [],
        "neither_block": [],
    }
    missing_combined = 0
    missing_two_strike = 0

    for trade in prospective:
        trade_id = trade.trade_id
        if trade_id not in combined_decisions:
            missing_combined += 1
            continue
        if trade_id not in two_decisions:
            missing_two_strike += 1
            continue

        reason = combined_decisions[trade_id]
        if reason is not None and not isinstance(reason, str):
            raise ProspectiveCandidateStackOverlapError(
                "combined block reason must be a string or null"
            )
        prior_strikes = _required_int(
            two_decisions[trade_id],
            field="two-strike prior strikes",
        )
        combined_blocks = reason is not None
        two_blocks = prior_strikes >= 2
        if combined_blocks and two_blocks:
            bucket = "both_block"
        elif combined_blocks:
            bucket = "combined_only"
        elif two_blocks:
            bucket = "two_strike_only"
        else:
            bucket = "neither_block"
        buckets[bucket].append(trade)

    resolved = {
        name: tuple(values)
        for name, values in buckets.items()
    }
    matched = tuple(
        trade
        for name in (
            "both_block",
            "combined_only",
            "two_strike_only",
            "neither_block",
        )
        for trade in resolved[name]
    )
    actual_pnl = sum((trade.net_pnl for trade in matched), ZERO)
    actual_r = sum((trade.net_r for trade in matched), ZERO)

    combined_admitted = (
        resolved["two_strike_only"]
        + resolved["neither_block"]
    )
    two_admitted = (
        resolved["combined_only"]
        + resolved["neither_block"]
    )
    stack_admitted = resolved["neither_block"]

    combined_pnl = sum(
        (trade.net_pnl for trade in combined_admitted),
        ZERO,
    )
    two_pnl = sum(
        (trade.net_pnl for trade in two_admitted),
        ZERO,
    )
    stack_pnl = sum(
        (trade.net_pnl for trade in stack_admitted),
        ZERO,
    )
    combined_r = sum(
        (trade.net_r for trade in combined_admitted),
        ZERO,
    )
    two_r = sum(
        (trade.net_r for trade in two_admitted),
        ZERO,
    )
    stack_r = sum(
        (trade.net_r for trade in stack_admitted),
        ZERO,
    )

    two_incremental = resolved["two_strike_only"]
    combined_incremental = resolved["combined_only"]
    two_incremental_robustness = prospective_filter_robustness(
        tuple(
            (
                trade,
                trade in two_incremental,
            )
            for trade in matched
        )
    )
    combined_incremental_robustness = prospective_filter_robustness(
        tuple(
            (
                trade,
                trade in combined_incremental,
            )
            for trade in matched
        )
    )

    two_incremental_by_direction = {
        direction.value: _summary(
            tuple(
                trade
                for trade in two_incremental
                if trade.direction is direction
            )
        )
        for direction in (Direction.LONG, Direction.SHORT)
    }

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "descriptive_only": True,
        "changes_readiness_gate": False,
        "overlap_started_at_ms": overlap_start,
        "combined_started_at_ms": combined_start,
        "two_strike_started_at_ms": two_start,
        "closed_trades_since_overlap_start": len(prospective),
        "matched_trades": len(matched),
        "missing_combined_decisions": missing_combined,
        "missing_two_strike_decisions": missing_two_strike,
        "integrity_clean": (
            missing_combined == 0
            and missing_two_strike == 0
        ),
        "buckets": {
            name: _summary(values)
            for name, values in resolved.items()
        },
        "actual_net_pnl": str(actual_pnl),
        "actual_net_r": str(actual_r),
        "combined_candidate_net_pnl": str(combined_pnl),
        "combined_candidate_net_r": str(combined_r),
        "two_strike_candidate_net_pnl": str(two_pnl),
        "two_strike_candidate_net_r": str(two_r),
        "stack_candidate_net_pnl": str(stack_pnl),
        "stack_candidate_net_r": str(stack_r),
        "stack_minus_combined_net_pnl": str(
            stack_pnl - combined_pnl
        ),
        "stack_minus_combined_net_r": str(
            stack_r - combined_r
        ),
        "stack_minus_two_strike_net_pnl": str(
            stack_pnl - two_pnl
        ),
        "stack_minus_two_strike_net_r": str(
            stack_r - two_r
        ),
        "two_strike_incremental_robustness": (
            two_incremental_robustness
        ),
        "combined_incremental_robustness": (
            combined_incremental_robustness
        ),
        "two_strike_incremental_by_direction": (
            two_incremental_by_direction
        ),
    }
