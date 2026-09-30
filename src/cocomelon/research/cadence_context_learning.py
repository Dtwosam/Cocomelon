from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from cocomelon.domain.features import FeatureSnapshot
from cocomelon.domain.strategy import Direction
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


class CadenceContextLearningError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _ContextEstimate:
    mean: Decimal
    count: int
    group_key: tuple[str, ...]
    specificity: str


@dataclass(frozen=True, slots=True)
class _ContextRow:
    outcome: ShadowCadenceOutcome
    feature: FeatureSnapshot


def _context_keys(
    row: _ContextRow,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    sample = row.outcome.sample
    direction = sample.direction.value
    strategy = sample.lead_strategy
    score = _score_band(sample.score)
    trend = row.feature.trend_regime.value
    volatility = row.feature.volatility_regime.value
    return (
        (
            "direction_strategy_score_trend_volatility",
            (direction, strategy, score, trend, volatility),
        ),
        (
            "direction_strategy_score_trend",
            (direction, strategy, score, trend, "*"),
        ),
        (
            "direction_strategy_score_volatility",
            (direction, strategy, score, "*", volatility),
        ),
        (
            "direction_strategy_score",
            (direction, strategy, score, "*", "*"),
        ),
        (
            "direction_strategy",
            (direction, strategy, "*", "*", "*"),
        ),
        (
            "direction_score",
            (direction, "*", score, "*", "*"),
        ),
        (
            "direction",
            (direction, "*", "*", "*", "*"),
        ),
        (
            "global",
            ("*", "*", "*", "*", "*"),
        ),
    )


def _resolve_rows(
    outcomes: tuple[ShadowCadenceOutcome, ...],
    feature_store: LearningFeatureSnapshotStore,
) -> tuple[tuple[_ContextRow, ...], tuple[str, ...]]:
    rows: list[_ContextRow] = []
    missing: list[str] = []
    for outcome in outcomes:
        snapshot_id = outcome.sample.feature_snapshot_id
        verified = feature_store.load(snapshot_id)
        if verified is None:
            missing.append(snapshot_id)
            continue
        feature = verified.snapshot
        if feature.market != outcome.sample.market:
            raise CadenceContextLearningError(
                "CADENCE_CONTEXT_FEATURE_MARKET_MISMATCH"
            )
        if feature.as_of_ms > outcome.sample.evaluated_at_ms:
            raise CadenceContextLearningError(
                "CADENCE_CONTEXT_FEATURE_AFTER_DECISION"
            )
        if feature.source_received_at_ms > outcome.sample.evaluated_at_ms:
            raise CadenceContextLearningError(
                "CADENCE_CONTEXT_FEATURE_SOURCE_AFTER_DECISION"
            )
        rows.append(_ContextRow(outcome=outcome, feature=feature))
    return tuple(rows), tuple(sorted(set(missing)))


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
    min_group_rows: int,
) -> _ContextEstimate | None:
    for specificity, key in _context_keys(row):
        count = counts[key]
        if count < min_group_rows:
            continue
        return _ContextEstimate(
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
        payload[direction] = {
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
    return payload


def _regime_summary(
    rows: tuple[tuple[_ContextRow, bool], ...],
) -> tuple[dict[str, object], ...]:
    grouped: dict[
        tuple[str, str, str],
        list[tuple[_ContextRow, bool]],
    ] = defaultdict(list)
    for row, take in rows:
        grouped[
            (
                row.outcome.sample.direction.value,
                row.feature.trend_regime.value,
                row.feature.volatility_regime.value,
            )
        ].append((row, take))

    output: list[dict[str, object]] = []
    for key, items in grouped.items():
        admitted = tuple(
            row.outcome
            for row, take in items
            if take
        )
        validation_sum = sum(
            (row.outcome.net_return for row, _ in items),
            ZERO,
        )
        candidate_sum = sum(
            (row.net_return for row in admitted),
            ZERO,
        )
        output.append(
            {
                "direction": key[0],
                "trend_regime": key[1],
                "volatility_regime": key[2],
                "validation_rows": len(items),
                "admitted_rows": len(admitted),
                "actual_net_return_sum": str(validation_sum),
                "candidate_net_return_sum": str(candidate_sum),
                "delta_net_return_sum": str(
                    candidate_sum - validation_sum
                ),
                "candidate_mean_net_return": (
                    None
                    if not admitted
                    else str(
                        candidate_sum / Decimal(len(admitted))
                    )
                ),
            }
        )
    output.sort(
        key=lambda item: (
            str(item["direction"]),
            str(item["trend_regime"]),
            str(item["volatility_regime"]),
        )
    )
    return tuple(output)


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


def _cohort_attribution(
    scored: tuple[
        tuple[_ContextRow, bool, _ContextEstimate],
        ...,
    ],
    *,
    admitted: bool,
) -> tuple[dict[str, object], ...]:
    groups: dict[
        tuple[str, str, str, str, str, str],
        list[tuple[_ContextRow, _ContextEstimate]],
    ] = defaultdict(list)
    for row, take, estimate in scored:
        if take is not admitted:
            continue
        groups[
            (
                row.outcome.sample.direction.value,
                row.outcome.sample.lead_strategy,
                _score_band(row.outcome.sample.score),
                row.feature.trend_regime.value,
                row.feature.volatility_regime.value,
                estimate.specificity,
            )
        ].append((row, estimate))

    output: list[tuple[Decimal, dict[str, object]]] = []
    for key, items in groups.items():
        outcomes = tuple(item.outcome for item, _ in items)
        estimates = tuple(estimate for _, estimate in items)
        first = estimates[0]
        if any(estimate != first for estimate in estimates[1:]):
            raise CadenceContextLearningError(
                "CADENCE_CONTEXT_ESTIMATE_DRIFT"
            )
        net_sum = sum((outcome.net_return for outcome in outcomes), ZERO)
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


def evaluate_cadence_context_learning(
    outcomes: tuple[ShadowCadenceOutcome, ...],
    feature_store: LearningFeatureSnapshotStore,
    *,
    cadence_ms: int = FIFTEEN_MINUTES_MS,
    horizon_ms: int = ONE_HOUR_MS,
    config: CadenceOpportunityLearningConfig = DEFAULT_CONFIG,
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
    if len(surface) < config.validation_rows:
        return {
            "status": "not_ready",
            "reason": "insufficient_validation_rows",
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "settled_rows": len(surface),
        }

    validation = surface[-config.validation_rows :]
    validation_start_ms = validation[0].sample.boundary_ms
    candidates = surface[:-config.validation_rows]
    training = tuple(
        row
        for row in candidates
        if row.sample.target_end_ms < validation_start_ms
    )
    purged = len(candidates) - len(training)
    if len(training) < config.min_train_rows:
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
            "settled_rows": len(surface),
            "training_rows": len(training),
            "validation_rows": len(validation),
            "purged_overlap_rows": purged,
            "missing_training_feature_snapshots": len(
                missing_training
            ),
            "missing_validation_feature_snapshots": len(
                missing_validation
            ),
            "missing_feature_snapshot_ids": (
                missing_training + missing_validation
            )[:20],
        }

    sums, counts = _fit(training_rows)
    scored: list[tuple[_ContextRow, bool, _ContextEstimate]] = []
    specificity = Counter[str]()
    missing_estimates = 0
    for row in validation_rows:
        estimate = _estimate(
            row,
            sums,
            counts,
            min_group_rows=config.min_group_rows,
        )
        if estimate is None:
            missing_estimates += 1
            continue
        specificity[estimate.specificity] += 1
        scored.append((row, estimate.mean > ZERO, estimate))

    if missing_estimates:
        return {
            "status": "not_ready",
            "reason": "validation_estimate_missing",
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "settled_rows": len(surface),
            "training_rows": len(training_rows),
            "validation_rows": len(validation_rows),
            "purged_overlap_rows": purged,
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
    by_direction = _direction_summary(realized)
    blocks = _stability_blocks(
        realized,
        blocks=config.stability_blocks,
        min_block_admitted=config.min_block_admitted,
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
        len(realized) == config.validation_rows
        and long_validation >= config.min_validation_per_direction
        and short_validation >= config.min_validation_per_direction
    )
    stable = all(bool(block["passes"]) for block in blocks)
    development_qualified = (
        structural_ready
        and len(admitted) >= config.min_validation_admitted
        and long_admitted >= config.min_admitted_per_direction
        and short_admitted >= config.min_admitted_per_direction
        and candidate_mean is not None
        and candidate_mean > ZERO
        and stable
    )

    return {
        "status": "completed",
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "claim_scope": "touched_contextual_meta_label_development",
        "model_family": "hierarchical_regime_grouped_mean_v1",
        "decision_policy": (
            "admit_if_purged_training_context_mean_net_return_gt_zero"
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
        "by_direction": by_direction,
        "by_regime": _regime_summary(realized),
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
        "configuration": {
            "min_train_rows": config.min_train_rows,
            "validation_rows": config.validation_rows,
            "min_group_rows": config.min_group_rows,
            "stability_blocks": config.stability_blocks,
            "min_validation_admitted": (
                config.min_validation_admitted
            ),
            "min_block_admitted": config.min_block_admitted,
            "min_validation_per_direction": (
                config.min_validation_per_direction
            ),
            "min_admitted_per_direction": (
                config.min_admitted_per_direction
            ),
        },
    }
