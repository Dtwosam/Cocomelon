from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Final

from cocomelon.domain.strategy import Direction
from cocomelon.research.cadence_opportunity_learning import (
    DEFAULT_CONFIG,
    CadenceOpportunityLearningConfig,
    _estimate,
    _fit_group_means,
    _score_band,
)
from cocomelon.research.cadence_shadow import (
    FIFTEEN_MINUTES_MS,
    ONE_HOUR_MS,
    ShadowCadenceOutcome,
)

ZERO: Final = Decimal("0")
HALF: Final = Decimal("0.5")


class CadenceOpportunityRobustnessError(RuntimeError):
    pass


def _ordered_surface(
    outcomes: tuple[ShadowCadenceOutcome, ...],
    *,
    cadence_ms: int,
    horizon_ms: int,
) -> tuple[ShadowCadenceOutcome, ...]:
    return tuple(
        sorted(
            (
                outcome
                for outcome in outcomes
                if outcome.sample.cadence_ms == cadence_ms
                and outcome.sample.horizon_ms == horizon_ms
            ),
            key=lambda item: (
                item.sample.boundary_ms,
                item.sample.market.canonical,
                item.sample.decision_id,
            ),
        )
    )


def _row_summary(
    rows: tuple[ShadowCadenceOutcome, ...],
) -> dict[str, object]:
    total = sum((row.net_return for row in rows), ZERO)
    return {
        "rows": len(rows),
        "positive_rows": sum(
            1 for row in rows if row.net_return > ZERO
        ),
        "negative_rows": sum(
            1 for row in rows if row.net_return < ZERO
        ),
        "flat_rows": sum(
            1 for row in rows if row.net_return == ZERO
        ),
        "net_return_sum": str(total),
        "mean_net_return": (
            None
            if not rows
            else str(total / Decimal(len(rows)))
        ),
    }


def _block_ranges(
    count: int,
    blocks: int,
) -> tuple[tuple[int, int], ...]:
    return tuple(
        (
            index * count // blocks,
            (index + 1) * count // blocks,
        )
        for index in range(blocks)
    )


def _market_payload(
    admitted: tuple[tuple[int, ShadowCadenceOutcome], ...],
    *,
    validation_count: int,
    blocks: int,
) -> tuple[dict[str, object], ...]:
    grouped: dict[
        str,
        list[tuple[int, ShadowCadenceOutcome]],
    ] = defaultdict(list)
    for index, row in admitted:
        grouped[row.sample.market.canonical].append((index, row))

    ranges = _block_ranges(validation_count, blocks)
    payload: list[dict[str, object]] = []
    for market, items in grouped.items():
        rows = tuple(row for _, row in items)
        summary = _row_summary(rows)
        block_payload: list[dict[str, object]] = []
        for block_index, (start, end) in enumerate(ranges):
            block_rows = tuple(
                row
                for index, row in items
                if start <= index < end
            )
            block_payload.append(
                {
                    "block_index": block_index,
                    **_row_summary(block_rows),
                }
            )
        payload.append(
            {
                "market": market,
                **summary,
                "blocks": tuple(block_payload),
            }
        )

    payload.sort(
        key=lambda item: (
            -abs(Decimal(str(item["net_return_sum"]))),
            str(item["market"]),
        )
    )
    return tuple(payload)


def _cohort_payload(
    admitted: tuple[
        tuple[int, ShadowCadenceOutcome, object],
        ...,
    ],
    *,
    validation_count: int,
    blocks: int,
) -> tuple[dict[str, object], ...]:
    grouped: dict[
        tuple[str, str, str],
        list[tuple[int, ShadowCadenceOutcome, object]],
    ] = defaultdict(list)
    for index, row, estimate in admitted:
        grouped[
            (
                row.sample.direction.value,
                row.sample.lead_strategy,
                _score_band(row.sample.score),
            )
        ].append((index, row, estimate))

    ranges = _block_ranges(validation_count, blocks)
    payload: list[dict[str, object]] = []
    for key, items in grouped.items():
        rows = tuple(row for _, row, _ in items)
        estimates = tuple(estimate for _, _, estimate in items)
        first = estimates[0]
        if any(estimate != first for estimate in estimates[1:]):
            raise CadenceOpportunityRobustnessError(
                "cohort training estimate drifted inside validation"
            )
        block_payload: list[dict[str, object]] = []
        for block_index, (start, end) in enumerate(ranges):
            block_rows = tuple(
                row
                for index, row, _ in items
                if start <= index < end
            )
            block_payload.append(
                {
                    "block_index": block_index,
                    **_row_summary(block_rows),
                }
            )
        markets = _market_payload(
            tuple((index, row) for index, row, _ in items),
            validation_count=validation_count,
            blocks=blocks,
        )
        payload.append(
            {
                "direction": key[0],
                "lead_strategy": key[1],
                "score_band": key[2],
                "training_estimate_mean_net_return": str(first.mean),
                "training_estimate_rows": first.count,
                "training_estimate_specificity": first.specificity,
                **_row_summary(rows),
                "blocks": tuple(block_payload),
                "markets": markets,
            }
        )

    payload.sort(
        key=lambda item: (
            -Decimal(str(item["net_return_sum"])),
            str(item["direction"]),
            str(item["lead_strategy"]),
            str(item["score_band"]),
        )
    )
    return tuple(payload)


def evaluate_cadence_opportunity_robustness(
    outcomes: tuple[ShadowCadenceOutcome, ...],
    *,
    cadence_ms: int = FIFTEEN_MINUTES_MS,
    horizon_ms: int = ONE_HOUR_MS,
    config: CadenceOpportunityLearningConfig = DEFAULT_CONFIG,
) -> dict[str, object]:
    ordered = _ordered_surface(
        outcomes,
        cadence_ms=cadence_ms,
        horizon_ms=horizon_ms,
    )
    if len(ordered) < config.validation_rows:
        return {
            "status": "not_ready",
            "reason": "insufficient_validation_rows",
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "settled_rows": len(ordered),
        }

    validation = ordered[-config.validation_rows :]
    validation_start_ms = validation[0].sample.boundary_ms
    train_candidates = ordered[: -config.validation_rows]
    training = tuple(
        row
        for row in train_candidates
        if row.sample.target_end_ms < validation_start_ms
    )
    purged = len(train_candidates) - len(training)
    if len(training) < config.min_train_rows:
        return {
            "status": "not_ready",
            "reason": "insufficient_purged_training_rows",
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "settled_rows": len(ordered),
            "training_rows": len(training),
            "validation_rows": len(validation),
            "purged_overlap_rows": purged,
        }

    sums, counts = _fit_group_means(training)
    scored: list[tuple[int, ShadowCadenceOutcome, bool, object]] = []
    missing_estimates = 0
    for index, row in enumerate(validation):
        estimate = _estimate(
            row,
            sums,
            counts,
            min_group_rows=config.min_group_rows,
        )
        if estimate is None:
            missing_estimates += 1
            continue
        scored.append(
            (
                index,
                row,
                estimate.mean > ZERO,
                estimate,
            )
        )
    if missing_estimates:
        return {
            "status": "not_ready",
            "reason": "validation_estimate_missing",
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "settled_rows": len(ordered),
            "training_rows": len(training),
            "validation_rows": len(validation),
            "purged_overlap_rows": purged,
            "missing_validation_estimates": missing_estimates,
        }

    admitted = tuple(
        (index, row, estimate)
        for index, row, take, estimate in scored
        if take
    )
    admitted_rows = tuple(row for _, row, _ in admitted)
    total = sum((row.net_return for row in admitted_rows), ZERO)
    markets = _market_payload(
        tuple((index, row) for index, row, _ in admitted),
        validation_count=len(validation),
        blocks=config.stability_blocks,
    )
    market_sums = tuple(
        Decimal(str(item["net_return_sum"]))
        for item in markets
    )
    absolute_total = sum(
        (abs(value) for value in market_sums),
        ZERO,
    )
    largest_abs_share = (
        None
        if absolute_total == ZERO
        else max(abs(value) for value in market_sums) / absolute_total
    )
    hhi = (
        None
        if absolute_total == ZERO
        else sum(
            (
                (abs(value) / absolute_total) ** 2
                for value in market_sums
            ),
            ZERO,
        )
    )
    positive_markets = tuple(
        item
        for item in markets
        if Decimal(str(item["net_return_sum"])) > ZERO
    )
    negative_markets = tuple(
        item
        for item in markets
        if Decimal(str(item["net_return_sum"])) < ZERO
    )
    largest_positive = (
        None
        if not positive_markets
        else max(
            positive_markets,
            key=lambda item: Decimal(
                str(item["net_return_sum"])
            ),
        )
    )
    without_largest_positive = (
        None
        if largest_positive is None
        else total
        - Decimal(str(largest_positive["net_return_sum"]))
    )
    leave_one_out = tuple(
        {
            "market": str(item["market"]),
            "candidate_net_return_sum": str(
                total - Decimal(str(item["net_return_sum"]))
            ),
        }
        for item in markets
    )
    leave_one_out_values = tuple(
        Decimal(str(item["candidate_net_return_sum"]))
        for item in leave_one_out
    )

    ranges = _block_ranges(
        len(validation),
        config.stability_blocks,
    )
    blocks: list[dict[str, object]] = []
    for block_index, (start, end) in enumerate(ranges):
        block_rows = tuple(
            row
            for index, row, _ in admitted
            if start <= index < end
        )
        blocks.append(
            {
                "block_index": block_index,
                **_row_summary(block_rows),
            }
        )

    cohorts = _cohort_payload(
        admitted,
        validation_count=len(validation),
        blocks=config.stability_blocks,
    )
    nonempty_blocks = tuple(
        block for block in blocks if int(block["rows"]) > 0
    )
    return {
        "status": "completed",
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "claim_scope": (
            "touched_validation_concentration_and_block_diagnostics"
        ),
        "cadence_ms": cadence_ms,
        "horizon_ms": horizon_ms,
        "settled_rows": len(ordered),
        "training_rows": len(training),
        "validation_rows": len(validation),
        "purged_overlap_rows": purged,
        "admitted_rows": len(admitted_rows),
        "candidate_net_return_sum": str(total),
        "candidate_mean_net_return": (
            None
            if not admitted_rows
            else str(total / Decimal(len(admitted_rows)))
        ),
        "market_count": len(markets),
        "positive_market_count": len(positive_markets),
        "negative_market_count": len(negative_markets),
        "flat_market_count": (
            len(markets) - len(positive_markets) - len(negative_markets)
        ),
        "absolute_market_contribution_sum": str(absolute_total),
        "largest_abs_market_share": (
            None
            if largest_abs_share is None
            else str(largest_abs_share)
        ),
        "absolute_market_contribution_hhi": (
            None if hhi is None else str(hhi)
        ),
        "largest_positive_market": largest_positive,
        "candidate_net_return_sum_without_largest_positive_market": (
            None
            if without_largest_positive is None
            else str(without_largest_positive)
        ),
        "leave_one_market_out": leave_one_out,
        "leave_one_market_out_min_sum": (
            None
            if not leave_one_out_values
            else str(min(leave_one_out_values))
        ),
        "leave_one_market_out_max_sum": (
            None
            if not leave_one_out_values
            else str(max(leave_one_out_values))
        ),
        "blocks": tuple(blocks),
        "cohorts": cohorts,
        "markets": markets,
        "diagnostic_checks": {
            "candidate_sum_positive": total > ZERO,
            "positive_after_removing_largest_positive_market": (
                without_largest_positive is not None
                and without_largest_positive > ZERO
            ),
            "at_least_three_positive_markets": (
                len(positive_markets) >= 3
            ),
            "largest_abs_market_share_lte_half": (
                largest_abs_share is not None
                and largest_abs_share <= HALF
            ),
            "all_blocks_have_min_admissions": all(
                int(block["rows"]) >= config.min_block_admitted
                for block in blocks
            ),
            "all_nonempty_blocks_positive": (
                bool(nonempty_blocks)
                and all(
                    Decimal(str(block["net_return_sum"])) > ZERO
                    for block in nonempty_blocks
                )
            ),
        },
    }
