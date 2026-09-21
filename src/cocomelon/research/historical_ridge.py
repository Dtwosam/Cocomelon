from __future__ import annotations

import importlib
import math
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from cocomelon.domain.features import TrendRegime
from cocomelon.research.historical_baselines import (
    DecisionPolicy,
    DirectionalPrediction,
    ExecutionCostAssumptions,
    PolicyBreakdownEntry,
    PolicyEvaluation,
    TemporalSplit,
    ThresholdCalibration,
    calibrate_no_trade_threshold,
    evaluate_policy,
    evaluate_policy_breakdowns,
    walk_forward_splits,
)
from cocomelon.research.historical_features import (
    BASKET_CONTEXT_FEATURE_NAMES,
    HistoricalFeatureRow,
    HistoricalTrainingRow,
)

ZERO = Decimal("0")

NUMERIC_FEATURES = (
    "return_5m",
    "return_15m",
    "return_1h",
    "return_4h",
    "realized_vol_15m",
    "range_expansion_15m",
    "relative_volume_15m",
    "funding_rate",
    "funding_change",
    "funding_premium",
    "funding_premium_change",
    "funding_age_ms",
    "candle_15m_age_ms",
    *BASKET_CONTEXT_FEATURE_NAMES,
)

TREND_REGIMES = tuple(TrendRegime)


class HistoricalRidgeError(RuntimeError):
    pass


class HistoricalRidgeDependencyError(RuntimeError):
    pass


def _np() -> Any:
    try:
        return importlib.import_module("numpy")
    except ModuleNotFoundError as exc:
        raise HistoricalRidgeDependencyError(
            "numpy is required for historical ridge research; install the research extra"
        ) from exc


def _numeric_value(feature: HistoricalFeatureRow, name: str) -> float | None:
    value = getattr(feature, name)
    if value is None:
        return None
    resolved = float(value)
    if not math.isfinite(resolved):
        raise HistoricalRidgeError(f"feature {name} must be finite")
    return resolved


@dataclass(frozen=True, slots=True)
class RidgeFeatureTransform:
    means: tuple[float, ...]
    scales: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.means) != len(NUMERIC_FEATURES):
            raise ValueError("means must match numeric feature registry")
        if len(self.scales) != len(NUMERIC_FEATURES):
            raise ValueError("scales must match numeric feature registry")
        if any(not math.isfinite(value) for value in self.means):
            raise ValueError("feature means must be finite")
        if any(not math.isfinite(value) or value <= 0 for value in self.scales):
            raise ValueError("feature scales must be positive and finite")

    @classmethod
    def fit(cls, features: Sequence[HistoricalFeatureRow]) -> RidgeFeatureTransform:
        if not features:
            raise HistoricalRidgeError("features must not be empty")
        means: list[float] = []
        scales: list[float] = []
        for name in NUMERIC_FEATURES:
            observed = tuple(
                value
                for feature in features
                if (value := _numeric_value(feature, name)) is not None
            )
            if not observed:
                means.append(0.0)
                scales.append(1.0)
                continue
            mean = sum(observed) / len(observed)
            variance = sum((value - mean) ** 2 for value in observed) / len(observed)
            scale = math.sqrt(variance)
            means.append(mean)
            scales.append(scale if scale > 1e-12 else 1.0)
        return cls(means=tuple(means), scales=tuple(scales))

    @property
    def shared_width(self) -> int:
        return 1 + 2 * len(NUMERIC_FEATURES) + len(TREND_REGIMES)

    def vector(
        self,
        feature: HistoricalFeatureRow,
        *,
        market_names: Sequence[str] = (),
    ) -> tuple[float, ...]:
        values: list[float] = [1.0]
        missing: list[float] = []
        for index, name in enumerate(NUMERIC_FEATURES):
            raw = _numeric_value(feature, name)
            if raw is None:
                values.append(0.0)
                missing.append(1.0)
            else:
                values.append((raw - self.means[index]) / self.scales[index])
                missing.append(0.0)
        values.extend(missing)
        values.extend(
            1.0 if feature.trend_regime is regime else 0.0
            for regime in TREND_REGIMES
        )
        values.extend(
            1.0 if feature.market.canonical == market else 0.0
            for market in market_names
        )
        return tuple(values)


@dataclass(frozen=True, slots=True)
class RidgeHorizonFit:
    horizon_ms: int
    sample_count: int
    transform: RidgeFeatureTransform
    market_names: tuple[str, ...]
    shared_coefficients: tuple[float, ...]
    market_coefficients: tuple[float, ...]

    def __post_init__(self) -> None:
        if self.horizon_ms <= 0:
            raise ValueError("horizon_ms must be positive")
        if self.sample_count <= 0:
            raise ValueError("sample_count must be positive")
        if len(self.shared_coefficients) != self.transform.shared_width:
            raise ValueError("shared coefficient width mismatch")
        expected_market_width = self.transform.shared_width + len(self.market_names)
        if len(self.market_coefficients) != expected_market_width:
            raise ValueError("market coefficient width mismatch")
        if tuple(sorted(set(self.market_names))) != self.market_names:
            raise ValueError("market_names must be sorted and unique")
        if any(not math.isfinite(value) for value in self.shared_coefficients):
            raise ValueError("shared coefficients must be finite")
        if any(not math.isfinite(value) for value in self.market_coefficients):
            raise ValueError("market coefficients must be finite")


@dataclass(frozen=True, slots=True)
class RidgeDirectionalEstimate:
    sample_count: int
    expected_long_return: Decimal
    expected_short_return: Decimal
    horizon_ms: int
    estimate_source: str

    def __post_init__(self) -> None:
        if self.sample_count <= 0:
            raise ValueError("sample_count must be positive")
        if self.horizon_ms <= 0:
            raise ValueError("horizon_ms must be positive")
        if not self.expected_long_return.is_finite():
            raise ValueError("expected_long_return must be finite")
        if not self.expected_short_return.is_finite():
            raise ValueError("expected_short_return must be finite")
        if self.expected_short_return != -self.expected_long_return:
            raise ValueError("ridge long/short estimates must be symmetric")
        if self.estimate_source not in {"shared_ridge", "market_ridge"}:
            raise ValueError("unsupported ridge estimate source")


@dataclass(frozen=True, slots=True)
class RidgeDirectionalModel:
    alpha: Decimal
    min_market_samples: int
    horizons: Mapping[int, RidgeHorizonFit]

    def __post_init__(self) -> None:
        if not self.alpha.is_finite() or self.alpha <= ZERO:
            raise ValueError("alpha must be positive and finite")
        if self.min_market_samples <= 0:
            raise ValueError("min_market_samples must be positive")
        if not self.horizons:
            raise ValueError("horizons must not be empty")

    def predict(
        self,
        feature: HistoricalFeatureRow,
        *,
        horizon_ms: int,
        allow_coin_calibration: bool = True,
    ) -> DirectionalPrediction:
        fitted = self.horizons.get(horizon_ms)
        if fitted is None:
            raise HistoricalRidgeError(f"no fitted ridge model for horizon {horizon_ms}")

        use_market = (
            allow_coin_calibration
            and feature.market.canonical in fitted.market_names
        )
        if use_market:
            vector = fitted.transform.vector(
                feature,
                market_names=fitted.market_names,
            )
            coefficients = fitted.market_coefficients
            source = "market_ridge"
        else:
            vector = fitted.transform.vector(feature)
            coefficients = fitted.shared_coefficients
            source = "shared_ridge"

        predicted = sum(
            coefficient * value
            for coefficient, value in zip(coefficients, vector, strict=True)
        )
        if not math.isfinite(predicted):
            raise HistoricalRidgeError("ridge prediction must be finite")
        long_return = Decimal(str(predicted))
        return RidgeDirectionalEstimate(
            sample_count=fitted.sample_count,
            expected_long_return=long_return,
            expected_short_return=-long_return,
            horizon_ms=horizon_ms,
            estimate_source=source,
        )


def _fit_coefficients(
    vectors: Sequence[Sequence[float]],
    targets: Sequence[float],
    *,
    alpha: Decimal,
) -> tuple[float, ...]:
    if not vectors or not targets or len(vectors) != len(targets):
        raise HistoricalRidgeError("ridge vectors and targets must be non-empty and aligned")
    np = _np()
    matrix = np.asarray(vectors, dtype=float)
    target = np.asarray(targets, dtype=float)
    gram = matrix.T @ matrix
    penalty = np.eye(matrix.shape[1], dtype=float) * float(alpha)
    penalty[0, 0] = 0.0
    rhs = matrix.T @ target
    coefficients = np.linalg.solve(gram + penalty, rhs)
    result = tuple(float(value) for value in coefficients.tolist())
    if any(not math.isfinite(value) for value in result):
        raise HistoricalRidgeError("ridge coefficients must be finite")
    return result


def fit_ridge_directional_model(
    rows: Sequence[HistoricalTrainingRow],
    *,
    alpha: Decimal,
    min_market_samples: int,
) -> RidgeDirectionalModel:
    if not rows:
        raise HistoricalRidgeError("rows must not be empty")
    if not alpha.is_finite() or alpha <= ZERO:
        raise ValueError("alpha must be positive and finite")
    if min_market_samples <= 0:
        raise ValueError("min_market_samples must be positive")

    by_horizon: dict[int, list[HistoricalTrainingRow]] = defaultdict(list)
    for row in rows:
        by_horizon[row.horizon_ms].append(row)

    fits: dict[int, RidgeHorizonFit] = {}
    for horizon_ms in sorted(by_horizon):
        horizon_rows = tuple(
            sorted(
                by_horizon[horizon_ms],
                key=lambda row: (
                    row.anchor_end_ms,
                    row.market.canonical,
                    row.training_row_id,
                ),
            )
        )
        transform = RidgeFeatureTransform.fit(tuple(row.feature for row in horizon_rows))
        market_counts = Counter(row.market.canonical for row in horizon_rows)
        market_names = tuple(
            sorted(
                market
                for market, count in market_counts.items()
                if count >= min_market_samples
            )
        )
        targets = tuple(float(row.long_gross_return) for row in horizon_rows)
        shared_vectors = tuple(transform.vector(row.feature) for row in horizon_rows)
        market_vectors = tuple(
            transform.vector(row.feature, market_names=market_names)
            for row in horizon_rows
        )
        fits[horizon_ms] = RidgeHorizonFit(
            horizon_ms=horizon_ms,
            sample_count=len(horizon_rows),
            transform=transform,
            market_names=market_names,
            shared_coefficients=_fit_coefficients(
                shared_vectors,
                targets,
                alpha=alpha,
            ),
            market_coefficients=_fit_coefficients(
                market_vectors,
                targets,
                alpha=alpha,
            ),
        )

    return RidgeDirectionalModel(
        alpha=alpha,
        min_market_samples=min_market_samples,
        horizons=fits,
    )


@dataclass(frozen=True, slots=True)
class PreparedRidgeFold:
    fold_index: int
    split: TemporalSplit
    models: tuple[tuple[Decimal, RidgeDirectionalModel], ...]

    def __post_init__(self) -> None:
        if self.fold_index <= 0:
            raise ValueError("fold_index must be positive")
        alphas = tuple(alpha for alpha, _model in self.models)
        if not alphas or alphas != tuple(sorted(set(alphas))):
            raise ValueError("prepared ridge models must use sorted unique alphas")

    def model(self, alpha: Decimal) -> RidgeDirectionalModel:
        for candidate, model in self.models:
            if candidate == alpha:
                return model
        raise HistoricalRidgeError(f"prepared ridge alpha missing: {alpha}")


@dataclass(frozen=True, slots=True)
class PreparedRidgeWalkForward:
    candidate_alphas: tuple[Decimal, ...]
    min_market_samples: int
    min_train_anchors: int
    validation_anchors: int
    test_anchors: int
    step_anchors: int
    embargo_anchors: int
    folds: tuple[PreparedRidgeFold, ...]

    def __post_init__(self) -> None:
        if not self.candidate_alphas:
            raise ValueError("candidate_alphas must not be empty")
        if self.candidate_alphas != tuple(sorted(set(self.candidate_alphas))):
            raise ValueError("candidate_alphas must be sorted and unique")
        if any(not alpha.is_finite() or alpha <= ZERO for alpha in self.candidate_alphas):
            raise ValueError("candidate_alphas must be positive finite Decimals")
        if self.min_market_samples <= 0:
            raise ValueError("min_market_samples must be positive")
        for field in (
            "min_train_anchors",
            "validation_anchors",
            "test_anchors",
            "step_anchors",
        ):
            if getattr(self, field) <= 0:
                raise ValueError(f"{field} must be positive")
        if self.embargo_anchors < 0:
            raise ValueError("embargo_anchors must be non-negative")
        if not self.folds:
            raise ValueError("folds must not be empty")


def prepare_ridge_walk_forward(
    rows: Sequence[HistoricalTrainingRow],
    *,
    candidate_alphas: Sequence[Decimal],
    min_train_anchors: int,
    validation_anchors: int,
    test_anchors: int,
    step_anchors: int,
    embargo_anchors: int,
    min_market_samples: int,
) -> PreparedRidgeWalkForward:
    alphas = tuple(sorted(set(candidate_alphas)))
    if not alphas:
        raise ValueError("candidate_alphas must not be empty")
    if any(not alpha.is_finite() or alpha <= ZERO for alpha in alphas):
        raise ValueError("candidate_alphas must be positive finite Decimals")
    if min_market_samples <= 0:
        raise ValueError("min_market_samples must be positive")

    splits = walk_forward_splits(
        rows,
        min_train_anchors=min_train_anchors,
        validation_anchors=validation_anchors,
        test_anchors=test_anchors,
        step_anchors=step_anchors,
        embargo_anchors=embargo_anchors,
    )
    if not splits:
        raise HistoricalRidgeError("walk-forward configuration produced no folds")

    folds = tuple(
        PreparedRidgeFold(
            fold_index=fold_index,
            split=split,
            models=tuple(
                (
                    alpha,
                    fit_ridge_directional_model(
                        split.train,
                        alpha=alpha,
                        min_market_samples=min_market_samples,
                    ),
                )
                for alpha in alphas
            ),
        )
        for fold_index, split in enumerate(splits, start=1)
    )
    return PreparedRidgeWalkForward(
        candidate_alphas=alphas,
        min_market_samples=min_market_samples,
        min_train_anchors=min_train_anchors,
        validation_anchors=validation_anchors,
        test_anchors=test_anchors,
        step_anchors=step_anchors,
        embargo_anchors=embargo_anchors,
        folds=folds,
    )


def validate_prepared_ridge_walk_forward(
    prepared: PreparedRidgeWalkForward,
    *,
    candidate_alphas: Sequence[Decimal],
    min_train_anchors: int,
    validation_anchors: int,
    test_anchors: int,
    step_anchors: int,
    embargo_anchors: int,
    min_market_samples: int,
) -> None:
    expected = (
        tuple(sorted(set(candidate_alphas))),
        min_market_samples,
        min_train_anchors,
        validation_anchors,
        test_anchors,
        step_anchors,
        embargo_anchors,
    )
    actual = (
        prepared.candidate_alphas,
        prepared.min_market_samples,
        prepared.min_train_anchors,
        prepared.validation_anchors,
        prepared.test_anchors,
        prepared.step_anchors,
        prepared.embargo_anchors,
    )
    if actual != expected:
        raise HistoricalRidgeError("prepared ridge walk-forward configuration mismatch")


@dataclass(frozen=True, slots=True)
class RidgeAlphaValidation:
    alpha: Decimal
    calibration: ThresholdCalibration

    def __post_init__(self) -> None:
        if not self.alpha.is_finite() or self.alpha <= ZERO:
            raise ValueError("alpha must be positive and finite")


@dataclass(frozen=True, slots=True)
class RidgeWalkForwardFold:
    fold_index: int
    train_anchor_count: int
    validation_anchor_count: int
    test_anchor_count: int
    shared_alpha: Decimal | None
    market_alpha: Decimal | None
    shared_threshold: Decimal | None
    market_threshold: Decimal | None
    shared_test: PolicyEvaluation
    market_test: PolicyEvaluation
    shared_validation: tuple[RidgeAlphaValidation, ...]
    market_validation: tuple[RidgeAlphaValidation, ...]
    shared_test_breakdowns: tuple[PolicyBreakdownEntry, ...]
    market_test_breakdowns: tuple[PolicyBreakdownEntry, ...]

    def __post_init__(self) -> None:
        if self.fold_index <= 0:
            raise ValueError("fold_index must be positive")
        if not self.shared_validation or not self.market_validation:
            raise ValueError("ridge validation candidates must not be empty")


@dataclass(frozen=True, slots=True)
class RidgeWalkForwardReport:
    folds: tuple[RidgeWalkForwardFold, ...]

    def __post_init__(self) -> None:
        if not self.folds:
            raise ValueError("folds must not be empty")


def _anchor_count(rows: Sequence[HistoricalTrainingRow]) -> int:
    return len({row.anchor_end_ms for row in rows})


def _selected_validation_score(
    candidate: RidgeAlphaValidation,
) -> tuple[Decimal, Decimal, int] | None:
    threshold = candidate.calibration.selected_threshold
    if threshold is None:
        return None
    selected = next(
        (
            item
            for item in candidate.calibration.candidates
            if item.threshold == threshold
        ),
        None,
    )
    if selected is None or selected.mean_realized_net_return is None:
        raise HistoricalRidgeError("selected ridge validation threshold is inconsistent")
    return (
        selected.mean_realized_net_return,
        selected.total_realized_net_return,
        selected.trade_count,
    )


def _choose_alpha(
    candidates: Sequence[RidgeAlphaValidation],
) -> RidgeAlphaValidation | None:
    eligible = tuple(
        (candidate, score)
        for candidate in candidates
        if (score := _selected_validation_score(candidate)) is not None
    )
    if not eligible:
        return None
    return max(
        eligible,
        key=lambda item: (
            item[1][0],
            item[1][1],
            item[1][2],
            -item[0].alpha,
        ),
    )[0]


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


def run_walk_forward_ridge(
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
) -> RidgeWalkForwardReport:
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

    results: list[RidgeWalkForwardFold] = []
    for prepared_fold in resolved.folds:
        fold_index = prepared_fold.fold_index
        fold = prepared_fold.split
        models = dict(prepared_fold.models)
        shared_candidates: list[RidgeAlphaValidation] = []
        market_candidates: list[RidgeAlphaValidation] = []
        for alpha in resolved.candidate_alphas:
            model = models[alpha]
            shared_candidates.append(
                RidgeAlphaValidation(
                    alpha=alpha,
                    calibration=calibrate_no_trade_threshold(
                        model,
                        fold.validation,
                        costs=costs,
                        candidate_thresholds=candidate_thresholds,
                        min_sample_count=min_sample_count,
                        min_validation_trades=min_validation_trades,
                        allow_coin_calibration=False,
                        min_validation_mean_net_return=min_validation_mean_net_return,
                    ),
                )
            )
            market_candidates.append(
                RidgeAlphaValidation(
                    alpha=alpha,
                    calibration=calibrate_no_trade_threshold(
                        model,
                        fold.validation,
                        costs=costs,
                        candidate_thresholds=candidate_thresholds,
                        min_sample_count=min_sample_count,
                        min_validation_trades=min_validation_trades,
                        allow_coin_calibration=True,
                        min_validation_mean_net_return=min_validation_mean_net_return,
                    ),
                )
            )

        selected_shared = _choose_alpha(shared_candidates)
        selected_market = _choose_alpha(market_candidates)
        shared_test_breakdowns: tuple[PolicyBreakdownEntry, ...]
        market_test_breakdowns: tuple[PolicyBreakdownEntry, ...]

        if selected_shared is None:
            shared_test = _abstained_evaluation(fold.test)
            shared_test_breakdowns = ()
            shared_alpha = None
            shared_threshold = None
        else:
            shared_alpha = selected_shared.alpha
            shared_threshold = selected_shared.calibration.selected_threshold
            if shared_threshold is None:
                raise HistoricalRidgeError("selected shared ridge candidate must have threshold")
            shared_policy = DecisionPolicy(
                min_expected_net_edge=shared_threshold,
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
            market_test = _abstained_evaluation(fold.test)
            market_test_breakdowns = ()
            market_alpha = None
            market_threshold = None
        else:
            market_alpha = selected_market.alpha
            market_threshold = selected_market.calibration.selected_threshold
            if market_threshold is None:
                raise HistoricalRidgeError("selected market ridge candidate must have threshold")
            market_policy = DecisionPolicy(
                min_expected_net_edge=market_threshold,
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
            RidgeWalkForwardFold(
                fold_index=fold_index,
                train_anchor_count=_anchor_count(fold.train),
                validation_anchor_count=_anchor_count(fold.validation),
                test_anchor_count=_anchor_count(fold.test),
                shared_alpha=shared_alpha,
                market_alpha=market_alpha,
                shared_threshold=shared_threshold,
                market_threshold=market_threshold,
                shared_test=shared_test,
                market_test=market_test,
                shared_validation=tuple(shared_candidates),
                market_validation=tuple(market_candidates),
                shared_test_breakdowns=shared_test_breakdowns,
                market_test_breakdowns=market_test_breakdowns,
            )
        )

    return RidgeWalkForwardReport(folds=tuple(results))
