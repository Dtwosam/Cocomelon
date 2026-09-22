from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from cocomelon.research.historical_baselines import (
    DecisionPolicy,
    ExecutionCostAssumptions,
    predict_training_rows,
)
from cocomelon.research.historical_features import HistoricalTrainingRow
from cocomelon.research.historical_occupancy import (
    HistoricalOccupancyBreakdownEntry,
    HistoricalOccupancyEvaluation,
    HistoricalOccupancyTradeSummary,
    evaluate_predicted_occupancy_policy,
    occupancy_trade_breakdowns,
    summarize_occupancy_trades,
)
from cocomelon.research.historical_ridge import (
    PreparedRidgeWalkForward,
    RidgeDirectionalModel,
    fit_ridge_directional_model,
    prepare_ridge_walk_forward,
    validate_prepared_ridge_walk_forward,
)
from cocomelon.research.historical_ridge_horizon import HorizonDecisionPolicy

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class OccupancyStableThresholdCandidate:
    threshold: Decimal
    overall: HistoricalOccupancyEvaluation
    blocks: tuple[HistoricalOccupancyTradeSummary, ...]
    qualifies: bool

    def __post_init__(self) -> None:
        if not self.threshold.is_finite() or self.threshold < ZERO:
            raise ValueError("threshold must be non-negative and finite")
        if not self.blocks:
            raise ValueError("blocks must not be empty")

    @property
    def worst_block_mean(self) -> Decimal | None:
        means = tuple(
            block.mean_realized_net_return
            for block in self.blocks
            if block.mean_realized_net_return is not None
        )
        if len(means) != len(self.blocks):
            return None
        return min(means)


@dataclass(frozen=True, slots=True)
class OccupancyStableThresholdCalibration:
    selected_threshold: Decimal | None
    candidates: tuple[OccupancyStableThresholdCandidate, ...]
    stability_blocks: int
    min_block_trades: int
    min_validation_trades: int
    min_validation_mean_net_return: Decimal

    def __post_init__(self) -> None:
        if not self.candidates:
            raise ValueError("candidates must not be empty")
        if self.stability_blocks <= 1:
            raise ValueError("stability_blocks must be greater than one")
        if self.min_block_trades <= 0:
            raise ValueError("min_block_trades must be positive")
        if self.min_validation_trades <= 0:
            raise ValueError("min_validation_trades must be positive")
        if not self.min_validation_mean_net_return.is_finite():
            raise ValueError("min_validation_mean_net_return must be finite")
        qualifying = tuple(item for item in self.candidates if item.qualifies)
        if self.selected_threshold is None:
            if qualifying:
                raise ValueError("abstention invalid when a candidate qualifies")
        elif not any(
            item.threshold == self.selected_threshold for item in qualifying
        ):
            raise ValueError("selected_threshold must identify a qualifying candidate")


@dataclass(frozen=True, slots=True)
class OccupancyHorizonCalibration:
    horizon_ms: int
    calibration: OccupancyStableThresholdCalibration

    def __post_init__(self) -> None:
        if self.horizon_ms <= 0:
            raise ValueError("horizon_ms must be positive")


@dataclass(frozen=True, slots=True)
class OccupancyRidgeAlphaValidation:
    alpha: Decimal
    horizons: tuple[OccupancyHorizonCalibration, ...]
    evaluation: HistoricalOccupancyEvaluation

    def __post_init__(self) -> None:
        if not self.alpha.is_finite() or self.alpha <= ZERO:
            raise ValueError("alpha must be positive and finite")
        if not self.horizons:
            raise ValueError("horizons must not be empty")


@dataclass(frozen=True, slots=True)
class OccupancyRidgeWalkForwardFold:
    fold_index: int
    train_anchor_count: int
    validation_anchor_count: int
    test_anchor_count: int
    shared_alpha: Decimal | None
    market_alpha: Decimal | None
    shared_horizon_thresholds: tuple[tuple[int, Decimal | None], ...]
    market_horizon_thresholds: tuple[tuple[int, Decimal | None], ...]
    shared_validation: tuple[OccupancyRidgeAlphaValidation, ...]
    market_validation: tuple[OccupancyRidgeAlphaValidation, ...]
    shared_test: HistoricalOccupancyEvaluation
    market_test: HistoricalOccupancyEvaluation
    shared_test_breakdowns: tuple[HistoricalOccupancyBreakdownEntry, ...]
    market_test_breakdowns: tuple[HistoricalOccupancyBreakdownEntry, ...]
    stability_blocks: int
    min_block_trades: int


@dataclass(frozen=True, slots=True)
class OccupancyRidgeWalkForwardReport:
    folds: tuple[OccupancyRidgeWalkForwardFold, ...]

    def __post_init__(self) -> None:
        if not self.folds:
            raise ValueError("folds must not be empty")


def _anchor_count(rows: Sequence[HistoricalTrainingRow]) -> int:
    return len({row.anchor_end_ms for row in rows})


def _validation_anchor_blocks(
    rows: Sequence[HistoricalTrainingRow],
    *,
    block_count: int,
) -> tuple[set[int], ...]:
    anchors = tuple(sorted({row.anchor_end_ms for row in rows}))
    if block_count <= 1:
        raise ValueError("block_count must be greater than one")
    if len(anchors) < block_count:
        raise ValueError("validation has fewer anchors than stability blocks")
    quotient, remainder = divmod(len(anchors), block_count)
    result: list[set[int]] = []
    offset = 0
    for index in range(block_count):
        size = quotient + (1 if index < remainder else 0)
        result.append(set(anchors[offset : offset + size]))
        offset += size
    return tuple(result)


def calibrate_occupancy_stable_threshold(
    model: RidgeDirectionalModel,
    validation_rows: Sequence[HistoricalTrainingRow],
    *,
    costs: ExecutionCostAssumptions,
    candidate_thresholds: Sequence[Decimal],
    min_sample_count: int,
    min_validation_trades: int,
    stability_blocks: int,
    min_block_trades: int,
    allow_coin_calibration: bool,
    min_validation_mean_net_return: Decimal = ZERO,
) -> OccupancyStableThresholdCalibration:
    if not validation_rows:
        raise ValueError("validation_rows must not be empty")
    thresholds = tuple(sorted(set(candidate_thresholds)))
    if not thresholds:
        raise ValueError("candidate_thresholds must not be empty")
    if any(not value.is_finite() or value < ZERO for value in thresholds):
        raise ValueError("candidate_thresholds must be non-negative finite Decimals")
    if min_sample_count <= 0:
        raise ValueError("min_sample_count must be positive")
    if min_validation_trades <= 0:
        raise ValueError("min_validation_trades must be positive")
    if min_block_trades <= 0:
        raise ValueError("min_block_trades must be positive")
    if not min_validation_mean_net_return.is_finite():
        raise ValueError("min_validation_mean_net_return must be finite")

    predicted = predict_training_rows(
        model,
        validation_rows,
        allow_coin_calibration=allow_coin_calibration,
    )
    anchor_blocks = _validation_anchor_blocks(
        validation_rows,
        block_count=stability_blocks,
    )
    candidates: list[OccupancyStableThresholdCandidate] = []
    for threshold in thresholds:
        policy = DecisionPolicy(
            min_expected_net_edge=threshold,
            min_sample_count=min_sample_count,
        )
        overall = evaluate_predicted_occupancy_policy(
            predicted,
            policy=policy,
            costs=costs,
        )
        blocks = tuple(
            summarize_occupancy_trades(
                tuple(
                    trade
                    for trade in overall.trades
                    if trade.anchor_end_ms in anchors
                )
            )
            for anchors in anchor_blocks
        )
        overall_mean = overall.mean_realized_net_return
        stable = all(
            block.trade_count >= min_block_trades
            and block.mean_realized_net_return is not None
            and block.mean_realized_net_return > min_validation_mean_net_return
            for block in blocks
        )
        qualifies = (
            overall.trade_count >= min_validation_trades
            and overall_mean is not None
            and overall_mean > min_validation_mean_net_return
            and stable
        )
        candidates.append(
            OccupancyStableThresholdCandidate(
                threshold=threshold,
                overall=overall,
                blocks=blocks,
                qualifies=qualifies,
            )
        )

    eligible = tuple(item for item in candidates if item.qualifies)
    selected_threshold: Decimal | None = None
    if eligible:
        def score(
            item: OccupancyStableThresholdCandidate,
        ) -> tuple[Decimal, Decimal, Decimal, int, Decimal]:
            worst = item.worst_block_mean
            mean = item.overall.mean_realized_net_return
            if worst is None or mean is None:
                raise ValueError("qualifying occupancy candidate must have means")
            return (
                worst,
                mean,
                item.overall.total_realized_net_return,
                item.overall.trade_count,
                -item.threshold,
            )

        selected_threshold = max(eligible, key=score).threshold

    return OccupancyStableThresholdCalibration(
        selected_threshold=selected_threshold,
        candidates=tuple(candidates),
        stability_blocks=stability_blocks,
        min_block_trades=min_block_trades,
        min_validation_trades=min_validation_trades,
        min_validation_mean_net_return=min_validation_mean_net_return,
    )


def _calibrate_horizons(
    model: RidgeDirectionalModel,
    validation_rows: Sequence[HistoricalTrainingRow],
    *,
    costs: ExecutionCostAssumptions,
    candidate_thresholds: Sequence[Decimal],
    min_sample_count: int,
    min_validation_trades: int,
    stability_blocks: int,
    min_block_trades: int,
    allow_coin_calibration: bool,
    min_validation_mean_net_return: Decimal,
) -> tuple[tuple[OccupancyHorizonCalibration, ...], HistoricalOccupancyEvaluation]:
    calibrations: list[OccupancyHorizonCalibration] = []
    for horizon_ms in sorted({row.horizon_ms for row in validation_rows}):
        horizon_rows = tuple(
            row for row in validation_rows if row.horizon_ms == horizon_ms
        )
        calibrations.append(
            OccupancyHorizonCalibration(
                horizon_ms=horizon_ms,
                calibration=calibrate_occupancy_stable_threshold(
                    model,
                    horizon_rows,
                    costs=costs,
                    candidate_thresholds=candidate_thresholds,
                    min_sample_count=min_sample_count,
                    min_validation_trades=min_validation_trades,
                    stability_blocks=stability_blocks,
                    min_block_trades=min_block_trades,
                    allow_coin_calibration=allow_coin_calibration,
                    min_validation_mean_net_return=min_validation_mean_net_return,
                ),
            )
        )

    resolved = tuple(calibrations)
    policy = HorizonDecisionPolicy(
        thresholds={
            item.horizon_ms: item.calibration.selected_threshold
            for item in resolved
        },
        min_sample_count=min_sample_count,
    )
    predicted = predict_training_rows(
        model,
        validation_rows,
        allow_coin_calibration=allow_coin_calibration,
    )
    return resolved, evaluate_predicted_occupancy_policy(
        predicted,
        policy=policy,
        costs=costs,
    )


def _choose_alpha(
    candidates: Sequence[OccupancyRidgeAlphaValidation],
    *,
    min_validation_trades: int,
    min_validation_mean_net_return: Decimal,
) -> OccupancyRidgeAlphaValidation | None:
    eligible = tuple(
        item
        for item in candidates
        if item.evaluation.trade_count >= min_validation_trades
        and item.evaluation.mean_realized_net_return is not None
        and item.evaluation.mean_realized_net_return > min_validation_mean_net_return
        and any(
            horizon.calibration.selected_threshold is not None
            for horizon in item.horizons
        )
    )
    if not eligible:
        return None
    return max(
        eligible,
        key=lambda item: (
            item.evaluation.mean_realized_net_return,
            item.evaluation.total_realized_net_return,
            item.evaluation.trade_count,
            -item.alpha,
        ),
    )


def _threshold_items(
    validation: OccupancyRidgeAlphaValidation,
) -> tuple[tuple[int, Decimal | None], ...]:
    return tuple(
        (item.horizon_ms, item.calibration.selected_threshold)
        for item in validation.horizons
    )


def select_final_occupancy_stable_ridge(
    fit_rows: Sequence[HistoricalTrainingRow],
    calibration_rows: Sequence[HistoricalTrainingRow],
    *,
    costs: ExecutionCostAssumptions,
    candidate_alphas: Sequence[Decimal],
    candidate_thresholds: Sequence[Decimal],
    min_market_samples: int,
    min_sample_count: int,
    min_validation_trades: int,
    stability_blocks: int,
    min_block_trades: int,
    allow_coin_calibration: bool,
    min_validation_mean_net_return: Decimal = ZERO,
) -> tuple[
    OccupancyRidgeAlphaValidation | None,
    tuple[OccupancyRidgeAlphaValidation, ...],
]:
    alphas = tuple(sorted(set(candidate_alphas)))
    if not alphas:
        raise ValueError("candidate_alphas must not be empty")
    if not fit_rows or not calibration_rows:
        raise ValueError("fit_rows and calibration_rows must not be empty")

    candidates: list[OccupancyRidgeAlphaValidation] = []
    for alpha in alphas:
        model = fit_ridge_directional_model(
            fit_rows,
            alpha=alpha,
            min_market_samples=min_market_samples,
        )
        horizons, evaluation = _calibrate_horizons(
            model,
            calibration_rows,
            costs=costs,
            candidate_thresholds=candidate_thresholds,
            min_sample_count=min_sample_count,
            min_validation_trades=min_validation_trades,
            stability_blocks=stability_blocks,
            min_block_trades=min_block_trades,
            allow_coin_calibration=allow_coin_calibration,
            min_validation_mean_net_return=min_validation_mean_net_return,
        )
        candidates.append(
            OccupancyRidgeAlphaValidation(
                alpha=alpha,
                horizons=horizons,
                evaluation=evaluation,
            )
        )
    resolved = tuple(candidates)
    return (
        _choose_alpha(
            resolved,
            min_validation_trades=min_validation_trades,
            min_validation_mean_net_return=min_validation_mean_net_return,
        ),
        resolved,
    )


def _abstained_evaluation(
    rows: Sequence[HistoricalTrainingRow],
) -> HistoricalOccupancyEvaluation:
    opportunities = {
        (row.market.canonical, row.anchor_end_ms)
        for row in rows
    }
    return HistoricalOccupancyEvaluation(
        prediction_row_count=len(rows),
        opportunity_count=len(opportunities),
        trade_count=0,
        long_count=0,
        short_count=0,
        no_trade_count=len(opportunities),
        occupied_skip_count=0,
        total_realized_net_return=ZERO,
        mean_realized_net_return=None,
        trades=(),
    )


def run_walk_forward_occupancy_stable_ridge(
    rows: Sequence[HistoricalTrainingRow],
    *,
    costs: ExecutionCostAssumptions,
    candidate_alphas: Sequence[Decimal],
    candidate_thresholds: Sequence[Decimal],
    min_train_anchors: int,
    validation_anchors: int,
    test_anchors: int,
    step_anchors: int,
    embargo_anchors: int,
    min_market_samples: int,
    min_sample_count: int,
    min_validation_trades: int,
    stability_blocks: int,
    min_block_trades: int,
    min_validation_mean_net_return: Decimal = ZERO,
    prepared: PreparedRidgeWalkForward | None = None,
) -> OccupancyRidgeWalkForwardReport:
    resolved = prepared
    if resolved is None:
        resolved = prepare_ridge_walk_forward(
            rows,
            candidate_alphas=candidate_alphas,
            min_train_anchors=min_train_anchors,
            validation_anchors=validation_anchors,
            test_anchors=test_anchors,
            step_anchors=step_anchors,
            embargo_anchors=embargo_anchors,
            min_market_samples=min_market_samples,
        )
    else:
        validate_prepared_ridge_walk_forward(
            resolved,
            candidate_alphas=candidate_alphas,
            min_train_anchors=min_train_anchors,
            validation_anchors=validation_anchors,
            test_anchors=test_anchors,
            step_anchors=step_anchors,
            embargo_anchors=embargo_anchors,
            min_market_samples=min_market_samples,
        )

    results: list[OccupancyRidgeWalkForwardFold] = []
    for prepared_fold in resolved.folds:
        fold = prepared_fold.split
        models = dict(prepared_fold.models)
        shared_candidates: list[OccupancyRidgeAlphaValidation] = []
        market_candidates: list[OccupancyRidgeAlphaValidation] = []

        for alpha in resolved.candidate_alphas:
            model = models[alpha]
            shared_horizons, shared_eval = _calibrate_horizons(
                model,
                fold.validation,
                costs=costs,
                candidate_thresholds=candidate_thresholds,
                min_sample_count=min_sample_count,
                min_validation_trades=min_validation_trades,
                stability_blocks=stability_blocks,
                min_block_trades=min_block_trades,
                allow_coin_calibration=False,
                min_validation_mean_net_return=min_validation_mean_net_return,
            )
            shared_candidates.append(
                OccupancyRidgeAlphaValidation(
                    alpha=alpha,
                    horizons=shared_horizons,
                    evaluation=shared_eval,
                )
            )
            market_horizons, market_eval = _calibrate_horizons(
                model,
                fold.validation,
                costs=costs,
                candidate_thresholds=candidate_thresholds,
                min_sample_count=min_sample_count,
                min_validation_trades=min_validation_trades,
                stability_blocks=stability_blocks,
                min_block_trades=min_block_trades,
                allow_coin_calibration=True,
                min_validation_mean_net_return=min_validation_mean_net_return,
            )
            market_candidates.append(
                OccupancyRidgeAlphaValidation(
                    alpha=alpha,
                    horizons=market_horizons,
                    evaluation=market_eval,
                )
            )

        selected_shared = _choose_alpha(
            shared_candidates,
            min_validation_trades=min_validation_trades,
            min_validation_mean_net_return=min_validation_mean_net_return,
        )
        selected_market = _choose_alpha(
            market_candidates,
            min_validation_trades=min_validation_trades,
            min_validation_mean_net_return=min_validation_mean_net_return,
        )

        if selected_shared is None:
            shared_alpha = None
            shared_thresholds: tuple[tuple[int, Decimal | None], ...] = ()
            shared_test = _abstained_evaluation(fold.test)
            shared_breakdowns: tuple[HistoricalOccupancyBreakdownEntry, ...] = ()
        else:
            shared_alpha = selected_shared.alpha
            shared_thresholds = _threshold_items(selected_shared)
            policy = HorizonDecisionPolicy(
                thresholds=dict(shared_thresholds),
                min_sample_count=min_sample_count,
            )
            predicted = predict_training_rows(
                models[shared_alpha],
                fold.test,
                allow_coin_calibration=False,
            )
            shared_test = evaluate_predicted_occupancy_policy(
                predicted,
                policy=policy,
                costs=costs,
            )
            shared_breakdowns = occupancy_trade_breakdowns(shared_test)

        if selected_market is None:
            market_alpha = None
            market_thresholds: tuple[tuple[int, Decimal | None], ...] = ()
            market_test = _abstained_evaluation(fold.test)
            market_breakdowns: tuple[HistoricalOccupancyBreakdownEntry, ...] = ()
        else:
            market_alpha = selected_market.alpha
            market_thresholds = _threshold_items(selected_market)
            policy = HorizonDecisionPolicy(
                thresholds=dict(market_thresholds),
                min_sample_count=min_sample_count,
            )
            predicted = predict_training_rows(
                models[market_alpha],
                fold.test,
                allow_coin_calibration=True,
            )
            market_test = evaluate_predicted_occupancy_policy(
                predicted,
                policy=policy,
                costs=costs,
            )
            market_breakdowns = occupancy_trade_breakdowns(market_test)

        results.append(
            OccupancyRidgeWalkForwardFold(
                fold_index=prepared_fold.fold_index,
                train_anchor_count=_anchor_count(fold.train),
                validation_anchor_count=_anchor_count(fold.validation),
                test_anchor_count=_anchor_count(fold.test),
                shared_alpha=shared_alpha,
                market_alpha=market_alpha,
                shared_horizon_thresholds=shared_thresholds,
                market_horizon_thresholds=market_thresholds,
                shared_validation=tuple(shared_candidates),
                market_validation=tuple(market_candidates),
                shared_test=shared_test,
                market_test=market_test,
                shared_test_breakdowns=shared_breakdowns,
                market_test_breakdowns=market_breakdowns,
                stability_blocks=stability_blocks,
                min_block_trades=min_block_trades,
            )
        )

    return OccupancyRidgeWalkForwardReport(folds=tuple(results))
