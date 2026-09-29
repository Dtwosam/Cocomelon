from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from cocomelon.domain.execution import PaperExecutionConfig, PaperOrderPlan
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.execution.accounting import PaperPosition
from cocomelon.journal.store import JournalStore
from cocomelon.research.continuous_paper_learning import (
    ContinuousPaperOpeningLineageStore,
)
from cocomelon.research.continuous_paper_opening_opportunity import (
    ContinuousPaperOpeningOpportunityStore,
)
from cocomelon.research.continuous_paper_opening_opportunity_paths import (
    ContinuousPaperOpeningOpportunityPath,
    ContinuousPaperOpeningOpportunityPathStore,
)
from cocomelon.research.continuous_paper_opening_rank import (
    ContinuousPaperOpeningRankStore,
)
from cocomelon.research.exact_decimal_aggregation import exact_decimal_sum
from cocomelon.research.prospective_capacity_reflow_fill_feasibility import (
    CandidateReplacementEntryFill,
    candidate_caused_replacement_entry_fill_records,
)
from cocomelon.research.prospective_capacity_reflow_opportunities import (
    candidate_eligible_capacity_release_options,
)
from cocomelon.research.prospective_capacity_reflow_release_lineage import (
    candidate_caused_capacity_release_options,
)
from cocomelon.research.prospective_combined_entry_filter import (
    ProspectiveCombinedEntryFilterState,
)

ZERO: Final = Decimal("0")


class ProspectiveCapacityReflowForwardMarkoutError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CandidateReplacementEntryForwardMarkout:
    opportunity_id: str
    opportunity_market: str
    direction: str
    release_market: str
    release_opening_plan_id: str
    replacement_plan_id: str
    execution_attempt_id: str
    filled_quantity: Decimal
    entry_vwap: Decimal
    entry_fee: Decimal
    fill_notional: Decimal
    horizon_target_ms: int
    horizon_observed_at_ms: int
    observation_lag_ms: int
    horizon_mark_px: Decimal
    gross_markout_cash: Decimal
    after_entry_fee_markout_cash: Decimal
    after_entry_fee_markout_fraction: Decimal

    def to_dict(self) -> dict[str, object]:
        return {
            "opportunity_id": self.opportunity_id,
            "opportunity_market": self.opportunity_market,
            "direction": self.direction,
            "release_market": self.release_market,
            "release_opening_plan_id": (
                self.release_opening_plan_id
            ),
            "replacement_plan_id": self.replacement_plan_id,
            "execution_attempt_id": self.execution_attempt_id,
            "filled_quantity": str(self.filled_quantity),
            "entry_vwap": str(self.entry_vwap),
            "entry_fee": str(self.entry_fee),
            "fill_notional": str(self.fill_notional),
            "horizon_target_ms": self.horizon_target_ms,
            "horizon_observed_at_ms": (
                self.horizon_observed_at_ms
            ),
            "observation_lag_ms": self.observation_lag_ms,
            "horizon_mark_px": str(self.horizon_mark_px),
            "gross_markout_cash": str(self.gross_markout_cash),
            "after_entry_fee_markout_cash": str(
                self.after_entry_fee_markout_cash
            ),
            "after_entry_fee_markout_fraction": str(
                self.after_entry_fee_markout_fraction
            ),
        }


def _path_by_opportunity(
    paths: tuple[ContinuousPaperOpeningOpportunityPath, ...],
) -> dict[str, ContinuousPaperOpeningOpportunityPath]:
    by_id: dict[str, ContinuousPaperOpeningOpportunityPath] = {}
    for path in paths:
        existing = by_id.get(path.opportunity_id)
        if existing is not None and existing != path:
            raise ProspectiveCapacityReflowForwardMarkoutError(
                "duplicate replacement markout paths"
            )
        by_id[path.opportunity_id] = path
    return by_id


def _completed_markout(
    record: CandidateReplacementEntryFill,
    path: ContinuousPaperOpeningOpportunityPath,
) -> CandidateReplacementEntryForwardMarkout:
    if (
        path.opportunity_id != record.opportunity_id
        or path.market != record.opportunity_market
        or path.direction != record.direction
        or path.opportunity_timestamp_ms
        != record.opportunity_timestamp_ms
    ):
        raise ProspectiveCapacityReflowForwardMarkoutError(
            "replacement markout path lineage mismatch"
        )
    if not path.complete:
        raise ProspectiveCapacityReflowForwardMarkoutError(
            "replacement markout requires completed path"
        )
    horizon_marks = tuple(
        mark
        for mark in path.marks
        if mark.observed_at_ms >= path.expires_at_ms
    )
    if len(horizon_marks) != 1:
        raise ProspectiveCapacityReflowForwardMarkoutError(
            "replacement markout horizon mark is ambiguous"
        )
    if (
        not record.fillable
        or record.average_fill_price is None
        or record.replacement_plan_id is None
        or record.execution_attempt_id is None
    ):
        raise ProspectiveCapacityReflowForwardMarkoutError(
            "replacement markout requires exact fill lineage"
        )
    mark = horizon_marks[0]
    if record.direction == "long":
        gross = (
            mark.mark_px - record.average_fill_price
        ) * record.filled_quantity
    elif record.direction == "short":
        gross = (
            record.average_fill_price - mark.mark_px
        ) * record.filled_quantity
    else:
        raise ProspectiveCapacityReflowForwardMarkoutError(
            "replacement markout direction is invalid"
        )
    after_entry_fee = gross - record.taker_fee
    if record.gross_fill_notional <= ZERO:
        raise ProspectiveCapacityReflowForwardMarkoutError(
            "replacement markout fill notional is non-positive"
        )
    return CandidateReplacementEntryForwardMarkout(
        opportunity_id=record.opportunity_id,
        opportunity_market=record.opportunity_market,
        direction=record.direction,
        release_market=record.release_market,
        release_opening_plan_id=(
            record.release_opening_plan_id
        ),
        replacement_plan_id=record.replacement_plan_id,
        execution_attempt_id=record.execution_attempt_id,
        filled_quantity=record.filled_quantity,
        entry_vwap=record.average_fill_price,
        entry_fee=record.taker_fee,
        fill_notional=record.gross_fill_notional,
        horizon_target_ms=path.expires_at_ms,
        horizon_observed_at_ms=mark.observed_at_ms,
        observation_lag_ms=(
            mark.observed_at_ms - path.expires_at_ms
        ),
        horizon_mark_px=mark.mark_px,
        gross_markout_cash=gross,
        after_entry_fee_markout_cash=after_entry_fee,
        after_entry_fee_markout_fraction=(
            after_entry_fee / record.gross_fill_notional
        ),
    )


def candidate_replacement_entry_forward_markout_records(
    fill_records: tuple[CandidateReplacementEntryFill, ...],
    paths: tuple[ContinuousPaperOpeningOpportunityPath, ...],
) -> tuple[CandidateReplacementEntryForwardMarkout, ...]:
    by_id = _path_by_opportunity(paths)
    output: list[CandidateReplacementEntryForwardMarkout] = []
    for record in fill_records:
        if not record.fillable:
            continue
        path = by_id.get(record.opportunity_id)
        if path is None or not path.complete:
            continue
        output.append(_completed_markout(record, path))
    return tuple(output)


def prospective_capacity_reflow_forward_markout_summary(
    fill_records: tuple[CandidateReplacementEntryFill, ...],
    paths: tuple[ContinuousPaperOpeningOpportunityPath, ...],
) -> dict[str, object]:
    by_id = _path_by_opportunity(paths)
    fillable = tuple(
        record for record in fill_records if record.fillable
    )
    completed: list[CandidateReplacementEntryForwardMarkout] = []
    matched_paths = 0
    pending_paths = 0
    missing_paths = 0

    for record in fillable:
        path = by_id.get(record.opportunity_id)
        if path is None:
            missing_paths += 1
            continue
        if (
            path.market != record.opportunity_market
            or path.direction != record.direction
            or path.opportunity_timestamp_ms
            != record.opportunity_timestamp_ms
        ):
            raise ProspectiveCapacityReflowForwardMarkoutError(
                "replacement markout path lineage mismatch"
            )
        matched_paths += 1
        if not path.complete:
            pending_paths += 1
            continue
        completed.append(_completed_markout(record, path))

    positive = sum(
        1
        for item in completed
        if item.after_entry_fee_markout_cash > ZERO
    )
    negative = sum(
        1
        for item in completed
        if item.after_entry_fee_markout_cash < ZERO
    )
    flat = len(completed) - positive - negative
    by_opportunity_market = Counter(
        item.opportunity_market for item in completed
    )
    by_release_market = Counter(
        item.release_market for item in completed
    )
    gross_markout = exact_decimal_sum(
        item.gross_markout_cash for item in completed
    )
    entry_fees = exact_decimal_sum(
        item.entry_fee for item in completed
    )
    after_entry_fee = exact_decimal_sum(
        item.after_entry_fee_markout_cash
        for item in completed
    )

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "claim_scope": (
            "candidate_caused_replacement_entry_"
            "completed_forward_markout"
        ),
        "portfolio_counterfactual": False,
        "other_baseline_positions_held_fixed": True,
        "replacement_entry_fills_modeled": True,
        "forward_markouts_modeled": True,
        "replacement_exits_modeled": False,
        "replacement_trades_modeled": False,
        "pnl_modeled": False,
        "fillable_options": len(fillable),
        "matched_paths": matched_paths,
        "complete_markouts": len(completed),
        "pending_paths": pending_paths,
        "missing_paths": missing_paths,
        "positive_after_entry_fee_markouts": positive,
        "negative_after_entry_fee_markouts": negative,
        "flat_after_entry_fee_markouts": flat,
        "gross_markout_cash": str(gross_markout),
        "entry_fees": str(entry_fees),
        "after_entry_fee_markout_cash": str(after_entry_fee),
        "by_opportunity_market": dict(
            sorted(by_opportunity_market.items())
        ),
        "by_release_market": dict(
            sorted(by_release_market.items())
        ),
        "completed": [item.to_dict() for item in completed],
    }


def evaluate_prospective_capacity_reflow_forward_markout(
    opportunity_store: ContinuousPaperOpeningOpportunityStore,
    lineage_store: ContinuousPaperOpeningLineageStore,
    journal: JournalStore,
    path_store: ContinuousPaperOpeningOpportunityPathStore,
    *,
    plan_loader: Callable[[str], PaperOrderPlan | None],
    fact_store: EvaluationFactStore,
    rank_store: ContinuousPaperOpeningRankStore,
    state: ProspectiveCombinedEntryFilterState,
    config: PaperExecutionConfig,
    position_history_loader: Callable[
        [str, int],
        tuple[PaperPosition, ...],
    ],
) -> dict[str, object]:
    opportunities = opportunity_store.iter_records()
    options = candidate_eligible_capacity_release_options(
        opportunities,
        state,
    )
    releases = candidate_caused_capacity_release_options(
        options,
        lineage_store.iter_records(),
        tuple(journal.iter_trades()),
        plan_loader=plan_loader,
        fact_loader=fact_store.load_decision_by_strategy_id,
        rank_loader=rank_store.load,
    )
    fill_records = candidate_caused_replacement_entry_fill_records(
        opportunities,
        releases,
        config,
        position_history_loader=position_history_loader,
    )
    return prospective_capacity_reflow_forward_markout_summary(
        fill_records,
        path_store.iter_paths(),
    )
