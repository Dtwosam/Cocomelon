from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final

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
    _direction_summary,
    _Encoder,
    _prediction_bands,
    _regressor,
    _stability_blocks,
)
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotStore,
)

ZERO: Final = Decimal("0")
MODEL_FAMILY: Final = "cadence_microstructure_tree_v1"
MICROSTRUCTURE_FEATURES: Final = (
    "realized_vol_15m",
    "range_expansion_15m",
    "relative_volume_15m",
    "spread_bps",
    "book_imbalance",
    "book_age_ms",
    "mark_oracle_dislocation_bps",
    "oi_change_fraction",
    "funding_change",
)


@dataclass(frozen=True, slots=True)
class _MicrostructureEncoder:
    base: _Encoder

    @classmethod
    def fit(
        cls,
        rows: tuple[_ContextRow, ...],
    ) -> _MicrostructureEncoder:
        return cls(base=_Encoder.fit(rows))

    @staticmethod
    def _numeric(value: Decimal | int | None) -> float:
        if value is None:
            return float("nan")
        resolved = float(value)
        if not math.isfinite(resolved):
            raise ValueError(
                "cadence microstructure feature must be finite"
            )
        return resolved

    def vector(self, row: _ContextRow) -> tuple[float, ...]:
        feature = row.feature
        values = list(self.base.vector(row))
        values.extend(
            (
                self._numeric(feature.realized_vol_15m),
                self._numeric(feature.range_expansion_15m),
                self._numeric(feature.relative_volume_15m),
                self._numeric(feature.spread_bps),
                self._numeric(feature.book_imbalance),
                self._numeric(feature.book_age_ms),
                self._numeric(feature.mark_oracle_dislocation_bps),
                self._numeric(feature.oi_change_fraction),
                self._numeric(feature.funding_change),
            )
        )
        return tuple(values)


def _fit_tree(
    rows: tuple[_ContextRow, ...],
    *,
    encoder: _MicrostructureEncoder,
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
    encoder: _MicrostructureEncoder,
    rows: tuple[_ContextRow, ...],
) -> tuple[Decimal, ...]:
    raw = estimator.predict(
        [encoder.vector(row) for row in rows]
    )
    output: list[Decimal] = []
    for value in raw:
        resolved = float(value)
        if not math.isfinite(resolved):
            raise ValueError(
                "cadence microstructure prediction must be finite"
            )
        output.append(Decimal(str(resolved)))
    return tuple(output)


def evaluate_cadence_microstructure_tree(
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
    prefix = surface[:-validation_config.validation_rows]
    training = tuple(
        row
        for row in prefix
        if row.sample.target_end_ms < validation_start_ms
    )
    purged = len(prefix) - len(training)
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

    encoder = _MicrostructureEncoder.fit(training_rows)
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
        and len(admitted)
        >= validation_config.min_validation_admitted
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
            "touched_cadence_microstructure_tree_development"
        ),
        "model_family": MODEL_FAMILY,
        "base_feature_registry": FEATURE_REGISTRY,
        "microstructure_feature_registry": MICROSTRUCTURE_FEATURES,
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
        "delta_net_return_sum": str(
            candidate_sum - actual_sum
        ),
        "candidate_mean_net_return": (
            None
            if candidate_mean is None
            else str(candidate_mean)
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
            "strategies": encoder.base.strategies,
            "trend_regimes": encoder.base.trend_regimes,
            "volatility_regimes": (
                encoder.base.volatility_regimes
            ),
        },
    }
