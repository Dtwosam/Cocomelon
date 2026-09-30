from __future__ import annotations

import importlib
import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final

from cocomelon.domain.features import FeatureSnapshot
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
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotStore,
)

ZERO: Final = Decimal("0")
MODEL_FAMILY: Final = "cadence_fixed_shallow_tree_v1"
FEATURE_REGISTRY: Final = (
    "direction",
    "lead_strategy",
    "score",
    "return_5m",
    "return_15m",
    "return_1h",
    "funding",
    "open_interest",
    "trend_regime",
    "volatility_regime",
)
DEFAULT_MAX_LEAF_NODES: Final = 7
DEFAULT_MIN_SAMPLES_LEAF: Final = 100
DEFAULT_LEARNING_RATE: Final = Decimal("0.05")
DEFAULT_MAX_ITER: Final = 100
DEFAULT_L2_REGULARIZATION: Final = Decimal("1")


class CadenceTreeLearningError(RuntimeError):
    pass


class CadenceTreeDependencyError(RuntimeError):
    pass


def _regressor() -> Any:
    try:
        ensemble = importlib.import_module("sklearn.ensemble")
    except ModuleNotFoundError as exc:
        raise CadenceTreeDependencyError(
            "scikit-learn is required for cadence tree research; "
            "install the research extra"
        ) from exc
    return ensemble.HistGradientBoostingRegressor


@dataclass(frozen=True, slots=True)
class CadenceTreeConfig:
    max_leaf_nodes: int = DEFAULT_MAX_LEAF_NODES
    min_samples_leaf: int = DEFAULT_MIN_SAMPLES_LEAF
    learning_rate: Decimal = DEFAULT_LEARNING_RATE
    max_iter: int = DEFAULT_MAX_ITER
    l2_regularization: Decimal = DEFAULT_L2_REGULARIZATION

    def __post_init__(self) -> None:
        if self.max_leaf_nodes < 2:
            raise ValueError("max_leaf_nodes must be at least two")
        if self.min_samples_leaf <= 0:
            raise ValueError("min_samples_leaf must be positive")
        if (
            not self.learning_rate.is_finite()
            or self.learning_rate <= ZERO
        ):
            raise ValueError("learning_rate must be positive and finite")
        if self.max_iter <= 0:
            raise ValueError("max_iter must be positive")
        if (
            not self.l2_regularization.is_finite()
            or self.l2_regularization < ZERO
        ):
            raise ValueError(
                "l2_regularization must be non-negative and finite"
            )


DEFAULT_TREE_CONFIG: Final = CadenceTreeConfig()


@dataclass(frozen=True, slots=True)
class _Encoder:
    strategies: tuple[str, ...]
    trend_regimes: tuple[str, ...]
    volatility_regimes: tuple[str, ...]

    @classmethod
    def fit(cls, rows: tuple[_ContextRow, ...]) -> _Encoder:
        return cls(
            strategies=tuple(
                sorted(
                    {
                        row.outcome.sample.lead_strategy
                        for row in rows
                    }
                )
            ),
            trend_regimes=tuple(
                sorted(
                    {
                        row.feature.trend_regime.value
                        for row in rows
                    }
                )
            ),
            volatility_regimes=tuple(
                sorted(
                    {
                        row.feature.volatility_regime.value
                        for row in rows
                    }
                )
            ),
        )

    @staticmethod
    def _numeric(value: Decimal | None) -> float:
        if value is None:
            return float("nan")
        resolved = float(value)
        if not math.isfinite(resolved):
            raise CadenceTreeLearningError(
                "cadence tree numeric feature must be finite"
            )
        return resolved

    def vector(self, row: _ContextRow) -> tuple[float, ...]:
        sample = row.outcome.sample
        feature = row.feature
        values: list[float] = [
            1.0 if sample.direction is Direction.LONG else 0.0,
            1.0 if sample.direction is Direction.SHORT else 0.0,
        ]
        values.extend(
            1.0 if sample.lead_strategy == strategy else 0.0
            for strategy in self.strategies
        )
        values.append(float(sample.score))
        values.extend(
            (
                self._numeric(feature.return_5m),
                self._numeric(feature.return_15m),
                self._numeric(feature.return_1h),
                self._numeric(feature.funding),
                self._numeric(feature.open_interest),
            )
        )
        values.extend(
            1.0 if feature.trend_regime.value == regime else 0.0
            for regime in self.trend_regimes
        )
        values.extend(
            1.0 if feature.volatility_regime.value == regime else 0.0
            for regime in self.volatility_regimes
        )
        return tuple(values)


def _fit_tree(
    rows: tuple[_ContextRow, ...],
    *,
    encoder: _Encoder,
    config: CadenceTreeConfig,
) -> Any:
    estimator_type = _regressor()
    estimator = estimator_type(
        loss="squared_error",
        learning_rate=float(config.learning_rate),
        max_iter=config.max_iter,
        max_leaf_nodes=config.max_leaf_nodes,
        min_samples_leaf=config.min_samples_leaf,
        l2_regularization=float(config.l2_regularization),
        early_stopping=False,
        random_state=0,
    )
    estimator.fit(
        [encoder.vector(row) for row in rows],
        [float(row.outcome.net_return) for row in rows],
    )
    return estimator


def _predict(
    estimator: Any,
    encoder: _Encoder,
    rows: tuple[_ContextRow, ...],
) -> tuple[Decimal, ...]:
    raw = estimator.predict([encoder.vector(row) for row in rows])
    output: list[Decimal] = []
    for value in raw:
        resolved = float(value)
        if not math.isfinite(resolved):
            raise CadenceTreeLearningError(
                "cadence tree prediction must be finite"
            )
        output.append(Decimal(str(resolved)))
    return tuple(output)


def _stability_blocks(
    rows: tuple[tuple[_ContextRow, bool, Decimal], ...],
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
            for row, take, _prediction in block
            if take
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


def _direction_summary(
    rows: tuple[tuple[_ContextRow, bool, Decimal], ...],
) -> dict[str, object]:
    output: dict[str, object] = {}
    for direction in (Direction.LONG.value, Direction.SHORT.value):
        cohort = tuple(
            (row, take, prediction)
            for row, take, prediction in rows
            if row.outcome.sample.direction.value == direction
        )
        admitted = tuple(
            row.outcome
            for row, take, _prediction in cohort
            if take
        )
        actual_sum = sum(
            (row.outcome.net_return for row, _, _ in cohort),
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


def _prediction_bands(
    rows: tuple[tuple[_ContextRow, bool, Decimal], ...],
) -> tuple[dict[str, object], ...]:
    ordered = tuple(
        sorted(
            rows,
            key=lambda item: (
                -item[2],
                item[0].outcome.sample.market.canonical,
            ),
        )
    )
    if not ordered:
        return ()
    band_count = min(5, len(ordered))
    output: list[dict[str, object]] = []
    for index in range(band_count):
        start = index * len(ordered) // band_count
        end = (index + 1) * len(ordered) // band_count
        band = ordered[start:end]
        actual = tuple(item[0].outcome.net_return for item in band)
        predictions = tuple(item[2] for item in band)
        output.append(
            {
                "band_index": index,
                "rows": len(band),
                "prediction_min": str(min(predictions)),
                "prediction_max": str(max(predictions)),
                "prediction_mean": str(
                    sum(predictions, ZERO) / Decimal(len(predictions))
                ),
                "actual_net_return_sum": str(sum(actual, ZERO)),
                "actual_mean_net_return": str(
                    sum(actual, ZERO) / Decimal(len(actual))
                ),
                "positive_rows": sum(
                    1 for value in actual if value > ZERO
                ),
                "negative_rows": sum(
                    1 for value in actual if value < ZERO
                ),
            }
        )
    return tuple(output)


def evaluate_cadence_tree_learning(
    outcomes: tuple[ShadowCadenceOutcome, ...],
    feature_store: LearningFeatureSnapshotStore,
    *,
    cadence_ms: int = FIFTEEN_MINUTES_MS,
    horizon_ms: int = ONE_HOUR_MS,
    validation_config: CadenceOpportunityLearningConfig = DEFAULT_CONFIG,
    tree_config: CadenceTreeConfig = DEFAULT_TREE_CONFIG,
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
    if len(surface) < validation_config.validation_rows:
        return {
            "status": "not_ready",
            "reason": "insufficient_validation_rows",
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "settled_rows": len(surface),
        }

    validation = surface[-validation_config.validation_rows :]
    validation_start_ms = validation[0].sample.boundary_ms
    candidates = surface[:-validation_config.validation_rows]
    training = tuple(
        row
        for row in candidates
        if row.sample.target_end_ms < validation_start_ms
    )
    purged = len(candidates) - len(training)
    if len(training) < validation_config.min_train_rows:
        return {
            "status": "not_ready",
            "reason": "insufficient_purged_training_rows",
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "settled_rows": len(surface),
            "training_rows": len(training),
            "validation_rows": len(validation),
            "purged_overlap_rows": purged,
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
            "status": "not_ready",
            "reason": "feature_snapshot_missing",
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
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
    predictions = _predict(estimator, encoder, validation_rows)
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
    candidate_sum = sum((row.net_return for row in admitted), ZERO)
    candidate_mean = (
        None
        if not admitted
        else candidate_sum / Decimal(len(admitted))
    )
    blocks = _stability_blocks(
        scored,
        blocks=validation_config.stability_blocks,
        min_block_admitted=validation_config.min_block_admitted,
    )

    long_validation = sum(
        1
        for row, _, _ in scored
        if row.outcome.sample.direction is Direction.LONG
    )
    short_validation = sum(
        1
        for row, _, _ in scored
        if row.outcome.sample.direction is Direction.SHORT
    )
    long_admitted = sum(
        1
        for row, take, _ in scored
        if take and row.outcome.sample.direction is Direction.LONG
    )
    short_admitted = sum(
        1
        for row, take, _ in scored
        if take and row.outcome.sample.direction is Direction.SHORT
    )
    structural_ready = (
        len(scored) == validation_config.validation_rows
        and long_validation
        >= validation_config.min_validation_per_direction
        and short_validation
        >= validation_config.min_validation_per_direction
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
        "claim_scope": "touched_cadence_tree_meta_label_development",
        "model_family": MODEL_FAMILY,
        "feature_registry": FEATURE_REGISTRY,
        "decision_policy": "admit_if_predicted_net_return_gt_zero",
        "cadence_ms": cadence_ms,
        "horizon_ms": horizon_ms,
        "settled_rows": len(surface),
        "training_rows": len(training_rows),
        "validation_rows": len(validation_rows),
        "purged_overlap_rows": purged,
        "validation_start_ms": validation_start_ms,
        "validation_end_ms": validation[-1].sample.target_end_ms,
        "admitted_rows": len(admitted),
        "skipped_rows": len(scored) - len(admitted),
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
        "by_direction": _direction_summary(scored),
        "stability_blocks": blocks,
        "prediction_bands": _prediction_bands(scored),
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
            "random_state": 0,
            "early_stopping": False,
        },
        "encoder": {
            "strategies": encoder.strategies,
            "trend_regimes": encoder.trend_regimes,
            "volatility_regimes": encoder.volatility_regimes,
        },
    }
