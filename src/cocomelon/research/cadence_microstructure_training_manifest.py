from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast

from cocomelon.research.cadence_shadow import (
    ShadowCadenceOutcome,
    _outcome_payload,
)
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotError,
    LearningFeatureSnapshotStore,
)

FROZEN_TRAINING_MANIFEST_SCHEMA_VERSION: Final = 2


class FrozenCadenceTrainingManifestError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256(value: object) -> str:
    return hashlib.sha256(
        _canonical_json(value).encode("utf-8")
    ).hexdigest()


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise FrozenCadenceTrainingManifestError(
            f"{field} must be an object"
        )
    return cast(dict[str, object], value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise FrozenCadenceTrainingManifestError(
            f"{field} must be a non-empty string"
        )
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise FrozenCadenceTrainingManifestError(
            f"{field} must be an integer"
        )
    return value


def _sha(value: object, field: str) -> str:
    resolved = _string(value, field)
    if len(resolved) != 64 or any(
        char not in "0123456789abcdef" for char in resolved
    ):
        raise FrozenCadenceTrainingManifestError(
            f"{field} must be a lowercase SHA-256"
        )
    return resolved


@dataclass(frozen=True, slots=True)
class FrozenCadenceTrainingManifest:
    model_family: str
    feature_registry: tuple[str, ...]
    prospective_start_ms: int
    cadence_ms: int
    horizon_ms: int
    source: dict[str, object]
    training_rows: int
    training_first_target_end_ms: int
    training_last_target_end_ms: int
    rows_sha256: str

    def __post_init__(self) -> None:
        if self.training_rows <= 0:
            raise FrozenCadenceTrainingManifestError(
                "training_rows must be positive"
            )
        if self.training_first_target_end_ms < 0:
            raise FrozenCadenceTrainingManifestError(
                "training first target must be non-negative"
            )
        if (
            self.training_last_target_end_ms
            < self.training_first_target_end_ms
        ):
            raise FrozenCadenceTrainingManifestError(
                "training target bounds are invalid"
            )
        if (
            self.training_last_target_end_ms
            >= self.prospective_start_ms
        ):
            raise FrozenCadenceTrainingManifestError(
                "frozen training reaches prospective boundary"
            )


def load_frozen_cadence_training_manifest(
    path: str | Path,
) -> FrozenCadenceTrainingManifest:
    source_path = Path(path)
    try:
        raw = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FrozenCadenceTrainingManifestError(
            "FROZEN_CADENCE_TRAINING_MANIFEST_INVALID"
        ) from exc
    root = _mapping(raw, "manifest")
    if (
        root.get("schema_version")
        != FROZEN_TRAINING_MANIFEST_SCHEMA_VERSION
    ):
        raise FrozenCadenceTrainingManifestError(
            "FROZEN_CADENCE_TRAINING_MANIFEST_SCHEMA_UNSUPPORTED"
        )
    registry_raw = root.get("feature_registry")
    if not isinstance(registry_raw, list) or not all(
        isinstance(item, str) and item
        for item in registry_raw
    ):
        raise FrozenCadenceTrainingManifestError(
            "feature_registry must be a string array"
        )
    return FrozenCadenceTrainingManifest(
        model_family=_string(
            root.get("model_family"),
            "model_family",
        ),
        feature_registry=tuple(registry_raw),
        prospective_start_ms=_integer(
            root.get("prospective_start_ms"),
            "prospective_start_ms",
        ),
        cadence_ms=_integer(
            root.get("cadence_ms"),
            "cadence_ms",
        ),
        horizon_ms=_integer(
            root.get("horizon_ms"),
            "horizon_ms",
        ),
        source=_mapping(root.get("source"), "source"),
        training_rows=_integer(
            root.get("training_rows"),
            "training_rows",
        ),
        training_first_target_end_ms=_integer(
            root.get("training_first_target_end_ms"),
            "training_first_target_end_ms",
        ),
        training_last_target_end_ms=_integer(
            root.get("training_last_target_end_ms"),
            "training_last_target_end_ms",
        ),
        rows_sha256=_sha(
            root.get("rows_sha256"),
            "rows_sha256",
        ),
    )


def _frozen_row_payload(
    outcome: ShadowCadenceOutcome,
    feature_record_sha256: str,
) -> dict[str, object]:
    return {
        "identity": {
            "cadence_ms": outcome.sample.cadence_ms,
            "decision_id": outcome.sample.decision_id,
            "horizon_ms": outcome.sample.horizon_ms,
        },
        "target_end_ms": outcome.sample.target_end_ms,
        "feature_snapshot_id": outcome.sample.feature_snapshot_id,
        "outcome_sha256": _sha256(_outcome_payload(outcome)),
        "feature_record_sha256": feature_record_sha256,
    }


def _fingerprint_rows(
    outcomes: tuple[ShadowCadenceOutcome, ...],
    feature_store: LearningFeatureSnapshotStore,
) -> str:
    payloads: list[dict[str, object]] = []
    for outcome in outcomes:
        try:
            verified = feature_store.load(
                outcome.sample.feature_snapshot_id
            )
        except LearningFeatureSnapshotError as exc:
            raise FrozenCadenceTrainingManifestError(
                "frozen training feature record invalid"
            ) from exc
        if verified is None:
            raise FrozenCadenceTrainingManifestError(
                "frozen training feature snapshot missing"
            )
        if verified.snapshot.market != outcome.sample.market:
            raise FrozenCadenceTrainingManifestError(
                "frozen training feature market mismatch"
            )
        if verified.snapshot.as_of_ms > outcome.sample.evaluated_at_ms:
            raise FrozenCadenceTrainingManifestError(
                "frozen training feature is after decision"
            )
        if (
            verified.snapshot.source_received_at_ms
            > outcome.sample.evaluated_at_ms
        ):
            raise FrozenCadenceTrainingManifestError(
                "frozen training feature source is after decision"
            )
        payloads.append(
            _frozen_row_payload(
                outcome,
                verified.record_sha256,
            )
        )
    return _sha256(payloads)


def build_frozen_cadence_training_manifest(
    outcomes: tuple[ShadowCadenceOutcome, ...],
    feature_store: LearningFeatureSnapshotStore,
    *,
    model_family: str,
    feature_registry: tuple[str, ...],
    prospective_start_ms: int,
    cadence_ms: int,
    horizon_ms: int,
    source: dict[str, object],
) -> FrozenCadenceTrainingManifest:
    selected = tuple(
        sorted(
            (
                outcome
                for outcome in outcomes
                if outcome.sample.cadence_ms == cadence_ms
                and outcome.sample.horizon_ms == horizon_ms
                and outcome.sample.target_end_ms
                < prospective_start_ms
            ),
            key=lambda outcome: (
                outcome.sample.target_end_ms,
                outcome.sample.market.canonical,
                outcome.sample.decision_id,
            ),
        )
    )
    if not selected:
        raise FrozenCadenceTrainingManifestError(
            "freeze source contains no training rows"
        )
    return FrozenCadenceTrainingManifest(
        model_family=model_family,
        feature_registry=feature_registry,
        prospective_start_ms=prospective_start_ms,
        cadence_ms=cadence_ms,
        horizon_ms=horizon_ms,
        source=dict(source),
        training_rows=len(selected),
        training_first_target_end_ms=(
            selected[0].sample.target_end_ms
        ),
        training_last_target_end_ms=(
            selected[-1].sample.target_end_ms
        ),
        rows_sha256=_fingerprint_rows(
            selected,
            feature_store,
        ),
    )


def frozen_cadence_training_manifest_payload(
    manifest: FrozenCadenceTrainingManifest,
) -> dict[str, object]:
    return {
        "schema_version": FROZEN_TRAINING_MANIFEST_SCHEMA_VERSION,
        "model_family": manifest.model_family,
        "feature_registry": list(manifest.feature_registry),
        "prospective_start_ms": manifest.prospective_start_ms,
        "cadence_ms": manifest.cadence_ms,
        "horizon_ms": manifest.horizon_ms,
        "source": manifest.source,
        "training_rows": manifest.training_rows,
        "training_first_target_end_ms": (
            manifest.training_first_target_end_ms
        ),
        "training_last_target_end_ms": (
            manifest.training_last_target_end_ms
        ),
        "rows_sha256": manifest.rows_sha256,
    }


def verify_frozen_cadence_training(
    manifest: FrozenCadenceTrainingManifest,
    outcomes: tuple[ShadowCadenceOutcome, ...],
    feature_store: LearningFeatureSnapshotStore,
    *,
    model_family: str,
    feature_registry: tuple[str, ...],
    prospective_start_ms: int,
    cadence_ms: int,
    horizon_ms: int,
) -> tuple[ShadowCadenceOutcome, ...]:
    if manifest.model_family != model_family:
        raise FrozenCadenceTrainingManifestError(
            "frozen manifest model family mismatch"
        )
    if manifest.feature_registry != feature_registry:
        raise FrozenCadenceTrainingManifestError(
            "frozen manifest feature registry mismatch"
        )
    if manifest.prospective_start_ms != prospective_start_ms:
        raise FrozenCadenceTrainingManifestError(
            "frozen manifest prospective start mismatch"
        )
    if (
        manifest.cadence_ms != cadence_ms
        or manifest.horizon_ms != horizon_ms
    ):
        raise FrozenCadenceTrainingManifestError(
            "frozen manifest surface mismatch"
        )

    selected = tuple(
        sorted(
            (
                outcome
                for outcome in outcomes
                if outcome.sample.cadence_ms == cadence_ms
                and outcome.sample.horizon_ms == horizon_ms
                and outcome.sample.target_end_ms
                <= manifest.training_last_target_end_ms
            ),
            key=lambda outcome: (
                outcome.sample.target_end_ms,
                outcome.sample.market.canonical,
                outcome.sample.decision_id,
            ),
        )
    )
    if len(selected) != manifest.training_rows:
        raise FrozenCadenceTrainingManifestError(
            "frozen training row count changed"
        )
    if not selected:
        raise FrozenCadenceTrainingManifestError(
            "frozen training rows disappeared"
        )
    if (
        selected[0].sample.target_end_ms
        != manifest.training_first_target_end_ms
    ):
        raise FrozenCadenceTrainingManifestError(
            "frozen training first target changed"
        )
    if (
        selected[-1].sample.target_end_ms
        != manifest.training_last_target_end_ms
    ):
        raise FrozenCadenceTrainingManifestError(
            "frozen training last target changed"
        )
    if any(
        outcome.sample.target_end_ms >= prospective_start_ms
        for outcome in selected
    ):
        raise FrozenCadenceTrainingManifestError(
            "frozen training includes post-boundary label"
        )
    if _fingerprint_rows(selected, feature_store) != manifest.rows_sha256:
        raise FrozenCadenceTrainingManifestError(
            "frozen training content changed"
        )
    return selected
