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
    DirectionalPrediction,
    ExecutionCostAssumptions,
    PolicyBreakdownEntry,
    PolicyEvaluation,
    evaluate_policy,
    evaluate_predicted_policy,
    evaluate_predicted_policy_breakdowns,
    predict_training_rows,
    walk_forward_splits,
)
from cocomelon.research.historical_features import (
    HistoricalFeatureRow,
    HistoricalTrainingRow,
)
from cocomelon.research.historical_ridge import NUMERIC_FEATURES
from cocomelon.research.historical_ridge_horizon import HorizonDecisionPolicy
from cocomelon.research.historical_ridge_stability import (
    StableHorizonCalibration,
    calibrate_stable_no_trade_threshold,
)

ZERO = Decimal("0")
TREND_REGIMES = tuple(TrendRegime)


class HistoricalTreeError(RuntimeError):
    pass


class HistoricalTreeDependencyError(RuntimeError):
    pass


def _hist_gradient_boosting_regressor() -> Any:
    try:
        ensemble = importlib.import_module("sklearn.ensemble")
    except ModuleNotFoundError as exc:
        raise HistoricalTreeDependencyError(
            "scikit-learn is required for historical tree research; "
            "install the research extra"
        ) from exc
    return ensemble.HistGradientBoostingRegressor


def _numeric_value(feature: HistoricalFeatureRow, name: str) -> float:
    value = getattr(feature, name)
    if value is None:
        return math.nan
    resolved = float(value)
    if not math.isfinite(resolved):
        raise HistoricalTreeError(f"feature {name} must be finite")
    return resolved


@dataclass(frozen=True, slots=True)
class TreeModelConfig:
    max_leaf_nodes: int = 7
    min_samples_leaf: int = 100
    learning_rate: Decimal = Decimal("0.05")
    max_iter: int = 100
    l2_regularization: Decimal = Decimal("1")

    def __post_init__(self) -> None:
        if self.max_leaf_nodes < 2:
            raise ValueError("max_leaf_nodes must be at least 2")
        if self.min_samples_leaf <= 0:
            raise ValueError("min_samples_leaf must be positive")
        if not self.learning_rate.is_finite() or self.learning_rate <= ZERO:
            raise ValueError("learning_rate must be positive and finite")
        if self.max_iter <= 0:
            raise ValueError("max_iter must be positive")
        if not self.l2_regularization.is_finite() or self.l2_regularization < ZERO:
            raise ValueError("l2_regularization must be non-negative and finite")

    def to_dict(self) -> dict[str, object]:
        return {
            "max_leaf_nodes": self.max_leaf_nodes,
            "min_samples_leaf": self.min_samples_leaf,
            "learning_rate": str(self.learning_rate),
            "max_iter": self.max_iter,
            "l2_regularization": str(self.l2_regularization),
            "early_stopping": False,
        }


@dataclass(frozen=True, slots=True)
class TreeFeatureEncoder:
    market_names: tuple[str, ...]
    numeric_features: tuple[str, ...]

    def __post_init__(self) -> None:
        if tuple(sorted(set(self.market_names))) != self.market_names:
            raise ValueError("market_names must be sorted and unique")
        allowed = set(NUMERIC_FEATURES)
        if len(set(self.numeric_features)) != len(self.numeric_features):
            raise ValueError("numeric_features must be unique")
        if any(name not in allowed for name in self.numeric_features):
            raise ValueError("numeric_features must come from the supervised registry")
        expected_order = tuple(
            name for name in NUMERIC_FEATURES if name in set(self.numeric_features)
        )
        if self.numeric_features != expected_order:
            raise ValueError("numeric_features must preserve supervised registry order")

    def vector(
        self,
        feature: HistoricalFeatureRow,
        *,
        include_market: bool,
    ) -> tuple[float, ...]:
        values = [_numeric_value(feature, name) for name in self.numeric_features]
        values.extend(
            1.0 if feature.trend_regime is regime else 0.0
            for regime in TREND_REGIMES
        )
        if include_market:
            values.extend(
                1.0 if feature.market.canonical == market else 0.0
                for market in self.market_names
            )
        return tuple(values)


@dataclass(frozen=True, slots=True)
class TreeHorizonFit:
    horizon_ms: int
    sample_count: int
    encoder: TreeFeatureEncoder
    shared_estimator: Any
    market_estimator: Any

    def __post_init__(self) -> None:
        if self.horizon_ms <= 0:
            raise ValueError("horizon_ms must be positive")
        if self.sample_count <= 0:
            raise ValueError("sample_count must be positive")


@dataclass(frozen=True, slots=True)
class TreeDirectionalEstimate:
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
        if self.expected_short_return != -self.expected_long_return:
            raise ValueError("tree long/short estimates must be symmetric")
        if self.estimate_source not in {"shared_tree", "market_tree"}:
            raise ValueError("unsupported tree estimate source")


@dataclass(frozen=True, slots=True)
class TreeDirectionalModel:
    config: TreeModelConfig
    min_market_samples: int
    horizons: Mapping[int, TreeHorizonFit]

    def __post_init__(self) -> None:
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
            raise HistoricalTreeError(f"no fitted tree model for horizon {horizon_ms}")

        use_market = (
            allow_coin_calibration
            and feature.market.canonical in fitted.encoder.market_names
        )
        if use_market:
            estimator = fitted.market_estimator
            vector = fitted.encoder.vector(feature, include_market=True)
            source = "market_tree"
        else:
            estimator = fitted.shared_estimator
            vector = fitted.encoder.vector(feature, include_market=False)
            source = "shared_tree"

        prediction = estimator.predict([vector])
        value = float(prediction[0])
        if not math.isfinite(value):
            raise HistoricalTreeError("tree prediction must be finite")
        long_return = Decimal(str(value))
        return TreeDirectionalEstimate(
            sample_count=fitted.sample_count,
            expected_long_return=long_return,
            expected_short_return=-long_return,
            horizon_ms=horizon_ms,
            estimate_source=source,
        )


def _fit_estimator(
    vectors: Sequence[Sequence[float]],
    targets: Sequence[float],
    *,
    config: TreeModelConfig,
) -> Any:
    if not vectors or len(vectors) != len(targets):
        raise HistoricalTreeError("tree vectors and targets must be non-empty and aligned")
    regressor = _hist_gradient_boosting_regressor()
    estimator = regressor(
        loss="squared_error",
        learning_rate=float(config.learning_rate),
        max_iter=config.max_iter,
        max_leaf_nodes=config.max_leaf_nodes,
        min_samples_leaf=config.min_samples_leaf,
        l2_regularization=float(config.l2_regularization),
        early_stopping=False,
    )
    estimator.fit(vectors, targets)
    return estimator


def fit_tree_directional_model(
    rows: Sequence[HistoricalTrainingRow],
    *,
    config: TreeModelConfig,
    min_market_samples: int,
) -> TreeDirectionalModel:
    if not rows:
        raise HistoricalTreeError("rows must not be empty")
    if min_market_samples <= 0:
        raise ValueError("min_market_samples must be positive")

    by_horizon: dict[int, list[HistoricalTrainingRow]] = defaultdict(list)
    for row in rows:
        by_horizon[row.horizon_ms].append(row)

    fits: dict[int, TreeHorizonFit] = {}
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
        market_counts = Counter(row.market.canonical for row in horizon_rows)
        market_names = tuple(
            sorted(
                market
                for market, count in market_counts.items()
                if count >= min_market_samples
            )
        )
        numeric_features = tuple(
            name
            for name in NUMERIC_FEATURES
            if any(
                getattr(row.feature, name) is not None
                for row in horizon_rows
            )
        )
        encoder = TreeFeatureEncoder(
            market_names=market_names,
            numeric_features=numeric_features,
        )
        targets = tuple(float(row.long_gross_return) for row in horizon_rows)
        shared_vectors = tuple(
            encoder.vector(row.feature, include_market=False)
            for row in horizon_rows
        )
        market_vectors = tuple(
            encoder.vector(row.feature, include_market=True)
            for row in horizon_rows
        )
        fits[horizon_ms] = TreeHorizonFit(
            horizon_ms=horizon_ms,
            sample_count=len(horizon_rows),
            encoder=encoder,
            shared_estimator=_fit_estimator(
                shared_vectors,
                targets,
                config=config,
            ),
            market_estimator=_fit_estimator(
                market_vectors,
                targets,
                config=config,
            ),
        )

    return TreeDirectionalModel(
        config=config,
        min_market_samples=min_market_samples,
        horizons=fits,
    )


@dataclass(frozen=True, slots=True)
class StableTreeValidation:
    horizons: tuple[StableHorizonCalibration, ...]
    evaluation: PolicyEvaluation

    def __post_init__(self) -> None:
        if not self.horizons:
            raise ValueError("horizon calibrations must not be empty")
        actual = tuple(item.horizon_ms for item in self.horizons)
        if actual != tuple(sorted(set(actual))):
            raise ValueError("horizon calibrations must be sorted and unique")


@dataclass(frozen=True, slots=True)
class StableTreeWalkForwardFold:
    fold_index: int
    train_anchor_count: int
    validation_anchor_count: int
    test_anchor_count: int
    shared_horizon_thresholds: tuple[tuple[int, Decimal | None], ...]
    market_horizon_thresholds: tuple[tuple[int, Decimal | None], ...]
    shared_validation: StableTreeValidation
    market_validation: StableTreeValidation
    shared_test: PolicyEvaluation
    market_test: PolicyEvaluation
    shared_test_breakdowns: tuple[PolicyBreakdownEntry, ...]
    market_test_breakdowns: tuple[PolicyBreakdownEntry, ...]
    stability_blocks: int
    min_block_trades: int

    def __post_init__(self) -> None:
        if self.fold_index <= 0:
            raise ValueError("fold_index must be positive")
        if self.stability_blocks <= 1:
            raise ValueError("stability_blocks must be greater than one")
        if self.min_block_trades <= 0:
            raise ValueError("min_block_trades must be positive")


@dataclass(frozen=True, slots=True)
class StableTreeWalkForwardReport:
    config: TreeModelConfig
    folds: tuple[StableTreeWalkForwardFold, ...]

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
    model: TreeDirectionalModel,
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
) -> StableTreeValidation:
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
    return StableTreeValidation(
        horizons=resolved,
        evaluation=evaluation,
    )


def _threshold_items(
    validation: StableTreeValidation,
) -> tuple[tuple[int, Decimal | None], ...]:
    return tuple(
        (item.horizon_ms, item.calibration.selected_threshold)
        for item in validation.horizons
    )


def _has_eligible_horizon(validation: StableTreeValidation) -> bool:
    return any(
        item.calibration.selected_threshold is not None
        for item in validation.horizons
    )


def calibrate_final_stable_tree(
    fit_rows: Sequence[HistoricalTrainingRow],
    calibration_rows: Sequence[HistoricalTrainingRow],
    *,
    config: TreeModelConfig,
    costs: ExecutionCostAssumptions,
    candidate_thresholds: Sequence[Decimal],
    min_market_samples: int,
    min_sample_count: int,
    min_validation_trades: int,
    stability_blocks: int,
    min_block_trades: int,
    allow_coin_calibration: bool,
    min_validation_mean_net_return: Decimal = ZERO,
) -> StableTreeValidation:
    if not fit_rows or not calibration_rows:
        raise ValueError("fit_rows and calibration_rows must not be empty")
    model = fit_tree_directional_model(
        fit_rows,
        config=config,
        min_market_samples=min_market_samples,
    )
    return _calibrate_horizons(
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


def run_walk_forward_stable_tree(
    rows: Sequence[HistoricalTrainingRow],
    *,
    config: TreeModelConfig,
    costs: ExecutionCostAssumptions,
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
) -> StableTreeWalkForwardReport:
    folds = walk_forward_splits(
        rows,
        min_train_anchors=min_train_anchors,
        validation_anchors=validation_anchors,
        test_anchors=test_anchors,
        step_anchors=step_anchors,
        embargo_anchors=embargo_anchors,
    )
    if not folds:
        raise HistoricalTreeError("walk-forward configuration produced no folds")

    results: list[StableTreeWalkForwardFold] = []
    for fold_index, fold in enumerate(folds, start=1):
        model = fit_tree_directional_model(
            fold.train,
            config=config,
            min_market_samples=min_market_samples,
        )
        shared_validation = _calibrate_horizons(
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
        market_validation = _calibrate_horizons(
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

        shared_thresholds = _threshold_items(shared_validation)
        market_thresholds = _threshold_items(market_validation)
        shared_test_breakdowns: tuple[PolicyBreakdownEntry, ...]
        market_test_breakdowns: tuple[PolicyBreakdownEntry, ...]

        if not _has_eligible_horizon(shared_validation):
            shared_test = _abstained_evaluation(fold.test)
            shared_test_breakdowns = ()
        else:
            shared_policy = HorizonDecisionPolicy(
                thresholds=dict(shared_thresholds),
                min_sample_count=min_sample_count,
            )
            shared_predictions = predict_training_rows(
                model,
                fold.test,
                allow_coin_calibration=False,
            )
            shared_test = evaluate_predicted_policy(
                shared_predictions,
                policy=shared_policy,
                costs=costs,
            )
            shared_test_breakdowns = evaluate_predicted_policy_breakdowns(
                shared_predictions,
                policy=shared_policy,
                costs=costs,
            )

        if not _has_eligible_horizon(market_validation):
            market_test = _abstained_evaluation(fold.test)
            market_test_breakdowns = ()
        else:
            market_policy = HorizonDecisionPolicy(
                thresholds=dict(market_thresholds),
                min_sample_count=min_sample_count,
            )
            market_predictions = predict_training_rows(
                model,
                fold.test,
                allow_coin_calibration=True,
            )
            market_test = evaluate_predicted_policy(
                market_predictions,
                policy=market_policy,
                costs=costs,
            )
            market_test_breakdowns = evaluate_predicted_policy_breakdowns(
                market_predictions,
                policy=market_policy,
                costs=costs,
            )

        results.append(
            StableTreeWalkForwardFold(
                fold_index=fold_index,
                train_anchor_count=_anchor_count(fold.train),
                validation_anchor_count=_anchor_count(fold.validation),
                test_anchor_count=_anchor_count(fold.test),
                shared_horizon_thresholds=shared_thresholds,
                market_horizon_thresholds=market_thresholds,
                shared_validation=shared_validation,
                market_validation=market_validation,
                shared_test=shared_test,
                market_test=market_test,
                shared_test_breakdowns=shared_test_breakdowns,
                market_test_breakdowns=market_test_breakdowns,
                stability_blocks=stability_blocks,
                min_block_trades=min_block_trades,
            )
        )

    return StableTreeWalkForwardReport(
        config=config,
        folds=tuple(results),
    )
