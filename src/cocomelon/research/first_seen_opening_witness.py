"""Read-only first-seen paper opening-lineage audit for historical research.

The original append-only opening-lineage store is recorded when actual paper
positions open, unlike the completed-trade journal populated after an exit.
Joining the two can establish *which* historical opens have original
immutable witness records. The record includes an exchange event timestamp
but no independent pre-opportunity archival attestation or direction, so it
cannot by itself grant decision-time equivalence or rehabilitate old ledgers.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.research.continuous_paper_learning import (
    ContinuousPaperOpeningLineage,
)
from cocomelon.research.continuous_paper_opening_opportunity import (
    ContinuousPaperOpeningOpportunityEvidence,
)


class FirstSeenOpeningWitnessError(RuntimeError):
    pass


def first_seen_opening_witness_summary(
    opportunities: Sequence[ContinuousPaperOpeningOpportunityEvidence],
    closed_trades: Sequence[TradeJournalEntry],
    opening_lineages: Sequence[ContinuousPaperOpeningLineage],
    *,
    overlap_started_at_ms: int,
) -> dict[str, object]:
    """Classify actual first-open witness coverage; never permit promotion.

    A later-finalized trade can be recognized by immutable opening-plan ID,
    opened time, market and feature ID. Missing records are reported rather
    than inferred from its later close. Any contradictory *existing* witness
    fails closed without downgrading into an apparent missing record.
    """
    if overlap_started_at_ms < 0:
        raise FirstSeenOpeningWitnessError("overlap start must be nonnegative")
    by_plan: dict[str, ContinuousPaperOpeningLineage] = {}
    for item in opening_lineages:
        if item.opening_plan_id in by_plan:
            raise FirstSeenOpeningWitnessError("duplicate first-seen opening identity")
        by_plan[item.opening_plan_id] = item

    all_trades = tuple(closed_trades)
    plans: set[str] = set()
    for trade in all_trades:
        if trade.opening_plan_id in plans:
            raise FirstSeenOpeningWitnessError("duplicate closed opening identity")
        plans.add(trade.opening_plan_id)
        witness = by_plan.get(trade.opening_plan_id)
        if witness is not None and (
            witness.market != trade.market.canonical
            or witness.opened_at_ms != trade.opened_at_ms
            or witness.feature_snapshot_id != trade.feature_snapshot_id
        ):
            raise FirstSeenOpeningWitnessError(
                "persisted first-seen opening conflicts with closed trade"
            )

    exposed_opportunities = 0
    approved_exposed = 0
    rejected_exposed = 0
    witnessed_opportunities = 0
    unwitnessed_opportunities = 0
    partially_witnessed_opportunities = 0
    exposed_trade_plans: set[str] = set()
    witnessed_trade_plans: set[str] = set()

    for evidence in opportunities:
        timestamp = evidence.opportunity_timestamp_ms
        if timestamp < overlap_started_at_ms:
            continue
        exposed = tuple(
            trade
            for trade in all_trades
            if overlap_started_at_ms <= trade.opened_at_ms < timestamp
            and trade.closed_at_ms > timestamp
            and trade.market.canonical == evidence.market
            and trade.direction.value == evidence.direction
        )
        if not exposed:
            continue
        exposed_opportunities += 1
        if evidence.baseline_risk_approved:
            approved_exposed += 1
        else:
            rejected_exposed += 1
        seen = 0
        for trade in exposed:
            exposed_trade_plans.add(trade.opening_plan_id)
            if trade.opening_plan_id in by_plan:
                witnessed_trade_plans.add(trade.opening_plan_id)
                seen += 1
        if seen == len(exposed):
            witnessed_opportunities += 1
        elif seen == 0:
            unwitnessed_opportunities += 1
        else:
            partially_witnessed_opportunities += 1

    identity_digest = hashlib.sha256(
        json.dumps(
            sorted(
                by_plan[plan].lineage_id
                for plan in witnessed_trade_plans
            ),
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()

    return {
        "kind": "first-seen-paper-opening-lineage-audit-v1",
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "historical_ledger_repair_authority": False,
        "changes_candidate_readiness": False,
        "event_time_attested_by_independent_archive": False,
        "decision_time_equivalence_verified": False,
        "opening_lineages_seen": len(by_plan),
        "closed_trades_seen": len(all_trades),
        "future_finalized_overlap_opportunities": exposed_opportunities,
        "risk_approved_overlap_opportunities": approved_exposed,
        "risk_rejected_overlap_opportunities": rejected_exposed,
        "fully_lineage_witnessed_overlap_opportunities": witnessed_opportunities,
        "partly_lineage_witnessed_overlap_opportunities": (
            partially_witnessed_opportunities
        ),
        "unwitnessed_overlap_opportunities": unwitnessed_opportunities,
        "unique_exposed_actual_openings": len(exposed_trade_plans),
        "unique_lineage_witnessed_exposed_openings": len(witnessed_trade_plans),
        "unique_missing_lineage_exposed_openings": (
            len(exposed_trade_plans - witnessed_trade_plans)
        ),
        "witness_lineage_id_sha256": identity_digest,
        "research_readiness_grant": False,
    }
