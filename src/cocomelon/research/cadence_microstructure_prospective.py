from __future__ import annotations

import importlib
import math
from dataclasses import dataclass
from pathlib import Path
from decimal import Decimal
from typing import Any, Final

from cocomelon.domain.strategy import Direction
from cocomelon.research.cadence_context_learning import (
    _ContextRow,
    _resolve_rows,
)
from cocomelon.research.cadence_microstructure_training_manifest import (
    FrozenCadenceTrainingManifestError,
    load_frozen_cadence_training_manifest,
    verify_frozen_cadence_training,
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
)
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotStore,
)

ZERO: Final = Decimal("0")
MODEL_FAMILY: Final = "cadence_microstructure_tree_prospective_v1"
PROSPECTIVE_START_MS: Final = 1_790_776_800_000
DEFAULT_FROZEN_TRAINING_MANIFEST_PATH: Final = (
    Path(__file__).with_name(
        "cadence_microstructure_frozen_training_v1.json"
    )
)
FEATURE_REGISTRY: Final = (
    "direction",
    "lead_strategy",
    "score",
    "return_5m",
    "return_15m",
    "return_1h",
    "funding",
    "open_interest",
    "oi_change_fraction",
    "funding_change",
    "mark_oracle_dislocation_bps",
    "realized_vol_15m",
    "range_expansion_15m",
    "relative_volume_15m",
    "spread_bps",
    "bid_depth_25bps",
    "ask_depth_25bps",
    "book_imbalance",
    "book_age_ms",
    "trend_regime",
    "volatility_regime",
)


class CadenceMicrostructureProspectiveError(RuntimeError):
    pass


def _regressor() -> Any:
    try:
        ensemble = importlib.import_module("sklearn.ensemble")
    except ModuleNotFoundError as exc:
        raise CadenceMicrostructureProspectiveError(
            "scikit-learn is required for cadence microstructure research"
        ) from exc
    return ensemble.HistGradientBoostingRegressor


@dataclass(frozen=True, slots=True)
class _Encoder:
    strategies: tuple[str, ...]
    trend_regimes: tuple[str, ...]
    volatility_regimes: tuple[str, ...]

    @classmethod
    def fit(cls, rows: tuple[_ContextRow, ...]) -> _Encoder:
        return cls(
            strategies=tuple(
                sorted(
                    {
                        row.outcome.sample.lead_strategy
                        for row in rows
                    }
                )
            ),
            trend_regimes=tuple(
                sorted(
                    {
                        row.feature.trend_regime.value
                        for row in rows
                    }
                )
            ),
            volatility_regimes=tuple(
                sorted(
                    {
                        row.feature.volatility_regime.value
                        for row in rows
                    }
                )
            ),
        )

    @staticmethod
    def _numeric(value: Decimal | int | None) -> float:
        if value is None:
            return float("nan")
        resolved = float(value)
        if not math.isfinite(resolved):
            raise CadenceMicrostructureProspectiveError(
                "prospective numeric feature must be finite"
            )
        return resolved

    def vector(self, row: _ContextRow) -> tuple[float, ...]:
        sample = row.outcome.sample
        feature = row.feature
        values: list[float] = [
            1.0 if sample.direction is Direction.LONG else 0.0,
            1.0 if sample.direction is Direction.SHORT else 0.0,
        ]
        values.extend(
            1.0 if sample.lead_strategy == strategy else 0.0
            for strategy in self.strategies
        )
        values.append(float(sample.score))
        values.extend(
            self._numeric(value)
            for value in (
                feature.return_5m,
                feature.return_15m,
                feature.return_1h,
                feature.funding,
                feature.open_interest,
                feature.oi_change_fraction,
                feature.funding_change,
                feature.mark_oracle_dislocation_bps,
                feature.realized_vol_15m,
                feature.range_expansion_15m,
                feature.relative_volume_15m,
                feature.spread_bps,
                feature.bid_depth_25bps,
                feature.ask_depth_25bps,
                feature.book_imbalance,
                feature.book_age_ms,
            )
        )
        values.extend(
            1.0 if feature.trend_regime.value == regime else 0.0
            for regime in self.trend_regimes
        )
        values.extend(
            1.0 if feature.volatility_regime.value == regime else 0.0
            for regime in self.volatility_regimes
        )
        return tuple(values)


def _fit(
    rows: tuple[_ContextRow, ...],
    *,
    encoder: _Encoder,
    config: CadenceTreeConfig,
) -> Any:
    estimator = _regressor()(
        loss="squared_error",
        learning_rate=float(config.learning_rate),
        max_iter=config.max_iter,
        max_leaf_nodes=config.max_leaf_nodes,
        min_samples_leaf=config.min_samples_leaf,
        l2_regularization=float(config.l2_regularization),
        early_stopping=False,
        random_state=0,
    )
    estimator.fit(
        [encoder.vector(row) for row in rows],
        [float(row.outcome.net_return) for row in rows],
    )
    return estimator


def _predict(
    estimator: Any,
    encoder: _Encoder,
    rows: tuple[_ContextRow, ...],
) -> tuple[Decimal, ...]:
    raw = estimator.predict([encoder.vector(row) for row in rows])
    output: list[Decimal] = []
    for value in raw:
        resolved = float(value)
        if not math.isfinite(resolved):
            raise CadenceMicrostructureProspectiveError(
                "prospective prediction must be finite"
            )
        output.append(Decimal(str(resolved)))
    return tuple(output)


def _direction_summary(
    scored: tuple[tuple[_ContextRow, Decimal], ...],
) -> dict[str, object]:
    output: dict[str, object] = {}
    for direction in (Direction.LONG.value, Direction.SHORT.value):
        rows = tuple(
            (row, prediction)
            for row, prediction in scored
            if row.outcome.sample.direction.value == direction
        )
        admitted = tuple(
            row.outcome
            for row, prediction in rows
            if prediction > ZERO
        )
        total = sum((row.net_return for row in admitted), ZERO)
        output[direction] = {
            "prospective_rows": len(rows),
            "admitted_rows": len(admitted),
            "candidate_net_return_sum": str(total),
            "candidate_mean_net_return": (
                None
                if not admitted
                else str(total / Decimal(len(admitted)))
            ),
        }
    return output


def _stability_blocks(
    scored: tuple[tuple[_ContextRow, Decimal], ...],
    *,
    blocks: int,
    min_block_admitted: int,
) -> tuple[dict[str, object], ...]:
    if not scored:
        return ()
    output: list[dict[str, object]] = []
    for index in range(blocks):
        start = index * len(scored) // blocks
        end = (index + 1) * len(scored) // blocks
        block = scored[start:end]
        admitted = tuple(
            row.outcome
            for row, prediction in block
            if prediction > ZERO
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
                "prospective_rows": len(block),
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


def evaluate_cadence_microstructure_prospective(
    outcomes: tuple[ShadowCadenceOutcome, ...],
    feature_store: LearningFeatureSnapshotStore,
    *,
    prospective_start_ms: int = PROSPECTIVE_START_MS,
    cadence_ms: int = FIFTEEN_MINUTES_MS,
    horizon_ms: int = ONE_HOUR_MS,
    validation_config: CadenceOpportunityLearningConfig = DEFAULT_CONFIG,
    tree_config: CadenceTreeConfig = DEFAULT_TREE_CONFIG,
    frozen_training_manifest_path: str | Path = (
        DEFAULT_FROZEN_TRAINING_MANIFEST_PATH
    ),
) -> dict[str, object]:
    if prospective_start_ms < 0:
        raise ValueError("prospective_start_ms must be non-negative")

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
    prospective = tuple(
        row
        for row in surface
        if row.sample.boundary_ms >= prospective_start_ms
    )
    try:
        manifest = load_frozen_cadence_training_manifest(
            frozen_training_manifest_path
        )
        training = verify_frozen_cadence_training(
            manifest,
            surface,
            feature_store,
            model_family=MODEL_FAMILY,
            feature_registry=FEATURE_REGISTRY,
            prospective_start_ms=prospective_start_ms,
            cadence_ms=cadence_ms,
            horizon_ms=horizon_ms,
        )
    except FrozenCadenceTrainingManifestError as exc:
        return {
            "status": "not_ready",
            "reason": "frozen_training_manifest_mismatch",
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "prospective_start_ms": prospective_start_ms,
            "prospective_rows": len(prospective),
            "frozen_training_error": str(exc),
        }
    if len(training) < validation_config.min_train_rows:
        return {
            "status": "not_ready",
            "reason": "insufficient_frozen_training_rows",
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "prospective_start_ms": prospective_start_ms,
            "training_rows": len(training),
            "prospective_rows": len(prospective),
            "frozen_training_rows_sha256": manifest.rows_sha256,
        }

    training_rows, missing_training = _resolve_rows(
        training,
        feature_store,
    )
    prospective_rows, missing_prospective = _resolve_rows(
        prospective,
        feature_store,
    )
    if missing_training or missing_prospective:
        return {
            "status": "not_ready",
            "reason": "feature_snapshot_missing",
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "prospective_start_ms": prospective_start_ms,
            "missing_training_feature_snapshots": len(
                missing_training
            ),
            "missing_prospective_feature_snapshots": len(
                missing_prospective
            ),
        }

    encoder = _Encoder.fit(training_rows)
    estimator = _fit(
        training_rows,
        encoder=encoder,
        config=tree_config,
    )
    predictions = (
        ()
        if not prospective_rows
        else _predict(
            estimator,
            encoder,
            prospective_rows,
        )
    )
    scored = tuple(
        zip(prospective_rows, predictions, strict=True)
    )
    admitted = tuple(
        row.outcome
        for row, prediction in scored
        if prediction > ZERO
    )
    candidate_sum = sum(
        (row.net_return for row in admitted),
        ZERO,
    )
    candidate_mean = (
        None
        if not admitted
        else candidate_sum / Decimal(len(admitted))
    )
    long_admitted = sum(
        1
        for row, prediction in scored
        if prediction > ZERO
        and row.outcome.sample.direction is Direction.LONG
    )
    short_admitted = sum(
        1
        for row, prediction in scored
        if prediction > ZERO
        and row.outcome.sample.direction is Direction.SHORT
    )
    blocks = _stability_blocks(
        scored,
        blocks=validation_config.stability_blocks,
        min_block_admitted=validation_config.min_block_admitted,
    )
    enough_rows = (
        len(prospective_rows)
        >= validation_config.validation_rows
    )
    qualified = (
        enough_rows
        and len(admitted)
        >= validation_config.min_validation_admitted
        and long_admitted
        >= validation_config.min_admitted_per_direction
        and short_admitted
        >= validation_config.min_admitted_per_direction
        and candidate_mean is not None
        and candidate_mean > ZERO
        and bool(blocks)
        and all(bool(block["passes"]) for block in blocks)
    )

    return {
        "status": (
            "completed" if enough_rows else "collecting"
        ),
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "claim_scope": "prospective_post_freeze_development_only",
        "model_family": MODEL_FAMILY,
        "feature_registry": FEATURE_REGISTRY,
        "prospective_start_ms": prospective_start_ms,
        "cadence_ms": cadence_ms,
        "horizon_ms": horizon_ms,
        "frozen_training_rows": len(training_rows),
        "frozen_training_rows_sha256": manifest.rows_sha256,
        "frozen_training_source": manifest.source,
        "frozen_training_last_target_end_ms": (
            None
            if not training
            else max(row.sample.target_end_ms for row in training)
        ),
        "prospective_rows": len(prospective_rows),
        "required_prospective_rows": (
            validation_config.validation_rows
        ),
        "admitted_rows": len(admitted),
        "skipped_rows": len(scored) - len(admitted),
        "candidate_net_return_sum": str(candidate_sum),
        "candidate_mean_net_return": (
            None
            if candidate_mean is None
            else str(candidate_mean)
        ),
        "by_direction": _direction_summary(scored),
        "stability_blocks": blocks,
        "development_qualified": qualified,
        "scored_rows": tuple(
            {
                "decision_id": row.outcome.sample.decision_id,
                "boundary_ms": row.outcome.sample.boundary_ms,
                "market": row.outcome.sample.market.canonical,
                "direction": row.outcome.sample.direction.value,
                "prediction_net_return": str(prediction),
                "admitted": prediction > ZERO,
                "realized_net_return": str(
                    row.outcome.net_return
                ),
            }
            for row, prediction in scored
        ),
        "tree_configuration": {
            "max_leaf_nodes": tree_config.max_leaf_nodes,
            "min_samples_leaf": tree_config.min_samples_leaf,
            "learning_rate": str(tree_config.learning_rate),
            "max_iter": tree_config.max_iter,
            "l2_regularization": str(
                tree_config.l2_regularization
            ),
            "random_state": 0,
            "early_stopping": False,
        },
    }
