from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from cocomelon.research.historical_baselines import (
    DecisionPolicy,
    ExecutionCostAssumptions,
    HistoricalDirectionalModel,
    PolicyBreakdownEntry,
    PolicyEvaluation,
    evaluate_policy,
    evaluate_policy_breakdowns,
)
from cocomelon.research.historical_features import HistoricalTrainingRow
from cocomelon.research.historical_ridge import (
    PreparedRidgeWalkForward,
    RidgeDirectionalModel,
    prepare_ridge_walk_forward,
    validate_prepared_ridge_walk_forward,
)
from cocomelon.research.historical_ridge_horizon import HorizonDecisionPolicy

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class StableThresholdCandidate:
    threshold: Decimal
    overall: PolicyEvaluation
    blocks: tuple[PolicyEvaluation, ...]
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
class StableThresholdCalibration:
    selected_threshold: Decimal | None
    candidates: tuple[StableThresholdCandidate, ...]
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
        selected = tuple(
            candidate
            for candidate in self.candidates
            if candidate.threshold == self.selected_threshold
        )
        if self.selected_threshold is None:
            if any(candidate.qualifies for candidate in self.candidates):
                raise ValueError("abstention invalid when a stable candidate qualifies")
        elif len(selected) != 1 or not selected[0].qualifies:
            raise ValueError("selected_threshold must identify one qualifying candidate")

    @property
    def abstained(self) -> bool:
        return self.selected_threshold is None


@dataclass(frozen=True, slots=True)
class StableHorizonCalibration:
    horizon_ms: int
    calibration: StableThresholdCalibration

    def __post_init__(self) -> None:
        if self.horizon_ms <= 0:
            raise ValueError("horizon_ms must be positive")


@dataclass(frozen=True, slots=True)
class StableRidgeAlphaValidation:
    alpha: Decimal
    horizons: tuple[StableHorizonCalibration, ...]
    evaluation: PolicyEvaluation

    def __post_init__(self) -> None:
        if not self.alpha.is_finite() or self.alpha <= ZERO:
            raise ValueError("alpha must be positive and finite")
        if not self.horizons:
            raise ValueError("horizons must not be empty")
        actual = tuple(item.horizon_ms for item in self.horizons)
        if actual != tuple(sorted(set(actual))):
            raise ValueError("horizon calibrations must be sorted and unique")


@dataclass(frozen=True, slots=True)
class StableRidgeWalkForwardFold:
    fold_index: int
    train_anchor_count: int
    validation_anchor_count: int
    test_anchor_count: int
    shared_alpha: Decimal | None
    market_alpha: Decimal | None
    shared_horizon_thresholds: tuple[tuple[int, Decimal | None], ...]
    market_horizon_thresholds: tuple[tuple[int, Decimal | None], ...]
    shared_test: PolicyEvaluation
    market_test: PolicyEvaluation
    shared_validation: tuple[StableRidgeAlphaValidation, ...]
    market_validation: tuple[StableRidgeAlphaValidation, ...]
    shared_test_breakdowns: tuple[PolicyBreakdownEntry, ...]
    market_test_breakdowns: tuple[PolicyBreakdownEntry, ...]
    stability_blocks: int
    min_block_trades: int

    def __post_init__(self) -> None:
        if self.fold_index <= 0:
            raise ValueError("fold_index must be positive")
        if not self.shared_validation or not self.market_validation:
            raise ValueError("validation candidates must not be empty")
        if self.stability_blocks <= 1:
            raise ValueError("stability_blocks must be greater than one")
        if self.min_block_trades <= 0:
            raise ValueError("min_block_trades must be positive")


@dataclass(frozen=True, slots=True)
class StableRidgeWalkForwardReport:
    folds: tuple[StableRidgeWalkForwardFold, ...]

    def __post_init__(self) -> None:
        if not self.folds:
            raise ValueError("folds must not be empty")


def _anchor_count(rows: Sequence[HistoricalTrainingRow]) -> int:
    return len({row.anchor_end_ms for row in rows})


def _validation_blocks(
    rows: Sequence[HistoricalTrainingRow],
    *,
    block_count: int,
) -> tuple[tuple[HistoricalTrainingRow, ...], ...]:
    if block_count <= 1:
        raise ValueError("block_count must be greater than one")
    anchors = tuple(sorted({row.anchor_end_ms for row in rows}))
    if len(anchors) < block_count:
        raise ValueError("validation has fewer anchors than stability blocks")

    quotient, remainder = divmod(len(anchors), block_count)
    blocks: list[tuple[HistoricalTrainingRow, ...]] = []
    offset = 0
    for index in range(block_count):
        size = quotient + (1 if index < remainder else 0)
        selected = set(anchors[offset : offset + size])
        blocks.append(
            tuple(
                row
                for row in rows
                if row.anchor_end_ms in selected
            )
        )
        offset += size
    return tuple(blocks)


def calibrate_stable_no_trade_threshold(
    model: HistoricalDirectionalModel,
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
) -> StableThresholdCalibration:
    if not validation_rows:
        raise ValueError("validation_rows must not be empty")
    if min_sample_count <= 0:
        raise ValueError("min_sample_count must be positive")
    if min_validation_trades <= 0:
        raise ValueError("min_validation_trades must be positive")
    if min_block_trades <= 0:
        raise ValueError("min_block_trades must be positive")
    if not min_validation_mean_net_return.is_finite():
        raise ValueError("min_validation_mean_net_return must be finite")

    thresholds = tuple(sorted(set(candidate_thresholds)))
    if not thresholds:
        raise ValueError("candidate_thresholds must not be empty")
    if any(not value.is_finite() or value < ZERO for value in thresholds):
        raise ValueError("candidate_thresholds must be non-negative finite Decimals")

    ordered = tuple(
        sorted(
            validation_rows,
            key=lambda row: (
                row.anchor_end_ms,
                row.market.canonical,
                row.horizon_ms,
                row.training_row_id,
            ),
        )
    )
    blocks = _validation_blocks(ordered, block_count=stability_blocks)
    candidates: list[StableThresholdCandidate] = []

    for threshold in thresholds:
        policy = DecisionPolicy(
            min_expected_net_edge=threshold,
            min_sample_count=min_sample_count,
        )
        overall = evaluate_policy(
            model,
            ordered,
            policy=policy,
            costs=costs,
            allow_coin_calibration=allow_coin_calibration,
        )
        block_evaluations = tuple(
            evaluate_policy(
                model,
                block,
                policy=policy,
                costs=costs,
                allow_coin_calibration=allow_coin_calibration,
            )
            for block in blocks
        )
        overall_mean = overall.mean_realized_net_return
        block_stable = all(
            block.trade_count >= min_block_trades
            and block.mean_realized_net_return is not None
            and block.mean_realized_net_return > min_validation_mean_net_return
            for block in block_evaluations
        )
        qualifies = (
            overall.trade_count >= min_validation_trades
            and overall_mean is not None
            and overall_mean > min_validation_mean_net_return
            and block_stable
        )
        candidates.append(
            StableThresholdCandidate(
                threshold=threshold,
                overall=overall,
                blocks=block_evaluations,
                qualifies=qualifies,
            )
        )

    eligible = tuple(candidate for candidate in candidates if candidate.qualifies)
    if not eligible:
        selected_threshold = None
    else:
        def score(
            candidate: StableThresholdCandidate,
        ) -> tuple[Decimal, Decimal, Decimal, int, Decimal]:
            worst = candidate.worst_block_mean
            overall_mean = candidate.overall.mean_realized_net_return
            if worst is None or overall_mean is None:
                raise ValueError("qualifying stable candidate must have realized means")
            return (
                worst,
                overall_mean,
                candidate.overall.total_realized_net_return,
                candidate.overall.trade_count,
                -candidate.threshold,
            )

        selected = max(eligible, key=score)
        selected_threshold = selected.threshold

    return StableThresholdCalibration(
        selected_threshold=selected_threshold,
        candidates=tuple(candidates),
        stability_blocks=stability_blocks,
        min_block_trades=min_block_trades,
        min_validation_trades=min_validation_trades,
        min_validation_mean_net_return=min_validation_mean_net_return,
    )


def _calibrate_stable_horizons(
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
) -> tuple[tuple[StableHorizonCalibration, ...], PolicyEvaluation]:
    calibrations: list[StableHorizonCalibration] = []
    for horizon_ms in sorted({row.horizon_ms for row in validation_rows}):
        horizon_rows = tuple(
            row for row in validation_rows if row.horizon_ms == horizon_ms
        )
        calibration = calibrate_stable_no_trade_threshold(
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
        )
        calibrations.append(
            StableHorizonCalibration(
                horizon_ms=horizon_ms,
                calibration=calibration,
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
    evaluation = evaluate_policy(
        model,
        validation_rows,
        policy=policy,
        costs=costs,
        allow_coin_calibration=allow_coin_calibration,
    )
    return resolved, evaluation


def _choose_alpha(
    candidates: Sequence[StableRidgeAlphaValidation],
    *,
    min_validation_trades: int,
    min_validation_mean_net_return: Decimal,
) -> StableRidgeAlphaValidation | None:
    eligible = tuple(
        candidate
        for candidate in candidates
        if candidate.evaluation.trade_count >= min_validation_trades
        and candidate.evaluation.mean_realized_net_return is not None
        and candidate.evaluation.mean_realized_net_return > min_validation_mean_net_return
        and any(
            item.calibration.selected_threshold is not None
            for item in candidate.horizons
        )
    )
    if not eligible:
        return None
    return max(
        eligible,
        key=lambda candidate: (
            candidate.evaluation.mean_realized_net_return,
            candidate.evaluation.total_realized_net_return,
            candidate.evaluation.trade_count,
            -candidate.alpha,
        ),
    )


def _threshold_items(
    candidate: StableRidgeAlphaValidation,
) -> tuple[tuple[int, Decimal | None], ...]:
    return tuple(
        (item.horizon_ms, item.calibration.selected_threshold)
        for item in candidate.horizons
    )


def _abstained_evaluation(rows: Sequence[HistoricalTrainingRow]) -> PolicyEvaluation:
    return PolicyEvaluation(
        row_count=len(rows),
        trade_count=0,
        long_count=0,
        short_count=0,
        no_trade_count=len(rows),
        total_realized_net_return=ZERO,
        mean_realized_net_return=None,
    )


def run_walk_forward_stable_horizon_ridge(
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
) -> StableRidgeWalkForwardReport:
    if stability_blocks <= 1:
        raise ValueError("stability_blocks must be greater than one")
    if min_block_trades <= 0:
        raise ValueError("min_block_trades must be positive")

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

    results: list[StableRidgeWalkForwardFold] = []
    for prepared_fold in resolved.folds:
        fold_index = prepared_fold.fold_index
        fold = prepared_fold.split
        models = dict(prepared_fold.models)
        shared_candidates: list[StableRidgeAlphaValidation] = []
        market_candidates: list[StableRidgeAlphaValidation] = []

        for alpha in resolved.candidate_alphas:
            model = models[alpha]

            shared_horizons, shared_validation = _calibrate_stable_horizons(
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
                StableRidgeAlphaValidation(
                    alpha=alpha,
                    horizons=shared_horizons,
                    evaluation=shared_validation,
                )
            )

            market_horizons, market_validation = _calibrate_stable_horizons(
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
                StableRidgeAlphaValidation(
                    alpha=alpha,
                    horizons=market_horizons,
                    evaluation=market_validation,
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

        shared_test_breakdowns: tuple[PolicyBreakdownEntry, ...]
        market_test_breakdowns: tuple[PolicyBreakdownEntry, ...]

        if selected_shared is None:
            shared_alpha = None
            shared_horizon_thresholds: tuple[tuple[int, Decimal | None], ...] = ()
            shared_test = _abstained_evaluation(fold.test)
            shared_test_breakdowns = ()
        else:
            shared_alpha = selected_shared.alpha
            shared_horizon_thresholds = _threshold_items(selected_shared)
            shared_policy = HorizonDecisionPolicy(
                thresholds=dict(shared_horizon_thresholds),
                min_sample_count=min_sample_count,
            )
            shared_test = evaluate_policy(
                models[shared_alpha],
                fold.test,
                policy=shared_policy,
                costs=costs,
                allow_coin_calibration=False,
            )
            shared_test_breakdowns = evaluate_policy_breakdowns(
                models[shared_alpha],
                fold.test,
                policy=shared_policy,
                costs=costs,
                allow_coin_calibration=False,
            )

        if selected_market is None:
            market_alpha = None
            market_horizon_thresholds: tuple[tuple[int, Decimal | None], ...] = ()
            market_test = _abstained_evaluation(fold.test)
            market_test_breakdowns = ()
        else:
            market_alpha = selected_market.alpha
            market_horizon_thresholds = _threshold_items(selected_market)
            market_policy = HorizonDecisionPolicy(
                thresholds=dict(market_horizon_thresholds),
                min_sample_count=min_sample_count,
            )
            market_test = evaluate_policy(
                models[market_alpha],
                fold.test,
                policy=market_policy,
                costs=costs,
                allow_coin_calibration=True,
            )
            market_test_breakdowns = evaluate_policy_breakdowns(
                models[market_alpha],
                fold.test,
                policy=market_policy,
                costs=costs,
                allow_coin_calibration=True,
            )

        results.append(
            StableRidgeWalkForwardFold(
                fold_index=fold_index,
                train_anchor_count=_anchor_count(fold.train),
                validation_anchor_count=_anchor_count(fold.validation),
                test_anchor_count=_anchor_count(fold.test),
                shared_alpha=shared_alpha,
                market_alpha=market_alpha,
                shared_horizon_thresholds=shared_horizon_thresholds,
                market_horizon_thresholds=market_horizon_thresholds,
                shared_test=shared_test,
                market_test=market_test,
                shared_validation=tuple(shared_candidates),
                market_validation=tuple(market_candidates),
                shared_test_breakdowns=shared_test_breakdowns,
                market_test_breakdowns=market_test_breakdowns,
                stability_blocks=stability_blocks,
                min_block_trades=min_block_trades,
            )
        )

    return StableRidgeWalkForwardReport(folds=tuple(results))
