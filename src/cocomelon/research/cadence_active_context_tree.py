from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final

from cocomelon.domain.strategy import Direction
from cocomelon.research.cadence_active_context import (
    DEFAULT_MIN_CONTEXT_MARKETS,
    CadenceActiveContextError,
    CadenceActiveCrossSection,
    CadenceActiveCrossSectionIndex,
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
from cocomelon.research.cadence_tree_learning import (
    DEFAULT_TREE_CONFIG,
    FEATURE_REGISTRY,
    CadenceTreeConfig,
    _Encoder,
    _regressor,
)
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotStore,
)

ZERO: Final = Decimal("0")
MODEL_FAMILY: Final = "cadence_active_context_tree_v1"
ACTIVE_CONTEXT_FEATURES: Final = (
    "active_median_return_1h",
    "active_breadth_positive_1h",
    "active_return_dispersion_1h",
    "active_relative_return_1h",
    "active_relative_zscore_1h",
    "active_context_state_1h",
)


@dataclass(frozen=True, slots=True)
class _ActiveRow:
    base: _ContextRow
    context: CadenceActiveCrossSection


@dataclass(frozen=True, slots=True)
class _ActiveEncoder:
    base: _Encoder
    direction_buckets: tuple[str, ...]
    breadth_buckets: tuple[str, ...]
    relative_buckets: tuple[str, ...]

    @classmethod
    def fit(cls, rows: tuple[_ActiveRow, ...]) -> _ActiveEncoder:
        base = _Encoder.fit(tuple(row.base for row in rows))
        states = tuple(
            row.context.context_state_1h.split("/")
            for row in rows
        )
        if any(len(state) != 3 for state in states):
            raise ValueError(
                "active context state must contain three buckets"
            )
        return cls(
            base=base,
            direction_buckets=tuple(
                sorted({state[0] for state in states})
            ),
            breadth_buckets=tuple(
                sorted({state[1] for state in states})
            ),
            relative_buckets=tuple(
                sorted({state[2] for state in states})
            ),
        )

    @staticmethod
    def _optional_float(value: Decimal | None) -> float:
        if value is None:
            return float("nan")
        resolved = float(value)
        if not math.isfinite(resolved):
            raise ValueError("active context value must be finite")
        return resolved

    def vector(self, row: _ActiveRow) -> tuple[float, ...]:
        context = row.context
        state = context.context_state_1h.split("/")
        if len(state) != 3:
            raise ValueError(
                "active context state must contain three buckets"
            )
        values = list(self.base.vector(row.base))
        values.extend(
            (
                float(context.median_return_1h),
                float(context.breadth_positive_1h),
                float(context.return_dispersion_1h),
                float(context.relative_return_1h),
                self._optional_float(context.relative_zscore_1h),
            )
        )
        values.extend(
            1.0 if state[0] == bucket else 0.0
            for bucket in self.direction_buckets
        )
        values.extend(
            1.0 if state[1] == bucket else 0.0
            for bucket in self.breadth_buckets
        )
        values.extend(
            1.0 if state[2] == bucket else 0.0
            for bucket in self.relative_buckets
        )
        return tuple(values)


def _resolve_active(
    rows: tuple[_ContextRow, ...],
    index: CadenceActiveCrossSectionIndex,
) -> tuple[tuple[_ActiveRow, ...], tuple[str, ...]]:
    output: list[_ActiveRow] = []
    errors: list[str] = []
    for row in rows:
        try:
            context = index.resolve(
                row.feature,
                decision_evaluated_at_ms=(
                    row.outcome.sample.evaluated_at_ms
                ),
            )
        except CadenceActiveContextError as exc:
            errors.append(str(exc))
            continue
        output.append(_ActiveRow(base=row, context=context))
    return tuple(output), tuple(errors)


def _fit_tree(
    rows: tuple[_ActiveRow, ...],
    *,
    encoder: _ActiveEncoder,
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
        [float(row.base.outcome.net_return) for row in rows],
    )
    return estimator


def _predict(
    estimator: Any,
    encoder: _ActiveEncoder,
    rows: tuple[_ActiveRow, ...],
) -> tuple[Decimal, ...]:
    raw = estimator.predict([encoder.vector(row) for row in rows])
    output: list[Decimal] = []
    for value in raw:
        resolved = float(value)
        if not math.isfinite(resolved):
            raise ValueError(
                "active context tree prediction must be finite"
            )
        output.append(Decimal(str(resolved)))
    return tuple(output)


def _stability_blocks(
    rows: tuple[tuple[_ActiveRow, bool, Decimal], ...],
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
            row.base.outcome
            for row, take, _prediction in block
            if take
        )
        total = sum((item.net_return for item in admitted), ZERO)
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


def _direction_summary(
    rows: tuple[tuple[_ActiveRow, bool, Decimal], ...],
) -> dict[str, object]:
    output: dict[str, object] = {}
    for direction in (Direction.LONG.value, Direction.SHORT.value):
        cohort = tuple(
            (row, take)
            for row, take, _prediction in rows
            if row.base.outcome.sample.direction.value == direction
        )
        admitted = tuple(
            row.base.outcome
            for row, take in cohort
            if take
        )
        actual = sum(
            (row.base.outcome.net_return for row, _ in cohort),
            ZERO,
        )
        candidate = sum(
            (row.net_return for row in admitted),
            ZERO,
        )
        output[direction] = {
            "validation_rows": len(cohort),
            "admitted_rows": len(admitted),
            "actual_net_return_sum": str(actual),
            "candidate_net_return_sum": str(candidate),
            "delta_net_return_sum": str(candidate - actual),
            "candidate_mean_net_return": (
                None
                if not admitted
                else str(candidate / Decimal(len(admitted)))
            ),
        }
    return output


def _context_breakdown(
    rows: tuple[tuple[_ActiveRow, bool, Decimal], ...],
) -> tuple[dict[str, object], ...]:
    groups: dict[str, list[tuple[_ActiveRow, bool]]] = {}
    for row, take, _prediction in rows:
        groups.setdefault(
            row.context.context_state_1h,
            [],
        ).append((row, take))
    output: list[dict[str, object]] = []
    for state, items in sorted(groups.items()):
        admitted = tuple(
            row.base.outcome
            for row, take in items
            if take
        )
        actual = sum(
            (row.base.outcome.net_return for row, _ in items),
            ZERO,
        )
        candidate = sum(
            (row.net_return for row in admitted),
            ZERO,
        )
        output.append(
            {
                "context_state_1h": state,
                "validation_rows": len(items),
                "admitted_rows": len(admitted),
                "actual_net_return_sum": str(actual),
                "candidate_net_return_sum": str(candidate),
                "candidate_mean_net_return": (
                    None
                    if not admitted
                    else str(
                        candidate / Decimal(len(admitted))
                    )
                ),
            }
        )
    return tuple(output)


def evaluate_cadence_active_context_tree(
    outcomes: tuple[ShadowCadenceOutcome, ...],
    feature_store: LearningFeatureSnapshotStore,
    *,
    cadence_ms: int = FIFTEEN_MINUTES_MS,
    horizon_ms: int = ONE_HOUR_MS,
    validation_config: CadenceOpportunityLearningConfig = DEFAULT_CONFIG,
    tree_config: CadenceTreeConfig = DEFAULT_TREE_CONFIG,
    min_context_markets: int = DEFAULT_MIN_CONTEXT_MARKETS,
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
        }
    validation = surface[-validation_config.validation_rows :]
    validation_start = validation[0].sample.boundary_ms
    prefix = surface[:-validation_config.validation_rows]
    training = tuple(
        row
        for row in prefix
        if row.sample.target_end_ms < validation_start
    )
    purged = len(prefix) - len(training)
    if len(training) < validation_config.min_train_rows:
        return {
            "status": "not_ready",
            "reason": "insufficient_purged_training_rows",
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "training_rows": len(training),
        }

    base_train, missing_train_features = _resolve_rows(
        training,
        feature_store,
    )
    base_validation, missing_validation_features = _resolve_rows(
        validation,
        feature_store,
    )
    if missing_train_features or missing_validation_features:
        return {
            "status": "not_ready",
            "reason": "feature_snapshot_missing",
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
        }

    index = CadenceActiveCrossSectionIndex(
        feature_store,
        min_context_markets=min_context_markets,
    )
    train_rows, train_context_errors = _resolve_active(
        base_train,
        index,
    )
    validation_rows, validation_context_errors = _resolve_active(
        base_validation,
        index,
    )
    if train_context_errors or validation_context_errors:
        return {
            "status": "not_ready",
            "reason": "active_context_missing",
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "training_rows": len(base_train),
            "validation_rows": len(base_validation),
            "training_context_errors": len(train_context_errors),
            "validation_context_errors": len(
                validation_context_errors
            ),
            "context_error_examples": (
                train_context_errors + validation_context_errors
            )[:20],
        }

    encoder = _ActiveEncoder.fit(train_rows)
    estimator = _fit_tree(
        train_rows,
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
        row.base.outcome
        for row, take, _prediction in scored
        if take
    )
    actual = sum(
        (row.base.outcome.net_return for row, _, _ in scored),
        ZERO,
    )
    candidate = sum(
        (row.net_return for row in admitted),
        ZERO,
    )
    mean = (
        None
        if not admitted
        else candidate / Decimal(len(admitted))
    )
    blocks = _stability_blocks(
        scored,
        blocks=validation_config.stability_blocks,
        min_block_admitted=validation_config.min_block_admitted,
    )
    long_validation = sum(
        1
        for row, _, _ in scored
        if row.base.outcome.sample.direction is Direction.LONG
    )
    short_validation = sum(
        1
        for row, _, _ in scored
        if row.base.outcome.sample.direction is Direction.SHORT
    )
    long_admitted = sum(
        1
        for row, take, _ in scored
        if take
        and row.base.outcome.sample.direction is Direction.LONG
    )
    short_admitted = sum(
        1
        for row, take, _ in scored
        if take
        and row.base.outcome.sample.direction is Direction.SHORT
    )
    structural = (
        len(scored) == validation_config.validation_rows
        and long_validation
        >= validation_config.min_validation_per_direction
        and short_validation
        >= validation_config.min_validation_per_direction
    )
    stable = all(bool(block["passes"]) for block in blocks)
    qualified = (
        structural
        and len(admitted) >= validation_config.min_validation_admitted
        and long_admitted
        >= validation_config.min_admitted_per_direction
        and short_admitted
        >= validation_config.min_admitted_per_direction
        and mean is not None
        and mean > ZERO
        and stable
    )

    return {
        "status": "completed",
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "claim_scope": (
            "touched_active_cross_section_tree_development"
        ),
        "model_family": MODEL_FAMILY,
        "base_feature_registry": FEATURE_REGISTRY,
        "active_context_features": ACTIVE_CONTEXT_FEATURES,
        "min_context_markets": min_context_markets,
        "cadence_ms": cadence_ms,
        "horizon_ms": horizon_ms,
        "training_rows": len(train_rows),
        "validation_rows": len(validation_rows),
        "purged_overlap_rows": purged,
        "admitted_rows": len(admitted),
        "skipped_rows": len(scored) - len(admitted),
        "actual_net_return_sum": str(actual),
        "candidate_net_return_sum": str(candidate),
        "delta_net_return_sum": str(candidate - actual),
        "candidate_mean_net_return": (
            None if mean is None else str(mean)
        ),
        "positive_admitted_rows": sum(
            1 for row in admitted if row.net_return > ZERO
        ),
        "negative_admitted_rows": sum(
            1 for row in admitted if row.net_return < ZERO
        ),
        "by_direction": _direction_summary(scored),
        "by_context_state_1h": _context_breakdown(scored),
        "stability_blocks": blocks,
        "structural_ready": structural,
        "development_qualified": qualified,
        "tree_configuration": {
            "max_leaf_nodes": tree_config.max_leaf_nodes,
            "min_samples_leaf": tree_config.min_samples_leaf,
            "learning_rate": str(tree_config.learning_rate),
            "max_iter": tree_config.max_iter,
            "l2_regularization": str(
                tree_config.l2_regularization
            ),
        },
        "encoder": {
            "strategies": encoder.base.strategies,
            "trend_regimes": encoder.base.trend_regimes,
            "volatility_regimes": (
                encoder.base.volatility_regimes
            ),
            "active_direction_buckets": (
                encoder.direction_buckets
            ),
            "active_breadth_buckets": encoder.breadth_buckets,
            "active_relative_buckets": encoder.relative_buckets,
        },
    }
