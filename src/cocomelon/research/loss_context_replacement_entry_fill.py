from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Final, cast

from cocomelon.domain.execution import PaperExecutionConfig
from cocomelon.execution.accounting import PaperPosition
from cocomelon.research.continuous_paper_opening_opportunity import (
    ContinuousPaperOpeningOpportunityEvidence,
)
from cocomelon.research.loss_context_candidate import (
    LossContextCandidateFreeze,
)
from cocomelon.research.prospective_capacity_reflow_fill_feasibility import (
    prospective_capacity_reflow_fill_feasibility_summary,
)
from cocomelon.research.prospective_capacity_reflow_release_lineage import (
    CandidateCausedCapacityRelease,
)

ZERO: Final = Decimal("0")
LOSS_CONTEXT_REPLACEMENT_ENTRY_FILL_SCHEMA_VERSION: Final = 1

PositionHistoryLoader = Callable[
    [str, int],
    tuple[PaperPosition, ...],
]


class LossContextReplacementEntryFillError(RuntimeError):
    pass


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(
        isinstance(key, str) for key in value
    ):
        raise LossContextReplacementEntryFillError(
            f"{field} must be an object"
        )
    return cast(dict[str, object], value)


def _sequence(value: object, field: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise LossContextReplacementEntryFillError(
            f"{field} must be an array"
        )
    return tuple(value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise LossContextReplacementEntryFillError(
            f"{field} must be a non-empty string"
        )
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LossContextReplacementEntryFillError(
            f"{field} must be a non-negative integer"
        )
    return value


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise LossContextReplacementEntryFillError(
            f"{field} must be a decimal string"
        )
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise LossContextReplacementEntryFillError(
            f"{field} must be a decimal string"
        ) from exc
    if not result.is_finite():
        raise LossContextReplacementEntryFillError(
            f"{field} must be finite"
        )
    return result


def _release_key(
    release: CandidateCausedCapacityRelease,
) -> tuple[str, str]:
    return release.opportunity_id, release.release_opening_plan_id


def _validate_holder_report(
    report: dict[str, object],
    *,
    freeze: LossContextCandidateFreeze,
) -> tuple[dict[str, object], ...]:
    if report.get("candidate_id") != freeze.candidate_id:
        raise LossContextReplacementEntryFillError(
            "LOSS_CONTEXT_ENTRY_HOLDER_CANDIDATE_MISMATCH"
        )
    for field in (
        "changes_strategy",
        "changes_risk_limits",
        "changes_positions",
        "promotion_authority",
        "execution_authority",
    ):
        if report.get(field) is not False:
            raise LossContextReplacementEntryFillError(
                "LOSS_CONTEXT_ENTRY_HOLDER_AUTHORITY_INVALID"
            )
    if report.get("replacement_entry_fills_modeled") is not False:
        raise LossContextReplacementEntryFillError(
            "LOSS_CONTEXT_ENTRY_ALREADY_MODELED"
        )
    if report.get("replacement_pnl_modeled") is not False:
        raise LossContextReplacementEntryFillError(
            "LOSS_CONTEXT_ENTRY_PNL_ALREADY_MODELED"
        )

    options = tuple(
        _mapping(item, "full_close_release_option")
        for item in _sequence(
            report.get("full_close_release_options"),
            "full_close_release_options",
        )
    )
    expected = _integer(
        report.get("exact_full_close_release_options"),
        "exact_full_close_release_options",
    )
    if expected != len(options):
        raise LossContextReplacementEntryFillError(
            "LOSS_CONTEXT_ENTRY_HOLDER_COUNT_MISMATCH"
        )
    return options


def loss_context_replacement_entry_fill_summary(
    opportunities: tuple[
        ContinuousPaperOpeningOpportunityEvidence,
        ...,
    ],
    releases: tuple[CandidateCausedCapacityRelease, ...],
    holder_release_execution: dict[str, object],
    *,
    freeze: LossContextCandidateFreeze,
    config: PaperExecutionConfig,
    position_history_loader: PositionHistoryLoader,
) -> dict[str, object]:
    full_close_options = _validate_holder_report(
        holder_release_execution,
        freeze=freeze,
    )

    opportunities_by_id = {
        item.opportunity_id: item for item in opportunities
    }
    if len(opportunities_by_id) != len(opportunities):
        raise LossContextReplacementEntryFillError(
            "duplicate opening opportunity ids"
        )

    releases_by_key: dict[
        tuple[str, str],
        CandidateCausedCapacityRelease,
    ] = {}
    for release in releases:
        key = _release_key(release)
        if key in releases_by_key:
            raise LossContextReplacementEntryFillError(
                "duplicate causal release option"
            )
        if release.opportunity_timestamp_ms < freeze.prospective_not_before_ms:
            raise LossContextReplacementEntryFillError(
                "causal release predates prospective boundary"
            )
        if release.release_block_reason != "frozen_loss_context":
            raise LossContextReplacementEntryFillError(
                "causal release reason is invalid"
            )
        releases_by_key[key] = release

    seen_option_ids: set[str] = set()
    option_results: list[dict[str, object]] = []
    fillable_release_option_ids: list[str] = []
    risk_approvals = 0
    planning_approvals = 0
    fillable = 0
    full_fills = 0
    partial_fills = 0
    no_fills = 0
    execution_rejections = 0
    gross_fill_notional = ZERO
    taker_fees = ZERO
    by_opportunity_market: Counter[str] = Counter()
    by_release_market: Counter[str] = Counter()
    by_execution_result: Counter[str] = Counter()
    by_risk_rejection: Counter[str] = Counter()
    by_planning_rejection: Counter[str] = Counter()

    for holder in full_close_options:
        option_id = _string(
            holder.get("release_option_id"),
            "release_option_id",
        )
        if option_id in seen_option_ids:
            raise LossContextReplacementEntryFillError(
                "duplicate full-close release option id"
            )
        seen_option_ids.add(option_id)

        opportunity_id = _string(
            holder.get("opportunity_id"),
            "opportunity_id",
        )
        plan_id = _string(
            holder.get("release_opening_plan_id"),
            "release_opening_plan_id",
        )
        expected_option_id = f"{opportunity_id}:{plan_id}"
        if option_id != expected_option_id:
            raise LossContextReplacementEntryFillError(
                "full-close release option id mismatch"
            )
        release = releases_by_key.get((opportunity_id, plan_id))
        if release is None:
            raise LossContextReplacementEntryFillError(
                "full-close release is absent from causal reflow"
            )
        opportunity = opportunities_by_id.get(opportunity_id)
        if opportunity is None:
            raise LossContextReplacementEntryFillError(
                "full-close release opportunity evidence is missing"
            )
        if (
            opportunity.opportunity_timestamp_ms
            != release.opportunity_timestamp_ms
            or opportunity.market != release.opportunity_market
        ):
            raise LossContextReplacementEntryFillError(
                "replacement opportunity lineage mismatch"
            )
        terminal = _decimal(
            holder.get("full_close_terminal_contribution"),
            "full_close_terminal_contribution",
        )

        replay = prospective_capacity_reflow_fill_feasibility_summary(
            (opportunity,),
            (release,),
            config,
            position_history_loader=position_history_loader,
            released_position_terminal_contribution_by_plan={
                plan_id: terminal
            },
        )
        rows = replay.get("option_results")
        if not isinstance(rows, list) or len(rows) != 1:
            raise LossContextReplacementEntryFillError(
                "replacement entry replay did not return exactly one row"
            )
        row = _mapping(rows[0], "replacement entry result")
        replay_option_id = _string(
            row.get("option_id"),
            "replacement option_id",
        )
        if replay_option_id != option_id:
            raise LossContextReplacementEntryFillError(
                "replacement entry option id mismatch"
            )
        enriched = dict(row)
        enriched["candidate_id"] = freeze.candidate_id
        enriched["holder_full_close_terminal_contribution"] = str(
            terminal
        )
        option_results.append(enriched)

        risk_approvals += _integer(
            replay.get("conservative_risk_approvals"),
            "conservative_risk_approvals",
        )
        planning_approvals += _integer(
            replay.get("planning_approvals"),
            "planning_approvals",
        )
        fillable += _integer(
            replay.get("fillable_options"),
            "fillable_options",
        )
        full_fills += _integer(
            replay.get("full_fill_options"),
            "full_fill_options",
        )
        partial_fills += _integer(
            replay.get("partial_fill_options"),
            "partial_fill_options",
        )
        no_fills += _integer(
            replay.get("no_fill_options"),
            "no_fill_options",
        )
        execution_rejections += _integer(
            replay.get("execution_rejected_options"),
            "execution_rejected_options",
        )
        gross_fill_notional += _decimal(
            replay.get("gross_fill_notional"),
            "gross_fill_notional",
        )
        taker_fees += _decimal(
            replay.get("taker_fees"),
            "taker_fees",
        )
        by_opportunity_market[release.opportunity_market] += 1
        by_release_market[release.release_market] += 1

        result = row.get("execution_result")
        if isinstance(result, str):
            by_execution_result[result] += 1
            if result in {"full", "partial"}:
                fillable_release_option_ids.append(option_id)
        risk_codes = row.get("risk_reason_codes")
        if isinstance(risk_codes, list) and risk_codes:
            first = risk_codes[0]
            if isinstance(first, str) and row.get("risk_approved") is False:
                by_risk_rejection[first] += 1
        planning_rejection = row.get("planning_rejection")
        if isinstance(planning_rejection, str):
            by_planning_rejection[planning_rejection] += 1

    if fillable != full_fills + partial_fills:
        raise LossContextReplacementEntryFillError(
            "replacement fill counters do not reconcile"
        )

    return {
        "candidate_id": freeze.candidate_id,
        "dimensions": freeze.dimensions,
        "values": freeze.values,
        "prospective_not_before_ms": freeze.prospective_not_before_ms,
        "research_only": True,
        "descriptive_only": True,
        "changes_strategy": False,
        "changes_risk_limits": False,
        "changes_positions": False,
        "promotion_authority": False,
        "execution_authority": False,
        "claim_scope": (
            "exact_replacement_entry_risk_planning_and_ioc_after_"
            "executed_loss_context_holder_release"
        ),
        "holder_full_close_release_options": len(full_close_options),
        "entry_replayed_options": len(option_results),
        "conservative_risk_approvals": risk_approvals,
        "planning_approvals": planning_approvals,
        "fillable_options": fillable,
        "full_fill_options": full_fills,
        "partial_fill_options": partial_fills,
        "no_fill_options": no_fills,
        "execution_rejected_options": execution_rejections,
        "gross_fill_notional": str(gross_fill_notional),
        "taker_fees": str(taker_fees),
        "fillable_release_option_ids": sorted(
            fillable_release_option_ids
        ),
        "option_results": sorted(
            option_results,
            key=lambda item: str(item["option_id"]),
        ),
        "by_opportunity_market": dict(
            sorted(by_opportunity_market.items())
        ),
        "by_release_market": dict(sorted(by_release_market.items())),
        "by_execution_result": dict(
            sorted(by_execution_result.items())
        ),
        "by_risk_rejection": dict(sorted(by_risk_rejection.items())),
        "by_planning_rejection": dict(
            sorted(by_planning_rejection.items())
        ),
        "holder_release_terminal_contribution_applied_per_option": True,
        "other_baseline_positions_held_fixed": True,
        "replacement_entry_fills_modeled": True,
        "replacement_exits_modeled": False,
        "replacement_pnl_modeled": False,
        "recursive_replacements_modeled": False,
        "ready_for_replacement_exit_investigation": fillable > 0,
        "schema_version": (
            LOSS_CONTEXT_REPLACEMENT_ENTRY_FILL_SCHEMA_VERSION
        ),
    }
