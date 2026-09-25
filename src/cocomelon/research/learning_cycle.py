from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from cocomelon.research.learning_experiment import (
    LearningExperimentResult,
    run_learning_experiment,
    verify_learning_experiment,
)
from cocomelon.research.learning_feature_snapshots import LearningFeatureSnapshotStore
from cocomelon.research.learning_grouped_mean import GROUPED_MEAN_MODEL_FAMILY
from cocomelon.research.learning_readiness import (
    LearningReadinessReport,
    evaluate_learning_readiness,
)
from cocomelon.research.learning_tree import TREE_MODEL_FAMILY
from cocomelon.research.outcome_learning import (
    LearningEvidenceKind,
    LearningEvidenceLedger,
    LearningEvidenceRecord,
)

LEARNING_CYCLE_SCHEMA_VERSION = 1
MIN_TRAIN_ROWS = 200
VALIDATION_ROWS = 20
STABILITY_BLOCKS = 4
MIN_BLOCK_TRADES = 5
MIN_VALIDATION_TRADES = 20

BASELINE_FEATURES = (
    "market",
    "direction",
    "trend_regime",
    "volatility_regime",
)
TREE_FEATURES = (
    "market",
    "direction",
    "return_5m",
    "return_15m",
    "return_1h",
    "funding",
    "open_interest",
    "trend_regime",
    "volatility_regime",
)

BASELINE_MODEL_CONFIG: dict[str, object] = {
    "min_train_rows": MIN_TRAIN_ROWS,
    "validation_rows": VALIDATION_ROWS,
    "min_group_train_rows": 20,
}
TREE_MODEL_CONFIG: dict[str, object] = {
    "min_train_rows": MIN_TRAIN_ROWS,
    "validation_rows": VALIDATION_ROWS,
    "max_leaf_nodes": 7,
    "min_samples_leaf": 100,
    "learning_rate": "0.05",
    "max_iter": 100,
    "l2_regularization": "1",
}
DECISION_POLICY: dict[str, object] = {
    "prediction_threshold": "0",
    "stability_blocks": STABILITY_BLOCKS,
    "min_block_trades": MIN_BLOCK_TRADES,
    "min_validation_trades": MIN_VALIDATION_TRADES,
    "min_validation_mean_target": "0",
}


class LearningCycleError(RuntimeError):
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


def _require_sha256(value: str, field: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} must be lowercase SHA-256")


def _require_commit_sha(value: str) -> None:
    if len(value) != 40 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(
            "implementation_commit_sha must be lowercase 40-character git SHA"
        )


def _atomic_write(path: Path, payload: dict[str, object]) -> None:
    data = (_canonical_json(payload) + "\n").encode("utf-8")
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


def _ordered_eligible_records(
    ledger: LearningEvidenceLedger,
    *,
    as_of_ms: int,
) -> tuple[LearningEvidenceRecord, ...]:
    return tuple(
        sorted(
            (
                record
                for record in ledger.eligible_records(as_of_ms=as_of_ms)
                if record.kind is LearningEvidenceKind.PAPER_EXECUTION
            ),
            key=lambda record: (
                record.opened_at_ms,
                record.closed_at_ms,
                record.record_id,
            ),
        )
    )


def _temporal_capacity(
    records: tuple[LearningEvidenceRecord, ...],
) -> tuple[int, int, int | None]:
    if len(records) < VALIDATION_ROWS:
        return 0, len(records), None
    validation = records[-VALIDATION_ROWS:]
    validation_start = validation[0].opened_at_ms
    prefix = records[:-VALIDATION_ROWS]
    settled_train = tuple(
        record for record in prefix if record.closed_at_ms < validation_start
    )
    return len(settled_train), len(validation), validation_start


@dataclass(frozen=True, slots=True)
class LearningCycleResult:
    output_root: Path
    status: str
    as_of_ms: int
    learning_state_digest: str
    feature_state_digest: str
    eligible_record_count: int
    settled_train_record_count: int
    validation_record_count: int
    validation_start_opened_at_ms: int | None
    baseline_structurally_ready: bool
    tree_structurally_ready: bool
    baseline_experiment_id: str | None
    tree_experiment_id: str | None
    baseline_qualifies_development: bool | None
    tree_qualifies_development: bool | None
    research_only: bool = True
    promotion_eligible: bool = False
    execution_ready: bool = False
    schema_version: int = LEARNING_CYCLE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.status not in {"not_ready", "completed"}:
            raise ValueError("unsupported learning cycle status")
        _require_sha256(self.learning_state_digest, "learning_state_digest")
        _require_sha256(self.feature_state_digest, "feature_state_digest")
        if min(
            self.eligible_record_count,
            self.settled_train_record_count,
            self.validation_record_count,
        ) < 0:
            raise ValueError("learning cycle counts must be non-negative")
        if self.status == "completed":
            if self.baseline_experiment_id is None or self.tree_experiment_id is None:
                raise ValueError("completed learning cycle requires both experiments")
        if not self.research_only:
            raise ValueError("learning cycle must remain research-only")
        if self.promotion_eligible or self.execution_ready:
            raise ValueError("learning cycle cannot authorize promotion or execution")

    def identity_payload(self) -> dict[str, object]:
        return {
            "status": self.status,
            "as_of_ms": self.as_of_ms,
            "learning_state_digest": self.learning_state_digest,
            "feature_state_digest": self.feature_state_digest,
            "eligible_record_count": self.eligible_record_count,
            "settled_train_record_count": self.settled_train_record_count,
            "validation_record_count": self.validation_record_count,
            "validation_start_opened_at_ms": self.validation_start_opened_at_ms,
            "baseline_structurally_ready": self.baseline_structurally_ready,
            "tree_structurally_ready": self.tree_structurally_ready,
            "baseline_experiment_id": self.baseline_experiment_id,
            "tree_experiment_id": self.tree_experiment_id,
            "baseline_qualifies_development": (
                self.baseline_qualifies_development
            ),
            "tree_qualifies_development": self.tree_qualifies_development,
            "baseline_features": BASELINE_FEATURES,
            "tree_features": TREE_FEATURES,
            "baseline_model_config": BASELINE_MODEL_CONFIG,
            "tree_model_config": TREE_MODEL_CONFIG,
            "decision_policy": DECISION_POLICY,
            "research_only": self.research_only,
            "promotion_eligible": self.promotion_eligible,
            "execution_ready": self.execution_ready,
            "schema_version": self.schema_version,
        }

    @property
    def cycle_id(self) -> str:
        return _sha256_json(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "cycle_id": self.cycle_id,
            "output_root": str(self.output_root),
        }


def _feature_state_digest(
    baseline: LearningReadinessReport,
    tree: LearningReadinessReport,
) -> str:
    baseline_digest = baseline.feature_store_state_digest
    tree_digest = tree.feature_store_state_digest
    if baseline_digest is None or tree_digest is None:
        raise LearningCycleError("FEATURE_STATE_DIGEST_MISSING")
    if baseline_digest != tree_digest:
        raise LearningCycleError("FEATURE_STATE_DIGEST_MISMATCH")
    _require_sha256(baseline_digest, "feature_state_digest")
    return baseline_digest


def _persist_result(result: LearningCycleResult) -> None:
    _atomic_write(result.output_root / "cycle.json", result.to_dict())


def _verify_result(
    result: LearningExperimentResult,
    *,
    expected_output_root: Path,
    expected_model_family: str,
) -> LearningExperimentResult:
    verified = verify_learning_experiment(output_root=expected_output_root)
    if verified.experiment_id != result.experiment_id:
        raise LearningCycleError("LEARNING_EXPERIMENT_ID_MISMATCH")
    if verified.model_family != expected_model_family:
        raise LearningCycleError("LEARNING_EXPERIMENT_MODEL_FAMILY_MISMATCH")
    return verified


def run_learning_cycle(
    *,
    learning_root: Path,
    feature_store_dir: Path,
    output_root: Path,
    as_of_ms: int,
    implementation_commit_sha: str,
    expected_learning_state_digest: str,
    expected_feature_state_digest: str,
) -> LearningCycleResult:
    if as_of_ms < 0:
        raise ValueError("as_of_ms must be non-negative")
    _require_commit_sha(implementation_commit_sha)
    _require_sha256(
        expected_learning_state_digest,
        "expected_learning_state_digest",
    )
    _require_sha256(
        expected_feature_state_digest,
        "expected_feature_state_digest",
    )
    if output_root.exists() and any(output_root.iterdir()):
        raise LearningCycleError("LEARNING_CYCLE_OUTPUT_NOT_EMPTY")
    output_root.mkdir(parents=True, exist_ok=True)

    ledger = LearningEvidenceLedger(learning_root)
    if ledger.state_digest != expected_learning_state_digest:
        raise LearningCycleError("LEARNING_STATE_DIGEST_MISMATCH")

    feature_store = LearningFeatureSnapshotStore(feature_store_dir)
    baseline_readiness = evaluate_learning_readiness(
        ledger,
        feature_store=feature_store,
        as_of_ms=as_of_ms,
        evidence_kind=LearningEvidenceKind.PAPER_EXECUTION,
        feature_registry=BASELINE_FEATURES,
    )
    tree_readiness = evaluate_learning_readiness(
        ledger,
        feature_store=feature_store,
        as_of_ms=as_of_ms,
        evidence_kind=LearningEvidenceKind.PAPER_EXECUTION,
        feature_registry=TREE_FEATURES,
    )
    feature_state_digest = _feature_state_digest(
        baseline_readiness,
        tree_readiness,
    )
    if feature_state_digest != expected_feature_state_digest:
        raise LearningCycleError("EXPECTED_FEATURE_STATE_DIGEST_MISMATCH")
    if baseline_readiness.ledger_state_digest != expected_learning_state_digest:
        raise LearningCycleError("BASELINE_LEDGER_STATE_DIGEST_MISMATCH")
    if tree_readiness.ledger_state_digest != expected_learning_state_digest:
        raise LearningCycleError("TREE_LEDGER_STATE_DIGEST_MISMATCH")
    if baseline_readiness.eligible_record_ids != tree_readiness.eligible_record_ids:
        raise LearningCycleError("LEARNING_READY_RECORD_SET_MISMATCH")

    records = _ordered_eligible_records(ledger, as_of_ms=as_of_ms)
    eligible_ids = tuple(sorted(record.record_id for record in records))
    if eligible_ids != baseline_readiness.eligible_record_ids:
        raise LearningCycleError("LEARNING_READY_RECORD_IDENTITY_MISMATCH")

    train_count, validation_count, validation_start = _temporal_capacity(records)
    experiments_ready = (
        baseline_readiness.structurally_ready
        and tree_readiness.structurally_ready
        and train_count >= MIN_TRAIN_ROWS
        and validation_count == VALIDATION_ROWS
    )
    if not experiments_ready:
        result = LearningCycleResult(
            output_root=output_root,
            status="not_ready",
            as_of_ms=as_of_ms,
            learning_state_digest=expected_learning_state_digest,
            feature_state_digest=feature_state_digest,
            eligible_record_count=len(records),
            settled_train_record_count=train_count,
            validation_record_count=validation_count,
            validation_start_opened_at_ms=validation_start,
            baseline_structurally_ready=baseline_readiness.structurally_ready,
            tree_structurally_ready=tree_readiness.structurally_ready,
            baseline_experiment_id=None,
            tree_experiment_id=None,
            baseline_qualifies_development=None,
            tree_qualifies_development=None,
        )
        _persist_result(result)
        return result

    baseline_root = output_root / "baseline"
    baseline = run_learning_experiment(
        learning_root=learning_root,
        feature_store_dir=feature_store_dir,
        output_root=baseline_root,
        as_of_ms=as_of_ms,
        evidence_kind=LearningEvidenceKind.PAPER_EXECUTION,
        feature_registry=BASELINE_FEATURES,
        model_family=GROUPED_MEAN_MODEL_FAMILY,
        model_config=dict(BASELINE_MODEL_CONFIG),
        decision_policy=dict(DECISION_POLICY),
        implementation_commit_sha=implementation_commit_sha,
    )
    baseline_verified = _verify_result(
        baseline,
        expected_output_root=baseline_root,
        expected_model_family=GROUPED_MEAN_MODEL_FAMILY,
    )

    tree_root = output_root / "tree"
    tree = run_learning_experiment(
        learning_root=learning_root,
        feature_store_dir=feature_store_dir,
        output_root=tree_root,
        as_of_ms=as_of_ms,
        evidence_kind=LearningEvidenceKind.PAPER_EXECUTION,
        feature_registry=TREE_FEATURES,
        model_family=TREE_MODEL_FAMILY,
        model_config=dict(TREE_MODEL_CONFIG),
        decision_policy=dict(DECISION_POLICY),
        implementation_commit_sha=implementation_commit_sha,
    )
    tree_verified = _verify_result(
        tree,
        expected_output_root=tree_root,
        expected_model_family=TREE_MODEL_FAMILY,
    )

    result = LearningCycleResult(
        output_root=output_root,
        status="completed",
        as_of_ms=as_of_ms,
        learning_state_digest=expected_learning_state_digest,
        feature_state_digest=feature_state_digest,
        eligible_record_count=len(records),
        settled_train_record_count=train_count,
        validation_record_count=validation_count,
        validation_start_opened_at_ms=validation_start,
        baseline_structurally_ready=True,
        tree_structurally_ready=True,
        baseline_experiment_id=baseline_verified.experiment_id,
        tree_experiment_id=tree_verified.experiment_id,
        baseline_qualifies_development=(
            baseline_verified.qualifies_development
        ),
        tree_qualifies_development=tree_verified.qualifies_development,
    )
    _persist_result(result)
    return result
