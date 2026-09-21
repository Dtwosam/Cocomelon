from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from cocomelon.research.historical_baselines import (
    DecisionPolicy,
    ExecutionCostAssumptions,
    PolicyBreakdownEntry,
    PolicyEvaluation,
    evaluate_policy,
    evaluate_policy_breakdowns,
    walk_forward_splits,
)
from cocomelon.research.historical_features import HistoricalTrainingRow
from cocomelon.research.historical_ridge import (
    HistoricalRidgeError,
    RidgeDirectionalModel,
    fit_ridge_directional_model,
)
from cocomelon.research.historical_ridge_horizon import HorizonDecisionPolicy

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class StableThresholdCandidate:
    threshold: Decimal
    combined: PolicyEvaluation
    segments: tuple[PolicyEvaluation, ...]

    def __post_init__(self) -> None:
        if not self.threshold.is_finite() or self.threshold < ZERO:
            raise ValueError("threshold must be non-negative and finite")
        if not self.segments:
            raise ValueError("segments must not be empty")


@dataclass(frozen=True, slots=True)
class StableHorizonCalibration:
    horizon_ms: int
    selected_threshold: Decimal | None
    candidates: tuple[StableThresholdCandidate, ...]

    def __post_init__(self) -> None:
        if self.horizon_ms <= 0:
            raise ValueError("horizon_ms must be positive")
        if not self.candidates:
            raise ValueError("candidates must not be empty")
        if self.selected_threshold is not None:
            if self.selected_threshold not in {
                item.threshold for item in self.candidates
            }:
                raise ValueError("selected_threshold must come from candidates")


@dataclass(frozen=True, slots=True)
class StableAlphaValidation:
    alpha: Decimal
    horizons: tuple[StableHorizonCalibration, ...]
    combined: PolicyEvaluation

    def __post_init__(self) -> None:
        if not self.alpha.is_finite() or self.alpha <= ZERO:
            raise ValueError("alpha must be positive and finite")
        if not self.horizons:
            raise ValueError("horizons must not be empty")

    @property
    def thresholds(self) -> dict[int, Decimal | None]:
        return {
            item.horizon_ms: item.selected_threshold
            for item in self.horizons
        }


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
    shared_validation: tuple[StableAlphaValidation, ...]
    market_validation: tuple[StableAlphaValidation, ...]
    shared_test_breakdowns: tuple[PolicyBreakdownEntry, ...]
    market_test_breakdowns: tuple[PolicyBreakdownEntry, ...]

    def __post_init__(self) -> None:
        if self.fold_index <= 0:
            raise ValueError("fold_index must be positive")
        for field in (
            "train_anchor_count",
            "validation_anchor_count",
            "test_anchor_count",
        ):
            if getattr(self, field) <= 0:
                raise ValueError(f"{field} must be positive")
        if not self.shared_validation or not self.market_validation:
            raise ValueError("validation candidates must not be empty")


@dataclass(frozen=True, slots=True)
class StableRidgeWalkForwardReport:
    folds: tuple[StableRidgeWalkForwardFold, ...]
    validation_segments: int
    min_segment_validation_trades: int

    def __post_init__(self) -> None:
        if not self.folds:
            raise ValueError("folds must not be empty")
        if self.validation_segments <= 1:
            raise ValueError("validation_segments must be greater than one")
        if self.min_segment_validation_trades <= 0:
            raise ValueError("min_segment_validation_trades must be positive")


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


def _split_validation(
    rows: Sequence[HistoricalTrainingRow],
    *,
    segment_count: int,
) -> tuple[tuple[HistoricalTrainingRow, ...], ...]:
    if segment_count <= 1:
        raise ValueError("segment_count must be greater than one")
    anchors = tuple(sorted({row.anchor_end_ms for row in rows}))
    if len(anchors) < segment_count:
        raise HistoricalRidgeError(
            "validation anchors must cover every stability segment"
        )
    base, remainder = divmod(len(anchors), segment_count)
    cursor = 0
    segments: list[tuple[HistoricalTrainingRow, ...]] = []
    ordered = tuple(
        sorted(
            rows,
            key=lambda row: (
                row.anchor_end_ms,
                row.market.canonical,
                row.horizon_ms,
                row.training_row_id,
            ),
        )
    )
    for index in range(segment_count):
        width = base + (1 if index < remainder else 0)
        segment_anchors = set(anchors[cursor : cursor + width])
        cursor += width
        segments.append(
            tuple(row for row in ordered if row.anchor_end_ms in segment_anchors)
        )
    return tuple(segments)


def _positive_mean(
    evaluation: PolicyEvaluation,
    *,
    min_trades: int,
    floor: Decimal,
) -> bool:
    return (
        evaluation.trade_count >= min_trades
        and evaluation.mean_realized_net_return is not None
        and evaluation.mean_realized_net_return > floor
    )


def _candidate_score(
    candidate: StableThresholdCandidate,
) -> tuple[Decimal, Decimal, Decimal, int, Decimal]:
    segment_means = tuple(
        segment.mean_realized_net_return
        for segment in candidate.segments
    )
    if (
        candidate.combined.mean_realized_net_return is None
        or any(value is None for value in segment_means)
    ):
        raise HistoricalRidgeError("stable candidate score requires realized means")
    resolved = tuple(value for value in segment_means if value is not None)
    return (
        min(resolved),
        candidate.combined.mean_realized_net_return,
        candidate.combined.total_realized_net_return,
        candidate.combined.trade_count,
        -candidate.threshold,
    )


def _calibrate_stable_horizon(
    model: RidgeDirectionalModel,
    horizon_rows: Sequence[HistoricalTrainingRow],
    horizon_segments: Sequence[Sequence[HistoricalTrainingRow]],
    *,
    costs: ExecutionCostAssumptions,
    candidate_thresholds: Sequence[Decimal],
    min_sample_count: int,
    min_validation_trades: int,
    min_segment_validation_trades: int,
    allow_coin_calibration: bool,
    min_validation_mean_net_return: Decimal,
) -> StableHorizonCalibration:
    if not horizon_rows:
        raise HistoricalRidgeError("horizon validation rows must not be empty")
    candidates: list[StableThresholdCandidate] = []
    eligible: list[StableThresholdCandidate] = []
    for threshold in tuple(sorted(set(candidate_thresholds))):
        policy = DecisionPolicy(
            min_expected_net_edge=threshold,
            min_sample_count=min_sample_count,
        )
        combined = evaluate_policy(
            model,
            horizon_rows,
            policy=policy,
            costs=costs,
            allow_coin_calibration=allow_coin_calibration,
        )
        segments = tuple(
            evaluate_policy(
                model,
                segment,
                policy=policy,
                costs=costs,
                allow_coin_calibration=allow_coin_calibration,
            )
            for segment in horizon_segments
        )
        candidate = StableThresholdCandidate(
            threshold=threshold,
            combined=combined,
            segments=segments,
        )
        candidates.append(candidate)
        if (
            _positive_mean(
                combined,
                min_trades=min_validation_trades,
                floor=min_validation_mean_net_return,
            )
            and all(
                _positive_mean(
                    segment,
                    min_trades=min_segment_validation_trades,
                    floor=min_validation_mean_net_return,
                )
                for segment in segments
            )
        ):
            eligible.append(candidate)

    selected = max(eligible, key=_candidate_score) if eligible else None
    horizon_ms = horizon_rows[0].horizon_ms
    if any(row.horizon_ms != horizon_ms for row in horizon_rows):
        raise HistoricalRidgeError("stable horizon calibration received mixed horizons")
    return StableHorizonCalibration(
        horizon_ms=horizon_ms,
        selected_threshold=None if selected is None else selected.threshold,
        candidates=tuple(candidates),
    )


def _calibrate_alpha(
    model: RidgeDirectionalModel,
    validation_rows: Sequence[HistoricalTrainingRow],
    *,
    alpha: Decimal,
    costs: ExecutionCostAssumptions,
    candidate_thresholds: Sequence[Decimal],
    validation_segments: int,
    min_sample_count: int,
    min_validation_trades: int,
    min_segment_validation_trades: int,
    allow_coin_calibration: bool,
    min_validation_mean_net_return: Decimal,
) -> StableAlphaValidation:
    segments = _split_validation(
        validation_rows,
        segment_count=validation_segments,
    )
    horizons: list[StableHorizonCalibration] = []
    for horizon_ms in sorted({row.horizon_ms for row in validation_rows}):
        horizon_rows = tuple(
            row for row in validation_rows if row.horizon_ms == horizon_ms
        )
        horizon_segments = tuple(
            tuple(row for row in segment if row.horizon_ms == horizon_ms)
            for segment in segments
        )
        horizons.append(
            _calibrate_stable_horizon(
                model,
                horizon_rows,
                horizon_segments,
                costs=costs,
                candidate_thresholds=candidate_thresholds,
                min_sample_count=min_sample_count,
                min_validation_trades=min_validation_trades,
                min_segment_validation_trades=min_segment_validation_trades,
                allow_coin_calibration=allow_coin_calibration,
                min_validation_mean_net_return=min_validation_mean_net_return,
            )
        )

    resolved = tuple(horizons)
    policy = HorizonDecisionPolicy(
        thresholds={
            item.horizon_ms: item.selected_threshold
            for item in resolved
        },
        min_sample_count=min_sample_count,
    )
    combined = evaluate_policy(
        model,
        validation_rows,
        policy=policy,
        costs=costs,
        allow_coin_calibration=allow_coin_calibration,
    )
    return StableAlphaValidation(
        alpha=alpha,
        horizons=resolved,
        combined=combined,
    )


def _selected_horizon_worst_mean(
    value: StableAlphaValidation,
) -> Decimal | None:
    worst: list[Decimal] = []
    for horizon in value.horizons:
        if horizon.selected_threshold is None:
            continue
        candidate = next(
            item
            for item in horizon.candidates
            if item.threshold == horizon.selected_threshold
        )
        for segment in candidate.segments:
            if segment.mean_realized_net_return is None:
                return None
            worst.append(segment.mean_realized_net_return)
    return min(worst) if worst else None


def _alpha_score(
    item: tuple[StableAlphaValidation, Decimal],
) -> tuple[Decimal, Decimal, Decimal, int, Decimal]:
    candidate, worst_mean = item
    mean_return = candidate.combined.mean_realized_net_return
    if mean_return is None:
        raise HistoricalRidgeError("stable alpha score requires realized mean")
    return (
        worst_mean,
        mean_return,
        candidate.combined.total_realized_net_return,
        candidate.combined.trade_count,
        -candidate.alpha,
    )


def _choose_alpha(
    candidates: Sequence[StableAlphaValidation],
    *,
    min_validation_trades: int,
    min_validation_mean_net_return: Decimal,
) -> StableAlphaValidation | None:
    eligible: list[tuple[StableAlphaValidation, Decimal]] = []
    for candidate in candidates:
        worst_mean = _selected_horizon_worst_mean(candidate)
        if (
            worst_mean is not None
            and _positive_mean(
                candidate.combined,
                min_trades=min_validation_trades,
                floor=min_validation_mean_net_return,
            )
            and worst_mean > min_validation_mean_net_return
        ):
            eligible.append((candidate, worst_mean))
    if not eligible:
        return None
    return max(eligible, key=_alpha_score)[0]


def _threshold_items(
    candidate: StableAlphaValidation,
) -> tuple[tuple[int, Decimal | None], ...]:
    return tuple(
        (item.horizon_ms, item.selected_threshold)
        for item in candidate.horizons
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
    validation_segments: int,
    min_segment_validation_trades: int,
    min_validation_mean_net_return: Decimal = ZERO,
) -> StableRidgeWalkForwardReport:
    alphas = tuple(sorted(set(candidate_alphas)))
    if not alphas:
        raise ValueError("candidate_alphas must not be empty")
    if any(not alpha.is_finite() or alpha <= ZERO for alpha in alphas):
        raise ValueError("candidate_alphas must be positive finite Decimals")
    if validation_segments <= 1:
        raise ValueError("validation_segments must be greater than one")
    if min_segment_validation_trades <= 0:
        raise ValueError("min_segment_validation_trades must be positive")

    folds = walk_forward_splits(
        rows,
        min_train_anchors=min_train_anchors,
        validation_anchors=validation_anchors,
        test_anchors=test_anchors,
        step_anchors=step_anchors,
        embargo_anchors=embargo_anchors,
    )
    if not folds:
        raise HistoricalRidgeError("walk-forward configuration produced no folds")

    results: list[StableRidgeWalkForwardFold] = []
    for fold_index, fold in enumerate(folds, start=1):
        models: dict[Decimal, RidgeDirectionalModel] = {}
        shared_candidates: list[StableAlphaValidation] = []
        market_candidates: list[StableAlphaValidation] = []
        for alpha in alphas:
            model = fit_ridge_directional_model(
                fold.train,
                alpha=alpha,
                min_market_samples=min_market_samples,
            )
            models[alpha] = model
            shared_candidates.append(
                _calibrate_alpha(
                    model,
                    fold.validation,
                    alpha=alpha,
                    costs=costs,
                    candidate_thresholds=candidate_thresholds,
                    validation_segments=validation_segments,
                    min_sample_count=min_sample_count,
                    min_validation_trades=min_validation_trades,
                    min_segment_validation_trades=min_segment_validation_trades,
                    allow_coin_calibration=False,
                    min_validation_mean_net_return=min_validation_mean_net_return,
                )
            )
            market_candidates.append(
                _calibrate_alpha(
                    model,
                    fold.validation,
                    alpha=alpha,
                    costs=costs,
                    candidate_thresholds=candidate_thresholds,
                    validation_segments=validation_segments,
                    min_sample_count=min_sample_count,
                    min_validation_trades=min_validation_trades,
                    min_segment_validation_trades=min_segment_validation_trades,
                    allow_coin_calibration=True,
                    min_validation_mean_net_return=min_validation_mean_net_return,
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

        shared_thresholds: tuple[tuple[int, Decimal | None], ...]
        market_thresholds: tuple[tuple[int, Decimal | None], ...]
        shared_breakdowns: tuple[PolicyBreakdownEntry, ...]
        market_breakdowns: tuple[PolicyBreakdownEntry, ...]

        if selected_shared is None:
            shared_alpha = None
            shared_thresholds = ()
            shared_test = _abstained_evaluation(fold.test)
            shared_breakdowns = ()
        else:
            shared_alpha = selected_shared.alpha
            shared_thresholds = _threshold_items(selected_shared)
            shared_policy = HorizonDecisionPolicy(
                thresholds=dict(shared_thresholds),
                min_sample_count=min_sample_count,
            )
            shared_test = evaluate_policy(
                models[shared_alpha],
                fold.test,
                policy=shared_policy,
                costs=costs,
                allow_coin_calibration=False,
            )
            shared_breakdowns = evaluate_policy_breakdowns(
                models[shared_alpha],
                fold.test,
                policy=shared_policy,
                costs=costs,
                allow_coin_calibration=False,
            )

        if selected_market is None:
            market_alpha = None
            market_thresholds = ()
            market_test = _abstained_evaluation(fold.test)
            market_breakdowns = ()
        else:
            market_alpha = selected_market.alpha
            market_thresholds = _threshold_items(selected_market)
            market_policy = HorizonDecisionPolicy(
                thresholds=dict(market_thresholds),
                min_sample_count=min_sample_count,
            )
            market_test = evaluate_policy(
                models[market_alpha],
                fold.test,
                policy=market_policy,
                costs=costs,
                allow_coin_calibration=True,
            )
            market_breakdowns = evaluate_policy_breakdowns(
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
                shared_horizon_thresholds=shared_thresholds,
                market_horizon_thresholds=market_thresholds,
                shared_test=shared_test,
                market_test=market_test,
                shared_validation=tuple(shared_candidates),
                market_validation=tuple(market_candidates),
                shared_test_breakdowns=shared_breakdowns,
                market_test_breakdowns=market_breakdowns,
            )
        )

    return StableRidgeWalkForwardReport(
        folds=tuple(results),
        validation_segments=validation_segments,
        min_segment_validation_trades=min_segment_validation_trades,
    )
