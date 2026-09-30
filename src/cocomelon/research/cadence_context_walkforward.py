from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, cast

from cocomelon.domain.strategy import Direction
from cocomelon.research.cadence_context_learning import (
    _ContextEstimate,
    _ContextRow,
    _estimate,
    _fit,
    _resolve_rows,
    evaluate_cadence_context_learning,
)
from cocomelon.research.cadence_opportunity_learning import (
    DEFAULT_CONFIG,
    CadenceOpportunityLearningConfig,
    _score_band,
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
DEFAULT_WALK_FORWARD_WINDOW_ROWS: Final = 300


class CadenceContextWalkForwardError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CadenceContextWalkForwardConfig:
    window_rows: int = DEFAULT_WALK_FORWARD_WINDOW_ROWS
    admission_margin: Decimal = ZERO

    def __post_init__(self) -> None:
        if self.window_rows <= 0:
            raise ValueError("window_rows must be positive")
        if (
            not self.admission_margin.is_finite()
            or self.admission_margin < ZERO
        ):
            raise ValueError(
                "admission_margin must be non-negative and finite"
            )


DEFAULT_WALK_FORWARD_CONFIG: Final = (
    CadenceContextWalkForwardConfig()
)


@dataclass(frozen=True, slots=True)
class _WalkForwardPrediction:
    row: _ContextRow
    admitted: bool
    estimate: _ContextEstimate
    training_rows: int
    prior_validation_labels_used: int


def _direction_summary(
    predictions: tuple[_WalkForwardPrediction, ...],
) -> dict[str, object]:
    payload: dict[str, object] = {}
    for direction in (Direction.LONG.value, Direction.SHORT.value):
        cohort = tuple(
            item
            for item in predictions
            if item.row.outcome.sample.direction.value == direction
        )
        admitted = tuple(
            item.row.outcome
            for item in cohort
            if item.admitted
        )
        actual_sum = sum(
            (item.row.outcome.net_return for item in cohort),
            ZERO,
        )
        candidate_sum = sum(
            (row.net_return for row in admitted),
            ZERO,
        )
        payload[direction] = {
            "validation_rows": len(cohort),
            "admitted_rows": len(admitted),
            "actual_net_return_sum": str(actual_sum),
            "candidate_net_return_sum": str(candidate_sum),
            "delta_net_return_sum": str(candidate_sum - actual_sum),
            "candidate_mean_net_return": (
                None
                if not admitted
                else str(
                    candidate_sum / Decimal(len(admitted))
                )
            ),
        }
    return payload


def _stability_blocks(
    predictions: tuple[_WalkForwardPrediction, ...],
    *,
    blocks: int,
    min_block_admitted: int,
) -> tuple[dict[str, object], ...]:
    output: list[dict[str, object]] = []
    count = len(predictions)
    for index in range(blocks):
        start = index * count // blocks
        end = (index + 1) * count // blocks
        block = predictions[start:end]
        admitted = tuple(
            item.row.outcome
            for item in block
            if item.admitted
        )
        net_sum = sum((row.net_return for row in admitted), ZERO)
        mean = (
            None
            if not admitted
            else net_sum / Decimal(len(admitted))
        )
        output.append(
            {
                "block_index": index,
                "validation_rows": len(block),
                "admitted_rows": len(admitted),
                "candidate_net_return_sum": str(net_sum),
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


def _cohort_summary(
    predictions: tuple[_WalkForwardPrediction, ...],
    *,
    admitted: bool,
) -> tuple[dict[str, object], ...]:
    groups: dict[
        tuple[str, str, str, str, str],
        list[_WalkForwardPrediction],
    ] = defaultdict(list)
    for item in predictions:
        if item.admitted is not admitted:
            continue
        sample = item.row.outcome.sample
        groups[
            (
                sample.direction.value,
                sample.lead_strategy,
                _score_band(sample.score),
                item.row.feature.trend_regime.value,
                item.row.feature.volatility_regime.value,
            )
        ].append(item)

    output: list[tuple[Decimal, dict[str, object]]] = []
    for key, items in groups.items():
        outcomes = tuple(item.row.outcome for item in items)
        net_sum = sum((row.net_return for row in outcomes), ZERO)
        estimate_means = tuple(item.estimate.mean for item in items)
        estimate_rows = tuple(item.estimate.count for item in items)
        specificity = Counter(
            item.estimate.specificity for item in items
        )
        output.append(
            (
                net_sum,
                {
                    "direction": key[0],
                    "lead_strategy": key[1],
                    "score_band": key[2],
                    "trend_regime": key[3],
                    "volatility_regime": key[4],
                    "validation_rows": len(items),
                    "positive_rows": sum(
                        1 for row in outcomes if row.net_return > ZERO
                    ),
                    "negative_rows": sum(
                        1 for row in outcomes if row.net_return < ZERO
                    ),
                    "validation_net_return_sum": str(net_sum),
                    "validation_mean_net_return": str(
                        net_sum / Decimal(len(outcomes))
                    ),
                    "mean_training_estimate": str(
                        sum(estimate_means, ZERO)
                        / Decimal(len(estimate_means))
                    ),
                    "min_training_estimate": str(min(estimate_means)),
                    "max_training_estimate": str(max(estimate_means)),
                    "min_training_support": min(estimate_rows),
                    "max_training_support": max(estimate_rows),
                    "estimate_specificity_counts": dict(specificity),
                },
            )
        )
    output.sort(
        key=lambda item: (
            -item[0] if admitted else item[0],
            str(item[1]["direction"]),
            str(item[1]["trend_regime"]),
            str(item[1]["volatility_regime"]),
        )
    )
    return tuple(payload for _, payload in output)


def evaluate_cadence_context_walk_forward(
    outcomes: tuple[ShadowCadenceOutcome, ...],
    feature_store: LearningFeatureSnapshotStore,
    *,
    cadence_ms: int = FIFTEEN_MINUTES_MS,
    horizon_ms: int = ONE_HOUR_MS,
    learning_config: CadenceOpportunityLearningConfig = DEFAULT_CONFIG,
    walk_forward_config: CadenceContextWalkForwardConfig = (
        DEFAULT_WALK_FORWARD_CONFIG
    ),
) -> dict[str, object]:
    if walk_forward_config.window_rows < learning_config.min_train_rows:
        raise ValueError(
            "walk-forward window must cover min_train_rows"
        )

    surface = tuple(
        sorted(
            (
                row
                for row in outcomes
                if row.sample.cadence_ms == cadence_ms
                and row.sample.horizon_ms == horizon_ms
            ),
            key=lambda row: (
                row.sample.boundary_ms,
                row.sample.market.canonical,
                row.sample.decision_id,
            ),
        )
    )
    if len(surface) < learning_config.validation_rows:
        return {
            "status": "not_ready",
            "reason": "insufficient_validation_rows",
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "settled_rows": len(surface),
        }

    rows, missing = _resolve_rows(surface, feature_store)
    if missing:
        return {
            "status": "not_ready",
            "reason": "feature_snapshot_missing",
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "missing_feature_snapshots": len(missing),
            "missing_feature_snapshot_ids": missing[:20],
        }

    validation = rows[-learning_config.validation_rows :]
    validation_ids = {
        item.outcome.sample.decision_id for item in validation
    }
    predictions: list[_WalkForwardPrediction] = []

    for row in validation:
        boundary_ms = row.outcome.sample.boundary_ms
        eligible = tuple(
            historical
            for historical in rows
            if (
                historical.outcome.sample.target_end_ms < boundary_ms
                and historical.outcome.sample.decision_id
                != row.outcome.sample.decision_id
            )
        )
        training = eligible[-walk_forward_config.window_rows :]
        if len(training) < learning_config.min_train_rows:
            return {
                "status": "not_ready",
                "reason": "insufficient_walk_forward_training_rows",
                "research_only": True,
                "execution_authority": False,
                "promotion_authority": False,
                "validation_boundary_ms": boundary_ms,
                "training_rows": len(training),
            }
        sums, counts = _fit(training)
        estimate = _estimate(
            row,
            sums,
            counts,
            min_group_rows=learning_config.min_group_rows,
        )
        if estimate is None:
            return {
                "status": "not_ready",
                "reason": "walk_forward_estimate_missing",
                "research_only": True,
                "execution_authority": False,
                "promotion_authority": False,
                "validation_boundary_ms": boundary_ms,
            }
        prior_validation_labels_used = sum(
            1
            for historical in training
            if historical.outcome.sample.decision_id in validation_ids
        )
        predictions.append(
            _WalkForwardPrediction(
                row=row,
                admitted=(
                    estimate.mean
                    > walk_forward_config.admission_margin
                ),
                estimate=estimate,
                training_rows=len(training),
                prior_validation_labels_used=(
                    prior_validation_labels_used
                ),
            )
        )

    resolved = tuple(predictions)
    admitted = tuple(
        item.row.outcome for item in resolved if item.admitted
    )
    actual_sum = sum(
        (item.row.outcome.net_return for item in resolved),
        ZERO,
    )
    candidate_sum = sum((row.net_return for row in admitted), ZERO)
    candidate_mean = (
        None
        if not admitted
        else candidate_sum / Decimal(len(admitted))
    )
    blocks = _stability_blocks(
        resolved,
        blocks=learning_config.stability_blocks,
        min_block_admitted=learning_config.min_block_admitted,
    )
    long_validation = sum(
        1
        for item in resolved
        if item.row.outcome.sample.direction is Direction.LONG
    )
    short_validation = sum(
        1
        for item in resolved
        if item.row.outcome.sample.direction is Direction.SHORT
    )
    long_admitted = sum(
        1
        for item in resolved
        if item.admitted
        and item.row.outcome.sample.direction is Direction.LONG
    )
    short_admitted = sum(
        1
        for item in resolved
        if item.admitted
        and item.row.outcome.sample.direction is Direction.SHORT
    )
    structural_ready = (
        len(resolved) == learning_config.validation_rows
        and long_validation
        >= learning_config.min_validation_per_direction
        and short_validation
        >= learning_config.min_validation_per_direction
    )
    stable = all(bool(block["passes"]) for block in blocks)
    development_qualified = (
        structural_ready
        and len(admitted)
        >= learning_config.min_validation_admitted
        and long_admitted
        >= learning_config.min_admitted_per_direction
        and short_admitted
        >= learning_config.min_admitted_per_direction
        and candidate_mean is not None
        and candidate_mean > ZERO
        and stable
    )

    baseline = evaluate_cadence_context_learning(
        outcomes,
        feature_store,
        cadence_ms=cadence_ms,
        horizon_ms=horizon_ms,
        config=learning_config,
    )
    baseline_sum = Decimal(
        str(baseline.get("candidate_net_return_sum", "0"))
    )
    baseline_admitted = cast(
        int,
        baseline.get("admitted_rows", 0),
    )

    specificity = Counter(
        item.estimate.specificity for item in resolved
    )
    training_counts = tuple(item.training_rows for item in resolved)
    online_counts = tuple(
        item.prior_validation_labels_used for item in resolved
    )

    return {
        "status": "completed",
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "claim_scope": (
            "touched_prequential_walk_forward_context_development"
        ),
        "model_family": "rolling_context_grouped_mean_v1",
        "decision_policy": (
            "rolling_fully_settled_context_mean_gt_margin"
        ),
        "cadence_ms": cadence_ms,
        "horizon_ms": horizon_ms,
        "settled_rows": len(surface),
        "validation_rows": len(resolved),
        "admitted_rows": len(admitted),
        "skipped_rows": len(resolved) - len(admitted),
        "actual_net_return_sum": str(actual_sum),
        "candidate_net_return_sum": str(candidate_sum),
        "delta_net_return_sum": str(candidate_sum - actual_sum),
        "candidate_mean_net_return": (
            None if candidate_mean is None else str(candidate_mean)
        ),
        "positive_admitted_rows": sum(
            1 for row in admitted if row.net_return > ZERO
        ),
        "negative_admitted_rows": sum(
            1 for row in admitted if row.net_return < ZERO
        ),
        "prediction_specificity_counts": dict(specificity),
        "walk_forward_training_rows_min": min(training_counts),
        "walk_forward_training_rows_max": max(training_counts),
        "prior_validation_labels_used_min": min(online_counts),
        "prior_validation_labels_used_max": max(online_counts),
        "by_direction": _direction_summary(resolved),
        "admitted_cohorts": _cohort_summary(
            resolved,
            admitted=True,
        ),
        "skipped_cohorts": _cohort_summary(
            resolved,
            admitted=False,
        ),
        "stability_blocks": blocks,
        "structural_ready": structural_ready,
        "development_qualified": development_qualified,
        "baseline_context_model": {
            "status": baseline.get("status"),
            "admitted_rows": baseline_admitted,
            "candidate_net_return_sum": str(baseline_sum),
            "development_qualified": baseline.get(
                "development_qualified"
            ),
        },
        "walk_forward_minus_baseline_net_return_sum": str(
            candidate_sum - baseline_sum
        ),
        "walk_forward_minus_baseline_admitted_rows": (
            len(admitted) - baseline_admitted
        ),
        "configuration": {
            "window_rows": walk_forward_config.window_rows,
            "admission_margin": str(
                walk_forward_config.admission_margin
            ),
            "min_train_rows": learning_config.min_train_rows,
            "min_group_rows": learning_config.min_group_rows,
            "validation_rows": learning_config.validation_rows,
            "stability_blocks": learning_config.stability_blocks,
            "min_validation_admitted": (
                learning_config.min_validation_admitted
            ),
            "min_block_admitted": (
                learning_config.min_block_admitted
            ),
            "min_validation_per_direction": (
                learning_config.min_validation_per_direction
            ),
            "min_admitted_per_direction": (
                learning_config.min_admitted_per_direction
            ),
        },
    }
