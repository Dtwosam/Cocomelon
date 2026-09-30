from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from cocomelon.domain.strategy import Direction
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
from cocomelon.research.cadence_tree_learning import (
    DEFAULT_TREE_CONFIG,
    FEATURE_REGISTRY,
    CadenceTreeConfig,
    _Encoder,
    _fit_tree,
    _predict,
)
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotStore,
)

ZERO: Final = Decimal("0")
DEFAULT_INNER_CALIBRATION_ROWS: Final = 100
DEFAULT_MIN_INNER_TRAIN_ROWS: Final = 300
DEFAULT_THRESHOLD_CANDIDATES: Final = (
    Decimal("0"),
    Decimal("0.0005"),
    Decimal("0.001"),
    Decimal("0.0015"),
    Decimal("0.002"),
    Decimal("0.003"),
    Decimal("0.005"),
)


@dataclass(frozen=True, slots=True)
class CadenceTreeNestedConfig:
    inner_calibration_rows: int = DEFAULT_INNER_CALIBRATION_ROWS
    min_inner_train_rows: int = DEFAULT_MIN_INNER_TRAIN_ROWS
    threshold_candidates: tuple[Decimal, ...] = (
        DEFAULT_THRESHOLD_CANDIDATES
    )

    def __post_init__(self) -> None:
        if self.inner_calibration_rows <= 0:
            raise ValueError(
                "inner_calibration_rows must be positive"
            )
        if self.min_inner_train_rows <= 0:
            raise ValueError("min_inner_train_rows must be positive")
        if not self.threshold_candidates:
            raise ValueError(
                "threshold_candidates must not be empty"
            )
        if self.threshold_candidates != tuple(
            sorted(set(self.threshold_candidates))
        ):
            raise ValueError(
                "threshold_candidates must be sorted and unique"
            )
        if any(
            not threshold.is_finite() or threshold < ZERO
            for threshold in self.threshold_candidates
        ):
            raise ValueError(
                "threshold_candidates must be finite and non-negative"
            )


DEFAULT_NESTED_CONFIG: Final = CadenceTreeNestedConfig()


def _blocks(
    rows: tuple[tuple[_ContextRow, Decimal], ...],
    *,
    threshold: Decimal,
    blocks: int,
) -> tuple[dict[str, object], ...]:
    output: list[dict[str, object]] = []
    count = len(rows)
    for index in range(blocks):
        start = index * count // blocks
        end = (index + 1) * count // blocks
        block = rows[start:end]
        admitted = tuple(
            row.outcome
            for row, prediction in block
            if prediction > threshold
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
                "rows": len(block),
                "admitted_rows": len(admitted),
                "net_return_sum": str(net_sum),
                "mean_net_return": (
                    None if mean is None else str(mean)
                ),
            }
        )
    return tuple(output)


def _threshold_result(
    rows: tuple[tuple[_ContextRow, Decimal], ...],
    *,
    threshold: Decimal,
    validation_config: CadenceOpportunityLearningConfig,
) -> dict[str, object]:
    admitted = tuple(
        row.outcome
        for row, prediction in rows
        if prediction > threshold
    )
    total = sum((row.net_return for row in admitted), ZERO)
    mean = (
        None
        if not admitted
        else total / Decimal(len(admitted))
    )
    long_count = sum(
        1
        for row, prediction in rows
        if prediction > threshold
        and row.outcome.sample.direction is Direction.LONG
    )
    short_count = sum(
        1
        for row, prediction in rows
        if prediction > threshold
        and row.outcome.sample.direction is Direction.SHORT
    )
    blocks = _blocks(
        rows,
        threshold=threshold,
        blocks=validation_config.stability_blocks,
    )
    stable = all(
        int(block["admitted_rows"])
        >= validation_config.min_block_admitted
        and block["mean_net_return"] is not None
        and Decimal(str(block["mean_net_return"])) > ZERO
        for block in blocks
    )
    eligible = (
        len(admitted) >= validation_config.min_validation_admitted
        and long_count
        >= validation_config.min_admitted_per_direction
        and short_count
        >= validation_config.min_admitted_per_direction
        and mean is not None
        and mean > ZERO
        and stable
    )
    return {
        "threshold": str(threshold),
        "admitted_rows": len(admitted),
        "long_admitted_rows": long_count,
        "short_admitted_rows": short_count,
        "net_return_sum": str(total),
        "mean_net_return": None if mean is None else str(mean),
        "stability_blocks": blocks,
        "eligible": eligible,
    }


def _select_threshold(
    rows: tuple[tuple[_ContextRow, Decimal], ...],
    *,
    candidates: tuple[Decimal, ...],
    validation_config: CadenceOpportunityLearningConfig,
) -> tuple[Decimal | None, tuple[dict[str, object], ...]]:
    results = tuple(
        _threshold_result(
            rows,
            threshold=threshold,
            validation_config=validation_config,
        )
        for threshold in candidates
    )
    eligible = tuple(
        result
        for result in results
        if result["eligible"] is True
    )
    if not eligible:
        return None, results
    selected = max(
        eligible,
        key=lambda result: (
            Decimal(str(result["mean_net_return"])),
            Decimal(str(result["net_return_sum"])),
            int(result["admitted_rows"]),
            -Decimal(str(result["threshold"])),
        ),
    )
    return Decimal(str(selected["threshold"])), results


def _direction_summary(
    rows: tuple[tuple[_ContextRow, Decimal], ...],
    *,
    threshold: Decimal | None,
) -> dict[str, object]:
    output: dict[str, object] = {}
    for direction in (Direction.LONG.value, Direction.SHORT.value):
        cohort = tuple(
            (row, prediction)
            for row, prediction in rows
            if row.outcome.sample.direction.value == direction
        )
        admitted = tuple(
            row.outcome
            for row, prediction in cohort
            if threshold is not None and prediction > threshold
        )
        actual_sum = sum(
            (row.outcome.net_return for row, _ in cohort),
            ZERO,
        )
        candidate_sum = sum(
            (row.net_return for row in admitted),
            ZERO,
        )
        output[direction] = {
            "validation_rows": len(cohort),
            "admitted_rows": len(admitted),
            "actual_net_return_sum": str(actual_sum),
            "candidate_net_return_sum": str(candidate_sum),
            "delta_net_return_sum": str(candidate_sum - actual_sum),
            "candidate_mean_net_return": (
                None
                if not admitted
                else str(candidate_sum / Decimal(len(admitted)))
            ),
        }
    return output


def evaluate_cadence_tree_nested(
    outcomes: tuple[ShadowCadenceOutcome, ...],
    feature_store: LearningFeatureSnapshotStore,
    *,
    cadence_ms: int = FIFTEEN_MINUTES_MS,
    horizon_ms: int = ONE_HOUR_MS,
    validation_config: CadenceOpportunityLearningConfig = DEFAULT_CONFIG,
    tree_config: CadenceTreeConfig = DEFAULT_TREE_CONFIG,
    nested_config: CadenceTreeNestedConfig = DEFAULT_NESTED_CONFIG,
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
    outer_count = validation_config.validation_rows
    if len(surface) < outer_count:
        return {
            "status": "not_ready",
            "reason": "insufficient_outer_validation_rows",
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
        }

    outer_validation = surface[-outer_count:]
    outer_start_ms = outer_validation[0].sample.boundary_ms
    outer_prefix = surface[:-outer_count]
    outer_training = tuple(
        row
        for row in outer_prefix
        if row.sample.target_end_ms < outer_start_ms
    )
    outer_purged = len(outer_prefix) - len(outer_training)
    if (
        len(outer_training)
        < nested_config.inner_calibration_rows
        + nested_config.min_inner_train_rows
    ):
        return {
            "status": "not_ready",
            "reason": "insufficient_nested_training_rows",
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "outer_training_rows": len(outer_training),
        }

    inner_calibration = outer_training[
        -nested_config.inner_calibration_rows :
    ]
    inner_start_ms = inner_calibration[0].sample.boundary_ms
    inner_prefix = outer_training[
        : -nested_config.inner_calibration_rows
    ]
    inner_training = tuple(
        row
        for row in inner_prefix
        if row.sample.target_end_ms < inner_start_ms
    )
    inner_purged = len(inner_prefix) - len(inner_training)
    if len(inner_training) < nested_config.min_inner_train_rows:
        return {
            "status": "not_ready",
            "reason": "insufficient_purged_inner_training_rows",
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "inner_training_rows": len(inner_training),
        }

    inner_rows, missing_inner = _resolve_rows(
        inner_training,
        feature_store,
    )
    calibration_rows, missing_calibration = _resolve_rows(
        inner_calibration,
        feature_store,
    )
    outer_rows, missing_outer = _resolve_rows(
        outer_validation,
        feature_store,
    )
    if missing_inner or missing_calibration or missing_outer:
        return {
            "status": "not_ready",
            "reason": "feature_snapshot_missing",
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "missing_inner_feature_snapshots": len(missing_inner),
            "missing_calibration_feature_snapshots": len(
                missing_calibration
            ),
            "missing_outer_feature_snapshots": len(missing_outer),
        }

    encoder = _Encoder.fit(inner_rows)
    estimator = _fit_tree(
        inner_rows,
        encoder=encoder,
        config=tree_config,
    )
    calibration_predictions = _predict(
        estimator,
        encoder,
        calibration_rows,
    )
    calibration_scored = tuple(
        zip(
            calibration_rows,
            calibration_predictions,
            strict=True,
        )
    )
    threshold, threshold_results = _select_threshold(
        calibration_scored,
        candidates=nested_config.threshold_candidates,
        validation_config=validation_config,
    )

    outer_predictions = _predict(estimator, encoder, outer_rows)
    outer_scored = tuple(
        zip(outer_rows, outer_predictions, strict=True)
    )
    admitted = tuple(
        row.outcome
        for row, prediction in outer_scored
        if threshold is not None and prediction > threshold
    )
    actual_sum = sum(
        (row.outcome.net_return for row, _ in outer_scored),
        ZERO,
    )
    candidate_sum = sum((row.net_return for row in admitted), ZERO)
    candidate_mean = (
        None
        if not admitted
        else candidate_sum / Decimal(len(admitted))
    )
    outer_blocks = (
        _blocks(
            outer_scored,
            threshold=threshold,
            blocks=validation_config.stability_blocks,
        )
        if threshold is not None
        else tuple(
            {
                "block_index": index,
                "rows": outer_count
                // validation_config.stability_blocks,
                "admitted_rows": 0,
                "net_return_sum": "0",
                "mean_net_return": None,
            }
            for index in range(
                validation_config.stability_blocks
            )
        )
    )
    long_validation = sum(
        1
        for row, _ in outer_scored
        if row.outcome.sample.direction is Direction.LONG
    )
    short_validation = sum(
        1
        for row, _ in outer_scored
        if row.outcome.sample.direction is Direction.SHORT
    )
    long_admitted = sum(
        1
        for row, prediction in outer_scored
        if threshold is not None
        and prediction > threshold
        and row.outcome.sample.direction is Direction.LONG
    )
    short_admitted = sum(
        1
        for row, prediction in outer_scored
        if threshold is not None
        and prediction > threshold
        and row.outcome.sample.direction is Direction.SHORT
    )
    stable = (
        threshold is not None
        and all(
            int(block["admitted_rows"])
            >= validation_config.min_block_admitted
            and block["mean_net_return"] is not None
            and Decimal(str(block["mean_net_return"])) > ZERO
            for block in outer_blocks
        )
    )
    structural_ready = (
        len(outer_scored) == outer_count
        and long_validation
        >= validation_config.min_validation_per_direction
        and short_validation
        >= validation_config.min_validation_per_direction
    )
    development_qualified = (
        threshold is not None
        and structural_ready
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
        "claim_scope": (
            "nested_temporal_cadence_tree_threshold_development"
        ),
        "model_family": "cadence_fixed_shallow_tree_nested_v1",
        "feature_registry": FEATURE_REGISTRY,
        "selected_threshold": (
            None if threshold is None else str(threshold)
        ),
        "threshold_candidates": tuple(
            str(value)
            for value in nested_config.threshold_candidates
        ),
        "calibration_results": threshold_results,
        "inner_training_rows": len(inner_rows),
        "inner_calibration_rows": len(calibration_rows),
        "inner_purged_overlap_rows": inner_purged,
        "outer_training_rows": len(outer_training),
        "outer_validation_rows": len(outer_rows),
        "outer_purged_overlap_rows": outer_purged,
        "outer_validation_start_ms": outer_start_ms,
        "outer_validation_end_ms": (
            outer_validation[-1].sample.target_end_ms
        ),
        "admitted_rows": len(admitted),
        "skipped_rows": len(outer_scored) - len(admitted),
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
        "by_direction": _direction_summary(
            outer_scored,
            threshold=threshold,
        ),
        "stability_blocks": outer_blocks,
        "structural_ready": structural_ready,
        "development_qualified": development_qualified,
        "tree_configuration": {
            "max_leaf_nodes": tree_config.max_leaf_nodes,
            "min_samples_leaf": tree_config.min_samples_leaf,
            "learning_rate": str(tree_config.learning_rate),
            "max_iter": tree_config.max_iter,
            "l2_regularization": str(
                tree_config.l2_regularization
            ),
        },
        "nested_configuration": {
            "inner_calibration_rows": (
                nested_config.inner_calibration_rows
            ),
            "min_inner_train_rows": (
                nested_config.min_inner_train_rows
            ),
        },
    }
