from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from typing import Final

from cocomelon.domain.evaluation import DecisionEvaluationFact
from cocomelon.domain.execution import OrderSide, PaperOrderPlan
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.strategy import Direction
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.journal.store import JournalStore
from cocomelon.research.continuous_paper_learning import (
    ContinuousPaperOpeningLineage,
    ContinuousPaperOpeningLineageStore,
)
from cocomelon.research.continuous_paper_opening_opportunity import (
    ContinuousPaperOpeningOpportunityStore,
)
from cocomelon.research.continuous_paper_opening_rank import (
    ContinuousPaperOpeningRankEvidence,
    ContinuousPaperOpeningRankStore,
)
from cocomelon.research.prospective_capacity_reflow_opportunities import (
    CapacityReleaseOpportunityOption,
    candidate_eligible_capacity_release_options,
)
from cocomelon.research.prospective_combined_entry_filter import (
    MAX_ACCEPTED_RANK_AGE_MS,
    TOP10_MAX_ORDINAL,
    ProspectiveCombinedEntryFilterState,
)

LONG_TREND: Final = "long_trend"
RANK_ABOVE_10: Final = "rank_above_10"
LONG_TREND_AND_RANK_ABOVE_10: Final = (
    "long_trend_and_rank_above_10"
)


class ProspectiveCapacityReflowReleaseLineageError(RuntimeError):
    pass


def _candidate_block_reason(
    fact: DecisionEvaluationFact,
    rank: ContinuousPaperOpeningRankEvidence,
) -> str | None:
    if fact.lead_strategy is None:
        raise ProspectiveCapacityReflowReleaseLineageError(
            "release position decision lost lead strategy"
        )
    long_trend = (
        fact.direction is Direction.LONG
        and fact.lead_strategy == "trend"
    )
    below_rank_cut = rank.ordinal > TOP10_MAX_ORDINAL
    if long_trend and below_rank_cut:
        return LONG_TREND_AND_RANK_ABOVE_10
    if long_trend:
        return LONG_TREND
    if below_rank_cut:
        return RANK_ABOVE_10
    return None


def _closed_by_plan(
    trades: tuple[TradeJournalEntry, ...],
) -> dict[str, TradeJournalEntry]:
    output: dict[str, TradeJournalEntry] = {}
    for trade in trades:
        existing = output.get(trade.opening_plan_id)
        if existing is not None and existing != trade:
            raise ProspectiveCapacityReflowReleaseLineageError(
                "duplicate closed-trade opening plan lineage"
            )
        output[trade.opening_plan_id] = trade
    return output


def _active_lineage(
    option: CapacityReleaseOpportunityOption,
    lineages: tuple[ContinuousPaperOpeningLineage, ...],
    closed_by_plan: dict[str, TradeJournalEntry],
) -> ContinuousPaperOpeningLineage | None:
    candidates: list[ContinuousPaperOpeningLineage] = []
    for lineage in lineages:
        if lineage.market != option.release_market:
            continue
        if lineage.opened_at_ms > option.opportunity_timestamp_ms:
            continue
        closed = closed_by_plan.get(lineage.opening_plan_id)
        if closed is not None:
            if (
                closed.market.canonical != lineage.market
                or closed.opened_at_ms != lineage.opened_at_ms
            ):
                raise ProspectiveCapacityReflowReleaseLineageError(
                    "closed trade does not match opening lineage"
                )
            if closed.closed_at_ms < option.opportunity_timestamp_ms:
                continue
        candidates.append(lineage)

    if len(candidates) > 1:
        raise ProspectiveCapacityReflowReleaseLineageError(
            "multiple active opening lineages for release market"
        )
    return None if not candidates else candidates[0]


def candidate_caused_capacity_release_options(
    options: tuple[CapacityReleaseOpportunityOption, ...],
    lineages: tuple[ContinuousPaperOpeningLineage, ...],
    closed_trades: tuple[TradeJournalEntry, ...],
    *,
    plan_loader: Callable[[str], PaperOrderPlan | None],
    fact_loader: Callable[
        [str, str],
        DecisionEvaluationFact | None,
    ],
    rank_loader: Callable[
        [str],
        ContinuousPaperOpeningRankEvidence | None,
    ],
) -> tuple[CapacityReleaseOpportunityOption, ...]:
    closed_by_plan = _closed_by_plan(closed_trades)
    output: list[CapacityReleaseOpportunityOption] = []
    for option in options:
        lineage = _active_lineage(
            option,
            lineages,
            closed_by_plan,
        )
        if lineage is None:
            raise ProspectiveCapacityReflowReleaseLineageError(
                "candidate capacity release lineage is missing"
            )
        plan = plan_loader(lineage.opening_plan_id)
        if plan is None:
            raise ProspectiveCapacityReflowReleaseLineageError(
                "candidate capacity release plan is missing"
            )
        if (
            plan.plan_id != lineage.opening_plan_id
            or plan.reduce_only
            or plan.market.canonical != option.release_market
        ):
            raise ProspectiveCapacityReflowReleaseLineageError(
                "release opening plan lineage mismatch"
            )
        fact = fact_loader(
            plan.strategy_decision_id,
            lineage.replay_run_id,
        )
        if fact is None or fact.lead_strategy is None:
            raise ProspectiveCapacityReflowReleaseLineageError(
                "candidate capacity release decision is missing"
            )
        expected_side = (
            OrderSide.BUY
            if fact.direction is Direction.LONG
            else OrderSide.SELL
        )
        if (
            fact.feature_snapshot_id
            != lineage.feature_snapshot_id
            or fact.market.canonical != option.release_market
            or fact.direction is Direction.NO_TRADE
            or plan.side is not expected_side
        ):
            raise ProspectiveCapacityReflowReleaseLineageError(
                "release decision lineage mismatch"
            )
        rank = rank_loader(lineage.opening_plan_id)
        if rank is None:
            raise ProspectiveCapacityReflowReleaseLineageError(
                "candidate capacity release rank is missing"
            )
        if (
            rank.market != option.release_market
            or rank.opened_at_ms != lineage.opened_at_ms
        ):
            raise ProspectiveCapacityReflowReleaseLineageError(
                "release scanner-rank lineage mismatch"
            )
        if rank.rank_age_ms > MAX_ACCEPTED_RANK_AGE_MS:
            raise ProspectiveCapacityReflowReleaseLineageError(
                "candidate capacity release rank is stale"
            )
        if _candidate_block_reason(fact, rank) is not None:
            output.append(option)
    return tuple(output)


def prospective_capacity_reflow_release_lineage_summary(
    options: tuple[CapacityReleaseOpportunityOption, ...],
    lineages: tuple[ContinuousPaperOpeningLineage, ...],
    closed_trades: tuple[TradeJournalEntry, ...],
    *,
    plan_loader: Callable[[str], PaperOrderPlan | None],
    fact_loader: Callable[
        [str, str],
        DecisionEvaluationFact | None,
    ],
    rank_loader: Callable[
        [str],
        ContinuousPaperOpeningRankEvidence | None,
    ],
    state: ProspectiveCombinedEntryFilterState,
) -> dict[str, object]:
    closed_by_plan = _closed_by_plan(closed_trades)
    lineage_misses = 0
    plan_misses = 0
    decision_misses = 0
    rank_misses = 0
    stale_ranks = 0
    candidate_blocked_options = 0
    candidate_allowed_options = 0
    blocked_opportunity_ids: set[str] = set()
    resolved_opportunity_ids: set[str] = set()
    by_block_reason: Counter[str] = Counter()
    by_blocked_release_market: Counter[str] = Counter()

    for option in options:
        lineage = _active_lineage(
            option,
            lineages,
            closed_by_plan,
        )
        if lineage is None:
            lineage_misses += 1
            continue

        plan = plan_loader(lineage.opening_plan_id)
        if plan is None:
            plan_misses += 1
            continue
        if (
            plan.plan_id != lineage.opening_plan_id
            or plan.reduce_only
            or plan.market.canonical != option.release_market
        ):
            raise ProspectiveCapacityReflowReleaseLineageError(
                "release opening plan lineage mismatch"
            )

        fact = fact_loader(
            plan.strategy_decision_id,
            lineage.replay_run_id,
        )
        if fact is None or fact.lead_strategy is None:
            decision_misses += 1
            continue
        expected_side = (
            OrderSide.BUY
            if fact.direction is Direction.LONG
            else OrderSide.SELL
        )
        if (
            fact.feature_snapshot_id != lineage.feature_snapshot_id
            or fact.market.canonical != option.release_market
            or fact.direction is Direction.NO_TRADE
            or plan.side is not expected_side
        ):
            raise ProspectiveCapacityReflowReleaseLineageError(
                "release decision lineage mismatch"
            )

        rank = rank_loader(lineage.opening_plan_id)
        if rank is None:
            rank_misses += 1
            continue
        if (
            rank.market != option.release_market
            or rank.opened_at_ms != lineage.opened_at_ms
        ):
            raise ProspectiveCapacityReflowReleaseLineageError(
                "release scanner-rank lineage mismatch"
            )
        if rank.rank_age_ms > MAX_ACCEPTED_RANK_AGE_MS:
            stale_ranks += 1
            continue

        resolved_opportunity_ids.add(option.opportunity_id)
        block_reason = _candidate_block_reason(fact, rank)
        if block_reason is None:
            candidate_allowed_options += 1
            continue

        candidate_blocked_options += 1
        blocked_opportunity_ids.add(option.opportunity_id)
        by_block_reason[block_reason] += 1
        by_blocked_release_market[option.release_market] += 1

    integrity_clean = (
        lineage_misses == 0
        and plan_misses == 0
        and decision_misses == 0
        and rank_misses == 0
        and stale_ranks == 0
    )
    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "candidate_id": state.candidate_id,
        "started_at_ms": state.started_at_ms,
        "claim_scope": (
            "candidate_filtered_position_capacity_release_lineage"
        ),
        "portfolio_counterfactual": False,
        "replacement_trades_modeled": False,
        "pnl_modeled": False,
        "release_options": len(options),
        "resolved_release_options": (
            candidate_blocked_options + candidate_allowed_options
        ),
        "resolved_opportunities": len(resolved_opportunity_ids),
        "candidate_blocked_release_options": candidate_blocked_options,
        "candidate_allowed_release_options": candidate_allowed_options,
        "candidate_capacity_release_opportunities": len(
            blocked_opportunity_ids
        ),
        "release_lineage_misses": lineage_misses,
        "release_plan_misses": plan_misses,
        "release_decision_misses": decision_misses,
        "release_rank_misses": rank_misses,
        "release_stale_ranks": stale_ranks,
        "integrity_clean": integrity_clean,
        "by_release_position_block_reason": dict(
            sorted(by_block_reason.items())
        ),
        "by_candidate_blocked_release_market": dict(
            sorted(by_blocked_release_market.items())
        ),
    }


def evaluate_prospective_capacity_reflow_release_lineage(
    opportunity_store: ContinuousPaperOpeningOpportunityStore,
    lineage_store: ContinuousPaperOpeningLineageStore,
    journal: JournalStore,
    *,
    plan_loader: Callable[[str], PaperOrderPlan | None],
    fact_store: EvaluationFactStore,
    rank_store: ContinuousPaperOpeningRankStore,
    state: ProspectiveCombinedEntryFilterState,
) -> dict[str, object]:
    options = candidate_eligible_capacity_release_options(
        opportunity_store.iter_records(),
        state,
    )
    return prospective_capacity_reflow_release_lineage_summary(
        options,
        lineage_store.iter_records(),
        tuple(journal.iter_trades()),
        plan_loader=plan_loader,
        fact_loader=fact_store.load_decision_by_strategy_id,
        rank_loader=rank_store.load,
        state=state,
    )
