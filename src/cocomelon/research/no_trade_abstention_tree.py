from __future__ import annotations

import hashlib
import importlib
import json
import math
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Final, cast

from cocomelon.domain.features import TrendRegime, VolatilityRegime
from cocomelon.domain.strategy import Direction
from cocomelon.research.continuous_paper_decision_facts import (
    ContinuousPaperDecisionFactStore,
)
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotStore,
)
from cocomelon.research.no_trade_forward_opportunity import (
    NO_TRADE_FORWARD_SCHEMA_VERSION,
    STRATEGY_ABSTENTION_REASONS,
)

ZERO: Final = Decimal("0")
ONE: Final = Decimal("1")
NO_TRADE_ABSTENTION_TREE_SCHEMA_VERSION = 1
MODEL_FAMILY: Final = "no_trade_abstention_fixed_shallow_tree_v1"
DEFAULT_SPLIT_FRACTION: Final = Decimal("0.70")
DEFAULT_MIN_TRAINING_ROWS = 500
DEFAULT_MIN_VALIDATION_ROWS = 300
DEFAULT_VALIDATION_BLOCKS = 4
MATERIAL_THRESHOLDS_BPS: Final = (50, 100, 200)
NUMERIC_FEATURES: Final = (
    "decision_score",
    "day_return",
    "funding",
    "open_interest",
    "day_notional_volume",
    "oi_change_fraction",
    "funding_change",
    "mark_oracle_dislocation_bps",
    "return_5m",
    "return_15m",
    "return_1h",
    "return_4h",
    "realized_vol_15m",
    "range_expansion_15m",
    "relative_volume_15m",
    "spread_bps",
    "bid_depth_25bps",
    "ask_depth_25bps",
    "book_imbalance",
    "book_age_ms",
)
CATEGORICAL_FEATURES: Final = (
    "reason_code",
    "trend_regime",
    "volatility_regime",
)
FEATURE_REGISTRY: Final = NUMERIC_FEATURES + CATEGORICAL_FEATURES
REASON_CATEGORIES: Final = tuple(sorted(STRATEGY_ABSTENTION_REASONS))
TREND_CATEGORIES: Final = tuple(item.value for item in TrendRegime)
VOLATILITY_CATEGORIES: Final = tuple(item.value for item in VolatilityRegime)
CATEGORY_REGISTRY: Final = (
    ("reason_code", REASON_CATEGORIES),
    ("trend_regime", TREND_CATEGORIES),
    ("volatility_regime", VOLATILITY_CATEGORIES),
)


class NoTradeAbstentionTreeError(RuntimeError):
    pass


class NoTradeAbstentionTreeDependencyError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _regressor() -> Any:
    try:
        ensemble = importlib.import_module("sklearn.ensemble")
    except ModuleNotFoundError as exc:
        raise NoTradeAbstentionTreeDependencyError(
            "scikit-learn is required for abstention-tree research"
        ) from exc
    return ensemble.HistGradientBoostingRegressor


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise NoTradeAbstentionTreeError(f"{field} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise NoTradeAbstentionTreeError(f"{field} keys must be strings")
    return cast(dict[str, object], value)


def _sequence(value: object, field: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise NoTradeAbstentionTreeError(f"{field} must be an array")
    return tuple(value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise NoTradeAbstentionTreeError(
            f"{field} must be a non-empty string"
        )
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise NoTradeAbstentionTreeError(f"{field} must be an integer")
    return value


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise NoTradeAbstentionTreeError(
            f"{field} must be a decimal string"
        )
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise NoTradeAbstentionTreeError(
            f"{field} must be a decimal string"
        ) from exc
    if not result.is_finite():
        raise NoTradeAbstentionTreeError(f"{field} must be finite")
    return result


@dataclass(frozen=True, slots=True)
class NoTradeAbstentionTreeConfig:
    max_leaf_nodes: int = 7
    min_samples_leaf: int = 100
    learning_rate: Decimal = Decimal("0.05")
    max_iter: int = 100
    l2_regularization: Decimal = Decimal("1")

    def __post_init__(self) -> None:
        if self.max_leaf_nodes < 2:
            raise ValueError("max_leaf_nodes must be at least two")
        if self.min_samples_leaf <= 0:
            raise ValueError("min_samples_leaf must be positive")
        if not self.learning_rate.is_finite():
            raise ValueError("learning_rate must be finite")
        if self.learning_rate <= ZERO:
            raise ValueError("learning_rate must be positive")
        if self.max_iter <= 0:
            raise ValueError("max_iter must be positive")
        if not self.l2_regularization.is_finite():
            raise ValueError("l2_regularization must be finite")
        if self.l2_regularization < ZERO:
            raise ValueError("l2_regularization must be non-negative")

    def to_dict(self) -> dict[str, object]:
        return {
            "max_leaf_nodes": self.max_leaf_nodes,
            "min_samples_leaf": self.min_samples_leaf,
            "learning_rate": str(self.learning_rate),
            "max_iter": self.max_iter,
            "l2_regularization": str(self.l2_regularization),
            "early_stopping": False,
            "random_state": 0,
        }


DEFAULT_TREE_CONFIG: Final = NoTradeAbstentionTreeConfig()


@dataclass(frozen=True, slots=True)
class _ResolvedRow:
    decision_timestamp_ms: int
    target_as_of_ms: int
    horizon_ms: int
    forward_return: Decimal
    feature_values: tuple[float, ...]


def _optional_float(value: Decimal | int | None) -> float:
    if value is None:
        return float("nan")
    resolved = float(value)
    if not math.isfinite(resolved):
        raise NoTradeAbstentionTreeError(
            "numeric feature must be finite when present"
        )
    return resolved


def _one_hot(value: str, categories: tuple[str, ...]) -> tuple[float, ...]:
    if value not in categories:
        raise NoTradeAbstentionTreeError(
            f"unknown categorical feature value: {value}"
        )
    return tuple(1.0 if value == item else 0.0 for item in categories)


def _resolve_rows(
    forward_report: dict[str, object],
    decisions: ContinuousPaperDecisionFactStore,
    features: LearningFeatureSnapshotStore,
) -> tuple[_ResolvedRow, ...]:
    output: list[_ResolvedRow] = []
    for raw_value in _sequence(forward_report.get("outcomes"), "outcomes"):
        raw = _mapping(raw_value, "outcome")
        if raw.get("decision_stage") != "strategy_abstained":
            continue

        fact_id = _string(raw.get("decision_fact_id"), "decision_fact_id")
        verified_fact = decisions.load(fact_id)
        if verified_fact is None:
            raise NoTradeAbstentionTreeError(
                "NO_TRADE_TREE_DECISION_FACT_MISSING"
            )
        fact = verified_fact.fact
        if fact.direction is not Direction.NO_TRADE:
            raise NoTradeAbstentionTreeError(
                "NO_TRADE_TREE_DECISION_DIRECTION_INVALID"
            )
        if len(fact.reason_codes) != 1:
            raise NoTradeAbstentionTreeError(
                "NO_TRADE_TREE_REASON_CARDINALITY_INVALID"
            )
        reason = fact.reason_codes[0]
        if reason not in STRATEGY_ABSTENTION_REASONS:
            raise NoTradeAbstentionTreeError(
                "NO_TRADE_TREE_NON_STRATEGY_ABSTENTION"
            )

        decision_timestamp_ms = _integer(
            raw.get("decision_timestamp_ms"),
            "decision_timestamp_ms",
        )
        if fact.timestamp_ms != decision_timestamp_ms:
            raise NoTradeAbstentionTreeError(
                "NO_TRADE_TREE_DECISION_TIMESTAMP_MISMATCH"
            )
        if fact.strategy_decision_id != _string(
            raw.get("strategy_decision_id"),
            "strategy_decision_id",
        ):
            raise NoTradeAbstentionTreeError(
                "NO_TRADE_TREE_STRATEGY_DECISION_MISMATCH"
            )
        if fact.market.canonical != _string(raw.get("market"), "market"):
            raise NoTradeAbstentionTreeError(
                "NO_TRADE_TREE_MARKET_MISMATCH"
            )
        if tuple(fact.reason_codes) != tuple(
            _string(item, "reason_codes item")
            for item in _sequence(raw.get("reason_codes"), "reason_codes")
        ):
            raise NoTradeAbstentionTreeError(
                "NO_TRADE_TREE_REASON_MISMATCH"
            )

        feature_snapshot_id = _string(
            raw.get("feature_snapshot_id"),
            "feature_snapshot_id",
        )
        if fact.feature_snapshot_id != feature_snapshot_id:
            raise NoTradeAbstentionTreeError(
                "NO_TRADE_TREE_FEATURE_ID_MISMATCH"
            )
        verified_feature = features.load(feature_snapshot_id)
        if verified_feature is None:
            raise NoTradeAbstentionTreeError(
                "NO_TRADE_TREE_FEATURE_MISSING"
            )
        feature = verified_feature.snapshot
        if feature.market != fact.market:
            raise NoTradeAbstentionTreeError(
                "NO_TRADE_TREE_FEATURE_MARKET_MISMATCH"
            )
        if feature.as_of_ms > decision_timestamp_ms:
            raise NoTradeAbstentionTreeError(
                "NO_TRADE_TREE_FEATURE_AFTER_DECISION"
            )
        if feature.source_received_at_ms > decision_timestamp_ms:
            raise NoTradeAbstentionTreeError(
                "NO_TRADE_TREE_FEATURE_SOURCE_AFTER_DECISION"
            )

        numeric = (
            _optional_float(fact.score),
            _optional_float(feature.day_return),
            _optional_float(feature.funding),
            _optional_float(feature.open_interest),
            _optional_float(feature.day_notional_volume),
            _optional_float(feature.oi_change_fraction),
            _optional_float(feature.funding_change),
            _optional_float(feature.mark_oracle_dislocation_bps),
            _optional_float(feature.return_5m),
            _optional_float(feature.return_15m),
            _optional_float(feature.return_1h),
            _optional_float(feature.return_4h),
            _optional_float(feature.realized_vol_15m),
            _optional_float(feature.range_expansion_15m),
            _optional_float(feature.relative_volume_15m),
            _optional_float(feature.spread_bps),
            _optional_float(feature.bid_depth_25bps),
            _optional_float(feature.ask_depth_25bps),
            _optional_float(feature.book_imbalance),
            _optional_float(feature.book_age_ms),
        )
        encoded = (
            *numeric,
            *_one_hot(reason, REASON_CATEGORIES),
            *_one_hot(feature.trend_regime.value, TREND_CATEGORIES),
            *_one_hot(
                feature.volatility_regime.value,
                VOLATILITY_CATEGORIES,
            ),
        )
        output.append(
            _ResolvedRow(
                decision_timestamp_ms=decision_timestamp_ms,
                target_as_of_ms=_integer(
                    raw.get("target_as_of_ms"),
                    "target_as_of_ms",
                ),
                horizon_ms=_integer(raw.get("horizon_ms"), "horizon_ms"),
                forward_return=_decimal(
                    raw.get("forward_mark_return"),
                    "forward_mark_return",
                ),
                feature_values=tuple(encoded),
            )
        )

    return tuple(
        sorted(
            output,
            key=lambda item: (
                item.horizon_ms,
                item.decision_timestamp_ms,
                item.target_as_of_ms,
                item.forward_return,
            ),
        )
    )


def _prediction_direction(value: Decimal) -> str:
    if value > ZERO:
        return "long"
    if value < ZERO:
        return "short"
    return "no_trade"


def _directional_return(
    prediction: Decimal,
    actual: Decimal,
) -> Decimal:
    if prediction > ZERO:
        return actual
    if prediction < ZERO:
        return -actual
    return ZERO


def _mean(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return sum(values, ZERO) / Decimal(len(values))


def _summary(
    rows: tuple[tuple[_ResolvedRow, Decimal], ...],
) -> dict[str, object]:
    if not rows:
        return {
            "rows": 0,
            "nonflat_actual_rows": 0,
            "direction_hits": 0,
            "direction_hit_rate": None,
            "predicted_long": 0,
            "predicted_short": 0,
            "predicted_no_trade": 0,
            "directional_mark_return_sum": "0",
            "mean_directional_mark_return": None,
            "mean_actual_forward_return": None,
            "mae": None,
            "rmse": None,
        }

    actual = tuple(item.forward_return for item, _prediction in rows)
    predictions = tuple(prediction for _item, prediction in rows)
    nonflat = tuple(
        (item, prediction)
        for item, prediction in rows
        if item.forward_return != ZERO
    )
    hits = sum(
        _prediction_direction(prediction)
        == _prediction_direction(item.forward_return)
        for item, prediction in nonflat
    )
    directional = tuple(
        _directional_return(prediction, item.forward_return)
        for item, prediction in rows
    )
    absolute_errors = tuple(
        abs(prediction - item.forward_return)
        for item, prediction in rows
    )
    squared_errors = tuple(value * value for value in absolute_errors)
    rmse = Decimal(
        str(
            math.sqrt(
                float(sum(squared_errors, ZERO) / Decimal(len(rows)))
            )
        )
    )
    return {
        "rows": len(rows),
        "nonflat_actual_rows": len(nonflat),
        "direction_hits": hits,
        "direction_hit_rate": (
            None if not nonflat else str(Decimal(hits) / Decimal(len(nonflat)))
        ),
        "predicted_long": sum(value > ZERO for value in predictions),
        "predicted_short": sum(value < ZERO for value in predictions),
        "predicted_no_trade": sum(value == ZERO for value in predictions),
        "directional_mark_return_sum": str(sum(directional, ZERO)),
        "mean_directional_mark_return": str(_mean(directional)),
        "mean_actual_forward_return": str(_mean(actual)),
        "mae": str(_mean(absolute_errors)),
        "rmse": str(rmse),
    }


def _blocks(
    rows: tuple[tuple[_ResolvedRow, Decimal], ...],
    *,
    blocks: int,
) -> tuple[dict[str, object], ...]:
    output: list[dict[str, object]] = []
    for index in range(blocks):
        start = index * len(rows) // blocks
        end = (index + 1) * len(rows) // blocks
        block = rows[start:end]
        output.append(
            {
                "block_index": index,
                "start_decision_timestamp_ms": (
                    None if not block else block[0][0].decision_timestamp_ms
                ),
                "end_decision_timestamp_ms": (
                    None if not block else block[-1][0].decision_timestamp_ms
                ),
                "summary": _summary(block),
            }
        )
    return tuple(output)


def _material_summaries(
    rows: tuple[tuple[_ResolvedRow, Decimal], ...],
) -> tuple[dict[str, object], ...]:
    output: list[dict[str, object]] = []
    for threshold_bps in MATERIAL_THRESHOLDS_BPS:
        threshold = Decimal(threshold_bps) / Decimal("10000")
        cohort = tuple(
            item
            for item in rows
            if abs(item[0].forward_return) >= threshold
        )
        output.append(
            {
                "threshold_bps": threshold_bps,
                "selection_uses_future_outcome": True,
                "diagnostic_only": True,
                "summary": _summary(cohort),
            }
        )
    return tuple(output)


def _evaluate_horizon(
    rows: tuple[_ResolvedRow, ...],
    *,
    horizon_ms: int,
    split_fraction: Decimal,
    min_training_rows: int,
    min_validation_rows: int,
    validation_blocks: int,
    tree_config: NoTradeAbstentionTreeConfig,
) -> dict[str, object]:
    if len(rows) < 2:
        return {
            "horizon_ms": horizon_ms,
            "status": "not_ready",
            "reason": "insufficient_labeled_rows",
            "labeled_rows": len(rows),
        }

    raw_split = int(Decimal(len(rows)) * split_fraction)
    split_index = min(max(raw_split, 1), len(rows) - 1)
    validation = rows[split_index:]
    validation_start_ms = validation[0].decision_timestamp_ms
    discovery_candidates = rows[:split_index]
    training = tuple(
        item
        for item in discovery_candidates
        if item.target_as_of_ms < validation_start_ms
    )
    purged = len(discovery_candidates) - len(training)

    if len(training) < min_training_rows:
        return {
            "horizon_ms": horizon_ms,
            "status": "not_ready",
            "reason": "insufficient_purged_training_rows",
            "labeled_rows": len(rows),
            "training_rows": len(training),
            "validation_rows": len(validation),
            "purged_overlap_rows": purged,
            "validation_start_ms": validation_start_ms,
        }
    if len(validation) < min_validation_rows:
        return {
            "horizon_ms": horizon_ms,
            "status": "not_ready",
            "reason": "insufficient_validation_rows",
            "labeled_rows": len(rows),
            "training_rows": len(training),
            "validation_rows": len(validation),
            "purged_overlap_rows": purged,
            "validation_start_ms": validation_start_ms,
        }

    estimator_type = _regressor()
    estimator = estimator_type(
        loss="squared_error",
        learning_rate=float(tree_config.learning_rate),
        max_iter=tree_config.max_iter,
        max_leaf_nodes=tree_config.max_leaf_nodes,
        min_samples_leaf=tree_config.min_samples_leaf,
        l2_regularization=float(tree_config.l2_regularization),
        early_stopping=False,
        random_state=0,
    )
    estimator.fit(
        [item.feature_values for item in training],
        [float(item.forward_return) for item in training],
    )
    raw_predictions = estimator.predict(
        [item.feature_values for item in validation]
    )
    predictions: list[Decimal] = []
    for raw in raw_predictions:
        value = float(raw)
        if not math.isfinite(value):
            raise NoTradeAbstentionTreeError(
                "NO_TRADE_TREE_PREDICTION_NONFINITE"
            )
        predictions.append(Decimal(str(value)))

    paired = tuple(zip(validation, predictions, strict=True))
    prediction_payload = tuple(
        {
            "decision_timestamp_ms": item.decision_timestamp_ms,
            "target_as_of_ms": item.target_as_of_ms,
            "prediction": str(prediction),
        }
        for item, prediction in paired
    )
    return {
        "horizon_ms": horizon_ms,
        "status": "completed",
        "labeled_rows": len(rows),
        "training_rows": len(training),
        "validation_rows": len(validation),
        "purged_overlap_rows": purged,
        "validation_start_ms": validation_start_ms,
        "validation_end_ms": validation[-1].decision_timestamp_ms,
        "prediction_sha256": _sha256_json(prediction_payload),
        "validation": _summary(paired),
        "validation_blocks": _blocks(
            paired,
            blocks=validation_blocks,
        ),
        "material_move_diagnostics": _material_summaries(paired),
        "all_long_baseline_mean_forward_return": str(
            _mean(tuple(item.forward_return for item in validation))
        ),
        "all_short_baseline_mean_directional_return": str(
            -cast(
                Decimal,
                _mean(tuple(item.forward_return for item in validation)),
            )
        ),
    }


def build_no_trade_abstention_tree_report(
    forward_report: dict[str, object],
    decisions: ContinuousPaperDecisionFactStore,
    features: LearningFeatureSnapshotStore,
    *,
    split_fraction: Decimal = DEFAULT_SPLIT_FRACTION,
    min_training_rows: int = DEFAULT_MIN_TRAINING_ROWS,
    min_validation_rows: int = DEFAULT_MIN_VALIDATION_ROWS,
    validation_blocks: int = DEFAULT_VALIDATION_BLOCKS,
    tree_config: NoTradeAbstentionTreeConfig = DEFAULT_TREE_CONFIG,
) -> dict[str, object]:
    if not ZERO < split_fraction < ONE:
        raise ValueError("split_fraction must be between zero and one")
    if min_training_rows <= 0:
        raise ValueError("min_training_rows must be positive")
    if min_validation_rows <= 0:
        raise ValueError("min_validation_rows must be positive")
    if validation_blocks <= 0:
        raise ValueError("validation_blocks must be positive")
    if forward_report.get("schema_version") != NO_TRADE_FORWARD_SCHEMA_VERSION:
        raise NoTradeAbstentionTreeError(
            "NO_TRADE_TREE_FORWARD_SCHEMA_MISMATCH"
        )
    if forward_report.get("diagnostic_only") is not True:
        raise NoTradeAbstentionTreeError(
            "NO_TRADE_TREE_SOURCE_NOT_DIAGNOSTIC"
        )
    if forward_report.get("hypothetical_pnl") is not False:
        raise NoTradeAbstentionTreeError(
            "NO_TRADE_TREE_SOURCE_PNL_AUTHORITY_INVALID"
        )
    if forward_report.get("execution_authority") is not False:
        raise NoTradeAbstentionTreeError(
            "NO_TRADE_TREE_SOURCE_EXECUTION_AUTHORITY_INVALID"
        )
    source_decision_digest = _string(
        forward_report.get("decision_state_digest"),
        "decision_state_digest",
    )
    source_feature_digest = _string(
        forward_report.get("feature_state_digest"),
        "feature_state_digest",
    )
    if source_decision_digest != decisions.state_digest:
        raise NoTradeAbstentionTreeError(
            "NO_TRADE_TREE_DECISION_STATE_DIGEST_MISMATCH"
        )
    if source_feature_digest != features.state_digest:
        raise NoTradeAbstentionTreeError(
            "NO_TRADE_TREE_FEATURE_STATE_DIGEST_MISMATCH"
        )

    resolved = _resolve_rows(forward_report, decisions, features)
    horizons = tuple(sorted({item.horizon_ms for item in resolved}))
    evaluations = tuple(
        _evaluate_horizon(
            tuple(item for item in resolved if item.horizon_ms == horizon_ms),
            horizon_ms=horizon_ms,
            split_fraction=split_fraction,
            min_training_rows=min_training_rows,
            min_validation_rows=min_validation_rows,
            validation_blocks=validation_blocks,
            tree_config=tree_config,
        )
        for horizon_ms in horizons
    )
    payload = {
        "model_family": MODEL_FAMILY,
        "model_config": tree_config.to_dict(),
        "model_config_id": _sha256_json(tree_config.to_dict()),
        "feature_registry": FEATURE_REGISTRY,
        "category_registry": CATEGORY_REGISTRY,
        "split_fraction": str(split_fraction),
        "min_training_rows": min_training_rows,
        "min_validation_rows": min_validation_rows,
        "validation_blocks": validation_blocks,
        "source_decision_state_digest": source_decision_digest,
        "source_feature_state_digest": source_feature_digest,
        "strategy_abstention_rows": len(resolved),
        "evaluations": evaluations,
        "completed_horizons": sum(
            item.get("status") == "completed" for item in evaluations
        ),
        "chronological_holdout_required": True,
        "label_overlap_purged": True,
        "material_subsets_are_post_outcome_diagnostics": True,
        "target": "future_trailing_candle_return",
        "hypothetical_pnl": False,
        "cost_complete": False,
        "research_only": True,
        "development_qualification_authority": False,
        "prospective_shadow_authority": False,
        "promotion_authority": False,
        "execution_authority": False,
        "schema_version": NO_TRADE_ABSTENTION_TREE_SCHEMA_VERSION,
    }
    return {**payload, "report_id": _sha256_json(payload)}
