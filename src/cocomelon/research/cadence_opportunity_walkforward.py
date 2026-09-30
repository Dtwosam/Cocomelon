from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, cast

from cocomelon.domain.strategy import Direction
from cocomelon.research.cadence_opportunity_learning import (
    _estimate,
    _fit_group_means,
    _MeanEstimate,
    _score_band,
)
from cocomelon.research.cadence_shadow import (
    FIFTEEN_MINUTES_MS,
    ONE_HOUR_MS,
    ShadowCadenceOutcome,
)

ZERO: Final = Decimal("0")


class CadenceOpportunityWalkforwardError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CadenceOpportunityWalkforwardConfig:
    validation_rows: int = 50
    folds: int = 6
    min_train_rows: int = 300
    min_group_rows: int = 25

    def __post_init__(self) -> None:
        if self.validation_rows <= 0:
            raise ValueError("validation_rows must be positive")
        if self.folds <= 0:
            raise ValueError("folds must be positive")
        if self.min_train_rows <= 0:
            raise ValueError("min_train_rows must be positive")
        if self.min_group_rows <= 0:
            raise ValueError("min_group_rows must be positive")


DEFAULT_CONFIG: Final = CadenceOpportunityWalkforwardConfig()


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


def _direction_summary(
    rows: tuple[tuple[ShadowCadenceOutcome, bool], ...],
) -> dict[str, dict[str, object]]:
    payload: dict[str, dict[str, object]] = {}
    for direction in (Direction.LONG.value, Direction.SHORT.value):
        cohort = tuple(
            (row, take)
            for row, take in rows
            if row.sample.direction.value == direction
        )
        admitted = tuple(row for row, take in cohort if take)
        candidate_sum = sum((row.net_return for row in admitted), ZERO)
        actual_sum = sum((row.net_return for row, _ in cohort), ZERO)
        payload[direction] = {
            "validation_rows": len(cohort),
            "admitted_rows": len(admitted),
            "actual_net_return_sum": str(actual_sum),
            "candidate_net_return_sum": str(candidate_sum),
            "candidate_mean_net_return": (
                None
                if not admitted
                else str(candidate_sum / Decimal(len(admitted)))
            ),
        }
    return payload


def _cohort_summary(
    scored: tuple[
        tuple[ShadowCadenceOutcome, bool, _MeanEstimate],
        ...,
    ],
) -> tuple[dict[str, object], ...]:
    grouped: dict[
        tuple[str, str, str],
        list[tuple[ShadowCadenceOutcome, _MeanEstimate]],
    ] = defaultdict(list)
    for row, take, estimate in scored:
        if not take:
            continue
        grouped[
            (
                row.sample.direction.value,
                row.sample.lead_strategy,
                _score_band(row.sample.score),
            )
        ].append((row, estimate))

    payload: list[dict[str, object]] = []
    for key, items in grouped.items():
        rows = tuple(row for row, _ in items)
        estimates = tuple(estimate for _, estimate in items)
        estimate_values = tuple(item.mean for item in estimates)
        candidate_sum = sum((row.net_return for row in rows), ZERO)
        payload.append(
            {
                "direction": key[0],
                "lead_strategy": key[1],
                "score_band": key[2],
                "rows": len(rows),
                "net_return_sum": str(candidate_sum),
                "mean_net_return": str(
                    candidate_sum / Decimal(len(rows))
                ),
                "training_estimate_min": str(min(estimate_values)),
                "training_estimate_max": str(max(estimate_values)),
                "training_estimate_specificities": sorted(
                    {estimate.specificity for estimate in estimates}
                ),
            }
        )
    payload.sort(
        key=lambda item: (
            -Decimal(str(item["net_return_sum"])),
            str(item["direction"]),
            str(item["lead_strategy"]),
            str(item["score_band"]),
        )
    )
    return tuple(payload)


def _evaluate_fold(
    ordered: tuple[ShadowCadenceOutcome, ...],
    *,
    fold_index: int,
    start: int,
    end: int,
    config: CadenceOpportunityWalkforwardConfig,
) -> dict[str, object]:
    validation = ordered[start:end]
    if len(validation) != config.validation_rows:
        raise CadenceOpportunityWalkforwardError(
            "walk-forward validation window is incomplete"
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

    sums, counts = _fit_group_means(training)
    scored: list[
        tuple[ShadowCadenceOutcome, bool, _MeanEstimate]
    ] = []
    for row in validation:
        estimate = _estimate(
            row,
            sums,
            counts,
            min_group_rows=config.min_group_rows,
        )
        if estimate is None:
            return {
                **base,
                "status": "not_ready",
                "reason": "validation_estimate_missing",
            }
        scored.append((row, estimate.mean > ZERO, estimate))

    scored_tuple = tuple(scored)
    realized = tuple((row, take) for row, take, _ in scored_tuple)
    admitted = tuple(row for row, take in realized if take)
    actual_sum = sum((row.net_return for row, _ in realized), ZERO)
    candidate_sum = sum((row.net_return for row in admitted), ZERO)
    return {
        **base,
        "status": "completed",
        "admitted_rows": len(admitted),
        "skipped_rows": len(realized) - len(admitted),
        "actual_net_return_sum": str(actual_sum),
        "candidate_net_return_sum": str(candidate_sum),
        "delta_net_return_sum": str(candidate_sum - actual_sum),
        "candidate_mean_net_return": (
            None
            if not admitted
            else str(candidate_sum / Decimal(len(admitted)))
        ),
        "candidate_sum_positive": candidate_sum > ZERO,
        "by_direction": _direction_summary(realized),
        "admitted_cohorts": _cohort_summary(scored_tuple),
    }


def _fold_direction_admitted(
    fold: dict[str, object],
    direction: str,
) -> int:
    raw_direction = fold.get("by_direction")
    if not isinstance(raw_direction, dict):
        raise CadenceOpportunityWalkforwardError(
            "completed fold direction summary is invalid"
        )
    raw_row = raw_direction.get(direction)
    if not isinstance(raw_row, dict):
        raise CadenceOpportunityWalkforwardError(
            "completed fold direction row is invalid"
        )
    value = raw_row.get("admitted_rows")
    if isinstance(value, bool) or not isinstance(value, int):
        raise CadenceOpportunityWalkforwardError(
            "completed fold admitted row count is invalid"
        )
    return value


def evaluate_cadence_opportunity_walkforward(
    outcomes: tuple[ShadowCadenceOutcome, ...],
    *,
    cadence_ms: int = FIFTEEN_MINUTES_MS,
    horizon_ms: int = ONE_HOUR_MS,
    config: CadenceOpportunityWalkforwardConfig = DEFAULT_CONFIG,
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
            fold_index=fold_index,
            start=first_start + fold_index * config.validation_rows,
            end=first_start + (fold_index + 1) * config.validation_rows,
            config=config,
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

    cohort_by_key: dict[
        tuple[str, str, str],
        dict[str, object],
    ] = {}
    for fold in completed:
        raw_cohorts = fold.get("admitted_cohorts", ())
        if not isinstance(raw_cohorts, tuple):
            continue
        for cohort in raw_cohorts:
            if not isinstance(cohort, dict):
                continue
            key = (
                str(cohort["direction"]),
                str(cohort["lead_strategy"]),
                str(cohort["score_band"]),
            )
            aggregate = cohort_by_key.setdefault(
                key,
                {
                    "direction": key[0],
                    "lead_strategy": key[1],
                    "score_band": key[2],
                    "folds_present": 0,
                    "positive_folds": 0,
                    "rows": 0,
                    "net_return_sum": ZERO,
                },
            )
            aggregate["folds_present"] = (
                cast(int, aggregate["folds_present"]) + 1
            )
            aggregate["rows"] = (
                cast(int, aggregate["rows"])
                + cast(int, cohort["rows"])
            )
            fold_sum = Decimal(str(cohort["net_return_sum"]))
            aggregate["net_return_sum"] = (
                Decimal(str(aggregate["net_return_sum"])) + fold_sum
            )
            if fold_sum > ZERO:
                aggregate["positive_folds"] = (
                    cast(int, aggregate["positive_folds"]) + 1
                )

    cohort_persistence: list[dict[str, object]] = []
    for aggregate in cohort_by_key.values():
        net_sum = Decimal(str(aggregate["net_return_sum"]))
        rows = cast(int, aggregate["rows"])
        cohort_persistence.append(
            {
                **aggregate,
                "net_return_sum": str(net_sum),
                "mean_net_return": (
                    None
                    if rows == 0
                    else str(net_sum / Decimal(rows))
                ),
            }
        )
    cohort_persistence.sort(
        key=lambda item: (
            -cast(int, item["folds_present"]),
            -Decimal(str(item["net_return_sum"])),
            str(item["direction"]),
            str(item["lead_strategy"]),
            str(item["score_band"]),
        )
    )

    candidate_total = sum(candidate_sums, ZERO)
    actual_total = sum(actual_sums, ZERO)
    return {
        "status": "completed",
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "claim_scope": (
            "touched_disjoint_purged_walkforward_diagnostic"
        ),
        "cadence_ms": cadence_ms,
        "horizon_ms": horizon_ms,
        "settled_rows": len(ordered),
        "fold_count": len(completed),
        "validation_rows_per_fold": config.validation_rows,
        "first_validation_index": first_start,
        "candidate_net_return_sum": str(candidate_total),
        "actual_net_return_sum": str(actual_total),
        "delta_net_return_sum": str(candidate_total - actual_total),
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
        "cohort_persistence": tuple(cohort_persistence),
        "configuration": {
            "validation_rows": config.validation_rows,
            "folds": config.folds,
            "min_train_rows": config.min_train_rows,
            "min_group_rows": config.min_group_rows,
        },
    }
