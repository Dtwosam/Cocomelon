from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.strategy import Direction

ZERO: Final = Decimal("0")
COHORT_ID: Final = "post-paper-data-freshness-fixes-v1"
COHORT_STARTED_AT_MS: Final = 1_790_880_761_000
COHORT_SOURCE_RUN_ID: Final = 36_910_111_457
COHORT_SOURCE_HEAD_SHA: Final = (
    "d97774d790628555cbff891f5c5d68952f287e43"
)
MIN_DESCRIPTIVE_CLOSED_TRADES: Final = 10


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


def post_freshness_paper_cohort_summary(
    trades: Sequence[TradeJournalEntry],
) -> dict[str, object]:
    values = tuple(trades)
    cohort = tuple(
        trade
        for trade in values
        if trade.opened_at_ms >= COHORT_STARTED_AT_MS
    )
    pre_cohort = tuple(
        trade
        for trade in values
        if trade.opened_at_ms < COHORT_STARTED_AT_MS
    )

    cohort_summary = _summary(cohort)
    pre_summary = _summary(pre_cohort)
    by_direction = {
        direction.value: _summary(
            tuple(
                trade
                for trade in cohort
                if trade.direction is direction
            )
        )
        for direction in (Direction.LONG, Direction.SHORT)
    }
    exit_reasons = sorted({trade.exit_reason for trade in cohort})
    by_exit_reason = {
        reason: _summary(
            tuple(
                trade
                for trade in cohort
                if trade.exit_reason == reason
            )
        )
        for reason in exit_reasons
    }

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "descriptive_only": True,
        "changes_readiness_gate": False,
        "cohort_id": COHORT_ID,
        "cohort_started_at_ms": COHORT_STARTED_AT_MS,
        "cohort_source_run_id": COHORT_SOURCE_RUN_ID,
        "cohort_source_head_sha": COHORT_SOURCE_HEAD_SHA,
        "cohort_boundary": "trade_opened_at_ms",
        "cohort_reason": (
            "first paper worker containing stale-L2 recovery, funding "
            "context continuity, 30s REST context refresh, and "
            "response-receipt context timestamping"
        ),
        "minimum_descriptive_closed_trades": (
            MIN_DESCRIPTIVE_CLOSED_TRADES
        ),
        "descriptive_sample_complete": (
            len(cohort) >= MIN_DESCRIPTIVE_CLOSED_TRADES
        ),
        "cohort_closed_trades": cohort_summary["trades"],
        "cohort_wins": cohort_summary["wins"],
        "cohort_losses": cohort_summary["losses"],
        "cohort_breakeven": cohort_summary["breakeven"],
        "cohort_net_pnl": cohort_summary["net_pnl"],
        "cohort_net_r": cohort_summary["net_r"],
        "cohort_mean_net_r": cohort_summary["mean_net_r"],
        "pre_cohort_closed_trades": pre_summary["trades"],
        "pre_cohort_net_pnl": pre_summary["net_pnl"],
        "pre_cohort_net_r": pre_summary["net_r"],
        "pre_cohort_mean_net_r": pre_summary["mean_net_r"],
        "by_direction": by_direction,
        "by_exit_reason": by_exit_reason,
    }
