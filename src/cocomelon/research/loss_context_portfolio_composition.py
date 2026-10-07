from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation
from typing import Final, cast

from cocomelon.research.loss_context_candidate import (
    LossContextCandidateFreeze,
)

ZERO: Final = Decimal("0")
LOSS_CONTEXT_PORTFOLIO_COMPOSITION_SCHEMA_VERSION: Final = 1


class LossContextPortfolioCompositionError(RuntimeError):
    pass


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(
        isinstance(key, str) for key in value
    ):
        raise LossContextPortfolioCompositionError(
            f"{field} must be an object"
        )
    return cast(dict[str, object], value)


def _sequence(value: object, field: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise LossContextPortfolioCompositionError(
            f"{field} must be an array"
        )
    return tuple(value)


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise LossContextPortfolioCompositionError(
            f"{field} must be a non-empty string"
        )
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LossContextPortfolioCompositionError(
            f"{field} must be a non-negative integer"
        )
    return value


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise LossContextPortfolioCompositionError(
            f"{field} must be a decimal string"
        )
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise LossContextPortfolioCompositionError(
            f"{field} must be a decimal string"
        ) from exc
    if not result.is_finite():
        raise LossContextPortfolioCompositionError(
            f"{field} must be finite"
        )
    return result


def _validate_authority(
    payload: dict[str, object],
    *,
    freeze: LossContextCandidateFreeze,
    field: str,
) -> None:
    if payload.get("candidate_id") != freeze.candidate_id:
        raise LossContextPortfolioCompositionError(
            f"{field} candidate mismatch"
        )
    if payload.get("research_only") is not True:
        raise LossContextPortfolioCompositionError(
            f"{field} must remain research only"
        )
    for key in (
        "changes_strategy",
        "changes_risk_limits",
        "promotion_authority",
        "execution_authority",
    ):
        if payload.get(key) is not False:
            raise LossContextPortfolioCompositionError(
                f"{field} authority drift"
            )


def _entry_index(
    entry_fill: dict[str, object],
) -> dict[str, dict[str, object]]:
    raw_ids = _sequence(
        entry_fill.get("fillable_option_ids"),
        "fillable_option_ids",
    )
    wanted = {_text(value, "fillable option id") for value in raw_ids}
    rows = _sequence(entry_fill.get("option_results"), "option_results")
    output: dict[str, dict[str, object]] = {}
    for raw in rows:
        row = _mapping(raw, "entry option")
        option_id = _text(row.get("option_id"), "option_id")
        if option_id not in wanted:
            continue
        if option_id in output:
            raise LossContextPortfolioCompositionError(
                "duplicate fillable entry option"
            )
        if row.get("execution_result") not in {"full", "partial"}:
            raise LossContextPortfolioCompositionError(
                "fillable entry option is not filled"
            )
        output[option_id] = row
    if set(output) != wanted:
        raise LossContextPortfolioCompositionError(
            "fillable entry option is missing"
        )
    return output


def _realized_index(
    exit_pnl: dict[str, object],
) -> tuple[
    tuple[int, ...],
    dict[str, dict[str, object]],
]:
    raw_horizons = _sequence(exit_pnl.get("horizons_ms"), "horizons_ms")
    horizons = tuple(
        _integer(value, "horizon_ms") for value in raw_horizons
    )
    if (
        not horizons
        or tuple(sorted(set(horizons))) != horizons
        or any(value <= 0 for value in horizons)
    ):
        raise LossContextPortfolioCompositionError(
            "replacement horizons must be positive and ordered"
        )
    realized = _mapping(exit_pnl.get("realized_pnl"), "realized_pnl")
    raw_options = _sequence(realized.get("option_results"), "realized options")
    output: dict[str, dict[str, object]] = {}
    for raw in raw_options:
        row = _mapping(raw, "realized option")
        option_id = _text(row.get("option_id"), "option_id")
        if option_id in output:
            raise LossContextPortfolioCompositionError(
                "duplicate realized option id"
            )
        output[option_id] = row
    return horizons, output


def _overlap_pairs(
    rows: tuple[dict[str, object], ...],
) -> int:
    ordered = tuple(
        sorted(
            rows,
            key=lambda row: (
                cast(int, row["entry_ms"]),
                cast(int, row["closed_at_ms"]),
                cast(str, row["option_id"]),
            ),
        )
    )
    overlaps = 0
    for index, left in enumerate(ordered):
        left_close = cast(int, left["closed_at_ms"])
        for right in ordered[index + 1 :]:
            right_entry = cast(int, right["entry_ms"])
            if right_entry >= left_close:
                break
            overlaps += 1
    return overlaps


def loss_context_portfolio_composition_summary(
    account_readiness: dict[str, object],
    entry_fill: dict[str, object],
    exit_pnl: dict[str, object],
    *,
    freeze: LossContextCandidateFreeze,
) -> dict[str, object]:
    _validate_authority(
        account_readiness,
        freeze=freeze,
        field="account readiness",
    )
    _validate_authority(
        entry_fill,
        freeze=freeze,
        field="replacement entry",
    )
    _validate_authority(
        exit_pnl,
        freeze=freeze,
        field="replacement exit",
    )

    if account_readiness.get("fixed_schedule_economics_ready") is not True:
        gate_reason = "fixed_schedule_account_not_ready"
    elif exit_pnl.get(
        "ready_for_portfolio_counterfactual_investigation"
    ) is not True:
        gate_reason = "replacement_horizons_incomplete"
    elif exit_pnl.get("all_horizons_complete") is not True:
        gate_reason = "replacement_horizons_incomplete"
    elif exit_pnl.get("cross_horizon_economics_aggregated") is not False:
        raise LossContextPortfolioCompositionError(
            "cross-horizon economics were aggregated"
        )
    elif exit_pnl.get("horizon_selection_performed") is not False:
        raise LossContextPortfolioCompositionError(
            "replacement horizon was selected"
        )
    else:
        gate_reason = None

    economics = _mapping(
        account_readiness.get("fixed_schedule_economics"),
        "fixed_schedule_economics",
    )
    actual_pnl = _decimal(
        economics.get("actual_net_pnl"),
        "actual_net_pnl",
    )
    filtered_pnl = _decimal(
        economics.get("candidate_net_pnl"),
        "candidate_net_pnl",
    )
    filtered_delta = _decimal(
        economics.get("delta_net_pnl"),
        "delta_net_pnl",
    )
    if filtered_pnl - actual_pnl != filtered_delta:
        raise LossContextPortfolioCompositionError(
            "fixed-schedule economics do not reconcile"
        )

    entry_by_id = _entry_index(entry_fill)
    horizons, realized_by_id = _realized_index(exit_pnl)
    if set(realized_by_id) != set(entry_by_id):
        raise LossContextPortfolioCompositionError(
            "replacement entry/realized option identities differ"
        )

    horizon_summaries: dict[str, object] = {}
    all_structurally_composable = gate_reason is None
    for horizon_ms in horizons:
        key = str(horizon_ms)
        rows: list[dict[str, object]] = []
        opportunity_counts: Counter[str] = Counter()
        release_counts: Counter[str] = Counter()
        replacement_pnl = ZERO

        for option_id in sorted(entry_by_id):
            entry = entry_by_id[option_id]
            realized = realized_by_id[option_id]
            opportunity_id = _text(
                entry.get("opportunity_id"),
                "entry opportunity_id",
            )
            if realized.get("opportunity_id") != opportunity_id:
                raise LossContextPortfolioCompositionError(
                    "replacement opportunity lineage mismatch"
                )
            release_plan_id = _text(
                entry.get("release_opening_plan_id"),
                "release_opening_plan_id",
            )
            entry_ms = _integer(
                realized.get("entry_attempt_timestamp_ms"),
                "entry_attempt_timestamp_ms",
            )
            exits = _mapping(realized.get("exits"), "realized exits")
            raw_exit = _mapping(exits.get(key), f"exit {key}")
            exact = raw_exit.get("exact_realized_pnl")
            if exact is None:
                raise LossContextPortfolioCompositionError(
                    "complete horizon is missing exact realized pnl"
                )
            pnl = _decimal(exact, "exact_realized_pnl")
            closed_at_ms = _integer(
                raw_exit.get("closed_at_ms"),
                "closed_at_ms",
            )
            if closed_at_ms < entry_ms:
                raise LossContextPortfolioCompositionError(
                    "replacement close precedes entry"
                )
            opportunity_counts[opportunity_id] += 1
            release_counts[release_plan_id] += 1
            replacement_pnl += pnl
            rows.append(
                {
                    "option_id": option_id,
                    "opportunity_id": opportunity_id,
                    "release_opening_plan_id": release_plan_id,
                    "entry_ms": entry_ms,
                    "closed_at_ms": closed_at_ms,
                    "exact_realized_pnl": str(pnl),
                }
            )

        ambiguous_opportunities = sorted(
            key for key, count in opportunity_counts.items() if count > 1
        )
        reused_release_holders = sorted(
            key for key, count in release_counts.items() if count > 1
        )
        overlaps = _overlap_pairs(tuple(rows))
        structurally_composable = (
            gate_reason is None
            and not ambiguous_opportunities
            and not reused_release_holders
            and overlaps == 0
        )
        all_structurally_composable = (
            all_structurally_composable and structurally_composable
        )
        first_order_candidate_pnl = filtered_pnl + replacement_pnl
        first_order_delta = first_order_candidate_pnl - actual_pnl

        horizon_summaries[key] = {
            "horizon_ms": horizon_ms,
            "exact_replacement_options": len(rows),
            "unique_opportunities": len(opportunity_counts),
            "unique_release_holders": len(release_counts),
            "ambiguous_opportunity_count": len(ambiguous_opportunities),
            "ambiguous_opportunity_ids": ambiguous_opportunities,
            "reused_release_holder_count": len(reused_release_holders),
            "reused_release_holder_plan_ids": reused_release_holders,
            "overlapping_replacement_pairs": overlaps,
            "structurally_composable": structurally_composable,
            "independent_path_exact_replacement_pnl": str(replacement_pnl),
            "fixed_schedule_filtered_pnl": str(filtered_pnl),
            "first_order_combined_pnl": str(first_order_candidate_pnl),
            "first_order_delta_vs_actual_pnl": str(first_order_delta),
            "chronological_account_state_replayed": False,
            "portfolio_counterfactual_complete": False,
            "strategy_level_realized_pnl_claimed": False,
        }

    return {
        "candidate_id": freeze.candidate_id,
        "dimensions": freeze.dimensions,
        "values": freeze.values,
        "prospective_not_before_ms": freeze.prospective_not_before_ms,
        "gate_open": gate_reason is None,
        "gate_reason": gate_reason,
        "research_only": True,
        "descriptive_only": True,
        "changes_strategy": False,
        "changes_risk_limits": False,
        "changes_positions": False,
        "promotion_authority": False,
        "execution_authority": False,
        "claim_scope": (
            "loss_context_replacement_portfolio_composition_safety"
        ),
        "actual_fixed_schedule_pnl": str(actual_pnl),
        "filtered_fixed_schedule_pnl": str(filtered_pnl),
        "filtered_fixed_schedule_delta_pnl": str(filtered_delta),
        "horizons_ms": horizons,
        "horizon_summaries": horizon_summaries,
        "all_horizons_structurally_composable": (
            all_structurally_composable
        ),
        "horizon_selection_performed": False,
        "cross_horizon_economics_aggregated": False,
        "independent_paths_summed_only_for_diagnostics": True,
        "chronological_account_state_replayed": False,
        "recursive_replacements_modeled": False,
        "portfolio_counterfactual_complete": False,
        "strategy_level_realized_pnl_claimed": False,
        "ready_for_chronological_portfolio_replay": (
            all_structurally_composable
        ),
        "schema_version": (
            LOSS_CONTEXT_PORTFOLIO_COMPOSITION_SCHEMA_VERSION
        ),
    }
