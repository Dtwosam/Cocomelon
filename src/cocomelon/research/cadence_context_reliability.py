from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, cast

from cocomelon.domain.strategy import Direction
from cocomelon.research.cadence_context_learning import (
    _context_keys,
    _ContextRow,
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
DEFAULT_ADMISSION_MARGIN: Final = Decimal("0.0001")


class CadenceContextReliabilityError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CadenceContextReliabilityConfig:
    min_exact_context_rows: int = DEFAULT_CONFIG.min_group_rows // 3
    admission_margin: Decimal = DEFAULT_ADMISSION_MARGIN

    def __post_init__(self) -> None:
        if self.min_exact_context_rows <= 0:
            raise ValueError("min_exact_context_rows must be positive")
        if (
            not self.admission_margin.is_finite()
            or self.admission_margin < ZERO
        ):
            raise ValueError(
                "admission_margin must be non-negative and finite"
            )


DEFAULT_RELIABILITY_CONFIG: Final = CadenceContextReliabilityConfig()


@dataclass(frozen=True, slots=True)
class _ReliabilityEstimate:
    mean: Decimal
    count: int
    group_key: tuple[str, ...]
    specificity: str


def _fit(
    rows: tuple[_ContextRow, ...],
) -> tuple[dict[tuple[str, ...], Decimal], Counter[tuple[str, ...]]]:
    sums: defaultdict[tuple[str, ...], Decimal] = defaultdict(
        lambda: ZERO
    )
    counts: Counter[tuple[str, ...]] = Counter()
    for row in rows:
        for _, key in _context_keys(row):
            sums[key] += row.outcome.net_return
            counts[key] += 1
    return dict(sums), counts


def _estimate(
    row: _ContextRow,
    sums: dict[tuple[str, ...], Decimal],
    counts: Counter[tuple[str, ...]],
    *,
    learning_config: CadenceOpportunityLearningConfig,
    reliability_config: CadenceContextReliabilityConfig,
) -> _ReliabilityEstimate | None:
    keys = _context_keys(row)
    exact_label, exact_key = keys[0]
    exact_count = counts[exact_key]
    if exact_count >= reliability_config.min_exact_context_rows:
        return _ReliabilityEstimate(
            mean=sums[exact_key] / Decimal(exact_count),
            count=exact_count,
            group_key=exact_key,
            specificity=(
                exact_label
                if exact_count >= learning_config.min_group_rows
                else f"{exact_label}_sparse_supported"
            ),
        )

    for specificity, key in keys[1:]:
        count = counts[key]
        if count < learning_config.min_group_rows:
            continue
        return _ReliabilityEstimate(
            mean=sums[key] / Decimal(count),
            count=count,
            group_key=key,
            specificity=specificity,
        )
    return None


def _direction_summary(
    rows: tuple[tuple[_ContextRow, bool], ...],
) -> dict[str, object]:
    payload: dict[str, object] = {}
    for direction in (Direction.LONG.value, Direction.SHORT.value):
        cohort = tuple(
            (row, admitted)
            for row, admitted in rows
            if row.outcome.sample.direction.value == direction
        )
        admitted_rows = tuple(
            row.outcome
            for row, admitted in cohort
            if admitted
        )
        actual_sum = sum(
            (row.outcome.net_return for row, _ in cohort),
            ZERO,
        )
        candidate_sum = sum(
            (row.net_return for row in admitted_rows),
            ZERO,
        )
        payload[direction] = {
            "validation_rows": len(cohort),
            "admitted_rows": len(admitted_rows),
            "actual_net_return_sum": str(actual_sum),
            "candidate_net_return_sum": str(candidate_sum),
            "delta_net_return_sum": str(candidate_sum - actual_sum),
            "candidate_mean_net_return": (
                None
                if not admitted_rows
                else str(
                    candidate_sum / Decimal(len(admitted_rows))
                )
            ),
        }
    return payload


def _stability_blocks(
    rows: tuple[tuple[_ContextRow, bool], ...],
    *,
    blocks: int,
    min_block_admitted: int,
) -> tuple[dict[str, object], ...]:
    result: list[dict[str, object]] = []
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
        result.append(
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
    return tuple(result)


def _cohort_attribution(
    scored: tuple[
        tuple[_ContextRow, bool, _ReliabilityEstimate],
        ...,
    ],
    *,
    admitted: bool,
) -> tuple[dict[str, object], ...]:
    groups: dict[
        tuple[str, str, str, str, str, str],
        list[tuple[_ContextRow, _ReliabilityEstimate]],
    ] = defaultdict(list)
    for row, take, estimate in scored:
        if take is not admitted:
            continue
        sample = row.outcome.sample
        groups[
            (
                sample.direction.value,
                sample.lead_strategy,
                _score_band(sample.score),
                row.feature.trend_regime.value,
                row.feature.volatility_regime.value,
                estimate.specificity,
            )
        ].append((row, estimate))

    output: list[tuple[Decimal, dict[str, object]]] = []
    for key, items in groups.items():
        outcomes = tuple(item.outcome for item, _ in items)
        first = items[0][1]
        if any(estimate != first for _, estimate in items[1:]):
            raise CadenceContextReliabilityError(
                "CADENCE_CONTEXT_RELIABILITY_ESTIMATE_DRIFT"
            )
        net_sum = sum((row.net_return for row in outcomes), ZERO)
        output.append(
            (
                net_sum,
                {
                    "direction": key[0],
                    "lead_strategy": key[1],
                    "score_band": key[2],
                    "trend_regime": key[3],
                    "volatility_regime": key[4],
                    "training_estimate_specificity": key[5],
                    "training_estimate_mean_net_return": str(first.mean),
                    "training_estimate_rows": first.count,
                    "training_group_key": first.group_key,
                    "validation_rows": len(outcomes),
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


def evaluate_cadence_context_reliability(
    outcomes: tuple[ShadowCadenceOutcome, ...],
    feature_store: LearningFeatureSnapshotStore,
    *,
    cadence_ms: int = FIFTEEN_MINUTES_MS,
    horizon_ms: int = ONE_HOUR_MS,
    learning_config: CadenceOpportunityLearningConfig = DEFAULT_CONFIG,
    reliability_config: CadenceContextReliabilityConfig = (
        DEFAULT_RELIABILITY_CONFIG
    ),
) -> dict[str, object]:
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

    validation = surface[-learning_config.validation_rows :]
    validation_start_ms = validation[0].sample.boundary_ms
    candidates = surface[: -learning_config.validation_rows]
    training = tuple(
        row
        for row in candidates
        if row.sample.target_end_ms < validation_start_ms
    )
    purged = len(candidates) - len(training)
    if len(training) < learning_config.min_train_rows:
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

    sums, counts = _fit(training_rows)
    scored: list[
        tuple[_ContextRow, bool, _ReliabilityEstimate]
    ] = []
    specificity = Counter[str]()
    missing_estimates = 0
    for row in validation_rows:
        estimate = _estimate(
            row,
            sums,
            counts,
            learning_config=learning_config,
            reliability_config=reliability_config,
        )
        if estimate is None:
            missing_estimates += 1
            continue
        specificity[estimate.specificity] += 1
        scored.append(
            (
                row,
                estimate.mean > reliability_config.admission_margin,
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
        blocks=learning_config.stability_blocks,
        min_block_admitted=learning_config.min_block_admitted,
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
        len(realized) == learning_config.validation_rows
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

    return {
        "status": "completed",
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "claim_scope": (
            "touched_contextual_reliability_meta_label_development"
        ),
        "model_family": "hierarchical_regime_reliability_v1",
        "decision_policy": (
            "use_exact_context_from_min_support_then_admit_above_margin"
        ),
        "cadence_ms": cadence_ms,
        "horizon_ms": horizon_ms,
        "settled_rows": len(surface),
        "training_rows": len(training_rows),
        "validation_rows": len(validation_rows),
        "purged_overlap_rows": purged,
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
        "baseline_context_model": {
            "status": baseline.get("status"),
            "admitted_rows": baseline_admitted,
            "candidate_net_return_sum": str(baseline_sum),
            "development_qualified": baseline.get(
                "development_qualified"
            ),
        },
        "reliability_minus_baseline_net_return_sum": str(
            candidate_sum - baseline_sum
        ),
        "reliability_minus_baseline_admitted_rows": (
            len(admitted) - baseline_admitted
        ),
        "configuration": {
            "min_exact_context_rows": (
                reliability_config.min_exact_context_rows
            ),
            "admission_margin": str(
                reliability_config.admission_margin
            ),
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
