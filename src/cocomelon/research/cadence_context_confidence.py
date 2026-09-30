from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from cocomelon.domain.strategy import Direction
from cocomelon.research.cadence_context_learning import (
    CadenceContextLearningError,
    _ContextRow,
    _context_keys,
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
DEFAULT_MIN_LOCAL_ROWS: Final = 5
DEFAULT_MIN_FALLBACK_ROWS: Final = 25
DEFAULT_STANDARD_ERROR_MULTIPLIER: Final = Decimal("1.28")


@dataclass(frozen=True, slots=True)
class CadenceContextConfidenceConfig:
    min_local_rows: int = DEFAULT_MIN_LOCAL_ROWS
    min_fallback_rows: int = DEFAULT_MIN_FALLBACK_ROWS
    standard_error_multiplier: Decimal = (
        DEFAULT_STANDARD_ERROR_MULTIPLIER
    )

    def __post_init__(self) -> None:
        if self.min_local_rows < 2:
            raise ValueError("min_local_rows must be at least two")
        if self.min_fallback_rows < self.min_local_rows:
            raise ValueError(
                "min_fallback_rows must be >= min_local_rows"
            )
        if (
            not self.standard_error_multiplier.is_finite()
            or self.standard_error_multiplier < ZERO
        ):
            raise ValueError(
                "standard_error_multiplier must be finite and non-negative"
            )


DEFAULT_CONFIDENCE_CONFIG: Final = CadenceContextConfidenceConfig()


@dataclass(frozen=True, slots=True)
class _GroupStats:
    count: int
    total: Decimal
    total_sq: Decimal

    @property
    def mean(self) -> Decimal:
        return self.total / Decimal(self.count)

    @property
    def sample_variance(self) -> Decimal:
        if self.count < 2:
            return ZERO
        count = Decimal(self.count)
        numerator = self.total_sq - (self.total * self.total / count)
        if numerator < ZERO:
            numerator = ZERO
        return numerator / Decimal(self.count - 1)

    @property
    def standard_error(self) -> Decimal:
        if self.count < 2:
            return ZERO
        return (self.sample_variance / Decimal(self.count)).sqrt()


@dataclass(frozen=True, slots=True)
class _ConfidenceEstimate:
    mean: Decimal
    standard_error: Decimal
    lower_bound: Decimal
    count: int
    group_key: tuple[str, ...]
    specificity: str
    support_threshold: int


def _fit_stats(
    rows: tuple[_ContextRow, ...],
) -> dict[tuple[str, ...], _GroupStats]:
    counts: Counter[tuple[str, ...]] = Counter()
    sums: defaultdict[tuple[str, ...], Decimal] = defaultdict(
        lambda: ZERO
    )
    sums_sq: defaultdict[tuple[str, ...], Decimal] = defaultdict(
        lambda: ZERO
    )
    for row in rows:
        value = row.outcome.net_return
        for _, key in _context_keys(row):
            counts[key] += 1
            sums[key] += value
            sums_sq[key] += value * value
    return {
        key: _GroupStats(
            count=count,
            total=sums[key],
            total_sq=sums_sq[key],
        )
        for key, count in counts.items()
    }


def _support_threshold(
    specificity: str,
    config: CadenceContextConfidenceConfig,
) -> int:
    if specificity in {
        "direction_strategy_score_trend_volatility",
        "direction_strategy_score_trend",
        "direction_strategy_score_volatility",
    }:
        return config.min_local_rows
    return config.min_fallback_rows


def _estimate(
    row: _ContextRow,
    stats: dict[tuple[str, ...], _GroupStats],
    *,
    config: CadenceContextConfidenceConfig,
) -> _ConfidenceEstimate | None:
    for specificity, key in _context_keys(row):
        threshold = _support_threshold(specificity, config)
        group = stats.get(key)
        if group is None or group.count < threshold:
            continue
        standard_error = group.standard_error
        lower_bound = (
            group.mean
            - config.standard_error_multiplier * standard_error
        )
        return _ConfidenceEstimate(
            mean=group.mean,
            standard_error=standard_error,
            lower_bound=lower_bound,
            count=group.count,
            group_key=key,
            specificity=specificity,
            support_threshold=threshold,
        )
    return None


def _stability_blocks(
    rows: tuple[tuple[_ContextRow, bool], ...],
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
            for row, take in block
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
    rows: tuple[tuple[_ContextRow, bool], ...],
) -> dict[str, object]:
    output: dict[str, object] = {}
    for direction in (Direction.LONG.value, Direction.SHORT.value):
        cohort = tuple(
            (row, take)
            for row, take in rows
            if row.outcome.sample.direction.value == direction
        )
        admitted = tuple(
            row.outcome
            for row, take in cohort
            if take
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


def _cohort_attribution(
    scored: tuple[
        tuple[_ContextRow, bool, _ConfidenceEstimate],
        ...,
    ],
    *,
    admitted: bool,
) -> tuple[dict[str, object], ...]:
    groups: dict[
        tuple[str, str, str, str, str, str],
        list[tuple[_ContextRow, _ConfidenceEstimate]],
    ] = defaultdict(list)
    for row, take, estimate in scored:
        if take is not admitted:
            continue
        groups[
            (
                row.outcome.sample.direction.value,
                row.outcome.sample.lead_strategy,
                str(row.outcome.sample.score),
                row.feature.trend_regime.value,
                row.feature.volatility_regime.value,
                estimate.specificity,
            )
        ].append((row, estimate))

    output: list[tuple[Decimal, dict[str, object]]] = []
    for key, items in groups.items():
        estimates = tuple(estimate for _, estimate in items)
        first = estimates[0]
        if any(estimate != first for estimate in estimates[1:]):
            raise CadenceContextLearningError(
                "CADENCE_CONTEXT_CONFIDENCE_ESTIMATE_DRIFT"
            )
        outcomes = tuple(row.outcome for row, _ in items)
        net_sum = sum((row.net_return for row in outcomes), ZERO)
        output.append(
            (
                net_sum,
                {
                    "direction": key[0],
                    "lead_strategy": key[1],
                    "score": key[2],
                    "trend_regime": key[3],
                    "volatility_regime": key[4],
                    "training_estimate_specificity": key[5],
                    "training_rows": first.count,
                    "support_threshold": first.support_threshold,
                    "training_mean_net_return": str(first.mean),
                    "training_standard_error": str(
                        first.standard_error
                    ),
                    "training_lower_bound": str(first.lower_bound),
                    "training_group_key": first.group_key,
                    "validation_rows": len(outcomes),
                    "positive_rows": sum(
                        1
                        for outcome in outcomes
                        if outcome.net_return > ZERO
                    ),
                    "negative_rows": sum(
                        1
                        for outcome in outcomes
                        if outcome.net_return < ZERO
                    ),
                    "validation_net_return_sum": str(net_sum),
                    "validation_mean_net_return": str(
                        net_sum / Decimal(len(outcomes))
                    ),
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


def evaluate_cadence_context_confidence(
    outcomes: tuple[ShadowCadenceOutcome, ...],
    feature_store: LearningFeatureSnapshotStore,
    *,
    cadence_ms: int = FIFTEEN_MINUTES_MS,
    horizon_ms: int = ONE_HOUR_MS,
    validation_config: CadenceOpportunityLearningConfig = DEFAULT_CONFIG,
    confidence_config: CadenceContextConfidenceConfig = (
        DEFAULT_CONFIDENCE_CONFIG
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

    stats = _fit_stats(training_rows)
    scored: list[
        tuple[_ContextRow, bool, _ConfidenceEstimate]
    ] = []
    specificity = Counter[str]()
    missing_estimates = 0
    for row in validation_rows:
        estimate = _estimate(
            row,
            stats,
            config=confidence_config,
        )
        if estimate is None:
            missing_estimates += 1
            continue
        specificity[estimate.specificity] += 1
        scored.append(
            (
                row,
                estimate.lower_bound > ZERO,
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
            "missing_validation_estimates": missing_estimates,
        }

    scored_rows = tuple(scored)
    realized = tuple((row, take) for row, take, _ in scored_rows)
    admitted = tuple(
        row.outcome
        for row, take in realized
        if take
    )
    actual_sum = sum(
        (row.outcome.net_return for row, _ in realized),
        ZERO,
    )
    candidate_sum = sum((row.net_return for row in admitted), ZERO)
    candidate_mean = (
        None
        if not admitted
        else candidate_sum / Decimal(len(admitted))
    )
    blocks = _stability_blocks(
        realized,
        blocks=validation_config.stability_blocks,
        min_block_admitted=validation_config.min_block_admitted,
    )

    long_validation = sum(
        1
        for row, _ in realized
        if row.outcome.sample.direction is Direction.LONG
    )
    short_validation = sum(
        1
        for row, _ in realized
        if row.outcome.sample.direction is Direction.SHORT
    )
    long_admitted = sum(
        1
        for row, take in realized
        if take and row.outcome.sample.direction is Direction.LONG
    )
    short_admitted = sum(
        1
        for row, take in realized
        if take and row.outcome.sample.direction is Direction.SHORT
    )
    structural_ready = (
        len(realized) == validation_config.validation_rows
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
        "claim_scope": (
            "touched_contextual_confidence_meta_label_development"
        ),
        "model_family": "hierarchical_context_lower_bound_v1",
        "decision_policy": (
            "admit_if_first_supported_context_training_lower_bound_gt_zero"
        ),
        "context_features": (
            "trend_regime",
            "volatility_regime",
        ),
        "cadence_ms": cadence_ms,
        "horizon_ms": horizon_ms,
        "settled_rows": len(surface),
        "training_rows": len(training_rows),
        "validation_rows": len(validation_rows),
        "purged_overlap_rows": purged,
        "validation_start_ms": validation_start_ms,
        "validation_end_ms": validation[-1].sample.target_end_ms,
        "admitted_rows": len(admitted),
        "skipped_rows": len(realized) - len(admitted),
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
        "by_direction": _direction_summary(realized),
        "admitted_cohorts": _cohort_attribution(
            scored_rows,
            admitted=True,
        ),
        "skipped_cohorts": _cohort_attribution(
            scored_rows,
            admitted=False,
        ),
        "stability_blocks": blocks,
        "structural_ready": structural_ready,
        "development_qualified": development_qualified,
        "confidence_configuration": {
            "min_local_rows": confidence_config.min_local_rows,
            "min_fallback_rows": confidence_config.min_fallback_rows,
            "standard_error_multiplier": str(
                confidence_config.standard_error_multiplier
            ),
        },
    }
