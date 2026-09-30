from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from cocomelon.domain.strategy import Direction
from cocomelon.research.cadence_context_confidence import (
    DEFAULT_CONFIDENCE_CONFIG,
    CadenceContextConfidenceConfig,
    _ConfidenceEstimate,
    _estimate,
    _fit_stats,
)
from cocomelon.research.cadence_context_learning import (
    _ContextRow,
    _resolve_rows,
)
from cocomelon.research.cadence_opportunity_learning import (
    DEFAULT_CONFIG,
    CadenceOpportunityLearningConfig,
)
from cocomelon.research.cadence_shadow import (
    FIFTEEN_MINUTES_MS,
    ONE_HOUR_MS,
    ShadowCadenceOutcome,
)
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotStore,
)

ZERO: Final = Decimal("0")
DEFAULT_LOOKBACK_ROWS: Final = 300
DEFAULT_EVALUATION_ROWS: Final = 100


@dataclass(frozen=True, slots=True)
class CadenceWalkForwardConfig:
    lookback_rows: int = DEFAULT_LOOKBACK_ROWS
    evaluation_rows: int = DEFAULT_EVALUATION_ROWS

    def __post_init__(self) -> None:
        if self.lookback_rows <= 0:
            raise ValueError("lookback_rows must be positive")
        if self.evaluation_rows <= 0:
            raise ValueError("evaluation_rows must be positive")


DEFAULT_WALK_FORWARD_CONFIG: Final = CadenceWalkForwardConfig()


def _direction_summary(
    rows: tuple[
        tuple[_ContextRow, bool, _ConfidenceEstimate | None],
        ...,
    ],
) -> dict[str, object]:
    output: dict[str, object] = {}
    for direction in (Direction.LONG.value, Direction.SHORT.value):
        cohort = tuple(
            (row, take, estimate)
            for row, take, estimate in rows
            if row.outcome.sample.direction.value == direction
        )
        admitted = tuple(
            row.outcome
            for row, take, _estimate_value in cohort
            if take
        )
        actual_total = sum(
            (row.outcome.net_return for row, _, _ in cohort),
            ZERO,
        )
        candidate_total = sum(
            (row.net_return for row in admitted),
            ZERO,
        )
        output[direction] = {
            "validation_rows": len(cohort),
            "admitted_rows": len(admitted),
            "skipped_rows": len(cohort) - len(admitted),
            "no_supported_estimate_rows": sum(
                1
                for _row, _take, estimate in cohort
                if estimate is None
            ),
            "actual_net_return_sum": str(actual_total),
            "candidate_net_return_sum": str(candidate_total),
            "delta_net_return_sum": str(
                candidate_total - actual_total
            ),
            "candidate_mean_net_return": (
                None
                if not admitted
                else str(candidate_total / Decimal(len(admitted)))
            ),
        }
    return output


def _stability_blocks(
    rows: tuple[
        tuple[_ContextRow, bool, _ConfidenceEstimate | None],
        ...,
    ],
    *,
    blocks: int,
    min_block_admitted: int,
) -> tuple[dict[str, object], ...]:
    output: list[dict[str, object]] = []
    count = len(rows)
    for index in range(blocks):
        start = index * count // blocks
        end = (index + 1) * count // blocks
        block = rows[start:end]
        admitted = tuple(
            row.outcome
            for row, take, _estimate_value in block
            if take
        )
        total = sum((row.net_return for row in admitted), ZERO)
        mean = (
            None
            if not admitted
            else total / Decimal(len(admitted))
        )
        output.append(
            {
                "block_index": index,
                "validation_rows": len(block),
                "admitted_rows": len(admitted),
                "no_supported_estimate_rows": sum(
                    1
                    for _row, _take, estimate in block
                    if estimate is None
                ),
                "candidate_net_return_sum": str(total),
                "candidate_mean_net_return": (
                    None if mean is None else str(mean)
                ),
                "passes": (
                    len(admitted) >= min_block_admitted
                    and mean is not None
                    and mean > ZERO
                ),
            }
        )
    return tuple(output)


def _estimate_payload(
    rows: tuple[
        tuple[_ContextRow, bool, _ConfidenceEstimate | None],
        ...,
    ],
) -> tuple[dict[str, object], ...]:
    grouped: defaultdict[
        tuple[str, str, str, str, str],
        list[tuple[_ContextRow, bool, _ConfidenceEstimate]],
    ] = defaultdict(list)
    for row, take, estimate in rows:
        if estimate is None:
            continue
        grouped[
            (
                row.outcome.sample.direction.value,
                row.outcome.sample.lead_strategy,
                row.feature.trend_regime.value,
                row.feature.volatility_regime.value,
                estimate.specificity,
            )
        ].append((row, take, estimate))

    output: list[tuple[Decimal, dict[str, object]]] = []
    for key, items in grouped.items():
        admitted = tuple(
            row.outcome
            for row, take, _estimate_value in items
            if take
        )
        total = sum((row.net_return for row in admitted), ZERO)
        estimates = tuple(item[2] for item in items)
        output.append(
            (
                total,
                {
                    "direction": key[0],
                    "lead_strategy": key[1],
                    "trend_regime": key[2],
                    "volatility_regime": key[3],
                    "estimate_specificity": key[4],
                    "validation_rows": len(items),
                    "admitted_rows": len(admitted),
                    "candidate_net_return_sum": str(total),
                    "candidate_mean_net_return": (
                        None
                        if not admitted
                        else str(total / Decimal(len(admitted)))
                    ),
                    "mean_training_rows": str(
                        sum(
                            (
                                Decimal(estimate.count)
                                for estimate in estimates
                            ),
                            ZERO,
                        )
                        / Decimal(len(estimates))
                    ),
                    "mean_training_lower_bound": str(
                        sum(
                            (
                                estimate.lower_bound
                                for estimate in estimates
                            ),
                            ZERO,
                        )
                        / Decimal(len(estimates))
                    ),
                },
            )
        )
    output.sort(
        key=lambda item: (
            -item[0],
            str(item[1]["direction"]),
            str(item[1]["trend_regime"]),
            str(item[1]["volatility_regime"]),
        )
    )
    return tuple(payload for _, payload in output)


def evaluate_cadence_walk_forward_confidence(
    outcomes: tuple[ShadowCadenceOutcome, ...],
    feature_store: LearningFeatureSnapshotStore,
    *,
    cadence_ms: int = FIFTEEN_MINUTES_MS,
    horizon_ms: int = ONE_HOUR_MS,
    validation_config: CadenceOpportunityLearningConfig = DEFAULT_CONFIG,
    confidence_config: CadenceContextConfidenceConfig = (
        DEFAULT_CONFIDENCE_CONFIG
    ),
    walk_forward_config: CadenceWalkForwardConfig = (
        DEFAULT_WALK_FORWARD_CONFIG
    ),
) -> dict[str, object]:
    surface = tuple(
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
    if len(surface) < walk_forward_config.evaluation_rows:
        return {
            "status": "not_ready",
            "reason": "insufficient_evaluation_rows",
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "settled_rows": len(surface),
        }

    context_rows, missing = _resolve_rows(surface, feature_store)
    if missing:
        return {
            "status": "not_ready",
            "reason": "feature_snapshot_missing",
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "missing_feature_snapshots": len(missing),
        }

    evaluation = context_rows[-walk_forward_config.evaluation_rows :]
    scored: list[
        tuple[_ContextRow, bool, _ConfidenceEstimate | None]
    ] = []
    history_counts: list[int] = []
    skipped_for_history = 0

    for row in evaluation:
        history = tuple(
            candidate
            for candidate in context_rows
            if (
                candidate.outcome.sample.target_end_ms
                < row.outcome.sample.boundary_ms
            )
        )
        if len(history) > walk_forward_config.lookback_rows:
            history = history[-walk_forward_config.lookback_rows :]
        history_counts.append(len(history))
        if len(history) < validation_config.min_train_rows:
            scored.append((row, False, None))
            skipped_for_history += 1
            continue

        stats = _fit_stats(history)
        estimate = _estimate(
            row,
            stats,
            config=confidence_config,
        )
        scored.append(
            (
                row,
                (
                    estimate is not None
                    and estimate.lower_bound > ZERO
                ),
                estimate,
            )
        )

    scored_rows = tuple(scored)
    admitted = tuple(
        row.outcome
        for row, take, _estimate_value in scored_rows
        if take
    )
    actual_total = sum(
        (row.outcome.net_return for row, _, _ in scored_rows),
        ZERO,
    )
    candidate_total = sum(
        (row.net_return for row in admitted),
        ZERO,
    )
    candidate_mean = (
        None
        if not admitted
        else candidate_total / Decimal(len(admitted))
    )
    blocks = _stability_blocks(
        scored_rows,
        blocks=validation_config.stability_blocks,
        min_block_admitted=validation_config.min_block_admitted,
    )
    long_validation = sum(
        1
        for row, _, _ in scored_rows
        if row.outcome.sample.direction is Direction.LONG
    )
    short_validation = sum(
        1
        for row, _, _ in scored_rows
        if row.outcome.sample.direction is Direction.SHORT
    )
    long_admitted = sum(
        1
        for row, take, _ in scored_rows
        if take and row.outcome.sample.direction is Direction.LONG
    )
    short_admitted = sum(
        1
        for row, take, _ in scored_rows
        if take and row.outcome.sample.direction is Direction.SHORT
    )
    structural_ready = (
        len(scored_rows) == walk_forward_config.evaluation_rows
        and long_validation
        >= validation_config.min_validation_per_direction
        and short_validation
        >= validation_config.min_validation_per_direction
        and skipped_for_history == 0
    )
    stable = all(bool(block["passes"]) for block in blocks)
    development_qualified = (
        structural_ready
        and len(admitted) >= validation_config.min_validation_admitted
        and long_admitted
        >= validation_config.min_admitted_per_direction
        and short_admitted
        >= validation_config.min_admitted_per_direction
        and candidate_mean is not None
        and candidate_mean > ZERO
        and stable
    )

    return {
        "status": "completed",
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "claim_scope": "touched_walk_forward_context_confidence",
        "model_family": "cadence_walk_forward_context_confidence_v1",
        "decision_policy": (
            "use_only_settled_recent_history_and_admit_if_context_lower_bound_gt_zero"
        ),
        "cadence_ms": cadence_ms,
        "horizon_ms": horizon_ms,
        "settled_rows": len(surface),
        "evaluation_rows": len(scored_rows),
        "lookback_rows": walk_forward_config.lookback_rows,
        "minimum_history_rows": min(history_counts),
        "maximum_history_rows": max(history_counts),
        "skipped_for_insufficient_history": skipped_for_history,
        "no_supported_estimate_rows": sum(
            1
            for _row, _take, estimate in scored_rows
            if estimate is None
        ),
        "admitted_rows": len(admitted),
        "skipped_rows": len(scored_rows) - len(admitted),
        "actual_net_return_sum": str(actual_total),
        "candidate_net_return_sum": str(candidate_total),
        "delta_net_return_sum": str(candidate_total - actual_total),
        "candidate_mean_net_return": (
            None if candidate_mean is None else str(candidate_mean)
        ),
        "positive_admitted_rows": sum(
            1 for row in admitted if row.net_return > ZERO
        ),
        "negative_admitted_rows": sum(
            1 for row in admitted if row.net_return < ZERO
        ),
        "by_direction": _direction_summary(scored_rows),
        "stability_blocks": blocks,
        "estimate_cohorts": _estimate_payload(scored_rows),
        "structural_ready": structural_ready,
        "development_qualified": development_qualified,
        "walk_forward_configuration": {
            "lookback_rows": walk_forward_config.lookback_rows,
            "evaluation_rows": walk_forward_config.evaluation_rows,
            "settlement_rule": (
                "history_target_end_ms_strictly_before_decision_boundary"
            ),
        },
        "confidence_configuration": {
            "min_local_rows": confidence_config.min_local_rows,
            "min_fallback_rows": confidence_config.min_fallback_rows,
            "standard_error_multiplier": str(
                confidence_config.standard_error_multiplier
            ),
        },
    }
