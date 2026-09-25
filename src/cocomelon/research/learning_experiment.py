from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from cocomelon.research.learning_challenger_run import (
    LearningChallengerRunManifest,
    load_learning_challenger_run_manifest,
    verify_learning_challenger_run_manifest,
)
from cocomelon.research.learning_dataset_bundle import (
    VerifiedLearningDatasetBundle,
    load_verified_learning_dataset_bundle,
)
from cocomelon.research.learning_feature_snapshots import LearningFeatureSnapshotStore
from cocomelon.research.learning_grouped_mean import (
    GROUPED_MEAN_MODEL_FAMILY,
    evaluate_learning_grouped_mean,
    write_learning_grouped_mean_evaluation,
)
from cocomelon.research.learning_training_bundle import (
    VerifiedLearningTrainingBundle,
    load_verified_learning_training_bundle,
    verify_learning_training_bundle,
    write_learning_training_bundle,
)
from cocomelon.research.learning_training_rows import (
    SNAPSHOT_FEATURES,
    build_learning_training_set,
)
from cocomelon.research.learning_tree import (
    TREE_MODEL_FAMILY,
    evaluate_learning_tree,
    write_learning_tree_evaluation,
)

LEARNING_EXPERIMENT_SCHEMA_VERSION = 1
DATASET_DIRNAME = "dataset"
FEATURES_DIRNAME = "features"
TRAINING_DIRNAME = "training"
RUN_MANIFEST_FILENAME = "run-manifest.json"
EVALUATION_FILENAME = "evaluation.json"
EXPERIMENT_FILENAME = "experiment.json"


class LearningExperimentError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: object) -> str:
    return _sha256_bytes(_canonical_json(value).encode("utf-8"))


def _require_sha256(value: str, field: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} must be lowercase SHA-256")


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise LearningExperimentError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LearningExperimentError(f"{field} must be a non-empty string")
    return value


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _string(value, field)


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise LearningExperimentError(f"{field} must be an integer")
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise LearningExperimentError(f"{field} must be boolean")
    return value


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _copy_exact(source: Path, target: Path) -> None:
    try:
        data = source.read_bytes()
    except OSError as exc:
        raise LearningExperimentError(
            f"learning experiment source is unreadable: {source}"
        ) from exc
    _atomic_write(target, data)


@dataclass(frozen=True, slots=True)
class LearningExperimentManifest:
    dataset_id: str
    dataset_lineage_id: str
    dataset_manifest_sha256: str
    dataset_records_sha256: str
    run_id: str
    run_manifest_sha256: str
    training_set_id: str
    training_bundle_id: str
    training_manifest_sha256: str
    training_rows_sha256: str
    model_family: str
    evaluation_id: str
    evaluation_sha256: str
    feature_snapshot_count: int
    feature_snapshot_state_digest: str | None
    research_only: bool = True
    promotion_eligible: bool = False
    execution_ready: bool = False
    schema_version: int = LEARNING_EXPERIMENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in (
            "dataset_id",
            "dataset_lineage_id",
            "dataset_manifest_sha256",
            "dataset_records_sha256",
            "run_id",
            "run_manifest_sha256",
            "training_set_id",
            "training_bundle_id",
            "training_manifest_sha256",
            "training_rows_sha256",
            "evaluation_id",
            "evaluation_sha256",
        ):
            _require_sha256(getattr(self, field), field)
        if not self.model_family.strip():
            raise ValueError("model_family must not be empty")
        if self.feature_snapshot_count < 0:
            raise ValueError("feature_snapshot_count must be non-negative")
        if self.feature_snapshot_count == 0:
            if self.feature_snapshot_state_digest is not None:
                raise ValueError(
                    "feature snapshot digest must be None when no snapshots are bound"
                )
        else:
            if self.feature_snapshot_state_digest is None:
                raise ValueError(
                    "feature snapshot digest is required when snapshots are bound"
                )
            _require_sha256(
                self.feature_snapshot_state_digest,
                "feature_snapshot_state_digest",
            )
        if not self.research_only:
            raise ValueError("learning experiment must remain research-only")
        if self.promotion_eligible or self.execution_ready:
            raise ValueError("learning experiment cannot authorize promotion/execution")
        if self.schema_version != LEARNING_EXPERIMENT_SCHEMA_VERSION:
            raise ValueError("unsupported learning experiment schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "dataset_id": self.dataset_id,
            "dataset_lineage_id": self.dataset_lineage_id,
            "dataset_manifest_sha256": self.dataset_manifest_sha256,
            "dataset_records_sha256": self.dataset_records_sha256,
            "run_id": self.run_id,
            "run_manifest_sha256": self.run_manifest_sha256,
            "training_set_id": self.training_set_id,
            "training_bundle_id": self.training_bundle_id,
            "training_manifest_sha256": self.training_manifest_sha256,
            "training_rows_sha256": self.training_rows_sha256,
            "model_family": self.model_family,
            "evaluation_id": self.evaluation_id,
            "evaluation_sha256": self.evaluation_sha256,
            "feature_snapshot_count": self.feature_snapshot_count,
            "feature_snapshot_state_digest": self.feature_snapshot_state_digest,
            "research_only": self.research_only,
            "promotion_eligible": self.promotion_eligible,
            "execution_ready": self.execution_ready,
            "schema_version": self.schema_version,
        }

    @property
    def experiment_id(self) -> str:
        return _sha256_json(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "experiment_id": self.experiment_id}


def _copy_dataset_bundle(source: Path, target: Path) -> VerifiedLearningDatasetBundle:
    _copy_exact(source / "manifest.json", target / "manifest.json")
    _copy_exact(source / "records.jsonl", target / "records.jsonl")
    return load_verified_learning_dataset_bundle(output_dir=target)


def _copy_run_manifest(
    source: Path,
    target: Path,
    *,
    bundle: VerifiedLearningDatasetBundle,
) -> LearningChallengerRunManifest:
    _copy_exact(source, target)
    return verify_learning_challenger_run_manifest(target, bundle=bundle)


def _uses_snapshot_features(manifest: LearningChallengerRunManifest) -> bool:
    return any(feature in SNAPSHOT_FEATURES for feature in manifest.feature_registry)


def _copy_feature_subset(
    source_store: LearningFeatureSnapshotStore,
    target_root: Path,
    *,
    bundle: VerifiedLearningDatasetBundle,
    manifest: LearningChallengerRunManifest,
) -> LearningFeatureSnapshotStore:
    records = {
        record.record_id: record
        for record in bundle.snapshot.eligible_records
    }
    snapshot_ids: set[str] = set()
    for record_id in manifest.input_record_ids:
        record = records.get(record_id)
        if record is None:
            raise LearningExperimentError(
                "LEARNING_EXPERIMENT_INPUT_RECORD_MISSING"
            )
        snapshot_ids.add(record.feature_snapshot_id)

    target_store = LearningFeatureSnapshotStore(target_root)
    for snapshot_id in sorted(snapshot_ids):
        verified = source_store.load(snapshot_id)
        if verified is None:
            raise LearningExperimentError(
                "LEARNING_EXPERIMENT_FEATURE_SNAPSHOT_MISSING"
            )
        _copy_exact(
            source_store.records_root / f"{snapshot_id}.json",
            target_store.records_root / f"{snapshot_id}.json",
        )
        copied = target_store.load(snapshot_id)
        if copied is None or copied.record_sha256 != verified.record_sha256:
            raise LearningExperimentError(
                "LEARNING_EXPERIMENT_FEATURE_SNAPSHOT_COPY_MISMATCH"
            )
    return target_store


def _evaluation_identity(path: Path) -> tuple[dict[str, object], str, str]:
    try:
        encoded = path.read_bytes()
        raw = _mapping(json.loads(encoded), "learning evaluation")
    except (OSError, json.JSONDecodeError) as exc:
        raise LearningExperimentError(
            "LEARNING_EXPERIMENT_EVALUATION_INVALID"
        ) from exc
    canonical = (_canonical_json(raw) + "\n").encode("utf-8")
    if encoded != canonical:
        raise LearningExperimentError(
            "LEARNING_EXPERIMENT_EVALUATION_NON_CANONICAL"
        )
    evaluation_id = _string(raw.get("evaluation_id"), "evaluation_id")
    _require_sha256(evaluation_id, "evaluation_id")
    identity = dict(raw)
    identity.pop("evaluation_id", None)
    if _sha256_json(identity) != evaluation_id:
        raise LearningExperimentError(
            "LEARNING_EXPERIMENT_EVALUATION_IDENTITY_MISMATCH"
        )
    return raw, evaluation_id, _sha256_bytes(encoded)


def _evaluate(
    training_bundle: VerifiedLearningTrainingBundle,
    manifest: LearningChallengerRunManifest,
    output_path: Path,
) -> None:
    if manifest.model_family == GROUPED_MEAN_MODEL_FAMILY:
        result = evaluate_learning_grouped_mean(training_bundle, manifest)
        write_learning_grouped_mean_evaluation(output_path, result)
        return
    if manifest.model_family == TREE_MODEL_FAMILY:
        result = evaluate_learning_tree(training_bundle, manifest)
        write_learning_tree_evaluation(output_path, result)
        return
    raise LearningExperimentError(
        "LEARNING_EXPERIMENT_MODEL_FAMILY_UNSUPPORTED"
    )


def _experiment_manifest_from_payload(
    raw: dict[str, object],
) -> LearningExperimentManifest:
    try:
        return LearningExperimentManifest(
            dataset_id=_string(raw.get("dataset_id"), "dataset_id"),
            dataset_lineage_id=_string(
                raw.get("dataset_lineage_id"),
                "dataset_lineage_id",
            ),
            dataset_manifest_sha256=_string(
                raw.get("dataset_manifest_sha256"),
                "dataset_manifest_sha256",
            ),
            dataset_records_sha256=_string(
                raw.get("dataset_records_sha256"),
                "dataset_records_sha256",
            ),
            run_id=_string(raw.get("run_id"), "run_id"),
            run_manifest_sha256=_string(
                raw.get("run_manifest_sha256"),
                "run_manifest_sha256",
            ),
            training_set_id=_string(
                raw.get("training_set_id"),
                "training_set_id",
            ),
            training_bundle_id=_string(
                raw.get("training_bundle_id"),
                "training_bundle_id",
            ),
            training_manifest_sha256=_string(
                raw.get("training_manifest_sha256"),
                "training_manifest_sha256",
            ),
            training_rows_sha256=_string(
                raw.get("training_rows_sha256"),
                "training_rows_sha256",
            ),
            model_family=_string(raw.get("model_family"), "model_family"),
            evaluation_id=_string(raw.get("evaluation_id"), "evaluation_id"),
            evaluation_sha256=_string(
                raw.get("evaluation_sha256"),
                "evaluation_sha256",
            ),
            feature_snapshot_count=_integer(
                raw.get("feature_snapshot_count"),
                "feature_snapshot_count",
            ),
            feature_snapshot_state_digest=_optional_string(
                raw.get("feature_snapshot_state_digest"),
                "feature_snapshot_state_digest",
            ),
            research_only=_boolean(raw.get("research_only"), "research_only"),
            promotion_eligible=_boolean(
                raw.get("promotion_eligible"),
                "promotion_eligible",
            ),
            execution_ready=_boolean(
                raw.get("execution_ready"),
                "execution_ready",
            ),
            schema_version=_integer(raw.get("schema_version"), "schema_version"),
        )
    except ValueError as exc:
        raise LearningExperimentError(
            "LEARNING_EXPERIMENT_MANIFEST_INVALID"
        ) from exc


def load_verified_learning_experiment(
    output_dir: Path,
) -> LearningExperimentManifest:
    experiment_path = output_dir / EXPERIMENT_FILENAME
    try:
        encoded = experiment_path.read_bytes()
        raw = _mapping(json.loads(encoded), "learning experiment manifest")
    except (OSError, json.JSONDecodeError) as exc:
        raise LearningExperimentError(
            "LEARNING_EXPERIMENT_MANIFEST_INVALID"
        ) from exc

    manifest = _experiment_manifest_from_payload(raw)
    if _canonical_json(raw) != _canonical_json(manifest.to_dict()):
        raise LearningExperimentError(
            "LEARNING_EXPERIMENT_MANIFEST_IDENTITY_MISMATCH"
        )
    if encoded != (_canonical_json(manifest.to_dict()) + "\n").encode("utf-8"):
        raise LearningExperimentError(
            "LEARNING_EXPERIMENT_MANIFEST_NON_CANONICAL"
        )

    dataset = load_verified_learning_dataset_bundle(
        output_dir=output_dir / DATASET_DIRNAME,
    )
    run_manifest = verify_learning_challenger_run_manifest(
        output_dir / RUN_MANIFEST_FILENAME,
        bundle=dataset,
    )
    training = verify_learning_training_bundle(
        output_dir=output_dir / TRAINING_DIRNAME,
        manifest=run_manifest,
    )
    evaluation, evaluation_id, evaluation_sha256 = _evaluation_identity(
        output_dir / EVALUATION_FILENAME
    )

    if dataset.snapshot.manifest.dataset_id != manifest.dataset_id:
        raise LearningExperimentError("LEARNING_EXPERIMENT_DATASET_ID_MISMATCH")
    if dataset.lineage_id != manifest.dataset_lineage_id:
        raise LearningExperimentError(
            "LEARNING_EXPERIMENT_DATASET_LINEAGE_MISMATCH"
        )
    if dataset.manifest_sha256 != manifest.dataset_manifest_sha256:
        raise LearningExperimentError(
            "LEARNING_EXPERIMENT_DATASET_MANIFEST_DIGEST_MISMATCH"
        )
    if dataset.records_sha256 != manifest.dataset_records_sha256:
        raise LearningExperimentError(
            "LEARNING_EXPERIMENT_DATASET_RECORDS_DIGEST_MISMATCH"
        )
    if run_manifest.run_id != manifest.run_id:
        raise LearningExperimentError("LEARNING_EXPERIMENT_RUN_ID_MISMATCH")
    run_bytes = (output_dir / RUN_MANIFEST_FILENAME).read_bytes()
    if _sha256_bytes(run_bytes) != manifest.run_manifest_sha256:
        raise LearningExperimentError(
            "LEARNING_EXPERIMENT_RUN_MANIFEST_DIGEST_MISMATCH"
        )
    if training.training_set.training_set_id != manifest.training_set_id:
        raise LearningExperimentError(
            "LEARNING_EXPERIMENT_TRAINING_SET_ID_MISMATCH"
        )
    if training.bundle_id != manifest.training_bundle_id:
        raise LearningExperimentError(
            "LEARNING_EXPERIMENT_TRAINING_BUNDLE_ID_MISMATCH"
        )
    if training.manifest_sha256 != manifest.training_manifest_sha256:
        raise LearningExperimentError(
            "LEARNING_EXPERIMENT_TRAINING_MANIFEST_DIGEST_MISMATCH"
        )
    if training.rows_sha256 != manifest.training_rows_sha256:
        raise LearningExperimentError(
            "LEARNING_EXPERIMENT_TRAINING_ROWS_DIGEST_MISMATCH"
        )
    if run_manifest.model_family != manifest.model_family:
        raise LearningExperimentError(
            "LEARNING_EXPERIMENT_MODEL_FAMILY_MISMATCH"
        )
    if evaluation_id != manifest.evaluation_id:
        raise LearningExperimentError(
            "LEARNING_EXPERIMENT_EVALUATION_ID_MISMATCH"
        )
    if evaluation_sha256 != manifest.evaluation_sha256:
        raise LearningExperimentError(
            "LEARNING_EXPERIMENT_EVALUATION_DIGEST_MISMATCH"
        )
    for field, expected in (
        ("run_id", run_manifest.run_id),
        ("training_bundle_id", training.bundle_id),
        ("training_set_id", training.training_set.training_set_id),
        ("dataset_lineage_id", dataset.lineage_id),
        ("model_family", run_manifest.model_family),
    ):
        if evaluation.get(field) != expected:
            raise LearningExperimentError(
                f"LEARNING_EXPERIMENT_EVALUATION_{field.upper()}_MISMATCH"
            )
    if (
        evaluation.get("research_only") is not True
        or evaluation.get("promotion_eligible") is not False
        or evaluation.get("execution_ready") is not False
    ):
        raise LearningExperimentError(
            "LEARNING_EXPERIMENT_EVALUATION_AUTHORITY_INVALID"
        )

    if _uses_snapshot_features(run_manifest):
        feature_store = LearningFeatureSnapshotStore(
            output_dir / FEATURES_DIRNAME
        )
        verified_features = feature_store.iter_verified()
        expected_snapshot_ids = tuple(
            sorted(
                {
                    row.feature_snapshot_id
                    for row in training.training_set.rows
                }
            )
        )
        actual_snapshot_ids = tuple(
            sorted(item.snapshot.snapshot_id for item in verified_features)
        )
        if actual_snapshot_ids != expected_snapshot_ids:
            raise LearningExperimentError(
                "LEARNING_EXPERIMENT_FEATURE_SNAPSHOT_SET_MISMATCH"
            )
        if len(verified_features) != manifest.feature_snapshot_count:
            raise LearningExperimentError(
                "LEARNING_EXPERIMENT_FEATURE_SNAPSHOT_COUNT_MISMATCH"
            )
        if feature_store.state_digest != manifest.feature_snapshot_state_digest:
            raise LearningExperimentError(
                "LEARNING_EXPERIMENT_FEATURE_SNAPSHOT_DIGEST_MISMATCH"
            )
    elif (
        manifest.feature_snapshot_count != 0
        or manifest.feature_snapshot_state_digest is not None
    ):
        raise LearningExperimentError(
            "LEARNING_EXPERIMENT_UNEXPECTED_FEATURE_SNAPSHOTS"
        )

    return manifest


def materialize_learning_experiment(
    *,
    dataset_bundle_dir: Path,
    run_manifest_path: Path,
    output_dir: Path,
    feature_store_dir: Path | None = None,
) -> LearningExperimentManifest:
    if output_dir.exists():
        raise LearningExperimentError(
            "learning experiment output directory must not already exist"
        )
    temporary = output_dir.with_name(f".{output_dir.name}.tmp")
    if temporary.exists():
        raise LearningExperimentError(
            "learning experiment temporary directory already exists"
        )
    temporary.parent.mkdir(parents=True, exist_ok=True)
    temporary.mkdir()

    try:
        dataset = _copy_dataset_bundle(
            dataset_bundle_dir,
            temporary / DATASET_DIRNAME,
        )
        run_manifest = _copy_run_manifest(
            run_manifest_path,
            temporary / RUN_MANIFEST_FILENAME,
            bundle=dataset,
        )

        feature_store: LearningFeatureSnapshotStore | None = None
        if _uses_snapshot_features(run_manifest):
            if feature_store_dir is None:
                raise LearningExperimentError(
                    "snapshot-backed experiment requires a feature store"
                )
            if not feature_store_dir.is_dir():
                raise LearningExperimentError(
                    "feature store directory must already exist"
                )
            source_store = LearningFeatureSnapshotStore(feature_store_dir)
            feature_store = _copy_feature_subset(
                source_store,
                temporary / FEATURES_DIRNAME,
                bundle=dataset,
                manifest=run_manifest,
            )

        training_set = build_learning_training_set(
            dataset,
            run_manifest,
            feature_store=feature_store,
        )
        write_learning_training_bundle(
            training_set,
            output_dir=temporary / TRAINING_DIRNAME,
        )
        training = load_verified_learning_training_bundle(
            output_dir=temporary / TRAINING_DIRNAME,
        )
        _evaluate(
            training,
            run_manifest,
            temporary / EVALUATION_FILENAME,
        )
        _evaluation, evaluation_id, evaluation_sha256 = _evaluation_identity(
            temporary / EVALUATION_FILENAME
        )

        feature_snapshot_count = 0
        feature_snapshot_state_digest: str | None = None
        if feature_store is not None:
            feature_snapshot_count = len(feature_store.iter_verified())
            feature_snapshot_state_digest = feature_store.state_digest

        run_manifest_bytes = (temporary / RUN_MANIFEST_FILENAME).read_bytes()
        manifest = LearningExperimentManifest(
            dataset_id=dataset.snapshot.manifest.dataset_id,
            dataset_lineage_id=dataset.lineage_id,
            dataset_manifest_sha256=dataset.manifest_sha256,
            dataset_records_sha256=dataset.records_sha256,
            run_id=run_manifest.run_id,
            run_manifest_sha256=_sha256_bytes(run_manifest_bytes),
            training_set_id=training.training_set.training_set_id,
            training_bundle_id=training.bundle_id,
            training_manifest_sha256=training.manifest_sha256,
            training_rows_sha256=training.rows_sha256,
            model_family=run_manifest.model_family,
            evaluation_id=evaluation_id,
            evaluation_sha256=evaluation_sha256,
            feature_snapshot_count=feature_snapshot_count,
            feature_snapshot_state_digest=feature_snapshot_state_digest,
        )
        _atomic_write(
            temporary / EXPERIMENT_FILENAME,
            (_canonical_json(manifest.to_dict()) + "\n").encode("utf-8"),
        )
        verified = load_verified_learning_experiment(temporary)
        os.replace(temporary, output_dir)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise

    return verified
