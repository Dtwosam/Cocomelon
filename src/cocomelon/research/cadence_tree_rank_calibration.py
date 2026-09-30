from __future__ import annotations

from collections import defaultdict
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
    CadenceTreeConfig,
    _Encoder,
    _fit_tree,
    _predict,
)
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotStore,
)

ZERO: Final = Decimal("0")
DEFAULT_CALIBRATION_ROWS: Final = 120
DEFAULT_BAND_COUNT: Final = 5
DEFAULT_MIN_BAND_ROWS: Final = 15
DEFAULT_STANDARD_ERROR_MULTIPLIER: Final = Decimal("1.0")


class CadenceTreeCalibrationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CadenceTreeCalibrationConfig:
    calibration_rows: int = DEFAULT_CALIBRATION_ROWS
    band_count: int = DEFAULT_BAND_COUNT
    min_band_rows: int = DEFAULT_MIN_BAND_ROWS
    standard_error_multiplier: Decimal = (
        DEFAULT_STANDARD_ERROR_MULTIPLIER
    )

    def __post_init__(self) -> None:
        if self.calibration_rows <= 0:
            raise ValueError("calibration_rows must be positive")
        if self.band_count < 2:
            raise ValueError("band_count must be at least two")
        if self.min_band_rows < 2:
            raise ValueError("min_band_rows must be at least two")
        if (
            not self.standard_error_multiplier.is_finite()
            or self.standard_error_multiplier < ZERO
        ):
            raise ValueError(
                "standard_error_multiplier must be finite and non-negative"
            )


DEFAULT_CALIBRATION_CONFIG: Final = CadenceTreeCalibrationConfig()


@dataclass(frozen=True, slots=True)
class _BandStats:
    rows: int
    total: Decimal
    total_sq: Decimal
    long_rows: int
    short_rows: int

    @property
    def mean(self) -> Decimal:
        return self.total / Decimal(self.rows)

    @property
    def standard_error(self) -> Decimal:
        if self.rows < 2:
            return ZERO
        count = Decimal(self.rows)
        numerator = self.total_sq - self.total * self.total / count
        if numerator < ZERO:
            numerator = ZERO
        variance = numerator / Decimal(self.rows - 1)
        return (variance / count).sqrt()


def _rank_band(
    prediction: Decimal,
    reference_predictions: tuple[Decimal, ...],
    *,
    band_count: int,
) -> int:
    if not reference_predictions:
        raise CadenceTreeCalibrationError(
            "rank calibration reference predictions are empty"
        )
    higher = sum(
        1 for value in reference_predictions if value > prediction
    )
    band = higher * band_count // len(reference_predictions)
    return min(band, band_count - 1)


def _band_stats(
    rows: tuple[tuple[_ContextRow, Decimal], ...],
    reference_predictions: tuple[Decimal, ...],
    *,
    band_count: int,
) -> dict[int, _BandStats]:
    values: defaultdict[int, list[_ContextRow]] = defaultdict(list)
    for row, prediction in rows:
        values[
            _rank_band(
                prediction,
                reference_predictions,
                band_count=band_count,
            )
        ].append(row)

    output: dict[int, _BandStats] = {}
    for band, items in values.items():
        returns = tuple(item.outcome.net_return for item in items)
        output[band] = _BandStats(
            rows=len(items),
            total=sum(returns, ZERO),
            total_sq=sum((value * value for value in returns), ZERO),
            long_rows=sum(
                1
                for item in items
                if item.outcome.sample.direction is Direction.LONG
            ),
            short_rows=sum(
                1
                for item in items
                if item.outcome.sample.direction is Direction.SHORT
            ),
        )
    return output


def _selected_bands(
    stats: dict[int, _BandStats],
    *,
    config: CadenceTreeCalibrationConfig,
) -> tuple[int, ...]:
    selected: list[int] = []
    for band in range(config.band_count):
        item = stats.get(band)
        if item is None or item.rows < config.min_band_rows:
            continue
        lower_bound = (
            item.mean
            - config.standard_error_multiplier
            * item.standard_error
        )
        if lower_bound > ZERO:
            selected.append(band)
    return tuple(selected)


def _calibration_band_payload(
    stats: dict[int, _BandStats],
    selected: tuple[int, ...],
    *,
    config: CadenceTreeCalibrationConfig,
) -> tuple[dict[str, object], ...]:
    output: list[dict[str, object]] = []
    for band in range(config.band_count):
        item = stats.get(band)
        if item is None:
            output.append(
                {
                    "band_index": band,
                    "rows": 0,
                    "selected": False,
                }
            )
            continue
        lower_bound = (
            item.mean
            - config.standard_error_multiplier
            * item.standard_error
        )
        output.append(
            {
                "band_index": band,
                "rows": item.rows,
                "long_rows": item.long_rows,
                "short_rows": item.short_rows,
                "net_return_sum": str(item.total),
                "mean_net_return": str(item.mean),
                "standard_error": str(item.standard_error),
                "lower_bound": str(lower_bound),
                "selected": band in selected,
            }
        )
    return tuple(output)


def _stability_blocks(
    rows: tuple[tuple[_ContextRow, bool, int, Decimal], ...],
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
            for row, take, _band, _prediction in block
            if take
        )
        total = sum((row.net_return for row in admitted), ZERO)
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
    rows: tuple[tuple[_ContextRow, bool, int, Decimal], ...],
) -> dict[str, object]:
    output: dict[str, object] = {}
    for direction in (Direction.LONG.value, Direction.SHORT.value):
        cohort = tuple(
            (row, take)
            for row, take, _band, _prediction in rows
            if row.outcome.sample.direction.value == direction
        )
        admitted = tuple(
            row.outcome
            for row, take in cohort
            if take
        )
        actual_total = sum(
            (row.outcome.net_return for row, _take in cohort),
            ZERO,
        )
        candidate_total = sum(
            (row.net_return for row in admitted),
            ZERO,
        )
        output[direction] = {
            "validation_rows": len(cohort),
            "admitted_rows": len(admitted),
            "actual_net_return_sum": str(actual_total),
            "candidate_net_return_sum": str(candidate_total),
            "delta_net_return_sum": str(
                candidate_total - actual_total
            ),
            "candidate_mean_net_return": (
                None
                if not admitted
                else str(candidate_total / Decimal(len(admitted)))
            ),
        }
    return output


def evaluate_cadence_tree_rank_calibration(
    outcomes: tuple[ShadowCadenceOutcome, ...],
    feature_store: LearningFeatureSnapshotStore,
    *,
    cadence_ms: int = FIFTEEN_MINUTES_MS,
    horizon_ms: int = ONE_HOUR_MS,
    validation_config: CadenceOpportunityLearningConfig = DEFAULT_CONFIG,
    tree_config: CadenceTreeConfig = DEFAULT_TREE_CONFIG,
    calibration_config: CadenceTreeCalibrationConfig = (
        DEFAULT_CALIBRATION_CONFIG
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
    outer_candidates = surface[:-validation_config.validation_rows]
    outer_training = tuple(
        row
        for row in outer_candidates
        if row.sample.target_end_ms < validation_start_ms
    )
    outer_purged = len(outer_candidates) - len(outer_training)
    if len(outer_training) < validation_config.min_train_rows:
        return {
            "status": "not_ready",
            "reason": "insufficient_purged_training_rows",
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "training_rows": len(outer_training),
            "validation_rows": len(validation),
            "purged_overlap_rows": outer_purged,
        }
    if len(outer_training) <= calibration_config.calibration_rows:
        return {
            "status": "not_ready",
            "reason": "insufficient_inner_calibration_rows",
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
        }

    inner_calibration = outer_training[
        -calibration_config.calibration_rows :
    ]
    inner_calibration_start_ms = (
        inner_calibration[0].sample.boundary_ms
    )
    inner_candidates = outer_training[
        : -calibration_config.calibration_rows
    ]
    inner_training = tuple(
        row
        for row in inner_candidates
        if row.sample.target_end_ms < inner_calibration_start_ms
    )
    inner_purged = len(inner_candidates) - len(inner_training)
    if len(inner_training) < validation_config.min_train_rows:
        return {
            "status": "not_ready",
            "reason": "insufficient_inner_training_rows",
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "inner_training_rows": len(inner_training),
            "inner_calibration_rows": len(inner_calibration),
            "inner_purged_overlap_rows": inner_purged,
        }

    inner_training_rows, missing_inner_training = _resolve_rows(
        inner_training,
        feature_store,
    )
    inner_calibration_rows, missing_calibration = _resolve_rows(
        inner_calibration,
        feature_store,
    )
    outer_training_rows, missing_outer_training = _resolve_rows(
        outer_training,
        feature_store,
    )
    validation_rows, missing_validation = _resolve_rows(
        validation,
        feature_store,
    )
    missing = (
        missing_inner_training
        + missing_calibration
        + missing_outer_training
        + missing_validation
    )
    if missing:
        return {
            "status": "not_ready",
            "reason": "feature_snapshot_missing",
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "missing_feature_snapshots": len(set(missing)),
        }

    inner_encoder = _Encoder.fit(inner_training_rows)
    inner_estimator = _fit_tree(
        inner_training_rows,
        encoder=inner_encoder,
        config=tree_config,
    )
    inner_reference_predictions = _predict(
        inner_estimator,
        inner_encoder,
        inner_training_rows,
    )
    inner_calibration_predictions = _predict(
        inner_estimator,
        inner_encoder,
        inner_calibration_rows,
    )
    calibration_scored = tuple(
        (row, prediction)
        for row, prediction in zip(
            inner_calibration_rows,
            inner_calibration_predictions,
            strict=True,
        )
    )
    stats = _band_stats(
        calibration_scored,
        inner_reference_predictions,
        band_count=calibration_config.band_count,
    )
    selected = _selected_bands(
        stats,
        config=calibration_config,
    )

    outer_encoder = _Encoder.fit(outer_training_rows)
    outer_estimator = _fit_tree(
        outer_training_rows,
        encoder=outer_encoder,
        config=tree_config,
    )
    outer_reference_predictions = _predict(
        outer_estimator,
        outer_encoder,
        outer_training_rows,
    )
    validation_predictions = _predict(
        outer_estimator,
        outer_encoder,
        validation_rows,
    )
    scored = tuple(
        (
            row,
            (
                band := _rank_band(
                    prediction,
                    outer_reference_predictions,
                    band_count=calibration_config.band_count,
                )
            )
            in selected,
            band,
            prediction,
        )
        for row, prediction in zip(
            validation_rows,
            validation_predictions,
            strict=True,
        )
    )

    admitted = tuple(
        row.outcome
        for row, take, _band, _prediction in scored
        if take
    )
    actual_total = sum(
        (row.outcome.net_return for row, _, _, _ in scored),
        ZERO,
    )
    candidate_total = sum(
        (row.net_return for row in admitted),
        ZERO,
    )
    candidate_mean = (
        None
        if not admitted
        else candidate_total / Decimal(len(admitted))
    )
    blocks = _stability_blocks(
        scored,
        blocks=validation_config.stability_blocks,
        min_block_admitted=validation_config.min_block_admitted,
    )
    long_validation = sum(
        1
        for row, _, _, _ in scored
        if row.outcome.sample.direction is Direction.LONG
    )
    short_validation = sum(
        1
        for row, _, _, _ in scored
        if row.outcome.sample.direction is Direction.SHORT
    )
    long_admitted = sum(
        1
        for row, take, _, _ in scored
        if take and row.outcome.sample.direction is Direction.LONG
    )
    short_admitted = sum(
        1
        for row, take, _, _ in scored
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

    validation_band_payload: list[dict[str, object]] = []
    grouped: defaultdict[
        int,
        list[tuple[_ContextRow, bool, Decimal]],
    ] = defaultdict(list)
    for row, take, band, prediction in scored:
        grouped[band].append((row, take, prediction))
    for band in range(calibration_config.band_count):
        items = grouped.get(band, [])
        values = tuple(
            item[0].outcome.net_return for item in items
        )
        predictions = tuple(item[2] for item in items)
        validation_band_payload.append(
            {
                "band_index": band,
                "selected": band in selected,
                "rows": len(items),
                "admitted_rows": sum(1 for _, take, _ in items if take),
                "net_return_sum": str(sum(values, ZERO)),
                "mean_net_return": (
                    None
                    if not values
                    else str(sum(values, ZERO) / Decimal(len(values)))
                ),
                "prediction_min": (
                    None if not predictions else str(min(predictions))
                ),
                "prediction_max": (
                    None if not predictions else str(max(predictions))
                ),
                "long_rows": sum(
                    1
                    for row, _, _ in items
                    if row.outcome.sample.direction is Direction.LONG
                ),
                "short_rows": sum(
                    1
                    for row, _, _ in items
                    if row.outcome.sample.direction is Direction.SHORT
                ),
            }
        )

    return {
        "status": "completed",
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "claim_scope": "touched_nested_tree_rank_calibration",
        "model_family": "cadence_tree_rank_calibration_v1",
        "decision_policy": (
            "admit_only_inner_calibration_positive_rank_bands"
        ),
        "cadence_ms": cadence_ms,
        "horizon_ms": horizon_ms,
        "settled_rows": len(surface),
        "outer_training_rows": len(outer_training_rows),
        "outer_validation_rows": len(validation_rows),
        "outer_purged_overlap_rows": outer_purged,
        "inner_training_rows": len(inner_training_rows),
        "inner_calibration_rows": len(inner_calibration_rows),
        "inner_purged_overlap_rows": inner_purged,
        "selected_band_indices": selected,
        "calibration_bands": _calibration_band_payload(
            stats,
            selected,
            config=calibration_config,
        ),
        "validation_bands": tuple(validation_band_payload),
        "admitted_rows": len(admitted),
        "skipped_rows": len(scored) - len(admitted),
        "actual_net_return_sum": str(actual_total),
        "candidate_net_return_sum": str(candidate_total),
        "delta_net_return_sum": str(candidate_total - actual_total),
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
        "structural_ready": structural_ready,
        "development_qualified": development_qualified,
        "calibration_configuration": {
            "calibration_rows": calibration_config.calibration_rows,
            "band_count": calibration_config.band_count,
            "min_band_rows": calibration_config.min_band_rows,
            "standard_error_multiplier": str(
                calibration_config.standard_error_multiplier
            ),
        },
        "tree_configuration": {
            "max_leaf_nodes": tree_config.max_leaf_nodes,
            "min_samples_leaf": tree_config.min_samples_leaf,
            "learning_rate": str(tree_config.learning_rate),
            "max_iter": tree_config.max_iter,
            "l2_regularization": str(
                tree_config.l2_regularization
            ),
        },
    }
