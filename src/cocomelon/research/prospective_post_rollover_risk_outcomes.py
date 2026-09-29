from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from cocomelon.domain.execution import PaperOrderPlan
from cocomelon.research.continuous_paper_learning import (
    ContinuousPaperOpeningLineage,
    ContinuousPaperOpeningLineageStore,
)
from cocomelon.research.continuous_paper_opening_opportunity import (
    ContinuousPaperOpeningOpportunityEvidence,
    ContinuousPaperOpeningOpportunityStore,
)
from cocomelon.research.prospective_combined_entry_filter import (
    MAX_ACCEPTED_RANK_AGE_MS,
    TOP10_MAX_ORDINAL,
)

SCHEMA_VERSION: Final = 1
COHORT_ID: Final = "post-utc-daily-ledger-rollover-v1"

PlanLoader = Callable[[str], PaperOrderPlan | None]


class ProspectivePostRolloverRiskOutcomeError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProspectivePostRolloverRiskOutcomeState:
    started_at_ms: int
    schema_version: int = SCHEMA_VERSION
    cohort_id: str = COHORT_ID

    def __post_init__(self) -> None:
        if self.started_at_ms < 0:
            raise ValueError("started_at_ms must be non-negative")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(
                "unsupported post-rollover outcome state schema"
            )
        if self.cohort_id != COHORT_ID:
            raise ValueError("unsupported post-rollover outcome cohort")

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "cohort_id": self.cohort_id,
            "started_at_ms": self.started_at_ms,
        }

    @classmethod
    def from_payload(
        cls,
        raw: object,
    ) -> ProspectivePostRolloverRiskOutcomeState:
        if not isinstance(raw, dict) or set(raw) != {
            "schema_version",
            "cohort_id",
            "started_at_ms",
        }:
            raise ProspectivePostRolloverRiskOutcomeError(
                "post-rollover outcome state must match canonical fields"
            )
        schema_version = raw["schema_version"]
        started_at_ms = raw["started_at_ms"]
        cohort_id = raw["cohort_id"]
        if isinstance(schema_version, bool) or not isinstance(
            schema_version,
            int,
        ):
            raise ProspectivePostRolloverRiskOutcomeError(
                "schema_version must be an integer"
            )
        if isinstance(started_at_ms, bool) or not isinstance(
            started_at_ms,
            int,
        ):
            raise ProspectivePostRolloverRiskOutcomeError(
                "started_at_ms must be an integer"
            )
        if not isinstance(cohort_id, str):
            raise ProspectivePostRolloverRiskOutcomeError(
                "cohort_id must be a string"
            )
        try:
            return cls(
                started_at_ms=started_at_ms,
                schema_version=schema_version,
                cohort_id=cohort_id,
            )
        except ValueError as exc:
            raise ProspectivePostRolloverRiskOutcomeError(
                str(exc)
            ) from exc


def _candidate_eligible(
    opportunity: ContinuousPaperOpeningOpportunityEvidence,
) -> bool | None:
    if (
        opportunity.rank_ordinal is None
        or opportunity.rank_observed_at_ms is None
    ):
        return None
    rank_age_ms = (
        opportunity.opportunity_timestamp_ms
        - opportunity.rank_observed_at_ms
    )
    if rank_age_ms < 0:
        raise ProspectivePostRolloverRiskOutcomeError(
            "opening opportunity rank is from the future"
        )
    if rank_age_ms > MAX_ACCEPTED_RANK_AGE_MS:
        return None
    if opportunity.rank_ordinal > TOP10_MAX_ORDINAL:
        return False
    if (
        opportunity.direction == "long"
        and opportunity.lead_strategy == "trend"
    ):
        return False
    return True


def prospective_post_rollover_risk_outcome_summary(
    opportunities: tuple[
        ContinuousPaperOpeningOpportunityEvidence,
        ...,
    ],
    lineages: tuple[ContinuousPaperOpeningLineage, ...],
    *,
    plan_loader: PlanLoader,
    state: ProspectivePostRolloverRiskOutcomeState,
) -> dict[str, object]:
    prospective = tuple(
        opportunity
        for opportunity in opportunities
        if opportunity.opportunity_timestamp_ms >= state.started_at_ms
    )

    plans_by_strategy_decision: dict[str, PaperOrderPlan] = {}
    lineage_plan_misses = 0
    lineage_mismatches = 0
    for lineage in lineages:
        if lineage.opened_at_ms < state.started_at_ms:
            continue
        plan = plan_loader(lineage.opening_plan_id)
        if plan is None:
            lineage_plan_misses += 1
            continue
        if (
            plan.plan_id != lineage.opening_plan_id
            or plan.market.canonical != lineage.market
        ):
            lineage_mismatches += 1
            continue
        existing = plans_by_strategy_decision.get(
            plan.strategy_decision_id
        )
        if existing is not None and existing.plan_id != plan.plan_id:
            raise ProspectivePostRolloverRiskOutcomeError(
                "multiple filled opening plans share strategy decision"
            )
        plans_by_strategy_decision[plan.strategy_decision_id] = plan

    approvals = tuple(
        item for item in prospective if item.baseline_risk_approved
    )
    rejections = tuple(
        item for item in prospective if not item.baseline_risk_approved
    )
    rejection_reasons: Counter[str] = Counter()
    for item in rejections:
        rejection_reasons.update(item.baseline_risk_reason_codes)

    filled_approvals = 0
    approved_fill_lineage_mismatches = 0
    filled_strategy_ids: set[str] = set()
    for item in approvals:
        plan = plans_by_strategy_decision.get(
            item.strategy_decision_id
        )
        if plan is None:
            continue
        if (
            plan.risk_decision_id
            != item.baseline_risk_decision_id
            or plan.market.canonical != item.market
        ):
            approved_fill_lineage_mismatches += 1
            continue
        filled_approvals += 1
        filled_strategy_ids.add(item.strategy_decision_id)

    rank_missing = 0
    rank_stale = 0
    candidate_eligible = 0
    candidate_eligible_approvals = 0
    candidate_eligible_rejections = 0
    candidate_eligible_fills = 0
    candidate_eligible_daily_loss_lockouts = 0
    for item in prospective:
        if (
            item.rank_ordinal is None
            or item.rank_observed_at_ms is None
        ):
            rank_missing += 1
            continue
        age_ms = (
            item.opportunity_timestamp_ms
            - item.rank_observed_at_ms
        )
        if age_ms < 0:
            raise ProspectivePostRolloverRiskOutcomeError(
                "opening opportunity rank is from the future"
            )
        if age_ms > MAX_ACCEPTED_RANK_AGE_MS:
            rank_stale += 1
            continue
        eligible = _candidate_eligible(item)
        if eligible is not True:
            continue
        candidate_eligible += 1
        if item.baseline_risk_approved:
            candidate_eligible_approvals += 1
            if item.strategy_decision_id in filled_strategy_ids:
                candidate_eligible_fills += 1
        else:
            candidate_eligible_rejections += 1
            if "daily_loss_lockout" in item.baseline_risk_reason_codes:
                candidate_eligible_daily_loss_lockouts += 1

    integrity_clean = (
        lineage_plan_misses == 0
        and lineage_mismatches == 0
        and approved_fill_lineage_mismatches == 0
        and rank_missing == 0
        and rank_stale == 0
    )
    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "cohort_id": state.cohort_id,
        "started_at_ms": state.started_at_ms,
        "claim_scope": (
            "prospective_post_daily_ledger_fix_risk_and_fill_outcomes"
        ),
        "opportunities": len(prospective),
        "risk_approvals": len(approvals),
        "risk_rejections": len(rejections),
        "filled_approvals": filled_approvals,
        "approved_without_observed_fill": (
            len(approvals) - filled_approvals
        ),
        "daily_loss_lockout_rejections": rejection_reasons.get(
            "daily_loss_lockout",
            0,
        ),
        "by_rejection_reason": dict(
            sorted(rejection_reasons.items())
        ),
        "lineage_plan_misses": lineage_plan_misses,
        "lineage_mismatches": lineage_mismatches,
        "approved_fill_lineage_mismatches": (
            approved_fill_lineage_mismatches
        ),
        "rank_missing": rank_missing,
        "rank_stale": rank_stale,
        "candidate_eligible_opportunities": candidate_eligible,
        "candidate_eligible_risk_approvals": (
            candidate_eligible_approvals
        ),
        "candidate_eligible_risk_rejections": (
            candidate_eligible_rejections
        ),
        "candidate_eligible_filled_approvals": (
            candidate_eligible_fills
        ),
        "candidate_eligible_daily_loss_lockout_rejections": (
            candidate_eligible_daily_loss_lockouts
        ),
        "integrity_clean": integrity_clean,
        "replacement_trades_modeled": False,
        "pnl_modeled": False,
    }


def evaluate_prospective_post_rollover_risk_outcomes(
    opportunity_store: ContinuousPaperOpeningOpportunityStore,
    lineage_store: ContinuousPaperOpeningLineageStore,
    *,
    plan_loader: PlanLoader,
    state: ProspectivePostRolloverRiskOutcomeState,
) -> dict[str, object]:
    return prospective_post_rollover_risk_outcome_summary(
        opportunity_store.iter_records(),
        lineage_store.iter_records(),
        plan_loader=plan_loader,
        state=state,
    )
