from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Final

ZERO: Final = Decimal("0")
TEMPORAL_BLOCKS: Final = 4
MIN_OPTIONS_PER_FULL_BLOCK: Final = 5
MIN_EXACT_OPTIONS_FOR_REVIEW: Final = 30


class ProspectiveReplacementExitRobustnessError(RuntimeError):
    pass


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProspectiveReplacementExitRobustnessError(
            f"{field} must be a non-negative integer"
        )
    return value


def _decimal(value: object, field: str) -> Decimal:
    try:
        resolved = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ProspectiveReplacementExitRobustnessError(
            f"{field} must be a decimal"
        ) from exc
    if not resolved.is_finite():
        raise ProspectiveReplacementExitRobustnessError(
            f"{field} must be finite"
        )
    return resolved


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProspectiveReplacementExitRobustnessError(
            f"{field} must be a non-empty string"
        )
    return value


def prospective_replacement_exit_robustness(
    policy: dict[str, object],
) -> dict[str, object]:
    if policy.get("discovery_cohort_reused_for_validation") is not False:
        raise ProspectiveReplacementExitRobustnessError(
            "discovery cohort must remain excluded"
        )
    if policy.get("cross_horizon_selection_frozen") is not True:
        raise ProspectiveReplacementExitRobustnessError(
            "replacement exit horizon must remain frozen"
        )

    prospective_options = _integer(
        policy.get("prospective_options"),
        "prospective_options",
    )
    expected_exact = _integer(
        policy.get("exact_realized_pnl_options"),
        "exact_realized_pnl_options",
    )
    expected_incomplete = _integer(
        policy.get("incomplete_options"),
        "incomplete_options",
    )
    if expected_exact + expected_incomplete != prospective_options:
        raise ProspectiveReplacementExitRobustnessError(
            "replacement option counts do not reconcile"
        )
    raw_options = policy.get("option_results")
    if not isinstance(raw_options, list):
        raise ProspectiveReplacementExitRobustnessError(
            "replacement option results must be an array"
        )
    if len(raw_options) != prospective_options:
        raise ProspectiveReplacementExitRobustnessError(
            "replacement option result count mismatch"
        )

    exact: list[tuple[str, str, int, Decimal]] = []
    incomplete_options = 0
    option_ids: set[str] = set()
    for raw in raw_options:
        if not isinstance(raw, dict):
            raise ProspectiveReplacementExitRobustnessError(
                "replacement option result is invalid"
            )
        option_id = _text(raw.get("option_id"), "option_id")
        if option_id in option_ids:
            raise ProspectiveReplacementExitRobustnessError(
                "replacement robustness contains duplicate option ids"
            )
        option_ids.add(option_id)
        market = _text(
            raw.get("opportunity_market"),
            "opportunity_market",
        )
        timestamp_ms = _integer(
            raw.get("opportunity_timestamp_ms"),
            "opportunity_timestamp_ms",
        )
        raw_pnl = raw.get("exact_realized_pnl")
        if raw_pnl is None:
            incomplete_options += 1
            continue
        exact.append(
            (
                option_id,
                market,
                timestamp_ms,
                _decimal(raw_pnl, "exact_realized_pnl"),
            )
        )

    if len(exact) != expected_exact or incomplete_options != expected_incomplete:
        raise ProspectiveReplacementExitRobustnessError(
            "replacement exact/incomplete counts do not match option results"
        )

    total = sum((item[3] for item in exact), ZERO)
    positive = tuple(item[3] for item in exact if item[3] > ZERO)
    negative = tuple(item[3] for item in exact if item[3] < ZERO)
    gross_profit = sum(positive, ZERO)
    gross_loss_abs = sum((-value for value in negative), ZERO)
    abs_total = sum((abs(item[3]) for item in exact), ZERO)

    largest_option = (
        None
        if not exact
        else max(
            exact,
            key=lambda item: (
                abs(item[3]),
                item[2],
                item[0],
            ),
        )
    )
    leave_one_option = tuple(
        total - item[3]
        for item in exact
    )

    by_market: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for _, market, _, pnl in exact:
        by_market[market] += pnl
    market_values = dict(sorted(by_market.items()))
    abs_market_total = sum(
        (abs(value) for value in market_values.values()),
        ZERO,
    )
    largest_market = (
        None
        if not market_values
        else max(
            market_values.items(),
            key=lambda item: (abs(item[1]), item[0]),
        )
    )
    leave_one_market = tuple(
        total - value
        for value in market_values.values()
    )

    ordered = tuple(
        sorted(
            exact,
            key=lambda item: (
                item[2],
                item[0],
            ),
        )
    )
    quotient, remainder = divmod(len(ordered), TEMPORAL_BLOCKS)
    blocks: list[dict[str, object]] = []
    start = 0
    for index in range(TEMPORAL_BLOCKS):
        count = quotient + (1 if index < remainder else 0)
        stop = start + count
        block = ordered[start:stop]
        start = stop
        if not block:
            continue
        pnl = sum((item[3] for item in block), ZERO)
        blocks.append(
            {
                "block": index + 1,
                "options": len(block),
                "first_opportunity_timestamp_ms": block[0][2],
                "last_opportunity_timestamp_ms": block[-1][2],
                "exact_realized_pnl": str(pnl),
                "positive_pnl": pnl > ZERO,
            }
        )

    def is_full_block(block: dict[str, object]) -> bool:
        count = block.get("options")
        return (
            isinstance(count, int)
            and not isinstance(count, bool)
            and count >= MIN_OPTIONS_PER_FULL_BLOCK
        )

    full_blocks = tuple(
        block
        for block in blocks
        if is_full_block(block)
    )
    positive_full_blocks = sum(
        1
        for block in full_blocks
        if block["positive_pnl"] is True
    )

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "candidate_id": policy.get("candidate_id"),
        "started_at_ms": policy.get("started_at_ms"),
        "exit_horizon_ms": policy.get("exit_horizon_ms"),
        "claim_scope": (
            "post_freeze_5m_replacement_exact_pnl_robustness"
        ),
        "changes_candidate_rule": False,
        "prospective_options": prospective_options,
        "exact_options": len(exact),
        "incomplete_options": incomplete_options,
        "exact_coverage_fraction": (
            None
            if prospective_options == 0
            else str(
                Decimal(len(exact))
                / Decimal(prospective_options)
            )
        ),
        "minimum_exact_options_for_review": (
            MIN_EXACT_OPTIONS_FOR_REVIEW
        ),
        "sample_ready_for_review": (
            len(exact) >= MIN_EXACT_OPTIONS_FOR_REVIEW
        ),
        "total_exact_realized_pnl": str(total),
        "gross_profit": str(gross_profit),
        "gross_loss_abs": str(gross_loss_abs),
        "profit_factor": (
            None
            if gross_loss_abs == ZERO
            else str(gross_profit / gross_loss_abs)
        ),
        "largest_abs_option_pnl": (
            None if largest_option is None else str(largest_option[3])
        ),
        "largest_abs_option_market": (
            None if largest_option is None else largest_option[1]
        ),
        "largest_abs_option_share": (
            None
            if largest_option is None or abs_total == ZERO
            else str(abs(largest_option[3]) / abs_total)
        ),
        "leave_one_option_out_min_pnl": (
            None
            if not leave_one_option
            else str(min(leave_one_option))
        ),
        "positive_after_any_single_option_removed": (
            None
            if len(exact) < 2
            else min(leave_one_option) > ZERO
        ),
        "exact_market_pnl": {
            market: str(value)
            for market, value in market_values.items()
        },
        "largest_abs_market": (
            None if largest_market is None else largest_market[0]
        ),
        "largest_abs_market_pnl": (
            None if largest_market is None else str(largest_market[1])
        ),
        "largest_abs_market_share": (
            None
            if largest_market is None or abs_market_total == ZERO
            else str(abs(largest_market[1]) / abs_market_total)
        ),
        "leave_one_market_out_min_pnl": (
            None
            if not leave_one_market
            else str(min(leave_one_market))
        ),
        "positive_after_any_single_market_removed": (
            None
            if len(market_values) < 2
            else min(leave_one_market) > ZERO
        ),
        "temporal": {
            "chronological_blocks": blocks,
            "configured_blocks": TEMPORAL_BLOCKS,
            "min_options_per_full_block": MIN_OPTIONS_PER_FULL_BLOCK,
            "full_blocks": len(full_blocks),
            "positive_full_blocks": positive_full_blocks,
            "all_full_blocks_positive": (
                len(full_blocks) == TEMPORAL_BLOCKS
                and positive_full_blocks == TEMPORAL_BLOCKS
            ),
        },
    }
