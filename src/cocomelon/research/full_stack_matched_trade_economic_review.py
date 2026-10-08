from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Final, cast

from cocomelon.research.prospective_full_stack_matched_trade_ledger import (
    validate_full_stack_matched_trade_ledger,
)

ZERO: Final = Decimal("0")
MIN_REVIEW_TRADES: Final = 40
MIN_PER_DIRECTION: Final = 10
MIN_REVIEW_MARKETS: Final = 4
MIN_ADMITTED: Final = 20
MIN_BLOCKED: Final = 5
TEMPORAL_BLOCKS: Final = 4
MIN_BLOCK_TRADES: Final = 10


class FullStackEconomicReviewError(RuntimeError):
    pass


def _value(row: dict[str, object], field: str) -> Decimal:
    return Decimal(cast(str, row[field]))


def _cohort(
    rows: Sequence[dict[str, object]],
) -> dict[str, object]:
    values = tuple(rows)
    actual_pnl = sum((_value(row, "actual_net_pnl") for row in values), ZERO)
    candidate_pnl = sum(
        (_value(row, "full_stack_candidate_net_pnl") for row in values), ZERO
    )
    actual_r = sum((_value(row, "actual_net_r") for row in values), ZERO)
    candidate_r = sum(
        (_value(row, "full_stack_candidate_net_r") for row in values), ZERO
    )
    entry_pnl = sum(
        (_value(row, "entry_stack_candidate_net_pnl") for row in values), ZERO
    )
    return {
        "trades": len(values),
        "actual_net_pnl": str(actual_pnl),
        "candidate_net_pnl": str(candidate_pnl),
        "entry_only_net_pnl": str(entry_pnl),
        "delta_net_pnl": str(candidate_pnl - actual_pnl),
        "exit_incremental_net_pnl": str(candidate_pnl - entry_pnl),
        "actual_net_r": str(actual_r),
        "candidate_net_r": str(candidate_r),
        "delta_net_r": str(candidate_r - actual_r),
        "candidate_profitable": (
            len(values) > 0 and candidate_pnl > ZERO and candidate_r > ZERO
        ),
        "incremental_positive": (
            len(values) > 0
            and candidate_pnl > actual_pnl
            and candidate_r > actual_r
        ),
    }


def review_durable_full_stack_economics(
    ledger: object,
) -> dict[str, object]:
    """Read-only check: never mutate or reinterpret the v1 ledger digest."""
    valid = validate_full_stack_matched_trade_ledger(ledger)
    raw_rows = valid["rows"]
    if not isinstance(raw_rows, tuple):
        raise FullStackEconomicReviewError(
            "validated ledger rows must be canonical tuple"
        )
    rows = cast(tuple[dict[str, object], ...], raw_rows)
    ordered = tuple(sorted(
        rows,
        key=lambda row: (
            cast(int, row["opened_at_ms"]),
            cast(int, row["closed_at_ms"]),
            cast(str, row["trade_id"]),
        ),
    ))
    overall = _cohort(ordered)
    directions = {
        side: _cohort(tuple(
            row for row in ordered if row["direction"] == side
        ))
        for side in ("long", "short")
    }
    market_count = len({
        cast(str, row["market"]) for row in ordered
    })
    admitted = tuple(
        row for row in ordered if row["entry_decision"] == "ADMIT"
    )
    blocked = tuple(
        row for row in ordered if row["entry_decision"] == "BLOCK"
    )
    missing = valid["pending_trade_count"]
    if isinstance(missing, bool) or not isinstance(missing, int):
        raise FullStackEconomicReviewError(
            "pending_trade_count must be canonical integer"
        )
    blocks: list[dict[str, object]] = []
    for index in range(TEMPORAL_BLOCKS):
        low = len(ordered) * index // TEMPORAL_BLOCKS
        high = len(ordered) * (index + 1) // TEMPORAL_BLOCKS
        cohort = ordered[low:high]
        summary = _cohort(cohort)
        passes = (
            len(cohort) >= MIN_BLOCK_TRADES
            and summary["candidate_profitable"] is True
            and summary["incremental_positive"] is True
        )
        blocks.append({
            "block_index": index,
            "first_opened_at_ms": (
                None if not cohort else cohort[0]["opened_at_ms"]
            ),
            "last_opened_at_ms": (
                None if not cohort else cohort[-1]["opened_at_ms"]
            ),
            **summary,
            "passes_absolute_and_incremental": passes,
        })

    preserved_winners = sum(
        _value(row, "entry_stack_candidate_net_pnl") > ZERO
        and _value(row, "full_stack_candidate_net_pnl") > ZERO
        for row in admitted
    )
    lost_exit_winners = sum(
        _value(row, "entry_stack_candidate_net_pnl") > ZERO
        and _value(row, "full_stack_candidate_net_pnl") <= ZERO
        for row in admitted
    )
    recovered_exit_losers = sum(
        _value(row, "entry_stack_candidate_net_pnl") <= ZERO
        and _value(row, "full_stack_candidate_net_pnl") > ZERO
        for row in admitted
    )
    blocked_losers = sum(
        _value(row, "actual_net_pnl") < ZERO
        for row in blocked
    )
    blocked_winners_forgone = sum(
        _value(row, "actual_net_pnl") > ZERO
        for row in blocked
    )
    robust = cast(
        dict[str, object],
        cast(dict[str, object], valid["summary"])["robustness"],
    )
    candidate_robust = (
        robust["candidate_positive_after_removing_any_one_trade"] is True
        and robust["candidate_positive_after_removing_any_one_market"] is True
    )
    delta_robust = (
        robust["delta_positive_after_removing_any_one_trade"] is True
        and robust["delta_positive_after_removing_any_one_market"] is True
    )
    sufficient = (
        len(ordered) >= MIN_REVIEW_TRADES
        and len(admitted) >= MIN_ADMITTED
        and len(blocked) >= MIN_BLOCKED
        and market_count >= MIN_REVIEW_MARKETS
        and all(
            cast(int, cohort["trades"]) >= MIN_PER_DIRECTION
            for cohort in directions.values()
        )
    )
    both_sides_profitable = all(
        cohort["candidate_profitable"] is True
        for cohort in directions.values()
    )
    time_stable = all(
        block["passes_absolute_and_incremental"] is True
        for block in blocks
    )
    screen_passes = (
        missing == 0
        and sufficient
        and overall["candidate_profitable"] is True
        and overall["incremental_positive"] is True
        and both_sides_profitable
        and time_stable
        and candidate_robust
        and delta_robust
    )
    return {
        "schema_version": 1,
        "source_ledger_sha256": valid["ledger_sha256"],
        "source_rows_sha256": valid["rows_sha256"],
        "source_row_count": valid["row_count"],
        "research_only": True,
        "descriptive_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "ready_for_review": False,
        "portfolio_counterfactual_complete": False,
        "economic_screen_passes": screen_passes,
        "sample_complete": sufficient,
        "source_integrity_complete": missing == 0,
        "both_sides_profitable": both_sides_profitable,
        "all_temporal_blocks_profitable_and_improved": time_stable,
        "candidate_leave_one_trade_and_market_robust": candidate_robust,
        "delta_leave_one_trade_and_market_robust": delta_robust,
        "required_trades": MIN_REVIEW_TRADES,
        "required_per_direction": MIN_PER_DIRECTION,
        "required_markets": MIN_REVIEW_MARKETS,
        "required_admitted_trades": MIN_ADMITTED,
        "required_blocked_trades": MIN_BLOCKED,
        "min_trades_per_temporal_block": MIN_BLOCK_TRADES,
        "pending_trades": missing,
        "market_count": market_count,
        "admitted_trades": len(admitted),
        "blocked_trades": len(blocked),
        "overall": overall,
        "by_direction": directions,
        "temporal_blocks": blocks,
        "blocked_losers": blocked_losers,
        "blocked_winners_forgone": blocked_winners_forgone,
        "admitted_winners_preserved": preserved_winners,
        "admitted_winners_lost_after_exit": lost_exit_winners,
        "admitted_losers_recovered_after_exit": recovered_exit_losers,
        "warning": (
            "Legacy matched-trade readiness is not account-level "
            "profitability proof. No replacement entry fills, capacity "
            "reflow, correlation exposure, position overlap or complete "
            "portfolio drawdown is inferred. A positive screen cannot "
            "change entries, exits, stops, sizing or risk controls."
        ),
    }
