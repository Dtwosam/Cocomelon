from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.strategy import Direction
from cocomelon.research.continuous_paper_learning import (
    ContinuousPaperOpeningLineage,
)
from cocomelon.research.continuous_paper_opening_opportunity import (
    ContinuousPaperOpeningOpportunityEvidence,
)

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



def _runway_slice(
    opportunities: tuple[
        ContinuousPaperOpeningOpportunityEvidence, ...
    ],
    lineages: tuple[ContinuousPaperOpeningLineage, ...],
    trades: tuple[TradeJournalEntry, ...],
    *,
    started_at_ms: int,
    now_ms: int,
) -> dict[str, object]:
    candidate_opportunities = tuple(
        item
        for item in opportunities
        if item.opportunity_timestamp_ms >= started_at_ms
    )
    candidate_lineages = tuple(
        item for item in lineages if item.opened_at_ms >= started_at_ms
    )
    candidate_trades = tuple(
        item for item in trades if item.opened_at_ms >= started_at_ms
    )

    approved = tuple(
        item
        for item in candidate_opportunities
        if item.baseline_risk_approved
    )
    rejected = tuple(
        item
        for item in candidate_opportunities
        if not item.baseline_risk_approved
    )
    reason_counts = Counter(
        reason
        for item in rejected
        for reason in item.baseline_risk_reason_codes
    )
    direction_counts = Counter(
        item.direction for item in candidate_opportunities
    )

    closed_plan_ids = {
        trade.opening_plan_id for trade in candidate_trades
    }
    lineage_plan_ids = {
        lineage.opening_plan_id for lineage in candidate_lineages
    }
    open_lineages = tuple(
        lineage
        for lineage in candidate_lineages
        if lineage.opening_plan_id not in closed_plan_ids
    )
    closed_without_lineage = tuple(
        trade
        for trade in candidate_trades
        if trade.opening_plan_id not in lineage_plan_ids
    )

    pnl = sum((trade.net_pnl for trade in candidate_trades), ZERO)
    net_r = sum((trade.net_r for trade in candidate_trades), ZERO)

    if not candidate_opportunities:
        stage = "waiting_for_directional_opportunity"
    elif not approved:
        stage = "risk_rejected"
    elif not candidate_lineages:
        stage = "approved_without_opening"
    elif not candidate_trades:
        stage = "openings_waiting_for_close"
    else:
        stage = "closed_trade_evidence_available"

    oldest_open_age_ms = (
        None
        if not open_lineages
        else max(
            0,
            now_ms
            - min(item.opened_at_ms for item in open_lineages),
        )
    )

    return {
        "started_at_ms": started_at_ms,
        "elapsed_ms": max(0, now_ms - started_at_ms),
        "stage": stage,
        "directional_opportunities": len(candidate_opportunities),
        "opportunities_long": direction_counts.get("long", 0),
        "opportunities_short": direction_counts.get("short", 0),
        "opportunity_markets": len(
            {item.market for item in candidate_opportunities}
        ),
        "risk_approved": len(approved),
        "risk_rejected": len(rejected),
        "risk_reason_counts": dict(
            sorted(reason_counts.items())
        ),
        "paper_openings": len(candidate_lineages),
        "paper_closed_trades": len(candidate_trades),
        "paper_unclosed_openings": len(open_lineages),
        "oldest_unclosed_opening_age_ms": oldest_open_age_ms,
        "closed_trade_net_pnl": str(pnl),
        "closed_trade_net_r": str(net_r),
        "closed_without_opening_lineage": len(
            closed_without_lineage
        ),
        "lineage_integrity_clean": not closed_without_lineage,
    }


def clean_evidence_runway_summary(
    opportunities: Sequence[
        ContinuousPaperOpeningOpportunityEvidence
    ],
    lineages: Sequence[ContinuousPaperOpeningLineage],
    trades: Sequence[TradeJournalEntry],
    candidate_starts: Mapping[str, int],
    *,
    now_ms: int,
) -> dict[str, object]:
    if now_ms < 0:
        raise ValueError("now_ms must be non-negative")
    if not candidate_starts:
        raise ValueError("candidate_starts must not be empty")
    for candidate_id, started_at_ms in candidate_starts.items():
        if not candidate_id.strip():
            raise ValueError("candidate id must not be empty")
        if started_at_ms < 0:
            raise ValueError(
                "candidate start must be non-negative"
            )

    opportunity_values = tuple(opportunities)
    lineage_values = tuple(lineages)
    trade_values = tuple(trades)
    ordered_starts = dict(sorted(candidate_starts.items()))
    common_started_at_ms = max(ordered_starts.values())

    by_candidate = {
        candidate_id: _runway_slice(
            opportunity_values,
            lineage_values,
            trade_values,
            started_at_ms=started_at_ms,
            now_ms=now_ms,
        )
        for candidate_id, started_at_ms in ordered_starts.items()
    }
    common = _runway_slice(
        opportunity_values,
        lineage_values,
        trade_values,
        started_at_ms=common_started_at_ms,
        now_ms=now_ms,
    )

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "descriptive_only": True,
        "changes_readiness_gate": False,
        "common_started_at_ms": common_started_at_ms,
        "common": common,
        "by_candidate": by_candidate,
    }
