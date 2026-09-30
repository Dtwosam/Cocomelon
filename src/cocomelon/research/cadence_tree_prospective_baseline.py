from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Final

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
    FEATURE_REGISTRY,
    MODEL_FAMILY,
    CadenceTreeConfig,
    _Encoder,
    _fit_tree,
    _predict,
)
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotStore,
)

ZERO: Final = Decimal("0")
PROSPECTIVE_START_MS: Final = 1_790_776_800_000
DEFAULT_FROZEN_TRAINING_MANIFEST_PATH: Final = Path(__file__).with_name(
    "cadence_tree_frozen_training_v1.json"
)


def _direction_summary(
    scored: tuple[tuple[_ContextRow, Decimal], ...],
) -> dict[str, object]:
    # Kept local so the prospective result has the same compact schema as
    # the microstructure challenger without changing the frozen tree module.
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


def evaluate_cadence_tree_prospective_baseline(
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
    estimator = _fit_tree(
        training_rows,
        encoder=encoder,
        config=tree_config,
    )
    predictions = _predict(
        estimator,
        encoder,
        prospective_rows,
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
        len(prospective_rows) >= validation_config.validation_rows
    )
    qualified = (
        enough_rows
        and len(admitted) >= validation_config.min_validation_admitted
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
        "status": "completed" if enough_rows else "collecting",
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "claim_scope": "prospective_baseline_comparator_only",
        "model_family": MODEL_FAMILY,
        "feature_registry": FEATURE_REGISTRY,
        "prospective_start_ms": prospective_start_ms,
        "cadence_ms": cadence_ms,
        "horizon_ms": horizon_ms,
        "frozen_training_rows": len(training_rows),
        "frozen_training_rows_sha256": manifest.rows_sha256,
        "frozen_training_source": manifest.source,
        "prospective_rows": len(prospective_rows),
        "required_prospective_rows": validation_config.validation_rows,
        "admitted_rows": len(admitted),
        "skipped_rows": len(scored) - len(admitted),
        "candidate_net_return_sum": str(candidate_sum),
        "candidate_mean_net_return": (
            None if candidate_mean is None else str(candidate_mean)
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
                "realized_net_return": str(row.outcome.net_return),
            }
            for row, prediction in scored
        ),
    }
