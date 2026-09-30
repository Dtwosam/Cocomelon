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
    LearningFeatureSnapshotStore,
)

FROZEN_TRAINING_MANIFEST_SCHEMA_VERSION: Final = 1


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
class FrozenCadenceTrainingRow:
    cadence_ms: int
    decision_id: str
    horizon_ms: int
    target_end_ms: int
    feature_snapshot_id: str
    outcome_sha256: str
    feature_record_sha256: str

    @property
    def identity(self) -> tuple[int, str, int]:
        return self.cadence_ms, self.decision_id, self.horizon_ms

    def payload(self) -> dict[str, object]:
        return {
            "identity": {
                "cadence_ms": self.cadence_ms,
                "decision_id": self.decision_id,
                "horizon_ms": self.horizon_ms,
            },
            "target_end_ms": self.target_end_ms,
            "feature_snapshot_id": self.feature_snapshot_id,
            "outcome_sha256": self.outcome_sha256,
            "feature_record_sha256": self.feature_record_sha256,
        }


@dataclass(frozen=True, slots=True)
class FrozenCadenceTrainingManifest:
    model_family: str
    feature_registry: tuple[str, ...]
    prospective_start_ms: int
    source: dict[str, object]
    training_rows: int
    training_first_target_end_ms: int | None
    training_last_target_end_ms: int | None
    rows_sha256: str
    rows: tuple[FrozenCadenceTrainingRow, ...]

    def __post_init__(self) -> None:
        if self.training_rows != len(self.rows):
            raise FrozenCadenceTrainingManifestError(
                "training_rows does not match rows length"
            )
        identities = tuple(row.identity for row in self.rows)
        if len(identities) != len(set(identities)):
            raise FrozenCadenceTrainingManifestError(
                "frozen training row identities must be unique"
            )
        expected = _sha256([row.payload() for row in self.rows])
        if self.rows_sha256 != expected:
            raise FrozenCadenceTrainingManifestError(
                "frozen training rows SHA-256 mismatch"
            )
        if self.rows:
            first = self.rows[0].target_end_ms
            last = self.rows[-1].target_end_ms
            if self.training_first_target_end_ms != first:
                raise FrozenCadenceTrainingManifestError(
                    "training_first_target_end_ms mismatch"
                )
            if self.training_last_target_end_ms != last:
                raise FrozenCadenceTrainingManifestError(
                    "training_last_target_end_ms mismatch"
                )
            if any(
                left.target_end_ms > right.target_end_ms
                for left, right in zip(
                    self.rows,
                    self.rows[1:],
                    strict=False,
                )
            ):
                raise FrozenCadenceTrainingManifestError(
                    "frozen training rows are not chronological"
                )
        elif (
            self.training_first_target_end_ms is not None
            or self.training_last_target_end_ms is not None
        ):
            raise FrozenCadenceTrainingManifestError(
                "empty training manifest has target bounds"
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
    rows_raw = root.get("rows")
    if not isinstance(rows_raw, list):
        raise FrozenCadenceTrainingManifestError(
            "rows must be an array"
        )
    rows: list[FrozenCadenceTrainingRow] = []
    for index, value in enumerate(rows_raw):
        row = _mapping(value, f"rows[{index}]")
        identity = _mapping(
            row.get("identity"),
            f"rows[{index}].identity",
        )
        rows.append(
            FrozenCadenceTrainingRow(
                cadence_ms=_integer(
                    identity.get("cadence_ms"),
                    f"rows[{index}].identity.cadence_ms",
                ),
                decision_id=_string(
                    identity.get("decision_id"),
                    f"rows[{index}].identity.decision_id",
                ),
                horizon_ms=_integer(
                    identity.get("horizon_ms"),
                    f"rows[{index}].identity.horizon_ms",
                ),
                target_end_ms=_integer(
                    row.get("target_end_ms"),
                    f"rows[{index}].target_end_ms",
                ),
                feature_snapshot_id=_string(
                    row.get("feature_snapshot_id"),
                    f"rows[{index}].feature_snapshot_id",
                ),
                outcome_sha256=_sha(
                    row.get("outcome_sha256"),
                    f"rows[{index}].outcome_sha256",
                ),
                feature_record_sha256=_sha(
                    row.get("feature_record_sha256"),
                    f"rows[{index}].feature_record_sha256",
                ),
            )
        )
    source = _mapping(root.get("source"), "source")
    first_raw = root.get("training_first_target_end_ms")
    last_raw = root.get("training_last_target_end_ms")
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
        source=source,
        training_rows=_integer(
            root.get("training_rows"),
            "training_rows",
        ),
        training_first_target_end_ms=(
            None
            if first_raw is None
            else _integer(
                first_raw,
                "training_first_target_end_ms",
            )
        ),
        training_last_target_end_ms=(
            None
            if last_raw is None
            else _integer(
                last_raw,
                "training_last_target_end_ms",
            )
        ),
        rows_sha256=_sha(
            root.get("rows_sha256"),
            "rows_sha256",
        ),
        rows=tuple(rows),
    )


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
    rows: list[FrozenCadenceTrainingRow] = []
    for outcome in selected:
        verified = feature_store.load(
            outcome.sample.feature_snapshot_id
        )
        if verified is None:
            raise FrozenCadenceTrainingManifestError(
                "freeze source feature snapshot missing"
            )
        if verified.snapshot.market != outcome.sample.market:
            raise FrozenCadenceTrainingManifestError(
                "freeze source feature market mismatch"
            )
        rows.append(
            FrozenCadenceTrainingRow(
                cadence_ms=outcome.sample.cadence_ms,
                decision_id=outcome.sample.decision_id,
                horizon_ms=outcome.sample.horizon_ms,
                target_end_ms=outcome.sample.target_end_ms,
                feature_snapshot_id=(
                    outcome.sample.feature_snapshot_id
                ),
                outcome_sha256=_sha256(
                    _outcome_payload(outcome)
                ),
                feature_record_sha256=verified.record_sha256,
            )
        )
    row_payloads = [row.payload() for row in rows]
    return FrozenCadenceTrainingManifest(
        model_family=model_family,
        feature_registry=feature_registry,
        prospective_start_ms=prospective_start_ms,
        source=dict(source),
        training_rows=len(rows),
        training_first_target_end_ms=(
            None if not rows else rows[0].target_end_ms
        ),
        training_last_target_end_ms=(
            None if not rows else rows[-1].target_end_ms
        ),
        rows_sha256=_sha256(row_payloads),
        rows=tuple(rows),
    )


def frozen_cadence_training_manifest_payload(
    manifest: FrozenCadenceTrainingManifest,
) -> dict[str, object]:
    return {
        "schema_version": FROZEN_TRAINING_MANIFEST_SCHEMA_VERSION,
        "model_family": manifest.model_family,
        "feature_registry": list(manifest.feature_registry),
        "prospective_start_ms": manifest.prospective_start_ms,
        "source": manifest.source,
        "training_rows": manifest.training_rows,
        "training_first_target_end_ms": (
            manifest.training_first_target_end_ms
        ),
        "training_last_target_end_ms": (
            manifest.training_last_target_end_ms
        ),
        "rows_sha256": manifest.rows_sha256,
        "rows": [row.payload() for row in manifest.rows],
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

    indexed: dict[tuple[int, str, int], ShadowCadenceOutcome] = {}
    for outcome in outcomes:
        key = (
            outcome.sample.cadence_ms,
            outcome.sample.decision_id,
            outcome.sample.horizon_ms,
        )
        if key in indexed:
            raise FrozenCadenceTrainingManifestError(
                "duplicate cadence outcome identity"
            )
        indexed[key] = outcome

    resolved: list[ShadowCadenceOutcome] = []
    for frozen in manifest.rows:
        if (
            frozen.cadence_ms != cadence_ms
            or frozen.horizon_ms != horizon_ms
        ):
            raise FrozenCadenceTrainingManifestError(
                "frozen manifest surface mismatch"
            )
        if frozen.target_end_ms >= prospective_start_ms:
            raise FrozenCadenceTrainingManifestError(
                "frozen manifest includes post-boundary label"
            )
        outcome = indexed.get(frozen.identity)
        if outcome is None:
            raise FrozenCadenceTrainingManifestError(
                "frozen training outcome missing"
            )
        if outcome.sample.target_end_ms != frozen.target_end_ms:
            raise FrozenCadenceTrainingManifestError(
                "frozen training target changed"
            )
        if (
            outcome.sample.feature_snapshot_id
            != frozen.feature_snapshot_id
        ):
            raise FrozenCadenceTrainingManifestError(
                "frozen training feature identity changed"
            )
        if _sha256(_outcome_payload(outcome)) != frozen.outcome_sha256:
            raise FrozenCadenceTrainingManifestError(
                "frozen training outcome content changed"
            )
        verified = feature_store.load(frozen.feature_snapshot_id)
        if verified is None:
            raise FrozenCadenceTrainingManifestError(
                "frozen training feature snapshot missing"
            )
        if verified.record_sha256 != frozen.feature_record_sha256:
            raise FrozenCadenceTrainingManifestError(
                "frozen training feature content changed"
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
        resolved.append(outcome)

    return tuple(resolved)
