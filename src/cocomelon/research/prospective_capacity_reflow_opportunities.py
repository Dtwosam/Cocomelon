from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Final

from cocomelon.domain.risk import OpenPositionRisk, RiskRequest
from cocomelon.research.continuous_paper_opening_opportunity import (
    ContinuousPaperOpeningOpportunityEvidence,
    ContinuousPaperOpeningOpportunityStore,
)
from cocomelon.research.prospective_combined_entry_filter import (
    MAX_ACCEPTED_RANK_AGE_MS,
    TOP10_MAX_ORDINAL,
    ProspectiveCombinedEntryFilterState,
)
from cocomelon.risk.capacity import calculate_risk_capacity
from cocomelon.risk.market_caps import calculate_market_caps
from cocomelon.risk.sizing import calculate_base_sizing

RISK_CAPACITY_REJECTION_REASONS: Final = frozenset(
    {
        "aggregate_risk_exhausted",
        "correlation_bucket_exhausted",
    }
)


class ProspectiveCapacityReflowOpportunityError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _ReleaseOption:
    market: str
    correlation_bucket: str


@dataclass(frozen=True, slots=True)
class CapacityReleaseOpportunityOption:
    opportunity_id: str
    opportunity_timestamp_ms: int
    opportunity_market: str
    release_market: str
    release_correlation_bucket: str


def _candidate_block_reason(
    evidence: ContinuousPaperOpeningOpportunityEvidence,
) -> str | None:
    ordinal = evidence.rank_ordinal
    if ordinal is None:
        raise ProspectiveCapacityReflowOpportunityError(
            "candidate block reason requires scanner rank"
        )
    long_trend = (
        evidence.direction == "long"
        and evidence.lead_strategy == "trend"
    )
    below_rank_cut = ordinal > TOP10_MAX_ORDINAL
    if long_trend and below_rank_cut:
        return "long_trend_and_rank_above_10"
    if long_trend:
        return "long_trend"
    if below_rank_cut:
        return "rank_above_10"
    return None


def _rank_age_ms(
    evidence: ContinuousPaperOpeningOpportunityEvidence,
) -> int | None:
    observed_at_ms = evidence.rank_observed_at_ms
    if observed_at_ms is None:
        return None
    age = evidence.opportunity_timestamp_ms - observed_at_ms
    if age < 0:
        raise ProspectiveCapacityReflowOpportunityError(
            "opening opportunity rank is from the future"
        )
    return age


def _request_without_position(
    request: RiskRequest,
    position: OpenPositionRisk,
) -> RiskRequest:
    removed = False
    remaining: list[OpenPositionRisk] = []
    for candidate in request.open_positions:
        if not removed and candidate == position:
            removed = True
            continue
        remaining.append(candidate)
    if not removed:
        raise ProspectiveCapacityReflowOpportunityError(
            "release position is absent from risk request"
        )
    return replace(request, open_positions=tuple(remaining))


def single_position_capacity_release_risk_positions(
    request: RiskRequest,
    baseline_risk_reason_codes: tuple[str, ...],
) -> tuple[OpenPositionRisk, ...]:
    if not baseline_risk_reason_codes:
        raise ProspectiveCapacityReflowOpportunityError(
            "rejected opportunity is missing risk reason"
        )
    baseline_reason = baseline_risk_reason_codes[0]
    if baseline_reason not in RISK_CAPACITY_REJECTION_REASONS:
        return ()

    stop = request.strategy_decision.invalidation_price
    if stop is None:
        return ()
    sizing = calculate_base_sizing(
        entry_price=request.entry_reference_price,
        stop_price=stop,
        equity=request.account_state.equity,
        costs=request.cost_estimate,
        limits=request.limits,
    )

    positions: list[OpenPositionRisk] = []
    for position in request.open_positions:
        counterfactual = _request_without_position(
            request,
            position,
        )
        capacity = calculate_risk_capacity(
            counterfactual,
            target_risk_amount=sizing.target_risk_amount,
        )
        if (
            capacity.rejection_reason is None
            and capacity.approved_risk_amount > 0
        ):
            positions.append(position)
    return tuple(positions)


def _single_position_release_options(
    evidence: ContinuousPaperOpeningOpportunityEvidence,
) -> tuple[_ReleaseOption, ...]:
    if evidence.baseline_risk_approved:
        return ()
    request = evidence.risk_request_object
    return tuple(
        _ReleaseOption(
            market=position.market.canonical,
            correlation_bucket=position.correlation_bucket,
        )
        for position in single_position_capacity_release_risk_positions(
            request,
            evidence.baseline_risk_reason_codes,
        )
    )


def single_position_capacity_release_options(
    evidence: ContinuousPaperOpeningOpportunityEvidence,
) -> tuple[CapacityReleaseOpportunityOption, ...]:
    return tuple(
        CapacityReleaseOpportunityOption(
            opportunity_id=evidence.opportunity_id,
            opportunity_timestamp_ms=evidence.opportunity_timestamp_ms,
            opportunity_market=evidence.market,
            release_market=option.market,
            release_correlation_bucket=option.correlation_bucket,
        )
        for option in _single_position_release_options(evidence)
    )


def candidate_eligible_capacity_release_options(
    opportunities: tuple[
        ContinuousPaperOpeningOpportunityEvidence,
        ...,
    ],
    state: ProspectiveCombinedEntryFilterState,
) -> tuple[CapacityReleaseOpportunityOption, ...]:
    output: list[CapacityReleaseOpportunityOption] = []
    for evidence in opportunities:
        if evidence.opportunity_timestamp_ms < state.started_at_ms:
            continue
        if evidence.baseline_risk_approved:
            continue
        if not evidence.baseline_risk_reason_codes:
            raise ProspectiveCapacityReflowOpportunityError(
                "rejected opportunity is missing risk reason"
            )
        rank_age_ms = _rank_age_ms(evidence)
        if rank_age_ms is None or evidence.rank_ordinal is None:
            continue
        if rank_age_ms > MAX_ACCEPTED_RANK_AGE_MS:
            continue
        if _candidate_block_reason(evidence) is not None:
            continue
        if (
            evidence.baseline_risk_reason_codes[0]
            not in RISK_CAPACITY_REJECTION_REASONS
        ):
            continue
        output.extend(
            single_position_capacity_release_options(evidence)
        )
    return tuple(
        sorted(
            output,
            key=lambda item: (
                item.opportunity_timestamp_ms,
                item.opportunity_market,
                item.release_market,
                item.opportunity_id,
            ),
        )
    )


def _minimum_notional_diagnostic(
    evidence: ContinuousPaperOpeningOpportunityEvidence,
) -> dict[str, object]:
    request = evidence.risk_request_object
    venue_minimum = request.liquidity_state.venue_min_notional
    stop = request.strategy_decision.invalidation_price
    if venue_minimum is None or stop is None:
        raise ProspectiveCapacityReflowOpportunityError(
            "minimum-notional rejection lacks frozen venue minimum or stop"
        )
    sizing = calculate_base_sizing(
        entry_price=request.entry_reference_price,
        stop_price=stop,
        equity=request.account_state.equity,
        costs=request.cost_estimate,
        limits=request.limits,
    )
    capacity = calculate_risk_capacity(
        request,
        target_risk_amount=sizing.target_risk_amount,
    )
    if capacity.rejection_reason is not None:
        raise ProspectiveCapacityReflowOpportunityError(
            "minimum-notional rejection conflicts with risk-capacity rejection"
        )
    market_caps = calculate_market_caps(
        request,
        approved_risk_amount=capacity.approved_risk_amount,
        effective_loss_fraction=sizing.effective_loss_fraction,
        raw_notional=sizing.raw_notional,
    )
    if market_caps.rejection_reason != "below_venue_min_notional":
        raise ProspectiveCapacityReflowOpportunityError(
            "minimum-notional rejection does not reproduce"
        )

    pre_minimum_notional = min(
        sizing.raw_notional,
        market_caps.risk_notional,
        market_caps.gross_capacity,
        market_caps.margin_capacity,
        market_caps.liquidity_capacity,
    )
    blockers: list[str] = []
    if sizing.raw_notional < venue_minimum:
        blockers.append("target_trade_risk")
    if market_caps.risk_notional < venue_minimum:
        blockers.append("aggregate_or_bucket_risk_capacity")
    if market_caps.gross_capacity < venue_minimum:
        blockers.append("gross_leverage_capacity")
    if market_caps.margin_capacity < venue_minimum:
        blockers.append("margin_capacity")
    if market_caps.liquidity_capacity < venue_minimum:
        blockers.append("visible_depth_capacity")
    if not blockers:
        raise ProspectiveCapacityReflowOpportunityError(
            "minimum-notional rejection has no sub-minimum safety cap"
        )

    minimum_notional_risk = (
        venue_minimum * sizing.effective_loss_fraction
    )
    forced_risk_overage = max(
        Decimal("0"),
        minimum_notional_risk - capacity.approved_risk_amount,
    )
    return {
        "market": evidence.market,
        "direction": evidence.direction,
        "venue_min_notional": str(venue_minimum),
        "pre_min_notional": str(pre_minimum_notional),
        "notional_shortfall": str(
            venue_minimum - pre_minimum_notional
        ),
        "minimum_notional_risk": str(minimum_notional_risk),
        "approved_risk_amount": str(capacity.approved_risk_amount),
        "forced_risk_overage": str(forced_risk_overage),
        "limiting_factors": tuple(blockers),
    }


def prospective_capacity_reflow_opportunity_summary(
    opportunities: tuple[
        ContinuousPaperOpeningOpportunityEvidence,
        ...,
    ],
    state: ProspectiveCombinedEntryFilterState,
) -> dict[str, object]:
    prospective = tuple(
        evidence
        for evidence in opportunities
        if evidence.opportunity_timestamp_ms >= state.started_at_ms
    )
    baseline_rejections = tuple(
        evidence
        for evidence in prospective
        if not evidence.baseline_risk_approved
    )

    baseline_reason_counts: Counter[str] = Counter()
    for evidence in baseline_rejections:
        if not evidence.baseline_risk_reason_codes:
            raise ProspectiveCapacityReflowOpportunityError(
                "rejected opportunity is missing risk reason"
            )
        baseline_reason_counts.update(
            evidence.baseline_risk_reason_codes
        )

    missing_rank_evidence = 0
    stale_rank_evidence = 0
    candidate_eligible_rejections: list[
        ContinuousPaperOpeningOpportunityEvidence
    ] = []
    candidate_blocked_rejections: list[
        ContinuousPaperOpeningOpportunityEvidence
    ] = []
    candidate_block_reason_counts: Counter[str] = Counter()

    for evidence in baseline_rejections:
        rank_age_ms = _rank_age_ms(evidence)
        if rank_age_ms is None or evidence.rank_ordinal is None:
            missing_rank_evidence += 1
            continue
        if rank_age_ms > MAX_ACCEPTED_RANK_AGE_MS:
            stale_rank_evidence += 1
            continue
        block_reason = _candidate_block_reason(evidence)
        if block_reason is None:
            candidate_eligible_rejections.append(evidence)
        else:
            candidate_blocked_rejections.append(evidence)
            candidate_block_reason_counts[block_reason] += 1

    eligible_capacity_rejections = tuple(
        evidence
        for evidence in candidate_eligible_rejections
        if evidence.baseline_risk_reason_codes[0]
        in RISK_CAPACITY_REJECTION_REASONS
    )
    release_options: dict[
        str,
        tuple[_ReleaseOption, ...],
    ] = {}
    for evidence in eligible_capacity_rejections:
        options = _single_position_release_options(evidence)
        if options:
            release_options[evidence.opportunity_id] = options

    minimum_notional_rejections = tuple(
        evidence
        for evidence in candidate_eligible_rejections
        if evidence.baseline_risk_reason_codes[0]
        == "below_venue_min_notional"
    )
    minimum_notional_diagnostics = tuple(
        _minimum_notional_diagnostic(evidence)
        for evidence in minimum_notional_rejections
    )
    minimum_notional_limiting_factors: Counter[str] = Counter()
    minimum_notional_by_market: Counter[str] = Counter()
    minimum_notional_shortfall = Decimal("0")
    forced_risk_overage = Decimal("0")
    for diagnostic in minimum_notional_diagnostics:
        factors = diagnostic["limiting_factors"]
        if not isinstance(factors, tuple):
            raise ProspectiveCapacityReflowOpportunityError(
                "minimum-notional limiting factors must be a tuple"
            )
        minimum_notional_limiting_factors.update(factors)
        minimum_notional_by_market[str(diagnostic["market"])] += 1
        minimum_notional_shortfall += Decimal(
            str(diagnostic["notional_shortfall"])
        )
        forced_risk_overage += Decimal(
            str(diagnostic["forced_risk_overage"])
        )

    by_release_market: Counter[str] = Counter()
    by_release_bucket: Counter[str] = Counter()
    for options in release_options.values():
        for option in options:
            by_release_market[option.market] += 1
            by_release_bucket[option.correlation_bucket] += 1

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "candidate_id": state.candidate_id,
        "started_at_ms": state.started_at_ms,
        "claim_scope": (
            "observed_opening_opportunity_capacity_release_sensitivity"
        ),
        "portfolio_counterfactual": False,
        "replacement_trades_modeled": False,
        "pnl_modeled": False,
        "one_position_capacity_release_sensitivity": True,
        "opportunities": len(prospective),
        "baseline_approvals": (
            len(prospective) - len(baseline_rejections)
        ),
        "baseline_rejections": len(baseline_rejections),
        "candidate_eligible_rejections": len(
            candidate_eligible_rejections
        ),
        "candidate_blocked_rejections": len(
            candidate_blocked_rejections
        ),
        "missing_rank_evidence": missing_rank_evidence,
        "stale_rank_evidence": stale_rank_evidence,
        "integrity_clean": (
            missing_rank_evidence == 0
            and stale_rank_evidence == 0
        ),
        "candidate_eligible_capacity_rejections": len(
            eligible_capacity_rejections
        ),
        "single_position_release_unblocked": len(
            release_options
        ),
        "single_position_release_options": sum(
            len(options)
            for options in release_options.values()
        ),
        "candidate_eligible_min_notional_rejections": len(
            minimum_notional_rejections
        ),
        "min_notional_notional_shortfall_sum": str(
            minimum_notional_shortfall
        ),
        "min_notional_forced_risk_overage_sum": str(
            forced_risk_overage
        ),
        "min_notional_safe_round_up": 0,
        "by_min_notional_limiting_factor": dict(
            sorted(minimum_notional_limiting_factors.items())
        ),
        "by_min_notional_market": dict(
            sorted(minimum_notional_by_market.items())
        ),
        "by_baseline_rejection_reason": dict(
            sorted(baseline_reason_counts.items())
        ),
        "by_candidate_block_reason": dict(
            sorted(candidate_block_reason_counts.items())
        ),
        "by_release_market": dict(
            sorted(by_release_market.items())
        ),
        "by_release_bucket": dict(
            sorted(by_release_bucket.items())
        ),
    }


def evaluate_prospective_capacity_reflow_opportunities(
    store: ContinuousPaperOpeningOpportunityStore,
    state: ProspectiveCombinedEntryFilterState,
) -> dict[str, object]:
    return prospective_capacity_reflow_opportunity_summary(
        store.iter_records(),
        state,
    )
