from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.strategy import Direction
from cocomelon.research.continuous_paper_learning import (
    ContinuousPaperOpeningLineage,
)
from cocomelon.research.continuous_paper_opening_opportunity import (
    ContinuousPaperOpeningOpportunityEvidence,
)
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotStore,
)
from cocomelon.research.prospective_capacity_reflow_opportunities import (
    RISK_CAPACITY_REJECTION_REASONS,
    CapacityReleaseOpportunityOption,
    single_position_capacity_release_options,
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

MOMENTUM_INTEGRITY_REASONS: Final = frozenset(
    {
        "missing_feature_fail_open",
        "incomplete_feature_fail_open",
    }
)


class ProspectiveFullStackCapacityReflowError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProspectiveFullStackCapacityReflowEvaluation:
    releases: tuple[CandidateCausedCapacityRelease, ...]
    summary: dict[str, object]


def _rank_age_ms(
    evidence: ContinuousPaperOpeningOpportunityEvidence,
) -> int | None:
    observed_at_ms = evidence.rank_observed_at_ms
    if observed_at_ms is None:
        return None
    age = evidence.opportunity_timestamp_ms - observed_at_ms
    if age < 0:
        raise ProspectiveFullStackCapacityReflowError(
            "opening opportunity rank is from the future"
        )
    return age


def _closed_by_plan(
    trades: tuple[TradeJournalEntry, ...],
) -> dict[str, TradeJournalEntry]:
    output: dict[str, TradeJournalEntry] = {}
    for trade in trades:
        existing = output.get(trade.opening_plan_id)
        if existing is not None and existing != trade:
            raise ProspectiveFullStackCapacityReflowError(
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
                raise ProspectiveFullStackCapacityReflowError(
                    "closed trade does not match opening lineage"
                )
            if closed.closed_at_ms < option.opportunity_timestamp_ms:
                continue
        candidates.append(lineage)

    if len(candidates) > 1:
        raise ProspectiveFullStackCapacityReflowError(
            "multiple active opening lineages for release market"
        )
    return None if not candidates else candidates[0]


def _required_decision_maps(
    combined: dict[str, object],
    two_strike: dict[str, object],
    momentum: dict[str, object],
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    combined_map = combined.get("decision_block_reason_by_trade_id")
    two_map = two_strike.get("decision_prior_strikes")
    momentum_map = momentum.get("decision_details")
    if not isinstance(combined_map, dict):
        raise ProspectiveFullStackCapacityReflowError(
            "combined decision map must be an object"
        )
    if not isinstance(two_map, dict):
        raise ProspectiveFullStackCapacityReflowError(
            "two-strike decision map must be an object"
        )
    if not isinstance(momentum_map, dict):
        raise ProspectiveFullStackCapacityReflowError(
            "momentum decision map must be an object"
        )
    return combined_map, two_map, momentum_map


def _release_block_reasons(
    trade: TradeJournalEntry,
    combined_map: dict[str, object],
    two_map: dict[str, object],
    momentum_map: dict[str, object],
) -> tuple[str, ...] | None:
    trade_id = trade.trade_id
    if (
        trade_id not in combined_map
        or trade_id not in two_map
        or trade_id not in momentum_map
    ):
        return None

    combined_reason = combined_map[trade_id]
    if combined_reason is not None and not isinstance(
        combined_reason,
        str,
    ):
        raise ProspectiveFullStackCapacityReflowError(
            "combined block reason must be a string or null"
        )
    prior_strikes = two_map[trade_id]
    if isinstance(prior_strikes, bool) or not isinstance(
        prior_strikes,
        int,
    ):
        raise ProspectiveFullStackCapacityReflowError(
            "two-strike prior strikes must be an integer"
        )
    momentum_detail = momentum_map[trade_id]
    if not isinstance(momentum_detail, dict):
        raise ProspectiveFullStackCapacityReflowError(
            "momentum decision detail must be an object"
        )
    momentum_decision = momentum_detail.get("decision")
    if momentum_decision not in {"ADMIT", "BLOCK"}:
        raise ProspectiveFullStackCapacityReflowError(
            "momentum decision must be ADMIT or BLOCK"
        )

    reasons: list[str] = []
    if combined_reason is not None:
        reasons.append(f"combined:{combined_reason}")
    if prior_strikes >= STRIKE_THRESHOLD:
        reasons.append("two_strike")
    if momentum_decision == "BLOCK":
        momentum_reason = momentum_detail.get("reason")
        if not isinstance(momentum_reason, str):
            raise ProspectiveFullStackCapacityReflowError(
                "momentum block reason must be a string"
            )
        reasons.append(f"momentum:{momentum_reason}")
    return tuple(reasons)


def prospective_full_stack_capacity_reflow(
    opportunities: tuple[ContinuousPaperOpeningOpportunityEvidence, ...],
    lineages: tuple[ContinuousPaperOpeningLineage, ...],
    closed_trades: tuple[TradeJournalEntry, ...],
    feature_store: LearningFeatureSnapshotStore,
    combined_state: ProspectiveCombinedEntryFilterState,
    two_strike_state: ProspectiveTwoStrikeStopFilterState,
    momentum_state: ProspectiveMomentumBandEntryState,
    combined_summary: dict[str, object],
    two_strike_summary: dict[str, object],
    momentum_summary: dict[str, object],
) -> ProspectiveFullStackCapacityReflowEvaluation:
    overlap_start = max(
        combined_state.started_at_ms,
        two_strike_state.started_at_ms,
        momentum_state.started_at_ms,
    )
    combined_map, two_map, momentum_map = _required_decision_maps(
        combined_summary,
        two_strike_summary,
        momentum_summary,
    )
    closed_by_plan = _closed_by_plan(closed_trades)

    prospective_opportunities = tuple(
        evidence
        for evidence in opportunities
        if evidence.opportunity_timestamp_ms >= overlap_start
    )
    baseline_capacity_rejections = 0
    missing_rank = 0
    stale_rank = 0
    momentum_feature_integrity_misses = 0
    full_stack_blocked_opportunities = 0
    full_stack_eligible_opportunities = 0
    single_release_options = 0
    release_lineage_misses = 0
    unresolved_release_positions = 0
    pre_start_release_positions = 0
    release_decision_map_misses = 0
    candidate_blocked_release_options = 0

    opportunity_block_reasons: Counter[str] = Counter()
    release_block_reasons: Counter[str] = Counter()
    by_release_market: Counter[str] = Counter()
    by_opportunity_market: Counter[str] = Counter()
    releases: list[CandidateCausedCapacityRelease] = []
    seen_release_keys: set[tuple[str, str]] = set()

    for evidence in prospective_opportunities:
        if evidence.baseline_risk_approved:
            continue
        if not evidence.baseline_risk_reason_codes:
            raise ProspectiveFullStackCapacityReflowError(
                "rejected opportunity is missing risk reason"
            )
        if (
            evidence.baseline_risk_reason_codes[0]
            not in RISK_CAPACITY_REJECTION_REASONS
        ):
            continue
        baseline_capacity_rejections += 1

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
        if direction is Direction.NO_TRADE:
            raise ProspectiveFullStackCapacityReflowError(
                "opening opportunity direction cannot be no-trade"
            )
        if (
            request.strategy_decision.market.canonical != evidence.market
            or direction.value != evidence.direction
            or request.strategy_decision.feature_snapshot_id
            != evidence.feature_snapshot_id
        ):
            raise ProspectiveFullStackCapacityReflowError(
                "opening opportunity decision lineage mismatch"
            )

        combined_reason = prospective_combined_block_reason(
            direction=direction,
            lead_strategy=evidence.lead_strategy,
            ordinal=ordinal,
        )
        two_prior_strikes = prospective_two_strike_prior_strikes_at(
            closed_trades,
            two_strike_state,
            market=evidence.market,
            direction=direction,
            timestamp_ms=evidence.opportunity_timestamp_ms,
        )
        momentum_detail = prospective_momentum_band_opportunity_decision(
            closed_trades,
            feature_store,
            momentum_state,
            market=request.strategy_decision.market,
            direction=direction,
            timestamp_ms=evidence.opportunity_timestamp_ms,
            feature_snapshot_id=evidence.feature_snapshot_id,
        )
        momentum_reason = momentum_detail.get("reason")
        if momentum_reason in MOMENTUM_INTEGRITY_REASONS:
            momentum_feature_integrity_misses += 1
            continue
        momentum_decision = momentum_detail.get("decision")
        if momentum_decision not in {"ADMIT", "BLOCK"}:
            raise ProspectiveFullStackCapacityReflowError(
                "momentum opportunity decision is invalid"
            )

        reasons: list[str] = []
        if combined_reason is not None:
            reasons.append(f"combined:{combined_reason}")
        if two_prior_strikes >= STRIKE_THRESHOLD:
            reasons.append("two_strike")
        if momentum_decision == "BLOCK":
            if not isinstance(momentum_reason, str):
                raise ProspectiveFullStackCapacityReflowError(
                    "momentum opportunity block reason is invalid"
                )
            reasons.append(f"momentum:{momentum_reason}")

        if reasons:
            full_stack_blocked_opportunities += 1
            opportunity_block_reasons.update(reasons)
            continue

        full_stack_eligible_opportunities += 1
        options = single_position_capacity_release_options(evidence)
        single_release_options += len(options)
        for option in options:
            lineage = _active_lineage(
                option,
                lineages,
                closed_by_plan,
            )
            if lineage is None:
                release_lineage_misses += 1
                continue
            release_trade = closed_by_plan.get(lineage.opening_plan_id)
            if release_trade is None:
                unresolved_release_positions += 1
                continue
            if release_trade.opened_at_ms < overlap_start:
                pre_start_release_positions += 1
                continue

            block_reasons = _release_block_reasons(
                release_trade,
                combined_map,
                two_map,
                momentum_map,
            )
            if block_reasons is None:
                release_decision_map_misses += 1
                continue
            if not block_reasons:
                continue

            key = (option.opportunity_id, lineage.opening_plan_id)
            if key in seen_release_keys:
                raise ProspectiveFullStackCapacityReflowError(
                    "duplicate full-stack release option"
                )
            seen_release_keys.add(key)
            candidate_blocked_release_options += 1
            release_block_reasons.update(block_reasons)
            by_release_market[option.release_market] += 1
            by_opportunity_market[option.opportunity_market] += 1
            releases.append(
                CandidateCausedCapacityRelease(
                    opportunity_id=option.opportunity_id,
                    opportunity_timestamp_ms=(
                        option.opportunity_timestamp_ms
                    ),
                    opportunity_market=option.opportunity_market,
                    release_market=option.release_market,
                    release_correlation_bucket=(
                        option.release_correlation_bucket
                    ),
                    release_opening_plan_id=lineage.opening_plan_id,
                    release_block_reason="+".join(block_reasons),
                )
            )

    integrity_clean = (
        missing_rank == 0
        and stale_rank == 0
        and momentum_feature_integrity_misses == 0
        and release_lineage_misses == 0
        and unresolved_release_positions == 0
        and release_decision_map_misses == 0
    )
    release_values = tuple(
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
    summary: dict[str, object] = {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "descriptive_only": True,
        "changes_readiness_gate": False,
        "claim_scope": (
            "full_entry_stack_caused_single_position_capacity_release"
        ),
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
        "momentum_feature_integrity_misses": (
            momentum_feature_integrity_misses
        ),
        "full_stack_blocked_opportunities": (
            full_stack_blocked_opportunities
        ),
        "full_stack_eligible_opportunities": (
            full_stack_eligible_opportunities
        ),
        "single_position_release_options": single_release_options,
        "release_lineage_misses": release_lineage_misses,
        "unresolved_release_positions": unresolved_release_positions,
        "pre_start_release_positions": pre_start_release_positions,
        "release_decision_map_misses": release_decision_map_misses,
        "candidate_blocked_release_options": (
            candidate_blocked_release_options
        ),
        "candidate_capacity_release_opportunities": len(
            {release.opportunity_id for release in release_values}
        ),
        "integrity_clean": integrity_clean,
        "by_opportunity_block_reason": dict(
            sorted(opportunity_block_reasons.items())
        ),
        "by_release_position_block_reason": dict(
            sorted(release_block_reasons.items())
        ),
        "by_release_market": dict(sorted(by_release_market.items())),
        "by_opportunity_market": dict(
            sorted(by_opportunity_market.items())
        ),
    }
    return ProspectiveFullStackCapacityReflowEvaluation(
        releases=release_values,
        summary=summary,
    )
