from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.strategy import Direction
from cocomelon.research.continuous_paper_opening_opportunity import (
    ContinuousPaperOpeningOpportunityEvidence,
)
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotStore,
)
from cocomelon.research.terminal_journal_asof import (
    future_finalized_open_exposure,
    terminal_trades_known_at,
)
from cocomelon.research.profit_lock_execution_shadow import (
    ProfitLockExecutionOutcome,
)
from cocomelon.research.prospective_breakeven_profit_lock import (
    RULE_ID as BREAKEVEN_RULE_ID,
)
from cocomelon.research.prospective_capacity_reflow_opportunities import (
    RISK_CAPACITY_REJECTION_REASONS,
)
from cocomelon.research.prospective_capacity_reflow_release_lineage import (
    CandidateCausedCapacityRelease,
)
from cocomelon.research.prospective_combined_entry_filter import (
    MAX_ACCEPTED_RANK_AGE_MS,
    ProspectiveCombinedEntryFilterState,
    prospective_combined_block_reason,
)
from cocomelon.research.prospective_momentum_band_entry import (
    ProspectiveMomentumBandEntryState,
    prospective_momentum_band_opportunity_decision,
)
from cocomelon.research.prospective_two_strike_stop_filter import (
    STRIKE_THRESHOLD,
    ProspectiveTwoStrikeStopFilterState,
    prospective_two_strike_prior_strikes_at,
)

RELEASE_REASON: Final = "breakeven_exact_early_close"
MOMENTUM_INTEGRITY_REASONS: Final = frozenset(
    {
        "missing_feature_fail_open",
        "incomplete_feature_fail_open",
    }
)


class ProspectiveFullStackExitCapacityReflowError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProspectiveFullStackExitCapacityReflowEvaluation:
    releases: tuple[CandidateCausedCapacityRelease, ...]
    release_terminal_contributions: tuple[tuple[str, Decimal], ...]
    summary: dict[str, object]


def _required_int(raw: object, *, field: str) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ProspectiveFullStackExitCapacityReflowError(
            f"{field} must be an integer"
        )
    return raw


def _rank_age_ms(
    evidence: ContinuousPaperOpeningOpportunityEvidence,
) -> int | None:
    observed_at_ms = evidence.rank_observed_at_ms
    if observed_at_ms is None:
        return None
    age = evidence.opportunity_timestamp_ms - observed_at_ms
    if age < 0:
        raise ProspectiveFullStackExitCapacityReflowError(
            "opening opportunity rank is from the future"
        )
    return age


def _outcomes_by_trade(
    execution_shadow_state: Mapping[str, object],
) -> dict[str, ProfitLockExecutionOutcome]:
    raw_outcomes = execution_shadow_state.get("outcomes")
    if not isinstance(raw_outcomes, list):
        raise ProspectiveFullStackExitCapacityReflowError(
            "execution shadow outcomes must be a list"
        )
    output: dict[str, ProfitLockExecutionOutcome] = {}
    for raw in raw_outcomes:
        outcome = ProfitLockExecutionOutcome.from_payload(raw)
        if outcome.rule_id != BREAKEVEN_RULE_ID:
            continue
        if outcome.trade_id in output:
            raise ProspectiveFullStackExitCapacityReflowError(
                "duplicate breakeven outcome trade id"
            )
        output[outcome.trade_id] = outcome
    return output


def _active_trade(
    trades: tuple[TradeJournalEntry, ...],
    *,
    market: str,
    direction: Direction,
    opportunity_timestamp_ms: int,
) -> TradeJournalEntry | None:
    matches = tuple(
        trade
        for trade in trades
        if trade.market.canonical == market
        and trade.direction is direction
        and trade.opened_at_ms <= opportunity_timestamp_ms
        and trade.closed_at_ms > opportunity_timestamp_ms
    )
    if len(matches) > 1:
        raise ProspectiveFullStackExitCapacityReflowError(
            "multiple active closed-trade lineages match one risk position"
        )
    return None if not matches else matches[0]


def prospective_full_stack_exit_capacity_reflow(
    opportunities: Sequence[ContinuousPaperOpeningOpportunityEvidence],
    closed_trades: Sequence[TradeJournalEntry],
    feature_store: LearningFeatureSnapshotStore,
    combined_state: ProspectiveCombinedEntryFilterState,
    two_strike_state: ProspectiveTwoStrikeStopFilterState,
    momentum_state: ProspectiveMomentumBandEntryState,
    full_stack_summary: Mapping[str, object],
    execution_shadow_state: Mapping[str, object],
) -> ProspectiveFullStackExitCapacityReflowEvaluation:
    overlap_start = _required_int(
        full_stack_summary.get("overlap_started_at_ms"),
        field="full-stack overlap_started_at_ms",
    )
    if overlap_start != max(
        combined_state.started_at_ms,
        two_strike_state.started_at_ms,
        momentum_state.started_at_ms,
        _required_int(
            full_stack_summary.get("breakeven_started_at_ms"),
            field="breakeven started_at_ms",
        ),
    ):
        raise ProspectiveFullStackExitCapacityReflowError(
            "full-stack overlap start does not reconcile"
        )

    raw_decisions = full_stack_summary.get("decision_by_trade_id")
    if not isinstance(raw_decisions, dict):
        raise ProspectiveFullStackExitCapacityReflowError(
            "full-stack decision map must be an object"
        )
    outcomes = _outcomes_by_trade(execution_shadow_state)
    trades = tuple(closed_trades)
    ids = tuple(trade.trade_id for trade in trades)
    if len(ids) != len(set(ids)):
        raise ProspectiveFullStackExitCapacityReflowError(
            "journal contains duplicate trade ids"
        )

    prospective_opportunities = tuple(
        evidence
        for evidence in opportunities
        if evidence.opportunity_timestamp_ms >= overlap_start
    )

    baseline_capacity_rejections = 0
    missing_rank = 0
    stale_rank = 0
    momentum_integrity_misses = 0
    journal_future_close_exposure_opportunities = 0
    entry_stack_blocked_opportunities = 0
    entry_stack_eligible_opportunities = 0
    pre_overlap_release_positions = 0
    missing_full_stack_decision = 0
    non_admitted_release_positions = 0
    missing_breakeven_outcomes = 0
    non_exact_breakeven_outcomes = 0
    not_yet_released_positions = 0

    by_release_market: Counter[str] = Counter()
    by_opportunity_market: Counter[str] = Counter()
    releases: list[CandidateCausedCapacityRelease] = []
    terminal_contributions: dict[str, Decimal] = {}
    seen_release_keys: set[tuple[str, str]] = set()

    for evidence in prospective_opportunities:
        if evidence.baseline_risk_approved:
            continue
        if not evidence.baseline_risk_reason_codes:
            raise ProspectiveFullStackExitCapacityReflowError(
                "rejected opportunity is missing risk reason"
            )
        if (
            evidence.baseline_risk_reason_codes[0]
            not in RISK_CAPACITY_REJECTION_REASONS
        ):
            continue
        baseline_capacity_rejections += 1
        if future_finalized_open_exposure(
            trades,
            timestamp_ms=evidence.opportunity_timestamp_ms,
            overlap_started_at_ms=overlap_start,
            market=evidence.market,
            direction=evidence.direction,
        ):
            journal_future_close_exposure_opportunities += 1

        rank_age_ms = _rank_age_ms(evidence)
        ordinal = evidence.rank_ordinal
        if rank_age_ms is None or ordinal is None:
            missing_rank += 1
            continue
        if rank_age_ms > MAX_ACCEPTED_RANK_AGE_MS:
            stale_rank += 1
            continue

        request = evidence.risk_request_object
        direction = request.strategy_decision.direction
        if (
            request.strategy_decision.market.canonical != evidence.market
            or direction.value != evidence.direction
            or request.strategy_decision.feature_snapshot_id
            != evidence.feature_snapshot_id
        ):
            raise ProspectiveFullStackExitCapacityReflowError(
                "opening opportunity decision lineage mismatch"
            )
        if direction is Direction.NO_TRADE:
            raise ProspectiveFullStackExitCapacityReflowError(
                "opening opportunity direction cannot be no-trade"
            )
        combined_reason = prospective_combined_block_reason(
            direction=direction,
            lead_strategy=evidence.lead_strategy,
            ordinal=ordinal,
        )
        decision_time_closed_trades = terminal_trades_known_at(
            trades, timestamp_ms=evidence.opportunity_timestamp_ms
        )
        prior_strikes = prospective_two_strike_prior_strikes_at(
            decision_time_closed_trades,
            two_strike_state,
            market=evidence.market,
            direction=direction,
            timestamp_ms=evidence.opportunity_timestamp_ms,
        )
        momentum_detail = prospective_momentum_band_opportunity_decision(
            decision_time_closed_trades,
            feature_store,
            momentum_state,
            market=request.strategy_decision.market,
            direction=direction,
            timestamp_ms=evidence.opportunity_timestamp_ms,
            feature_snapshot_id=evidence.feature_snapshot_id,
        )
        momentum_reason = momentum_detail.get("reason")
        if momentum_reason in MOMENTUM_INTEGRITY_REASONS:
            momentum_integrity_misses += 1
            continue
        momentum_decision = momentum_detail.get("decision")
        if momentum_decision not in {"ADMIT", "BLOCK"}:
            raise ProspectiveFullStackExitCapacityReflowError(
                "momentum opportunity decision is invalid"
            )
        if (
            combined_reason is not None
            or prior_strikes >= STRIKE_THRESHOLD
            or momentum_decision == "BLOCK"
        ):
            entry_stack_blocked_opportunities += 1
            continue
        entry_stack_eligible_opportunities += 1

        for position in request.open_positions:
            trade = _active_trade(
                trades,
                market=position.market.canonical,
                direction=position.direction,
                opportunity_timestamp_ms=evidence.opportunity_timestamp_ms,
            )
            if trade is None:
                continue
            if trade.opened_at_ms < overlap_start:
                pre_overlap_release_positions += 1
                continue

            raw_decision = raw_decisions.get(trade.trade_id)
            if not isinstance(raw_decision, dict):
                missing_full_stack_decision += 1
                continue
            if raw_decision.get("entry_decision") != "ADMIT":
                non_admitted_release_positions += 1
                continue

            outcome = outcomes.get(trade.trade_id)
            if outcome is None:
                missing_breakeven_outcomes += 1
                continue
            if (
                outcome.opening_plan_id != trade.opening_plan_id
                or outcome.market != trade.market.canonical
                or outcome.direction != trade.direction.value
                or outcome.actual_net_pnl != trade.net_pnl
                or outcome.actual_net_r != trade.net_r
            ):
                raise ProspectiveFullStackExitCapacityReflowError(
                    "breakeven outcome journal lineage drift"
                )
            if (
                not outcome.triggered
                or not outcome.simulated_close_complete
                or outcome.candidate_source != "visible_book_ioc"
                or outcome.completion_timestamp_ms is None
                or outcome.candidate_net_pnl_estimate is None
            ):
                non_exact_breakeven_outcomes += 1
                continue
            if (
                outcome.completion_timestamp_ms <= trade.opened_at_ms
                or outcome.completion_timestamp_ms > trade.closed_at_ms
            ):
                raise ProspectiveFullStackExitCapacityReflowError(
                    "breakeven completion timestamp is outside trade lifetime"
                )
            if (
                outcome.completion_timestamp_ms
                > evidence.opportunity_timestamp_ms
            ):
                not_yet_released_positions += 1
                continue

            key = (evidence.opportunity_id, trade.opening_plan_id)
            if key in seen_release_keys:
                raise ProspectiveFullStackExitCapacityReflowError(
                    "duplicate exit-driven capacity release"
                )
            seen_release_keys.add(key)
            candidate_contribution = outcome.candidate_net_pnl_estimate
            assert candidate_contribution is not None
            existing_contribution = terminal_contributions.get(
                trade.opening_plan_id
            )
            if (
                existing_contribution is not None
                and existing_contribution != candidate_contribution
            ):
                raise ProspectiveFullStackExitCapacityReflowError(
                    "early-release terminal contribution drift"
                )
            terminal_contributions[trade.opening_plan_id] = (
                candidate_contribution
            )
            by_release_market[trade.market.canonical] += 1
            by_opportunity_market[evidence.market] += 1
            releases.append(
                CandidateCausedCapacityRelease(
                    opportunity_id=evidence.opportunity_id,
                    opportunity_timestamp_ms=(
                        evidence.opportunity_timestamp_ms
                    ),
                    opportunity_market=evidence.market,
                    release_market=trade.market.canonical,
                    release_correlation_bucket=(
                        position.correlation_bucket
                    ),
                    release_opening_plan_id=trade.opening_plan_id,
                    release_block_reason=RELEASE_REASON,
                )
            )

    values = tuple(
        sorted(
            releases,
            key=lambda item: (
                item.opportunity_timestamp_ms,
                item.opportunity_market,
                item.release_market,
                item.release_opening_plan_id,
            ),
        )
    )
    release_opportunities = {
        item.opportunity_id for item in values
    }
    release_positions = {
        item.release_opening_plan_id for item in values
    }
    integrity_clean = (
        missing_rank == 0
        and stale_rank == 0
        and momentum_integrity_misses == 0
        and missing_full_stack_decision == 0
        and missing_breakeven_outcomes == 0
        and journal_future_close_exposure_opportunities == 0
    )
    summary: dict[str, object] = {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "descriptive_only": True,
        "changes_readiness_gate": False,
        "claim_scope": "exact_breakeven_caused_capacity_release",
        "portfolio_counterfactual": False,
        "recursive_replacements_modeled": False,
        "replacement_entries_modeled": False,
        "replacement_exits_modeled": False,
        "pnl_modeled": False,
        "overlap_started_at_ms": overlap_start,
        "observed_opportunities": len(prospective_opportunities),
        "baseline_capacity_rejections": baseline_capacity_rejections,
        "missing_rank_evidence": missing_rank,
        "stale_rank_evidence": stale_rank,
        "momentum_feature_integrity_misses": momentum_integrity_misses,
        "journal_future_close_exposure_opportunities": (
            journal_future_close_exposure_opportunities
        ),
        "journal_asof_provenance": "closed_trades_only_no_original_open_event_witness",
        "entry_stack_blocked_opportunities": (
            entry_stack_blocked_opportunities
        ),
        "entry_stack_eligible_opportunities": (
            entry_stack_eligible_opportunities
        ),
        "pre_overlap_release_positions": pre_overlap_release_positions,
        "missing_full_stack_decision": missing_full_stack_decision,
        "non_admitted_release_positions": non_admitted_release_positions,
        "missing_breakeven_outcomes": missing_breakeven_outcomes,
        "non_exact_breakeven_outcomes": non_exact_breakeven_outcomes,
        "not_yet_released_positions": not_yet_released_positions,
        "candidate_early_release_options": len(values),
        "candidate_capacity_release_opportunities": (
            len(release_opportunities)
        ),
        "candidate_early_released_positions": len(release_positions),
        "by_release_market": dict(sorted(by_release_market.items())),
        "by_opportunity_market": dict(
            sorted(by_opportunity_market.items())
        ),
        "release_terminal_contribution_by_opening_plan": {
            plan_id: str(value)
            for plan_id, value in sorted(terminal_contributions.items())
        },
        "integrity_clean": integrity_clean,
    }
    return ProspectiveFullStackExitCapacityReflowEvaluation(
        releases=values,
        release_terminal_contributions=tuple(
            sorted(terminal_contributions.items())
        ),
        summary=summary,
    )
