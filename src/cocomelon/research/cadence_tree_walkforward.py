from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final, cast

from cocomelon.research.cadence_context_learning import _resolve_rows
from cocomelon.research.cadence_shadow import (
    FIFTEEN_MINUTES_MS,
    ONE_HOUR_MS,
    ShadowCadenceOutcome,
)
from cocomelon.research.cadence_tree_learning import (
    DEFAULT_TREE_CONFIG,
    CadenceTreeConfig,
    _direction_summary,
    _Encoder,
    _fit_tree,
    _predict,
)
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotStore,
)

ZERO: Final = Decimal("0")


class CadenceTreeWalkforwardError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CadenceTreeWalkforwardConfig:
    validation_rows: int = 50
    folds: int = 6
    min_train_rows: int = 300

    def __post_init__(self) -> None:
        if self.validation_rows <= 0:
            raise ValueError("validation_rows must be positive")
        if self.folds <= 0:
            raise ValueError("folds must be positive")
        if self.min_train_rows <= 0:
            raise ValueError("min_train_rows must be positive")


DEFAULT_CONFIG: Final = CadenceTreeWalkforwardConfig()


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


def _fold_direction_admitted(
    fold: dict[str, object],
    direction: str,
) -> int:
    raw_direction = fold.get("by_direction")
    if not isinstance(raw_direction, dict):
        raise CadenceTreeWalkforwardError(
            "completed fold direction summary is invalid"
        )
    raw_row = raw_direction.get(direction)
    if not isinstance(raw_row, dict):
        raise CadenceTreeWalkforwardError(
            "completed fold direction row is invalid"
        )
    value = raw_row.get("admitted_rows")
    if isinstance(value, bool) or not isinstance(value, int):
        raise CadenceTreeWalkforwardError(
            "completed fold admitted row count is invalid"
        )
    return value


def _evaluate_fold(
    ordered: tuple[ShadowCadenceOutcome, ...],
    feature_store: LearningFeatureSnapshotStore,
    *,
    fold_index: int,
    start: int,
    end: int,
    config: CadenceTreeWalkforwardConfig,
    tree_config: CadenceTreeConfig,
) -> dict[str, object]:
    validation = ordered[start:end]
    if len(validation) != config.validation_rows:
        raise CadenceTreeWalkforwardError(
            "tree walk-forward validation window is incomplete"
        )
    validation_start_ms = validation[0].sample.boundary_ms
    train_candidates = ordered[:start]
    training = tuple(
        row
        for row in train_candidates
        if row.sample.target_end_ms < validation_start_ms
    )
    purged = len(train_candidates) - len(training)
    base = {
        "fold_index": fold_index,
        "validation_start_index": start,
        "validation_end_index_exclusive": end,
        "validation_start_ms": validation_start_ms,
        "validation_end_ms": validation[-1].sample.target_end_ms,
        "training_rows": len(training),
        "validation_rows": len(validation),
        "purged_overlap_rows": purged,
    }
    if len(training) < config.min_train_rows:
        return {
            **base,
            "status": "not_ready",
            "reason": "insufficient_purged_training_rows",
        }

    training_rows, missing_training = _resolve_rows(
        training,
        feature_store,
    )
    validation_rows, missing_validation = _resolve_rows(
        validation,
        feature_store,
    )
    if missing_training or missing_validation:
        return {
            **base,
            "status": "not_ready",
            "reason": "feature_snapshot_missing",
            "missing_training_feature_snapshots": len(
                missing_training
            ),
            "missing_validation_feature_snapshots": len(
                missing_validation
            ),
        }

    encoder = _Encoder.fit(training_rows)
    estimator = _fit_tree(
        training_rows,
        encoder=encoder,
        config=tree_config,
    )
    predictions = _predict(
        estimator,
        encoder,
        validation_rows,
    )
    scored = tuple(
        (row, prediction > ZERO, prediction)
        for row, prediction in zip(
            validation_rows,
            predictions,
            strict=True,
        )
    )
    admitted = tuple(
        row.outcome
        for row, take, _prediction in scored
        if take
    )
    actual_sum = sum(
        (row.outcome.net_return for row, _, _ in scored),
        ZERO,
    )
    candidate_sum = sum(
        (row.net_return for row in admitted),
        ZERO,
    )
    return {
        **base,
        "status": "completed",
        "admitted_rows": len(admitted),
        "skipped_rows": len(scored) - len(admitted),
        "actual_net_return_sum": str(actual_sum),
        "candidate_net_return_sum": str(candidate_sum),
        "delta_net_return_sum": str(
            candidate_sum - actual_sum
        ),
        "candidate_mean_net_return": (
            None
            if not admitted
            else str(candidate_sum / Decimal(len(admitted)))
        ),
        "positive_admitted_rows": sum(
            1 for row in admitted if row.net_return > ZERO
        ),
        "negative_admitted_rows": sum(
            1 for row in admitted if row.net_return < ZERO
        ),
        "candidate_sum_positive": candidate_sum > ZERO,
        "by_direction": _direction_summary(scored),
    }


def evaluate_cadence_tree_walkforward(
    outcomes: tuple[ShadowCadenceOutcome, ...],
    feature_store: LearningFeatureSnapshotStore,
    *,
    cadence_ms: int = FIFTEEN_MINUTES_MS,
    horizon_ms: int = ONE_HOUR_MS,
    config: CadenceTreeWalkforwardConfig = DEFAULT_CONFIG,
    tree_config: CadenceTreeConfig = DEFAULT_TREE_CONFIG,
) -> dict[str, object]:
    ordered = _ordered_surface(
        outcomes,
        cadence_ms=cadence_ms,
        horizon_ms=horizon_ms,
    )
    required_rows = (
        config.min_train_rows
        + config.validation_rows * config.folds
    )
    if len(ordered) < required_rows:
        return {
            "status": "not_ready",
            "reason": "insufficient_surface_rows",
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "cadence_ms": cadence_ms,
            "horizon_ms": horizon_ms,
            "settled_rows": len(ordered),
            "minimum_nominal_rows": required_rows,
        }

    first_start = len(ordered) - (
        config.validation_rows * config.folds
    )
    folds = tuple(
        _evaluate_fold(
            ordered,
            feature_store,
            fold_index=fold_index,
            start=(
                first_start
                + fold_index * config.validation_rows
            ),
            end=(
                first_start
                + (fold_index + 1) * config.validation_rows
            ),
            config=config,
            tree_config=tree_config,
        )
        for fold_index in range(config.folds)
    )
    completed = tuple(
        fold for fold in folds if fold["status"] == "completed"
    )
    if len(completed) != config.folds:
        return {
            "status": "not_ready",
            "reason": "one_or_more_folds_not_ready",
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "cadence_ms": cadence_ms,
            "horizon_ms": horizon_ms,
            "settled_rows": len(ordered),
            "folds": folds,
        }

    candidate_sums = tuple(
        Decimal(str(fold["candidate_net_return_sum"]))
        for fold in completed
    )
    actual_sums = tuple(
        Decimal(str(fold["actual_net_return_sum"]))
        for fold in completed
    )
    admitted_rows = sum(
        cast(int, fold["admitted_rows"])
        for fold in completed
    )
    long_admitted = sum(
        _fold_direction_admitted(fold, "long")
        for fold in completed
    )
    short_admitted = sum(
        _fold_direction_admitted(fold, "short")
        for fold in completed
    )
    candidate_total = sum(candidate_sums, ZERO)
    actual_total = sum(actual_sums, ZERO)

    return {
        "status": "completed",
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "claim_scope": (
            "touched_disjoint_purged_tree_walkforward_diagnostic"
        ),
        "model_family": "cadence_fixed_shallow_tree_v1",
        "cadence_ms": cadence_ms,
        "horizon_ms": horizon_ms,
        "settled_rows": len(ordered),
        "fold_count": len(completed),
        "validation_rows_per_fold": config.validation_rows,
        "first_validation_index": first_start,
        "candidate_net_return_sum": str(candidate_total),
        "actual_net_return_sum": str(actual_total),
        "delta_net_return_sum": str(
            candidate_total - actual_total
        ),
        "positive_candidate_folds": sum(
            1 for value in candidate_sums if value > ZERO
        ),
        "negative_candidate_folds": sum(
            1 for value in candidate_sums if value < ZERO
        ),
        "flat_candidate_folds": sum(
            1 for value in candidate_sums if value == ZERO
        ),
        "admitted_rows": admitted_rows,
        "long_admitted_rows": long_admitted,
        "short_admitted_rows": short_admitted,
        "folds": folds,
        "configuration": {
            "validation_rows": config.validation_rows,
            "folds": config.folds,
            "min_train_rows": config.min_train_rows,
            "tree": {
                "max_leaf_nodes": tree_config.max_leaf_nodes,
                "min_samples_leaf": tree_config.min_samples_leaf,
                "learning_rate": str(tree_config.learning_rate),
                "max_iter": tree_config.max_iter,
                "l2_regularization": str(
                    tree_config.l2_regularization
                ),
                "random_state": 0,
                "early_stopping": False,
            },
        },
    }
