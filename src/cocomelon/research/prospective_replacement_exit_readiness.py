from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Final

from cocomelon.research.prospective_replacement_exit_policy import (
    CANDIDATE_ID,
    EXIT_HORIZON_MS,
)
from cocomelon.research.prospective_replacement_exit_robustness import (
    MIN_EXACT_OPTIONS_FOR_REVIEW,
    TEMPORAL_BLOCKS,
)

ZERO: Final = Decimal("0")
ONE: Final = Decimal("1")


class ProspectiveReplacementExitReadinessError(RuntimeError):
    pass


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProspectiveReplacementExitReadinessError(
            f"{field} must be a non-negative integer"
        )
    return value


def _decimal(value: object, field: str) -> Decimal:
    try:
        resolved = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ProspectiveReplacementExitReadinessError(
            f"{field} must be a decimal"
        ) from exc
    if not resolved.is_finite():
        raise ProspectiveReplacementExitReadinessError(
            f"{field} must be finite"
        )
    return resolved


def _optional_decimal(value: object, field: str) -> Decimal | None:
    if value is None:
        return None
    return _decimal(value, field)


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ProspectiveReplacementExitReadinessError(
            f"{field} must be a boolean"
        )
    return value


def prospective_replacement_exit_readiness(
    robustness: dict[str, object],
) -> dict[str, object]:
    if robustness.get("candidate_id") != CANDIDATE_ID:
        raise ProspectiveReplacementExitReadinessError(
            "replacement readiness candidate does not match frozen policy"
        )
    if robustness.get("exit_horizon_ms") != EXIT_HORIZON_MS:
        raise ProspectiveReplacementExitReadinessError(
            "replacement readiness horizon does not match frozen policy"
        )
    if robustness.get("changes_candidate_rule") is not False:
        raise ProspectiveReplacementExitReadinessError(
            "robustness layer must not change the candidate rule"
        )
    if robustness.get("execution_authority") is not False:
        raise ProspectiveReplacementExitReadinessError(
            "robustness layer unexpectedly grants execution authority"
        )
    if robustness.get("promotion_authority") is not False:
        raise ProspectiveReplacementExitReadinessError(
            "robustness layer unexpectedly grants promotion authority"
        )

    exact_options = _integer(
        robustness.get("exact_options"),
        "exact_options",
    )
    upstream_sample_ready = _boolean(
        robustness.get("sample_ready_for_review"),
        "sample_ready_for_review",
    )
    expected_sample_ready = (
        exact_options >= MIN_EXACT_OPTIONS_FOR_REVIEW
    )
    if upstream_sample_ready is not expected_sample_ready:
        raise ProspectiveReplacementExitReadinessError(
            "replacement robustness sample readiness is inconsistent"
        )

    total_pnl = _decimal(
        robustness.get("total_exact_realized_pnl"),
        "total_exact_realized_pnl",
    )
    profit_factor = _optional_decimal(
        robustness.get("profit_factor"),
        "profit_factor",
    )
    gross_profit = _decimal(
        robustness.get("gross_profit"),
        "gross_profit",
    )
    gross_loss_abs = _decimal(
        robustness.get("gross_loss_abs"),
        "gross_loss_abs",
    )
    if gross_profit < ZERO or gross_loss_abs < ZERO:
        raise ProspectiveReplacementExitReadinessError(
            "replacement robustness gross PnL values must be non-negative"
        )
    if gross_profit - gross_loss_abs != total_pnl:
        raise ProspectiveReplacementExitReadinessError(
            "replacement robustness gross PnL does not reconcile"
        )
    if gross_loss_abs == ZERO:
        if profit_factor is not None:
            raise ProspectiveReplacementExitReadinessError(
                "profit factor must be absent when gross loss is zero"
            )
    else:
        expected_profit_factor = gross_profit / gross_loss_abs
        if profit_factor != expected_profit_factor:
            raise ProspectiveReplacementExitReadinessError(
                "replacement robustness profit factor is inconsistent"
            )
    profit_factor_above_one = (
        (
            profit_factor is not None
            and profit_factor > ONE
        )
        or (
            profit_factor is None
            and gross_loss_abs == ZERO
            and gross_profit > ZERO
        )
    )
    option_leave_one_positive = robustness.get(
        "positive_after_any_single_option_removed"
    )
    market_leave_one_positive = robustness.get(
        "positive_after_any_single_market_removed"
    )
    if option_leave_one_positive is not None:
        option_leave_one_positive = _boolean(
            option_leave_one_positive,
            "positive_after_any_single_option_removed",
        )
    if market_leave_one_positive is not None:
        market_leave_one_positive = _boolean(
            market_leave_one_positive,
            "positive_after_any_single_market_removed",
        )

    temporal = robustness.get("temporal")
    if not isinstance(temporal, dict):
        raise ProspectiveReplacementExitReadinessError(
            "replacement robustness temporal evidence must be an object"
        )
    configured_blocks = _integer(
        temporal.get("configured_blocks"),
        "configured_blocks",
    )
    full_blocks = _integer(
        temporal.get("full_blocks"),
        "full_blocks",
    )
    positive_full_blocks = _integer(
        temporal.get("positive_full_blocks"),
        "positive_full_blocks",
    )
    all_full_blocks_positive = _boolean(
        temporal.get("all_full_blocks_positive"),
        "all_full_blocks_positive",
    )
    if configured_blocks != TEMPORAL_BLOCKS:
        raise ProspectiveReplacementExitReadinessError(
            "replacement robustness temporal block count drifted"
        )
    if positive_full_blocks > full_blocks:
        raise ProspectiveReplacementExitReadinessError(
            "positive temporal blocks exceed full temporal blocks"
        )

    checks = (
        (
            "minimum_exact_options",
            exact_options >= MIN_EXACT_OPTIONS_FOR_REVIEW,
        ),
        (
            "positive_total_exact_pnl",
            total_pnl > ZERO,
        ),
        (
            "profit_factor_above_one",
            profit_factor_above_one,
        ),
        (
            "positive_after_any_single_option_removed",
            option_leave_one_positive is True,
        ),
        (
            "positive_after_any_single_market_removed",
            market_leave_one_positive is True,
        ),
        (
            "all_four_full_chronological_blocks_positive",
            (
                full_blocks == TEMPORAL_BLOCKS
                and positive_full_blocks == TEMPORAL_BLOCKS
                and all_full_blocks_positive
            ),
        ),
    )
    failed = [
        name
        for name, passed in checks
        if not passed
    ]

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "candidate_id": CANDIDATE_ID,
        "exit_horizon_ms": EXIT_HORIZON_MS,
        "claim_scope": (
            "precommitted_post_freeze_5m_replacement_review_gate"
        ),
        "changes_candidate_rule": False,
        "ready_for_review": not failed,
        "failed_requirements": failed,
        "requirements": {
            "minimum_exact_options": MIN_EXACT_OPTIONS_FOR_REVIEW,
            "requires_positive_total_exact_pnl": True,
            "requires_profit_factor_above_one": True,
            "requires_positive_after_any_single_option_removed": True,
            "requires_positive_after_any_single_market_removed": True,
            "requires_all_four_full_chronological_blocks_positive": True,
        },
        "exact_options": exact_options,
        "missing_exact_options": max(
            0,
            MIN_EXACT_OPTIONS_FOR_REVIEW - exact_options,
        ),
        "total_exact_realized_pnl": str(total_pnl),
        "profit_factor": (
            None if profit_factor is None else str(profit_factor)
        ),
        "profit_factor_above_one": profit_factor_above_one,
        "positive_after_any_single_option_removed": (
            option_leave_one_positive
        ),
        "positive_after_any_single_market_removed": (
            market_leave_one_positive
        ),
        "temporal_full_blocks": full_blocks,
        "temporal_positive_full_blocks": positive_full_blocks,
        "temporal_all_full_blocks_positive": all_full_blocks_positive,
    }
