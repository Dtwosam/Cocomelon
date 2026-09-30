from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from cocomelon.domain.strategy import Direction
from cocomelon.research.cadence_shadow import (
    DEFAULT_HORIZONS_MS,
    FIFTEEN_MINUTES_MS,
    SUPPORTED_CADENCES_MS,
    ShadowCadenceOutcome,
)

ZERO: Final = Decimal("0")
DEFAULT_MIN_TRAIN_ROWS: Final = 300
DEFAULT_VALIDATION_ROWS: Final = 100
DEFAULT_MIN_GROUP_ROWS: Final = 25
DEFAULT_STABILITY_BLOCKS: Final = 4
DEFAULT_MIN_VALIDATION_ADMITTED: Final = 20
DEFAULT_MIN_BLOCK_ADMITTED: Final = 3
DEFAULT_MIN_VALIDATION_PER_DIRECTION: Final = 10
DEFAULT_MIN_ADMITTED_PER_DIRECTION: Final = 5


class CadenceOpportunityLearningError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CadenceOpportunityLearningConfig:
    min_train_rows: int = DEFAULT_MIN_TRAIN_ROWS
    validation_rows: int = DEFAULT_VALIDATION_ROWS
    min_group_rows: int = DEFAULT_MIN_GROUP_ROWS
    stability_blocks: int = DEFAULT_STABILITY_BLOCKS
    min_validation_admitted: int = DEFAULT_MIN_VALIDATION_ADMITTED
    min_block_admitted: int = DEFAULT_MIN_BLOCK_ADMITTED
    min_validation_per_direction: int = DEFAULT_MIN_VALIDATION_PER_DIRECTION
    min_admitted_per_direction: int = DEFAULT_MIN_ADMITTED_PER_DIRECTION

    def __post_init__(self) -> None:
        values = (
            self.min_train_rows,
            self.validation_rows,
            self.min_group_rows,
            self.stability_blocks,
            self.min_validation_admitted,
            self.min_block_admitted,
            self.min_validation_per_direction,
            self.min_admitted_per_direction,
        )
        if any(value <= 0 for value in values):
            raise ValueError(
                "cadence opportunity learning thresholds must be positive"
            )
        if self.validation_rows < self.stability_blocks:
            raise ValueError(
                "validation_rows must cover every stability block"
            )
        if (
            self.min_validation_admitted
            > self.validation_rows
        ):
            raise ValueError(
                "min_validation_admitted cannot exceed validation_rows"
            )


DEFAULT_CONFIG: Final = CadenceOpportunityLearningConfig()


def _score_band(score: Decimal) -> str:
    if score < Decimal("65"):
        return "<65"
    if score < Decimal("70"):
        return "65-<70"
    if score < Decimal("75"):
        return "70-<75"
    if score < Decimal("80"):
        return "75-<80"
    return "80+"


def _surface_key(outcome: ShadowCadenceOutcome) -> tuple[int, int]:
    sample = outcome.sample
    return sample.cadence_ms, sample.horizon_ms


def _group_keys(
    outcome: ShadowCadenceOutcome,
) -> tuple[tuple[str, str, str], ...]:
    sample = outcome.sample
    direction = sample.direction.value
    strategy = sample.lead_strategy
    band = _score_band(sample.score)
    return (
        (direction, strategy, band),
        (direction, strategy, "*"),
        (direction, "*", band),
        (direction, "*", "*"),
        ("*", "*", "*"),
    )


def _surface_name(cadence_ms: int, horizon_ms: int) -> str:
    return f"{cadence_ms}:{horizon_ms}"


@dataclass(frozen=True, slots=True)
class _MeanEstimate:
    mean: Decimal
    count: int
    group_key: tuple[str, str, str]
    specificity: str


def _fit_group_means(
    rows: tuple[ShadowCadenceOutcome, ...],
) -> tuple[
    dict[tuple[str, str, str], Decimal],
    Counter[tuple[str, str, str]],
]:
    sums: defaultdict[tuple[str, str, str], Decimal] = defaultdict(
        lambda: ZERO
    )
    counts: Counter[tuple[str, str, str]] = Counter()
    for row in rows:
        for key in _group_keys(row):
            sums[key] += row.net_return
            counts[key] += 1
    return dict(sums), counts


def _estimate(
    row: ShadowCadenceOutcome,
    sums: dict[tuple[str, str, str], Decimal],
    counts: Counter[tuple[str, str, str]],
    *,
    min_group_rows: int,
) -> _MeanEstimate | None:
    labels = (
        "direction_strategy_score",
        "direction_strategy",
        "direction_score",
        "direction",
        "global",
    )
    for label, key in zip(labels, _group_keys(row), strict=True):
        count = counts[key]
        if count < min_group_rows:
            continue
        return _MeanEstimate(
            mean=sums[key] / Decimal(count),
            count=count,
            group_key=key,
            specificity=label,
        )
    return None


def _direction_summary(
    rows: tuple[tuple[ShadowCadenceOutcome, bool], ...],
) -> dict[str, object]:
    payload: dict[str, object] = {}
    for direction in (Direction.LONG.value, Direction.SHORT.value):
        cohort = tuple(
            (row, admitted)
            for row, admitted in rows
            if row.sample.direction.value == direction
        )
        admitted_rows = tuple(
            row for row, admitted in cohort if admitted
        )
        actual_sum = sum((row.net_return for row, _ in cohort), ZERO)
        candidate_sum = sum(
            (row.net_return for row in admitted_rows),
            ZERO,
        )
        payload[direction] = {
            "validation_rows": len(cohort),
            "admitted_rows": len(admitted_rows),
            "actual_mean_net_return": (
                None
                if not cohort
                else str(actual_sum / Decimal(len(cohort)))
            ),
            "candidate_mean_net_return": (
                None
                if not admitted_rows
                else str(
                    candidate_sum / Decimal(len(admitted_rows))
                )
            ),
            "actual_net_return_sum": str(actual_sum),
            "candidate_net_return_sum": str(candidate_sum),
            "delta_net_return_sum": str(candidate_sum - actual_sum),
        }
    return payload


def _stability_blocks(
    rows: tuple[tuple[ShadowCadenceOutcome, bool], ...],
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
            row for row, take in block if take
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


def _surface_report(
    rows: tuple[ShadowCadenceOutcome, ...],
    *,
    cadence_ms: int,
    horizon_ms: int,
    config: CadenceOpportunityLearningConfig,
) -> dict[str, object]:
    ordered = tuple(
        sorted(
            rows,
            key=lambda item: (
                item.sample.boundary_ms,
                item.sample.market.canonical,
                item.sample.decision_id,
            ),
        )
    )
    if len(ordered) < config.validation_rows:
        return {
            "cadence_ms": cadence_ms,
            "horizon_ms": horizon_ms,
            "status": "not_ready",
            "settled_rows": len(ordered),
            "reason": "insufficient_validation_rows",
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
        }

    validation = ordered[-config.validation_rows :]
    validation_start_ms = validation[0].sample.boundary_ms
    train_candidates = ordered[: -config.validation_rows]
    training = tuple(
        row
        for row in train_candidates
        if row.sample.target_end_ms < validation_start_ms
    )
    purged_overlap_count = len(train_candidates) - len(training)

    if len(training) < config.min_train_rows:
        return {
            "cadence_ms": cadence_ms,
            "horizon_ms": horizon_ms,
            "status": "not_ready",
            "settled_rows": len(ordered),
            "training_rows": len(training),
            "validation_rows": len(validation),
            "purged_overlap_rows": purged_overlap_count,
            "validation_start_ms": validation_start_ms,
            "reason": "insufficient_purged_training_rows",
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
        }

    sums, counts = _fit_group_means(training)
    scored: list[
        tuple[ShadowCadenceOutcome, bool, _MeanEstimate]
    ] = []
    missing_estimate = 0
    specificity = Counter[str]()
    for row in validation:
        estimate = _estimate(
            row,
            sums,
            counts,
            min_group_rows=config.min_group_rows,
        )
        if estimate is None:
            missing_estimate += 1
            continue
        specificity[estimate.specificity] += 1
        scored.append((row, estimate.mean > ZERO, estimate))

    if missing_estimate:
        return {
            "cadence_ms": cadence_ms,
            "horizon_ms": horizon_ms,
            "status": "not_ready",
            "settled_rows": len(ordered),
            "training_rows": len(training),
            "validation_rows": len(validation),
            "purged_overlap_rows": purged_overlap_count,
            "validation_start_ms": validation_start_ms,
            "missing_validation_estimates": missing_estimate,
            "reason": "validation_estimate_missing",
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
        }

    realized = tuple((row, take) for row, take, _ in scored)
    admitted = tuple(row for row, take in realized if take)
    actual_sum = sum((row.net_return for row, _ in realized), ZERO)
    candidate_sum = sum((row.net_return for row in admitted), ZERO)
    candidate_mean = (
        None
        if not admitted
        else candidate_sum / Decimal(len(admitted))
    )

    by_direction = _direction_summary(realized)
    long_summary = by_direction[Direction.LONG.value]
    short_summary = by_direction[Direction.SHORT.value]
    if not isinstance(long_summary, dict) or not isinstance(
        short_summary,
        dict,
    ):
        raise CadenceOpportunityLearningError(
            "direction summary is invalid"
        )
    blocks = _stability_blocks(
        realized,
        blocks=config.stability_blocks,
        min_block_admitted=config.min_block_admitted,
    )
    stable = all(bool(block["passes"]) for block in blocks)

    structural_ready = (
        len(realized) == config.validation_rows
        and int(long_summary["validation_rows"])
        >= config.min_validation_per_direction
        and int(short_summary["validation_rows"])
        >= config.min_validation_per_direction
    )
    development_qualified = (
        structural_ready
        and len(admitted) >= config.min_validation_admitted
        and int(long_summary["admitted_rows"])
        >= config.min_admitted_per_direction
        and int(short_summary["admitted_rows"])
        >= config.min_admitted_per_direction
        and candidate_mean is not None
        and candidate_mean > ZERO
        and stable
    )

    return {
        "cadence_ms": cadence_ms,
        "horizon_ms": horizon_ms,
        "status": "completed",
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "model_family": "hierarchical_grouped_mean_v1",
        "decision_policy": "admit_if_purged_training_mean_net_return_gt_zero",
        "settled_rows": len(ordered),
        "training_rows": len(training),
        "validation_rows": len(validation),
        "purged_overlap_rows": purged_overlap_count,
        "validation_start_ms": validation_start_ms,
        "validation_end_ms": validation[-1].sample.target_end_ms,
        "admitted_rows": len(admitted),
        "skipped_rows": len(realized) - len(admitted),
        "actual_net_return_sum": str(actual_sum),
        "candidate_net_return_sum": str(candidate_sum),
        "delta_net_return_sum": str(candidate_sum - actual_sum),
        "actual_mean_net_return": str(
            actual_sum / Decimal(len(realized))
        ),
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


def evaluate_cadence_opportunity_learning(
    outcomes: tuple[ShadowCadenceOutcome, ...],
    *,
    config: CadenceOpportunityLearningConfig = DEFAULT_CONFIG,
) -> dict[str, object]:
    by_surface: defaultdict[
        tuple[int, int],
        list[ShadowCadenceOutcome],
    ] = defaultdict(list)
    for outcome in outcomes:
        key = _surface_key(outcome)
        if key[0] not in SUPPORTED_CADENCES_MS:
            raise CadenceOpportunityLearningError(
                "unsupported cadence in cadence outcome"
            )
        if key[1] not in DEFAULT_HORIZONS_MS:
            raise CadenceOpportunityLearningError(
                "unsupported horizon in cadence outcome"
            )
        by_surface[key].append(outcome)

    surfaces: dict[str, dict[str, object]] = {}
    for cadence_ms in SUPPORTED_CADENCES_MS:
        for horizon_ms in DEFAULT_HORIZONS_MS:
            key = (cadence_ms, horizon_ms)
            surfaces[_surface_name(*key)] = _surface_report(
                tuple(by_surface.get(key, ())),
                cadence_ms=cadence_ms,
                horizon_ms=horizon_ms,
                config=config,
            )

    primary_keys = tuple(
        _surface_name(FIFTEEN_MINUTES_MS, horizon_ms)
        for horizon_ms in DEFAULT_HORIZONS_MS
    )
    primary = tuple(surfaces[key] for key in primary_keys)
    primary_ready = all(
        item.get("status") == "completed"
        and item.get("structural_ready") is True
        for item in primary
    )
    development_qualified = (
        primary_ready
        and all(
            item.get("development_qualified") is True
            for item in primary
        )
    )

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "model_family": "hierarchical_grouped_mean_v1",
        "claim_scope": (
            "cost_adjusted_directional_forward_opportunity_validation"
        ),
        "settled_outcomes": len(outcomes),
        "primary_execution_cadence_ms": FIFTEEN_MINUTES_MS,
        "primary_surface_keys": primary_keys,
        "primary_ready_for_review": primary_ready,
        "development_qualified": development_qualified,
        "surfaces": surfaces,
    }
