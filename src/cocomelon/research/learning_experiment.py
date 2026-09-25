from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from cocomelon.research.learning_challenger_run import (
    LearningChallengerRunManifest,
    build_learning_challenger_run_manifest,
    load_learning_challenger_run_manifest,
    write_learning_challenger_run_manifest,
)
from cocomelon.research.learning_dataset import build_learning_dataset_snapshot
from cocomelon.research.learning_dataset_bundle import (
    load_verified_learning_dataset_bundle,
    write_learning_dataset_bundle,
)
from cocomelon.research.learning_feature_snapshots import LearningFeatureSnapshotStore
from cocomelon.research.learning_grouped_mean import (
    GROUPED_MEAN_MODEL_FAMILY,
    evaluate_learning_grouped_mean,
    write_learning_grouped_mean_evaluation,
)
from cocomelon.research.learning_training_bundle import (
    verify_learning_training_bundle,
    write_learning_training_bundle,
)
from cocomelon.research.learning_training_rows import build_learning_training_set
from cocomelon.research.learning_tree import (
    TREE_MODEL_FAMILY,
    evaluate_learning_tree,
    write_learning_tree_evaluation,
)
from cocomelon.research.outcome_learning import (
    LearningEvidenceKind,
    LearningEvidenceLedger,
)

LEARNING_EXPERIMENT_SCHEMA_VERSION = 1
SUPPORTED_MODEL_FAMILIES = frozenset(
    {
        GROUPED_MEAN_MODEL_FAMILY,
        TREE_MODEL_FAMILY,
    }
)


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


def _atomic_write(path: Path, data: bytes) -> None:
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


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise LearningExperimentError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LearningExperimentError(f"{field} must be a non-empty string")
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise LearningExperimentError(f"{field} must be boolean")
    return value


@dataclass(frozen=True, slots=True)
class LearningExperimentResult:
    output_root: Path
    experiment_id: str
    dataset_id: str
    dataset_lineage_id: str
    run_id: str
    training_set_id: str
    training_bundle_id: str
    evaluation_id: str
    model_family: str
    qualifies_development: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "output_root": str(self.output_root),
            "experiment_id": self.experiment_id,
            "dataset_id": self.dataset_id,
            "dataset_lineage_id": self.dataset_lineage_id,
            "run_id": self.run_id,
            "training_set_id": self.training_set_id,
            "training_bundle_id": self.training_bundle_id,
            "evaluation_id": self.evaluation_id,
            "model_family": self.model_family,
            "qualifies_development": self.qualifies_development,
            "research_only": True,
            "promotion_eligible": False,
            "execution_ready": False,
        }


def _evaluate(
    *,
    model_family: str,
    training_bundle_dir: Path,
    manifest: LearningChallengerRunManifest,
    output_path: Path,
) -> tuple[str, bool]:
    verified = verify_learning_training_bundle(
        output_dir=training_bundle_dir,
        manifest=manifest,
    )
    if model_family == GROUPED_MEAN_MODEL_FAMILY:
        evaluation = evaluate_learning_grouped_mean(verified, manifest)
        write_learning_grouped_mean_evaluation(output_path, evaluation)
        return evaluation.evaluation_id, evaluation.qualifies_development
    if model_family == TREE_MODEL_FAMILY:
        evaluation = evaluate_learning_tree(verified, manifest)
        write_learning_tree_evaluation(output_path, evaluation)
        return evaluation.evaluation_id, evaluation.qualifies_development
    raise LearningExperimentError(
        f"unsupported learning experiment model family: {model_family}"
    )


def run_learning_experiment(
    *,
    learning_root: Path,
    feature_store_dir: Path,
    output_root: Path,
    as_of_ms: int,
    evidence_kind: LearningEvidenceKind,
    feature_registry: tuple[str, ...],
    model_family: str,
    model_config: dict[str, object],
    decision_policy: dict[str, object],
    implementation_commit_sha: str,
) -> LearningExperimentResult:
    if model_family not in SUPPORTED_MODEL_FAMILIES:
        raise LearningExperimentError(
            f"unsupported learning experiment model family: {model_family}"
        )
    if evidence_kind not in {
        LearningEvidenceKind.PROSPECTIVE_PAPER,
        LearningEvidenceKind.PAPER_EXECUTION,
        LearningEvidenceKind.LIVE_EXECUTION,
    }:
        raise LearningExperimentError("unsupported learning evidence kind")
    if output_root.exists() and any(output_root.iterdir()):
        raise LearningExperimentError(
            "learning experiment output directory must be empty"
        )
    output_root.mkdir(parents=True, exist_ok=True)

    ledger = LearningEvidenceLedger(learning_root)
    snapshot = build_learning_dataset_snapshot(ledger, as_of_ms=as_of_ms)
    dataset_dir = output_root / "dataset"
    write_learning_dataset_bundle(snapshot, output_dir=dataset_dir)
    bundle = load_verified_learning_dataset_bundle(output_dir=dataset_dir)

    manifest = build_learning_challenger_run_manifest(
        bundle,
        input_kinds=(evidence_kind,),
        feature_registry=feature_registry,
        model_family=model_family,
        model_config=model_config,
        decision_policy=decision_policy,
        implementation_commit_sha=implementation_commit_sha,
    )
    manifest_path = output_root / "challenger-run.json"
    write_learning_challenger_run_manifest(manifest_path, manifest)

    feature_store = LearningFeatureSnapshotStore(feature_store_dir)
    training_set = build_learning_training_set(
        bundle,
        manifest,
        feature_store=feature_store,
    )
    training_dir = output_root / "training"
    write_learning_training_bundle(training_set, output_dir=training_dir)
    verified_training = verify_learning_training_bundle(
        output_dir=training_dir,
        manifest=manifest,
    )

    evaluation_path = output_root / "evaluation.json"
    evaluation_id, qualifies_development = _evaluate(
        model_family=model_family,
        training_bundle_dir=training_dir,
        manifest=manifest,
        output_path=evaluation_path,
    )

    summary_payload: dict[str, object] = {
        "schema_version": LEARNING_EXPERIMENT_SCHEMA_VERSION,
        "as_of_ms": as_of_ms,
        "evidence_kind": evidence_kind.value,
        "model_family": model_family,
        "dataset_id": bundle.snapshot.manifest.dataset_id,
        "dataset_lineage_id": bundle.lineage_id,
        "dataset_manifest_sha256": bundle.manifest_sha256,
        "dataset_records_sha256": bundle.records_sha256,
        "learning_state_digest": snapshot.manifest.ledger_state_digest,
        "feature_store_state_digest": feature_store.state_digest,
        "run_id": manifest.run_id,
        "feature_registry": manifest.feature_registry,
        "feature_registry_id": manifest.feature_registry_id,
        "model_config_id": manifest.model_config_id,
        "decision_policy_id": manifest.decision_policy_id,
        "implementation_commit_sha": implementation_commit_sha,
        "training_set_id": verified_training.training_set.training_set_id,
        "training_bundle_id": verified_training.bundle_id,
        "evaluation_id": evaluation_id,
        "qualifies_development": qualifies_development,
        "research_only": True,
        "promotion_eligible": False,
        "execution_ready": False,
    }
    experiment_id = _sha256_bytes(
        _canonical_json(summary_payload).encode("utf-8")
    )
    persisted = {
        **summary_payload,
        "experiment_id": experiment_id,
    }
    summary_bytes = (_canonical_json(persisted) + "\n").encode("utf-8")
    _atomic_write(output_root / "experiment.json", summary_bytes)

    return LearningExperimentResult(
        output_root=output_root,
        experiment_id=experiment_id,
        dataset_id=bundle.snapshot.manifest.dataset_id,
        dataset_lineage_id=bundle.lineage_id,
        run_id=manifest.run_id,
        training_set_id=verified_training.training_set.training_set_id,
        training_bundle_id=verified_training.bundle_id,
        evaluation_id=evaluation_id,
        model_family=model_family,
        qualifies_development=qualifies_development,
    )



def verify_learning_experiment(
    *,
    output_root: Path,
) -> LearningExperimentResult:
    summary_path = output_root / "experiment.json"
    try:
        summary_bytes = summary_path.read_bytes()
        summary = _mapping(
            json.loads(summary_bytes),
            "learning experiment manifest",
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise LearningExperimentError(
            "LEARNING_EXPERIMENT_MANIFEST_INVALID"
        ) from exc

    stored_experiment_id = _string(
        summary.get("experiment_id"),
        "experiment_id",
    )
    identity_payload = dict(summary)
    identity_payload.pop("experiment_id", None)
    if _sha256_bytes(_canonical_json(identity_payload).encode("utf-8")) != (
        stored_experiment_id
    ):
        raise LearningExperimentError(
            "LEARNING_EXPERIMENT_IDENTITY_MISMATCH"
        )
    if summary_bytes != (_canonical_json(summary) + "\n").encode("utf-8"):
        raise LearningExperimentError(
            "LEARNING_EXPERIMENT_MANIFEST_NON_CANONICAL"
        )
    if summary.get("schema_version") != LEARNING_EXPERIMENT_SCHEMA_VERSION:
        raise LearningExperimentError(
            "LEARNING_EXPERIMENT_SCHEMA_UNSUPPORTED"
        )
    if (
        not _boolean(summary.get("research_only"), "research_only")
        or _boolean(summary.get("promotion_eligible"), "promotion_eligible")
        or _boolean(summary.get("execution_ready"), "execution_ready")
    ):
        raise LearningExperimentError(
            "LEARNING_EXPERIMENT_AUTHORITY_INVALID"
        )

    dataset = load_verified_learning_dataset_bundle(
        output_dir=output_root / "dataset",
    )
    manifest = load_learning_challenger_run_manifest(
        output_root / "challenger-run.json"
    )
    training = verify_learning_training_bundle(
        output_dir=output_root / "training",
        manifest=manifest,
    )

    evaluation_path = output_root / "evaluation.json"
    try:
        evaluation_bytes = evaluation_path.read_bytes()
        evaluation = _mapping(
            json.loads(evaluation_bytes),
            "learning experiment evaluation",
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise LearningExperimentError(
            "LEARNING_EXPERIMENT_EVALUATION_INVALID"
        ) from exc
    evaluation_id = _string(
        evaluation.get("evaluation_id"),
        "evaluation_id",
    )
    evaluation_identity = dict(evaluation)
    evaluation_identity.pop("evaluation_id", None)
    if _sha256_bytes(
        _canonical_json(evaluation_identity).encode("utf-8")
    ) != evaluation_id:
        raise LearningExperimentError(
            "LEARNING_EXPERIMENT_EVALUATION_IDENTITY_MISMATCH"
        )
    if evaluation_bytes != (_canonical_json(evaluation) + "\n").encode("utf-8"):
        raise LearningExperimentError(
            "LEARNING_EXPERIMENT_EVALUATION_NON_CANONICAL"
        )
    if (
        not _boolean(evaluation.get("research_only"), "evaluation research_only")
        or _boolean(
            evaluation.get("promotion_eligible"),
            "evaluation promotion_eligible",
        )
        or _boolean(evaluation.get("execution_ready"), "evaluation execution_ready")
    ):
        raise LearningExperimentError(
            "LEARNING_EXPERIMENT_EVALUATION_AUTHORITY_INVALID"
        )

    expected = {
        "dataset_id": dataset.snapshot.manifest.dataset_id,
        "dataset_lineage_id": dataset.lineage_id,
        "dataset_manifest_sha256": dataset.manifest_sha256,
        "dataset_records_sha256": dataset.records_sha256,
        "learning_state_digest": dataset.snapshot.manifest.ledger_state_digest,
        "run_id": manifest.run_id,
        "feature_registry_id": manifest.feature_registry_id,
        "model_config_id": manifest.model_config_id,
        "decision_policy_id": manifest.decision_policy_id,
        "implementation_commit_sha": manifest.implementation_commit_sha,
        "training_set_id": training.training_set.training_set_id,
        "training_bundle_id": training.bundle_id,
        "evaluation_id": evaluation_id,
        "model_family": manifest.model_family,
    }
    for field, value in expected.items():
        if summary.get(field) != value:
            raise LearningExperimentError(
                f"LEARNING_EXPERIMENT_LINEAGE_MISMATCH:{field}"
            )
    if evaluation.get("run_id") != manifest.run_id:
        raise LearningExperimentError(
            "LEARNING_EXPERIMENT_EVALUATION_RUN_MISMATCH"
        )
    if evaluation.get("training_bundle_id") != training.bundle_id:
        raise LearningExperimentError(
            "LEARNING_EXPERIMENT_EVALUATION_BUNDLE_MISMATCH"
        )
    if evaluation.get("model_family") != manifest.model_family:
        raise LearningExperimentError(
            "LEARNING_EXPERIMENT_EVALUATION_MODEL_MISMATCH"
        )

    qualifies_development = _boolean(
        evaluation.get("qualifies_development"),
        "qualifies_development",
    )
    if summary.get("qualifies_development") is not qualifies_development:
        raise LearningExperimentError(
            "LEARNING_EXPERIMENT_QUALIFICATION_MISMATCH"
        )

    return LearningExperimentResult(
        output_root=output_root,
        experiment_id=stored_experiment_id,
        dataset_id=dataset.snapshot.manifest.dataset_id,
        dataset_lineage_id=dataset.lineage_id,
        run_id=manifest.run_id,
        training_set_id=training.training_set.training_set_id,
        training_bundle_id=training.bundle_id,
        evaluation_id=evaluation_id,
        model_family=manifest.model_family,
        qualifies_development=qualifies_development,
    )
