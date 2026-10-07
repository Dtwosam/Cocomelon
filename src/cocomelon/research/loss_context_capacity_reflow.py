from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from typing import cast

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.research.continuous_paper_learning import (
    ContinuousPaperOpeningLineage,
)
from cocomelon.research.continuous_paper_opening_opportunity import (
    ContinuousPaperOpeningOpportunityEvidence,
)
from cocomelon.research.continuous_paper_opening_rank import (
    ContinuousPaperOpeningRankStore,
)
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotStore,
)
from cocomelon.research.loss_context_candidate import (
    LossContextCandidateFreeze,
)
from cocomelon.research.loss_streak_context_audit import (
    try_resolve_entry_context_row,
)
from cocomelon.research.prospective_capacity_reflow_opportunities import (
    RISK_CAPACITY_REJECTION_REASONS,
    CapacityReleaseOpportunityOption,
    single_position_capacity_release_options,
)
from cocomelon.research.prospective_capacity_reflow_release_lineage import (
    CandidateCausedCapacityRelease,
)

ZERO = Decimal("0")
LOSS_CONTEXT_CAPACITY_REFLOW_SCHEMA_VERSION = 1


class LossContextCapacityReflowError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class LossContextCapacityReflowEvaluation:
    releases: tuple[CandidateCausedCapacityRelease, ...]
    summary: dict[str, object]


def _closed_by_plan(
    trades: tuple[TradeJournalEntry, ...],
) -> dict[str, TradeJournalEntry]:
    output: dict[str, TradeJournalEntry] = {}
    for trade in trades:
        existing = output.get(trade.opening_plan_id)
        if existing is not None and existing != trade:
            raise LossContextCapacityReflowError(
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
                raise LossContextCapacityReflowError(
                    "closed trade does not match opening lineage"
                )
            if closed.closed_at_ms < option.opportunity_timestamp_ms:
                continue
        candidates.append(lineage)

    if len(candidates) > 1:
        raise LossContextCapacityReflowError(
            "multiple active opening lineages for release market"
        )
    return None if not candidates else candidates[0]


def _sign(value: Decimal | None) -> str:
    if value is None:
        return "missing"
    if value > ZERO:
        return "positive"
    if value < ZERO:
        return "negative"
    return "flat"


def _rank_band(ordinal: int | None) -> str:
    if ordinal is None:
        return "missing"
    if ordinal <= 3:
        return "top3"
    if ordinal <= 10:
        return "top10"
    return "outside10"


def _opportunity_context_row(
    evidence: ContinuousPaperOpeningOpportunityEvidence,
    feature_store: LearningFeatureSnapshotStore,
) -> dict[str, object] | None:
    verified = feature_store.load(evidence.feature_snapshot_id)
    if verified is None:
        return None
    feature = verified.snapshot
    if feature.market.canonical != evidence.market:
        raise LossContextCapacityReflowError(
            "replacement opportunity feature market mismatch"
        )
    if (
        feature.as_of_ms > evidence.opportunity_timestamp_ms
        or feature.source_received_at_ms
        > evidence.opportunity_timestamp_ms
    ):
        raise LossContextCapacityReflowError(
            "replacement opportunity feature is from the future"
        )
    return {
        "market": evidence.market,
        "direction": evidence.direction,
        "lead_strategy": evidence.lead_strategy,
        "trend_regime": feature.trend_regime.value,
        "volatility_regime": feature.volatility_regime.value,
        "return_15m_sign": _sign(feature.return_15m),
        "return_1h_sign": _sign(feature.return_1h),
        "rank_band": _rank_band(evidence.rank_ordinal),
    }


def _matches_context(
    row: dict[str, object],
    freeze: LossContextCandidateFreeze,
) -> bool:
    try:
        values = tuple(str(row[name]) for name in freeze.dimensions)
    except KeyError as exc:
        raise LossContextCapacityReflowError(
            f"loss-context reflow row missing dimension: {exc.args[0]}"
        ) from exc
    return values == freeze.values


def _validate_account_readiness(
    readiness: dict[str, object],
    freeze: LossContextCandidateFreeze,
) -> bool:
    if readiness.get("candidate_id") != freeze.candidate_id:
        raise LossContextCapacityReflowError(
            "LOSS_CONTEXT_REFLOW_CANDIDATE_MISMATCH"
        )
    for field in (
        "changes_strategy",
        "changes_risk_limits",
        "promotion_authority",
        "execution_authority",
    ):
        if readiness.get(field) is not False:
            raise LossContextCapacityReflowError(
                "LOSS_CONTEXT_REFLOW_AUTHORITY_INVALID"
            )
    if readiness.get("capacity_reflow_modeled") is not False:
        raise LossContextCapacityReflowError(
            "LOSS_CONTEXT_REFLOW_ALREADY_MODELED"
        )
    if (
        readiness.get("capacity_reflow_required_before_strategy_use")
        is not True
    ):
        raise LossContextCapacityReflowError(
            "LOSS_CONTEXT_REFLOW_REQUIREMENT_MISSING"
        )
    return (
        readiness.get("prospective_filter_review_ready") is True
        and readiness.get("fixed_schedule_economics_ready") is True
        and readiness.get("source_complete") is True
        and readiness.get("ready_for_capacity_reflow_investigation") is True
    )


def loss_context_capacity_reflow(
    opportunities: tuple[
        ContinuousPaperOpeningOpportunityEvidence,
        ...,
    ],
    lineages: tuple[ContinuousPaperOpeningLineage, ...],
    closed_trades: tuple[TradeJournalEntry, ...],
    feature_store: LearningFeatureSnapshotStore,
    fact_store: EvaluationFactStore,
    rank_store: ContinuousPaperOpeningRankStore,
    *,
    freeze: LossContextCandidateFreeze,
    account_readiness: dict[str, object],
) -> LossContextCapacityReflowEvaluation:
    gate_open = _validate_account_readiness(
        account_readiness,
        freeze,
    )
    if not gate_open:
        return LossContextCapacityReflowEvaluation(
            releases=(),
            summary={
                "candidate_id": freeze.candidate_id,
                "enabled": False,
                "gate_open": False,
                "gate_reason": "fixed_schedule_account_readiness_not_met",
                "research_only": True,
                "descriptive_only": True,
                "changes_strategy": False,
                "changes_risk_limits": False,
                "promotion_authority": False,
                "execution_authority": False,
                "replacement_entries_modeled": False,
                "replacement_exits_modeled": False,
                "replacement_pnl_modeled": False,
                "schema_version": LOSS_CONTEXT_CAPACITY_REFLOW_SCHEMA_VERSION,
            },
        )

    closed_by_plan = _closed_by_plan(closed_trades)
    prospective = tuple(
        evidence
        for evidence in opportunities
        if evidence.opportunity_timestamp_ms
        >= freeze.prospective_not_before_ms
    )

    baseline_capacity_rejections = 0
    newcomer_feature_misses = 0
    candidate_blocked_newcomers = 0
    candidate_eligible_capacity_rejections = 0
    single_release_options = 0
    release_lineage_misses = 0
    unresolved_release_positions = 0
    pre_boundary_release_positions = 0
    release_context_misses = 0
    candidate_allowed_release_options = 0
    candidate_blocked_release_options = 0

    by_baseline_reason: Counter[str] = Counter()
    by_release_market: Counter[str] = Counter()
    by_opportunity_market: Counter[str] = Counter()
    releases: list[CandidateCausedCapacityRelease] = []
    seen_release_keys: set[tuple[str, str]] = set()

    for evidence in prospective:
        if evidence.baseline_risk_approved:
            continue
        if not evidence.baseline_risk_reason_codes:
            raise LossContextCapacityReflowError(
                "rejected opening opportunity is missing risk reason"
            )
        baseline_reason = evidence.baseline_risk_reason_codes[0]
        if baseline_reason not in RISK_CAPACITY_REJECTION_REASONS:
            continue
        baseline_capacity_rejections += 1
        by_baseline_reason[baseline_reason] += 1

        newcomer_row = _opportunity_context_row(
            evidence,
            feature_store,
        )
        if newcomer_row is None:
            newcomer_feature_misses += 1
            continue
        if _matches_context(newcomer_row, freeze):
            candidate_blocked_newcomers += 1
            continue

        candidate_eligible_capacity_rejections += 1
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
            if lineage.opened_at_ms < freeze.prospective_not_before_ms:
                pre_boundary_release_positions += 1
                continue

            release_trade = closed_by_plan.get(lineage.opening_plan_id)
            if release_trade is None:
                unresolved_release_positions += 1
                continue
            row, reason = try_resolve_entry_context_row(
                release_trade,
                fact_store,
                feature_store,
                rank_store,
            )
            if row is None:
                release_context_misses += 1
                continue
            if not _matches_context(row, freeze):
                candidate_allowed_release_options += 1
                continue

            key = (
                option.opportunity_id,
                lineage.opening_plan_id,
            )
            if key in seen_release_keys:
                raise LossContextCapacityReflowError(
                    "duplicate loss-context capacity release option"
                )
            seen_release_keys.add(key)
            candidate_blocked_release_options += 1
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
                    release_block_reason="frozen_loss_context",
                )
            )

    integrity_clean = (
        newcomer_feature_misses == 0
        and release_lineage_misses == 0
        and unresolved_release_positions == 0
        and release_context_misses == 0
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
    return LossContextCapacityReflowEvaluation(
        releases=release_values,
        summary={
            "candidate_id": freeze.candidate_id,
            "dimensions": freeze.dimensions,
            "values": freeze.values,
            "prospective_not_before_ms": freeze.prospective_not_before_ms,
            "enabled": True,
            "gate_open": True,
            "research_only": True,
            "descriptive_only": True,
            "changes_strategy": False,
            "changes_risk_limits": False,
            "promotion_authority": False,
            "execution_authority": False,
            "claim_scope": (
                "loss_context_caused_single_position_capacity_release"
            ),
            "observed_future_opportunities": len(prospective),
            "baseline_capacity_rejections": baseline_capacity_rejections,
            "by_baseline_rejection_reason": dict(
                sorted(by_baseline_reason.items())
            ),
            "newcomer_feature_misses": newcomer_feature_misses,
            "candidate_blocked_newcomers": candidate_blocked_newcomers,
            "candidate_eligible_capacity_rejections": (
                candidate_eligible_capacity_rejections
            ),
            "single_position_release_options": single_release_options,
            "release_lineage_misses": release_lineage_misses,
            "unresolved_release_positions": unresolved_release_positions,
            "pre_boundary_release_positions": (
                pre_boundary_release_positions
            ),
            "release_context_misses": release_context_misses,
            "candidate_allowed_release_options": (
                candidate_allowed_release_options
            ),
            "candidate_blocked_release_options": (
                candidate_blocked_release_options
            ),
            "candidate_capacity_release_opportunities": len(
                {item.opportunity_id for item in release_values}
            ),
            "by_release_market": dict(sorted(by_release_market.items())),
            "by_opportunity_market": dict(
                sorted(by_opportunity_market.items())
            ),
            "integrity_clean": integrity_clean,
            "ready_for_replacement_fill_investigation": (
                integrity_clean and bool(release_values)
            ),
            "replacement_entries_modeled": False,
            "replacement_exits_modeled": False,
            "replacement_pnl_modeled": False,
            "recursive_replacements_modeled": False,
            "schema_version": LOSS_CONTEXT_CAPACITY_REFLOW_SCHEMA_VERSION,
        },
    )
