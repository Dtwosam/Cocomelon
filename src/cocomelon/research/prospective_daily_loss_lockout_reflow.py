from __future__ import annotations

from collections import Counter
from decimal import Decimal
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.strategy import Direction
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.research.continuous_paper_opening_opportunity import (
    ContinuousPaperOpeningOpportunityEvidence,
    ContinuousPaperOpeningOpportunityStore,
)
from cocomelon.research.continuous_paper_opening_rank import (
    ContinuousPaperOpeningRankStore,
)
from cocomelon.research.exact_decimal_aggregation import (
    exact_decimal_sum,
)
from cocomelon.research.prospective_combined_entry_filter import (
    MAX_ACCEPTED_RANK_AGE_MS,
    TOP10_MAX_ORDINAL,
    ProspectiveCombinedEntryFilterState,
)

DAY_MS: Final = 86_400_000
DAILY_LOSS_LOCKOUT: Final = "daily_loss_lockout"
ZERO: Final = Decimal("0")


class ProspectiveDailyLossLockoutReflowError(RuntimeError):
    pass


def _opportunity_rank_age_ms(
    evidence: ContinuousPaperOpeningOpportunityEvidence,
) -> int | None:
    if evidence.rank_observed_at_ms is None:
        return None
    age = (
        evidence.opportunity_timestamp_ms
        - evidence.rank_observed_at_ms
    )
    if age < 0:
        raise ProspectiveDailyLossLockoutReflowError(
            "opening opportunity rank is from the future"
        )
    return age


def _block_reason(
    *,
    direction: Direction,
    lead_strategy: str,
    ordinal: int,
) -> str | None:
    long_trend = (
        direction is Direction.LONG
        and lead_strategy == "trend"
    )
    rank_above_10 = ordinal > TOP10_MAX_ORDINAL
    if long_trend and rank_above_10:
        return "long_trend_and_rank_above_10"
    if long_trend:
        return "long_trend"
    if rank_above_10:
        return "rank_above_10"
    return None


def _opportunity_block_reason(
    evidence: ContinuousPaperOpeningOpportunityEvidence,
) -> str | None:
    if evidence.rank_ordinal is None:
        raise ProspectiveDailyLossLockoutReflowError(
            "opportunity block reason requires scanner rank"
        )
    try:
        direction = Direction(evidence.direction)
    except ValueError as exc:
        raise ProspectiveDailyLossLockoutReflowError(
            "opening opportunity direction is invalid"
        ) from exc
    return _block_reason(
        direction=direction,
        lead_strategy=evidence.lead_strategy,
        ordinal=evidence.rank_ordinal,
    )


def _trade_block_reason(
    trade: TradeJournalEntry,
    fact_store: EvaluationFactStore,
    rank_store: ContinuousPaperOpeningRankStore,
) -> tuple[str | None, str | None]:
    if trade.replay_run_id is None:
        return None, "decision"
    fact = fact_store.load_decision_by_strategy_id(
        trade.strategy_decision_id,
        trade.replay_run_id,
    )
    if fact is None or fact.lead_strategy is None:
        return None, "decision"
    if (
        fact.market != trade.market
        or fact.direction is not trade.direction
        or fact.feature_snapshot_id != trade.feature_snapshot_id
    ):
        raise ProspectiveDailyLossLockoutReflowError(
            "daily-lockout decision lineage does not match trade"
        )

    rank = rank_store.load(trade.opening_plan_id)
    if rank is None:
        return None, "rank"
    if (
        rank.market != trade.market.canonical
        or rank.opened_at_ms != trade.opened_at_ms
    ):
        raise ProspectiveDailyLossLockoutReflowError(
            "daily-lockout rank lineage does not match trade"
        )
    if rank.rank_age_ms > MAX_ACCEPTED_RANK_AGE_MS:
        return None, "stale_rank"
    return (
        _block_reason(
            direction=trade.direction,
            lead_strategy=fact.lead_strategy,
            ordinal=rank.ordinal,
        ),
        None,
    )


def _decimal_min(values: tuple[Decimal, ...]) -> str | None:
    return None if not values else str(min(values))


def _decimal_max(values: tuple[Decimal, ...]) -> str | None:
    return None if not values else str(max(values))


def prospective_daily_loss_lockout_reflow_summary(
    opportunities: tuple[
        ContinuousPaperOpeningOpportunityEvidence,
        ...,
    ],
    trades: tuple[TradeJournalEntry, ...],
    fact_store: EvaluationFactStore,
    rank_store: ContinuousPaperOpeningRankStore,
    state: ProspectiveCombinedEntryFilterState,
) -> dict[str, object]:
    prospective = tuple(
        evidence
        for evidence in opportunities
        if evidence.opportunity_timestamp_ms >= state.started_at_ms
    )
    lockouts = tuple(
        evidence
        for evidence in prospective
        if not evidence.baseline_risk_approved
        and DAILY_LOSS_LOCKOUT
        in evidence.baseline_risk_reason_codes
    )

    candidate_eligible: list[
        ContinuousPaperOpeningOpportunityEvidence
    ] = []
    opportunity_missing_rank = 0
    opportunity_stale_rank = 0
    opportunity_candidate_blocked = 0
    for evidence in lockouts:
        rank_age_ms = _opportunity_rank_age_ms(evidence)
        if rank_age_ms is None or evidence.rank_ordinal is None:
            opportunity_missing_rank += 1
            continue
        if rank_age_ms > MAX_ACCEPTED_RANK_AGE_MS:
            opportunity_stale_rank += 1
            continue
        if _opportunity_block_reason(evidence) is not None:
            opportunity_candidate_blocked += 1
            continue
        candidate_eligible.append(evidence)

    closed_trade_adjusted_unlocks = 0
    exact_cash_scope = 0
    exact_candidate_unlocks = 0
    same_day_closed_trade_instances = 0
    cross_day_closed_trade_instances = 0
    candidate_blocked_closed_trade_instances = 0
    trade_decision_misses = 0
    trade_rank_misses = 0
    trade_stale_ranks = 0
    open_position_instances = 0
    baseline_cash_reconciliation_misses = 0
    blocked_trade_ids: set[str] = set()
    block_reason_counts: Counter[str] = Counter()
    actual_daily_values: list[Decimal] = []
    adjusted_daily_values: list[Decimal] = []
    threshold_values: list[Decimal] = []
    removed_net_values: list[Decimal] = []

    ordered_trades = tuple(
        sorted(
            trades,
            key=lambda trade: (
                trade.closed_at_ms,
                trade.opened_at_ms,
                trade.trade_id,
            ),
        )
    )

    for evidence in candidate_eligible:
        request = evidence.risk_request_object
        account = request.account_state
        threshold = -(
            account.day_start_equity
            * request.limits.daily_loss_limit
        )
        if account.daily_realized_pnl > threshold:
            raise ProspectiveDailyLossLockoutReflowError(
                "daily-loss rejection does not match captured account state"
            )

        day_start_ms = (
            evidence.opportunity_timestamp_ms // DAY_MS
        ) * DAY_MS
        closed_before = tuple(
            trade
            for trade in ordered_trades
            if day_start_ms <= trade.closed_at_ms
            < evidence.opportunity_timestamp_ms
        )
        cross_day = tuple(
            trade
            for trade in closed_before
            if trade.opened_at_ms < day_start_ms
        )
        same_day = tuple(
            trade
            for trade in closed_before
            if trade.opened_at_ms >= day_start_ms
        )
        same_day_closed_trade_instances += len(same_day)
        cross_day_closed_trade_instances += len(cross_day)
        open_position_instances += len(request.open_positions)

        blocked: list[TradeJournalEntry] = []
        attribution_clean = True
        for trade in same_day:
            if trade.opened_at_ms < state.started_at_ms:
                continue
            reason, miss = _trade_block_reason(
                trade,
                fact_store,
                rank_store,
            )
            if miss == "decision":
                trade_decision_misses += 1
                attribution_clean = False
                continue
            if miss == "rank":
                trade_rank_misses += 1
                attribution_clean = False
                continue
            if miss == "stale_rank":
                trade_stale_ranks += 1
                attribution_clean = False
                continue
            if reason is not None:
                blocked.append(trade)
                candidate_blocked_closed_trade_instances += 1
                blocked_trade_ids.add(trade.trade_id)
                block_reason_counts[reason] += 1

        same_day_closed_net_pnl = exact_decimal_sum(
            trade.net_pnl for trade in same_day
        )
        baseline_cash_reconciles = (
            not cross_day
            and not request.open_positions
            and same_day_closed_net_pnl
            == account.daily_realized_pnl
        )
        if (
            not cross_day
            and not request.open_positions
            and not baseline_cash_reconciles
        ):
            baseline_cash_reconciliation_misses += 1

        blocked_net_pnl = exact_decimal_sum(
            trade.net_pnl for trade in blocked
        )
        adjusted_daily = (
            account.daily_realized_pnl - blocked_net_pnl
        )
        unlocks = adjusted_daily > threshold
        if attribution_clean and unlocks:
            closed_trade_adjusted_unlocks += 1

        cash_scope_complete = (
            attribution_clean
            and baseline_cash_reconciles
        )
        if cash_scope_complete:
            exact_cash_scope += 1
            if unlocks:
                exact_candidate_unlocks += 1

        actual_daily_values.append(account.daily_realized_pnl)
        adjusted_daily_values.append(adjusted_daily)
        threshold_values.append(threshold)
        removed_net_values.append(blocked_net_pnl)

    opportunity_integrity_clean = (
        opportunity_missing_rank == 0
        and opportunity_stale_rank == 0
    )
    trade_attribution_clean = (
        trade_decision_misses == 0
        and trade_rank_misses == 0
        and trade_stale_ranks == 0
    )
    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "candidate_id": state.candidate_id,
        "started_at_ms": state.started_at_ms,
        "claim_scope": (
            "candidate_filtered_same_day_closed_trade_"
            "daily_loss_lockout_reflow"
        ),
        "portfolio_counterfactual": False,
        "replacement_trades_modeled": False,
        "pnl_modeled": False,
        "open_position_cash_effects_modeled": False,
        "cross_day_trade_cash_effects_modeled": False,
        "daily_loss_lockout_opportunities": len(lockouts),
        "candidate_eligible_lockout_opportunities": len(
            candidate_eligible
        ),
        "candidate_blocked_lockout_opportunities": (
            opportunity_candidate_blocked
        ),
        "opportunity_missing_rank_evidence": (
            opportunity_missing_rank
        ),
        "opportunity_stale_rank_evidence": (
            opportunity_stale_rank
        ),
        "opportunity_integrity_clean": opportunity_integrity_clean,
        "same_day_closed_trade_instances": (
            same_day_closed_trade_instances
        ),
        "cross_day_closed_trade_instances": (
            cross_day_closed_trade_instances
        ),
        "open_position_instances": open_position_instances,
        "baseline_cash_reconciliation_misses": (
            baseline_cash_reconciliation_misses
        ),
        "baseline_cash_reconciliation_clean": (
            baseline_cash_reconciliation_misses == 0
        ),
        "candidate_blocked_closed_trade_instances": (
            candidate_blocked_closed_trade_instances
        ),
        "distinct_candidate_blocked_trade_ids": len(
            blocked_trade_ids
        ),
        "trade_decision_attribution_misses": (
            trade_decision_misses
        ),
        "trade_rank_attribution_misses": trade_rank_misses,
        "trade_stale_rank_attribution": trade_stale_ranks,
        "trade_attribution_clean": trade_attribution_clean,
        "closed_trade_adjusted_unlock_opportunities": (
            closed_trade_adjusted_unlocks
        ),
        "exact_cash_scope_opportunities": exact_cash_scope,
        "exact_candidate_unlock_opportunities": (
            exact_candidate_unlocks
        ),
        "baseline_daily_realized_pnl_min": _decimal_min(
            tuple(actual_daily_values)
        ),
        "baseline_daily_realized_pnl_max": _decimal_max(
            tuple(actual_daily_values)
        ),
        "candidate_daily_realized_pnl_min": _decimal_min(
            tuple(adjusted_daily_values)
        ),
        "candidate_daily_realized_pnl_max": _decimal_max(
            tuple(adjusted_daily_values)
        ),
        "daily_loss_threshold_min": _decimal_min(
            tuple(threshold_values)
        ),
        "daily_loss_threshold_max": _decimal_max(
            tuple(threshold_values)
        ),
        "removed_blocked_trade_net_pnl_min": _decimal_min(
            tuple(removed_net_values)
        ),
        "removed_blocked_trade_net_pnl_max": _decimal_max(
            tuple(removed_net_values)
        ),
        "by_removed_trade_block_reason": dict(
            sorted(block_reason_counts.items())
        ),
    }


def evaluate_prospective_daily_loss_lockout_reflow(
    opportunity_store: ContinuousPaperOpeningOpportunityStore,
    trades: tuple[TradeJournalEntry, ...],
    fact_store: EvaluationFactStore,
    rank_store: ContinuousPaperOpeningRankStore,
    state: ProspectiveCombinedEntryFilterState,
) -> dict[str, object]:
    return prospective_daily_loss_lockout_reflow_summary(
        opportunity_store.iter_records(),
        trades,
        fact_store,
        rank_store,
        state,
    )
