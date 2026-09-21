from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from cocomelon.research.historical_baselines import (
    DecisionAction,
    DecisionPolicy,
    DirectionalDecision,
    DirectionalPrediction,
    ExecutionCostAssumptions,
    PolicyBreakdownEntry,
    PolicyEvaluation,
    ThresholdCalibration,
    calibrate_no_trade_threshold,
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

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class HorizonDecisionPolicy:
    thresholds: Mapping[int, Decimal | None]
    min_sample_count: int

    def __post_init__(self) -> None:
        if not self.thresholds:
            raise ValueError("thresholds must not be empty")
        if self.min_sample_count <= 0:
            raise ValueError("min_sample_count must be positive")
        for horizon_ms, threshold in self.thresholds.items():
            if horizon_ms <= 0:
                raise ValueError("horizon keys must be positive")
            if threshold is not None:
                if not threshold.is_finite() or threshold < ZERO:
                    raise ValueError("horizon thresholds must be non-negative finite Decimals")

    def decide(
        self,
        estimate: DirectionalPrediction,
        *,
        costs: ExecutionCostAssumptions,
    ) -> DirectionalDecision:
        threshold = self.thresholds.get(estimate.horizon_ms)
        if threshold is not None:
            return DecisionPolicy(
                min_expected_net_edge=threshold,
                min_sample_count=self.min_sample_count,
            ).decide(estimate, costs=costs)

        cost_fraction = costs.total_cost_fraction(estimate.horizon_ms)
        return DirectionalDecision(
            action=DecisionAction.NO_TRADE,
            expected_long_net_return=estimate.expected_long_return - cost_fraction,
            expected_short_net_return=estimate.expected_short_return - cost_fraction,
            cost_fraction=cost_fraction,
            min_expected_net_edge=ZERO,
            sample_count=estimate.sample_count,
            estimate_source=estimate.estimate_source,
        )


@dataclass(frozen=True, slots=True)
class HorizonThresholdCalibration:
    horizon_ms: int
    calibration: ThresholdCalibration

    def __post_init__(self) -> None:
        if self.horizon_ms <= 0:
            raise ValueError("horizon_ms must be positive")


@dataclass(frozen=True, slots=True)
class RidgeHorizonAlphaValidation:
    alpha: Decimal
    horizons: tuple[HorizonThresholdCalibration, ...]
    evaluation: PolicyEvaluation

    def __post_init__(self) -> None:
        if not self.alpha.is_finite() or self.alpha <= ZERO:
            raise ValueError("alpha must be positive and finite")
        if not self.horizons:
            raise ValueError("horizon calibrations must not be empty")
        actual = tuple(item.horizon_ms for item in self.horizons)
        if actual != tuple(sorted(set(actual))):
            raise ValueError("horizon calibrations must be sorted and unique")

    @property
    def thresholds(self) -> dict[int, Decimal | None]:
        return {
            item.horizon_ms: item.calibration.selected_threshold
            for item in self.horizons
        }


@dataclass(frozen=True, slots=True)
class RidgeHorizonWalkForwardFold:
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
    shared_validation: tuple[RidgeHorizonAlphaValidation, ...]
    market_validation: tuple[RidgeHorizonAlphaValidation, ...]
    shared_test_breakdowns: tuple[PolicyBreakdownEntry, ...]
    market_test_breakdowns: tuple[PolicyBreakdownEntry, ...]

    def __post_init__(self) -> None:
        if self.fold_index <= 0:
            raise ValueError("fold_index must be positive")
        if not self.shared_validation or not self.market_validation:
            raise ValueError("ridge horizon validation candidates must not be empty")
        for field in ("train_anchor_count", "validation_anchor_count", "test_anchor_count"):
            if getattr(self, field) <= 0:
                raise ValueError(f"{field} must be positive")


@dataclass(frozen=True, slots=True)
class RidgeHorizonWalkForwardReport:
    folds: tuple[RidgeHorizonWalkForwardFold, ...]

    def __post_init__(self) -> None:
        if not self.folds:
            raise ValueError("folds must not be empty")


def _anchor_count(rows: Sequence[HistoricalTrainingRow]) -> int:
    return len({row.anchor_end_ms for row in rows})


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


def _calibrate_horizons(
    model: RidgeDirectionalModel,
    validation_rows: Sequence[HistoricalTrainingRow],
    *,
    costs: ExecutionCostAssumptions,
    candidate_thresholds: Sequence[Decimal],
    min_sample_count: int,
    min_validation_trades: int,
    allow_coin_calibration: bool,
    min_validation_mean_net_return: Decimal,
) -> tuple[tuple[HorizonThresholdCalibration, ...], PolicyEvaluation]:
    horizons: list[HorizonThresholdCalibration] = []
    for horizon_ms in sorted({row.horizon_ms for row in validation_rows}):
        horizon_rows = tuple(
            row for row in validation_rows if row.horizon_ms == horizon_ms
        )
        calibration = calibrate_no_trade_threshold(
            model,
            horizon_rows,
            costs=costs,
            candidate_thresholds=candidate_thresholds,
            min_sample_count=min_sample_count,
            min_validation_trades=min_validation_trades,
            allow_coin_calibration=allow_coin_calibration,
            min_validation_mean_net_return=min_validation_mean_net_return,
            abstain_on_insufficient_validation_trades=True,
        )
        horizons.append(
            HorizonThresholdCalibration(
                horizon_ms=horizon_ms,
                calibration=calibration,
            )
        )

    resolved = tuple(horizons)
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
    candidates: Sequence[RidgeHorizonAlphaValidation],
    *,
    min_validation_trades: int,
    min_validation_mean_net_return: Decimal,
) -> RidgeHorizonAlphaValidation | None:
    eligible = tuple(
        candidate
        for candidate in candidates
        if candidate.evaluation.trade_count >= min_validation_trades
        and candidate.evaluation.mean_realized_net_return is not None
        and candidate.evaluation.mean_realized_net_return > min_validation_mean_net_return
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
    candidate: RidgeHorizonAlphaValidation,
) -> tuple[tuple[int, Decimal | None], ...]:
    return tuple(
        (item.horizon_ms, item.calibration.selected_threshold)
        for item in candidate.horizons
    )


def run_walk_forward_horizon_calibrated_ridge(
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
    min_validation_mean_net_return: Decimal = ZERO,
    prepared: PreparedRidgeWalkForward | None = None,
) -> RidgeHorizonWalkForwardReport:
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

    results: list[RidgeHorizonWalkForwardFold] = []
    for prepared_fold in resolved.folds:
        fold_index = prepared_fold.fold_index
        fold = prepared_fold.split
        models = dict(prepared_fold.models)
        shared_candidates: list[RidgeHorizonAlphaValidation] = []
        market_candidates: list[RidgeHorizonAlphaValidation] = []

        for alpha in resolved.candidate_alphas:
            model = models[alpha]

            shared_horizons, shared_validation = _calibrate_horizons(
                model,
                fold.validation,
                costs=costs,
                candidate_thresholds=candidate_thresholds,
                min_sample_count=min_sample_count,
                min_validation_trades=min_validation_trades,
                allow_coin_calibration=False,
                min_validation_mean_net_return=min_validation_mean_net_return,
            )
            shared_candidates.append(
                RidgeHorizonAlphaValidation(
                    alpha=alpha,
                    horizons=shared_horizons,
                    evaluation=shared_validation,
                )
            )

            market_horizons, market_validation = _calibrate_horizons(
                model,
                fold.validation,
                costs=costs,
                candidate_thresholds=candidate_thresholds,
                min_sample_count=min_sample_count,
                min_validation_trades=min_validation_trades,
                allow_coin_calibration=True,
                min_validation_mean_net_return=min_validation_mean_net_return,
            )
            market_candidates.append(
                RidgeHorizonAlphaValidation(
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
        shared_horizon_thresholds: tuple[tuple[int, Decimal | None], ...]
        market_horizon_thresholds: tuple[tuple[int, Decimal | None], ...]

        if selected_shared is None:
            shared_alpha = None
            shared_horizon_thresholds = ()
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
            market_horizon_thresholds = ()
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
            RidgeHorizonWalkForwardFold(
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
            )
        )

    return RidgeHorizonWalkForwardReport(folds=tuple(results))
