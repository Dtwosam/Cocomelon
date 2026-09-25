from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from cocomelon.research.learning_candidate_package import (
    verify_learning_candidate_package,
)
from cocomelon.research.learning_clean_evidence import LearningCleanEvidenceStore
from cocomelon.research.learning_clean_validation_spec import (
    verify_learning_clean_validation_spec,
)

LEARNING_CLEAN_STATE_SCHEMA_VERSION = 1


class LearningCleanStateError(RuntimeError):
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
        raise ValueError(f"{field} must be a lowercase SHA-256 identity")


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise LearningCleanStateError(f"{field} must be a JSON object")
    return cast(dict[str, object], value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LearningCleanStateError(f"{field} must be a non-empty string")
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LearningCleanStateError(f"{field} must be a non-negative integer")
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise LearningCleanStateError(f"{field} must be boolean")
    return value


@dataclass(frozen=True, slots=True)
class LearningCleanState:
    candidate_id: str
    candidate_package_id: str
    validation_spec_id: str
    model_family: str
    validation_start_ms: int
    as_of_ms: int
    clean_evidence_state_digest: str
    prediction_count: int
    settled_outcome_count: int
    unsettled_trade_prediction_count: int
    target_settled_trades: int
    status: str
    paper_only: bool = True
    prospective_only: bool = True
    research_only: bool = True
    promotion_eligible: bool = False
    execution_ready: bool = False
    schema_version: int = LEARNING_CLEAN_STATE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in (
            "candidate_id",
            "candidate_package_id",
            "validation_spec_id",
            "clean_evidence_state_digest",
        ):
            _require_sha256(getattr(self, field), field)
        if not self.model_family.strip():
            raise ValueError("model_family must not be empty")
        if self.validation_start_ms < 0 or self.as_of_ms < 0:
            raise ValueError("clean state timestamps must be non-negative")
        for field in (
            "prediction_count",
            "settled_outcome_count",
            "unsettled_trade_prediction_count",
            "target_settled_trades",
        ):
            if getattr(self, field) < 0:
                raise ValueError(f"{field} must be non-negative")
        if self.target_settled_trades <= 0:
            raise ValueError("target_settled_trades must be positive")
        if self.settled_outcome_count > self.prediction_count:
            raise ValueError("settled outcomes cannot exceed predictions")
        if self.unsettled_trade_prediction_count > self.prediction_count:
            raise ValueError("unsettled trade predictions cannot exceed predictions")
        if self.status not in {
            "waiting_for_validation_start",
            "collecting",
            "ready_to_score",
        }:
            raise ValueError("unsupported learning clean state status")
        if self.status == "waiting_for_validation_start":
            if self.as_of_ms >= self.validation_start_ms:
                raise ValueError("waiting state must precede validation start")
            if self.prediction_count or self.settled_outcome_count:
                raise ValueError("pre-validation state must not contain clean evidence")
        elif self.status == "collecting":
            if self.as_of_ms < self.validation_start_ms:
                raise ValueError("collecting state cannot predate validation start")
            if self.settled_outcome_count >= self.target_settled_trades:
                raise ValueError("collecting state must remain below target outcomes")
        else:
            if self.as_of_ms < self.validation_start_ms:
                raise ValueError("ready state cannot predate validation start")
            if self.settled_outcome_count < self.target_settled_trades:
                raise ValueError("ready state requires target settled outcomes")
        if not self.paper_only or not self.prospective_only or not self.research_only:
            raise ValueError("clean state must remain prospective paper research")
        if self.promotion_eligible:
            raise ValueError("clean state cannot authorize promotion")
        if self.execution_ready:
            raise ValueError("clean state cannot authorize execution")
        if self.schema_version != LEARNING_CLEAN_STATE_SCHEMA_VERSION:
            raise ValueError("unsupported learning clean state schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "candidate_package_id": self.candidate_package_id,
            "validation_spec_id": self.validation_spec_id,
            "model_family": self.model_family,
            "validation_start_ms": self.validation_start_ms,
            "as_of_ms": self.as_of_ms,
            "clean_evidence_state_digest": self.clean_evidence_state_digest,
            "prediction_count": self.prediction_count,
            "settled_outcome_count": self.settled_outcome_count,
            "unsettled_trade_prediction_count": self.unsettled_trade_prediction_count,
            "target_settled_trades": self.target_settled_trades,
            "status": self.status,
            "paper_only": self.paper_only,
            "prospective_only": self.prospective_only,
            "research_only": self.research_only,
            "promotion_eligible": self.promotion_eligible,
            "execution_ready": self.execution_ready,
            "schema_version": self.schema_version,
        }

    @property
    def state_id(self) -> str:
        return _sha256_json(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "state_id": self.state_id}


def build_learning_clean_state(
    *,
    package_root: Path,
    validation_spec_path: Path,
    evidence_root: Path,
    as_of_ms: int,
) -> LearningCleanState:
    if as_of_ms < 0:
        raise ValueError("as_of_ms must be non-negative")

    package = verify_learning_candidate_package(package_root)
    spec = verify_learning_clean_validation_spec(
        validation_spec_path,
        package_root=package_root,
    )
    if package.candidate_id != spec.candidate_id:
        raise LearningCleanStateError("LEARNING_CLEAN_STATE_CANDIDATE_MISMATCH")
    if package.package_id != spec.candidate_package_id:
        raise LearningCleanStateError("LEARNING_CLEAN_STATE_PACKAGE_MISMATCH")

    store = LearningCleanEvidenceStore(evidence_root, spec=spec)
    store.verify()
    predictions = store.iter_predictions()
    outcomes = store.iter_outcomes()
    if any(item.observed_at_ms > as_of_ms for item in predictions):
        raise LearningCleanStateError("LEARNING_CLEAN_STATE_FUTURE_PREDICTION")
    if any(item.closed_at_ms > as_of_ms for item in outcomes):
        raise LearningCleanStateError("LEARNING_CLEAN_STATE_FUTURE_OUTCOME")

    unsettled = store.unsettled_trade_prediction_ids
    if as_of_ms < spec.validation_start_ms:
        status = "waiting_for_validation_start"
    elif len(outcomes) < spec.target_settled_trades:
        status = "collecting"
    else:
        status = "ready_to_score"

    return LearningCleanState(
        candidate_id=spec.candidate_id,
        candidate_package_id=spec.candidate_package_id,
        validation_spec_id=spec.spec_id,
        model_family=spec.model_family,
        validation_start_ms=spec.validation_start_ms,
        as_of_ms=as_of_ms,
        clean_evidence_state_digest=store.state_digest,
        prediction_count=len(predictions),
        settled_outcome_count=len(outcomes),
        unsettled_trade_prediction_count=len(unsettled),
        target_settled_trades=spec.target_settled_trades,
        status=status,
    )


def write_learning_clean_state(
    output_root: Path,
    state: LearningCleanState,
) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / "state.json"
    payload = (_canonical_json(state.to_dict()) + "\n").encode("utf-8")
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise LearningCleanStateError("LEARNING_CLEAN_STATE_CONFLICT")
        return path
    temporary = output_root / ".state.json.tmp"
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return path


def _state_from_payload(raw: dict[str, object]) -> LearningCleanState:
    try:
        state = LearningCleanState(
            candidate_id=_string(raw.get("candidate_id"), "candidate_id"),
            candidate_package_id=_string(
                raw.get("candidate_package_id"),
                "candidate_package_id",
            ),
            validation_spec_id=_string(
                raw.get("validation_spec_id"),
                "validation_spec_id",
            ),
            model_family=_string(raw.get("model_family"), "model_family"),
            validation_start_ms=_integer(
                raw.get("validation_start_ms"),
                "validation_start_ms",
            ),
            as_of_ms=_integer(raw.get("as_of_ms"), "as_of_ms"),
            clean_evidence_state_digest=_string(
                raw.get("clean_evidence_state_digest"),
                "clean_evidence_state_digest",
            ),
            prediction_count=_integer(
                raw.get("prediction_count"),
                "prediction_count",
            ),
            settled_outcome_count=_integer(
                raw.get("settled_outcome_count"),
                "settled_outcome_count",
            ),
            unsettled_trade_prediction_count=_integer(
                raw.get("unsettled_trade_prediction_count"),
                "unsettled_trade_prediction_count",
            ),
            target_settled_trades=_integer(
                raw.get("target_settled_trades"),
                "target_settled_trades",
            ),
            status=_string(raw.get("status"), "status"),
            paper_only=_boolean(raw.get("paper_only"), "paper_only"),
            prospective_only=_boolean(
                raw.get("prospective_only"),
                "prospective_only",
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
        raise LearningCleanStateError("LEARNING_CLEAN_STATE_INVALID") from exc
    if raw.get("state_id") != state.state_id:
        raise LearningCleanStateError("LEARNING_CLEAN_STATE_ID_MISMATCH")
    return state


def load_learning_clean_state(path: Path) -> LearningCleanState:
    try:
        stored_bytes = path.read_bytes()
        raw = _mapping(json.loads(stored_bytes), "learning clean state")
    except (OSError, json.JSONDecodeError) as exc:
        raise LearningCleanStateError("LEARNING_CLEAN_STATE_INVALID") from exc
    state = _state_from_payload(raw)
    canonical = (_canonical_json(state.to_dict()) + "\n").encode("utf-8")
    if stored_bytes != canonical:
        raise LearningCleanStateError("LEARNING_CLEAN_STATE_NON_CANONICAL")
    return state


def verify_learning_clean_state(
    path: Path,
    *,
    package_root: Path,
    validation_spec_path: Path,
    evidence_root: Path,
) -> LearningCleanState:
    stored = load_learning_clean_state(path)
    expected = build_learning_clean_state(
        package_root=package_root,
        validation_spec_path=validation_spec_path,
        evidence_root=evidence_root,
        as_of_ms=stored.as_of_ms,
    )
    if stored != expected:
        raise LearningCleanStateError("LEARNING_CLEAN_STATE_EVIDENCE_MISMATCH")
    return stored
