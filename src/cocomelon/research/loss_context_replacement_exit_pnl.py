from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Final, cast

from cocomelon.domain.execution import PaperExecutionConfig
from cocomelon.research.continuous_paper_opening_opportunity_exit_books import (
    OpeningOpportunityExitBookEvidence,
)
from cocomelon.research.continuous_paper_replacement_funding import (
    ReplacementFundingBoundaryEvidence,
)
from cocomelon.research.loss_context_candidate import (
    LossContextCandidateFreeze,
)
from cocomelon.research.prospective_capacity_reflow_exit_fill import (
    prospective_capacity_reflow_exit_fill_summary,
)
from cocomelon.research.prospective_capacity_reflow_realized_pnl import (
    prospective_capacity_reflow_realized_pnl_summary,
)

ZERO: Final = Decimal("0")
LOSS_CONTEXT_REPLACEMENT_EXIT_PNL_SCHEMA_VERSION: Final = 1


class LossContextReplacementExitPnlError(RuntimeError):
    pass


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(
        isinstance(key, str) for key in value
    ):
        raise LossContextReplacementExitPnlError(
            f"{field} must be an object"
        )
    return cast(dict[str, object], value)


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LossContextReplacementExitPnlError(
            f"{field} must be a non-negative integer"
        )
    return value


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise LossContextReplacementExitPnlError(
            f"{field} must be a decimal string"
        )
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise LossContextReplacementExitPnlError(
            f"{field} must be a decimal string"
        ) from exc
    if not result.is_finite():
        raise LossContextReplacementExitPnlError(
            f"{field} must be finite"
        )
    return result


def _validate_entry_fill(
    entry_fill: dict[str, object],
    *,
    freeze: LossContextCandidateFreeze,
) -> None:
    if entry_fill.get("candidate_id") != freeze.candidate_id:
        raise LossContextReplacementExitPnlError(
            "LOSS_CONTEXT_EXIT_ENTRY_CANDIDATE_MISMATCH"
        )
    for field in (
        "changes_strategy",
        "changes_risk_limits",
        "changes_positions",
        "promotion_authority",
        "execution_authority",
    ):
        if entry_fill.get(field) is not False:
            raise LossContextReplacementExitPnlError(
                "LOSS_CONTEXT_EXIT_ENTRY_AUTHORITY_INVALID"
            )
    if entry_fill.get("replacement_entry_fills_modeled") is not True:
        raise LossContextReplacementExitPnlError(
            "LOSS_CONTEXT_EXIT_ENTRY_NOT_MODELED"
        )
    if entry_fill.get("replacement_exits_modeled") is not False:
        raise LossContextReplacementExitPnlError(
            "LOSS_CONTEXT_EXIT_ALREADY_MODELED"
        )
    if entry_fill.get("replacement_pnl_modeled") is not False:
        raise LossContextReplacementExitPnlError(
            "LOSS_CONTEXT_EXIT_PNL_ALREADY_MODELED"
        )


def loss_context_replacement_exit_pnl_summary(
    entry_fill: dict[str, object],
    exit_books: tuple[OpeningOpportunityExitBookEvidence, ...],
    funding_records: tuple[ReplacementFundingBoundaryEvidence, ...],
    *,
    freeze: LossContextCandidateFreeze,
    config: PaperExecutionConfig,
    horizons_ms: tuple[int, ...],
) -> dict[str, object]:
    _validate_entry_fill(entry_fill, freeze=freeze)
    if not horizons_ms:
        raise ValueError("horizons_ms must not be empty")
    if tuple(sorted(set(horizons_ms))) != horizons_ms:
        raise ValueError("horizons_ms must be ordered and unique")
    if any(value <= 0 for value in horizons_ms):
        raise ValueError("horizons_ms must be positive")

    exit_fill = prospective_capacity_reflow_exit_fill_summary(
        entry_fill,
        exit_books,
        config,
        horizons_ms=horizons_ms,
    )
    realized = prospective_capacity_reflow_realized_pnl_summary(
        exit_fill,
        funding_records,
    )

    for payload, field in (
        (exit_fill, "replacement exit fill"),
        (realized, "replacement realized pnl"),
    ):
        if payload.get("execution_authority") is not False:
            raise LossContextReplacementExitPnlError(
                f"{field} gained execution authority"
            )
        if payload.get("promotion_authority") is not False:
            raise LossContextReplacementExitPnlError(
                f"{field} gained promotion authority"
            )

    realized_by_horizon = _mapping(
        realized.get("by_horizon"),
        "realized by_horizon",
    )
    horizon_reviews: dict[str, object] = {}
    all_horizons_complete = True
    all_horizons_positive = True
    any_options = False

    for horizon_ms in horizons_ms:
        key = str(horizon_ms)
        raw = _mapping(
            realized_by_horizon.get(key),
            f"realized horizon {key}",
        )
        options = _integer(raw.get("options"), "options")
        exact = _integer(
            raw.get("exact_realized_pnl_options"),
            "exact_realized_pnl_options",
        )
        pnl = _decimal(
            raw.get("exact_realized_pnl"),
            "exact_realized_pnl",
        )
        complete = options > 0 and exact == options
        positive = complete and pnl > ZERO
        any_options = any_options or options > 0
        all_horizons_complete = all_horizons_complete and complete
        all_horizons_positive = all_horizons_positive and positive
        horizon_reviews[key] = {
            "horizon_ms": horizon_ms,
            "options": options,
            "exact_realized_pnl_options": exact,
            "exact_realized_pnl": str(pnl),
            "complete": complete,
            "positive": positive,
            "incomplete_or_missing_exits": _integer(
                raw.get("incomplete_or_missing_exits"),
                "incomplete_or_missing_exits",
            ),
            "funding_evidence_missing_closes": _integer(
                raw.get("funding_evidence_missing_closes"),
                "funding_evidence_missing_closes",
            ),
        }

    all_horizons_complete = any_options and all_horizons_complete
    all_horizons_positive = (
        all_horizons_complete and all_horizons_positive
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
            "fixed_horizon_exact_replacement_exit_and_funding_pnl_"
            "after_loss_context_holder_release"
        ),
        "horizons_ms": horizons_ms,
        "entry_fillable_options": _integer(
            entry_fill.get("fillable_options"),
            "entry fillable_options",
        ),
        "exit_fill": exit_fill,
        "realized_pnl": realized,
        "horizon_reviews": horizon_reviews,
        "all_horizons_complete": all_horizons_complete,
        "all_horizons_positive": all_horizons_positive,
        "exact_realized_pnl_available": (
            realized.get("exact_realized_pnl_available") is True
        ),
        "cross_horizon_economics_aggregated": False,
        "horizon_selection_performed": False,
        "selected_horizon_ms": None,
        "strategy_level_realized_pnl_claimed": False,
        "portfolio_counterfactual_complete": False,
        "replacement_entry_fills_modeled": True,
        "replacement_exits_modeled": True,
        "replacement_pnl_modeled": True,
        "recursive_replacements_modeled": False,
        "ready_for_portfolio_counterfactual_investigation": (
            all_horizons_complete
        ),
        "schema_version": (
            LOSS_CONTEXT_REPLACEMENT_EXIT_PNL_SCHEMA_VERSION
        ),
    }
