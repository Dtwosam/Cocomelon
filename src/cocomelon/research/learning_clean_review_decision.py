from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from cocomelon.research.learning_clean_review_dossier import (
    verify_learning_clean_review_dossier,
)

LEARNING_CLEAN_REVIEW_DECISION_SCHEMA_VERSION = 1
DECISION_ADVANCE = "advance_to_shadow_evaluation"
DECISION_REJECT = "reject_candidate"
_ALLOWED_DECISIONS = {DECISION_ADVANCE, DECISION_REJECT}


class LearningCleanReviewDecisionError(RuntimeError):
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
        raise LearningCleanReviewDecisionError(f"{field} must be a JSON object")
    return cast(dict[str, object], value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LearningCleanReviewDecisionError(f"{field} must be a non-empty string")
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LearningCleanReviewDecisionError(f"{field} must be a non-negative integer")
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise LearningCleanReviewDecisionError(f"{field} must be boolean")
    return value


@dataclass(frozen=True, slots=True)
class LearningCleanReviewDecision:
    candidate_id: str
    candidate_package_id: str
    validation_spec_id: str
    validation_score_id: str
    finalization_id: str
    review_dossier_id: str
    reviewer: str
    reviewed_at_ms: int
    decision: str
    rationale: str
    shadow_evaluation_authorized: bool
    human_review_completed: bool = True
    paper_only: bool = True
    research_only: bool = True
    promotion_eligible: bool = False
    execution_ready: bool = False
    live_promotion_authorized: bool = False
    schema_version: int = LEARNING_CLEAN_REVIEW_DECISION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in (
            "candidate_id",
            "candidate_package_id",
            "validation_spec_id",
            "validation_score_id",
            "finalization_id",
            "review_dossier_id",
        ):
            _require_sha256(getattr(self, field), field)
        if not self.reviewer.strip():
            raise ValueError("reviewer must not be empty")
        if self.reviewed_at_ms < 0:
            raise ValueError("reviewed_at_ms must be non-negative")
        if self.decision not in _ALLOWED_DECISIONS:
            raise ValueError("unsupported clean review decision")
        if not self.rationale.strip():
            raise ValueError("review rationale must not be empty")
        expected_shadow = self.decision == DECISION_ADVANCE
        if self.shadow_evaluation_authorized != expected_shadow:
            raise ValueError("shadow authorization must match review decision")
        if not self.human_review_completed:
            raise ValueError("review decision requires completed human review")
        if not self.paper_only or not self.research_only:
            raise ValueError("review decision must remain paper research")
        if self.promotion_eligible:
            raise ValueError("review decision cannot authorize live promotion")
        if self.execution_ready:
            raise ValueError("review decision cannot authorize execution")
        if self.live_promotion_authorized:
            raise ValueError("review decision cannot authorize live capital")
        if self.schema_version != LEARNING_CLEAN_REVIEW_DECISION_SCHEMA_VERSION:
            raise ValueError("unsupported learning clean review decision schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "candidate_package_id": self.candidate_package_id,
            "validation_spec_id": self.validation_spec_id,
            "validation_score_id": self.validation_score_id,
            "finalization_id": self.finalization_id,
            "review_dossier_id": self.review_dossier_id,
            "reviewer": self.reviewer,
            "reviewed_at_ms": self.reviewed_at_ms,
            "decision": self.decision,
            "rationale": self.rationale,
            "shadow_evaluation_authorized": self.shadow_evaluation_authorized,
            "human_review_completed": self.human_review_completed,
            "paper_only": self.paper_only,
            "research_only": self.research_only,
            "promotion_eligible": self.promotion_eligible,
            "execution_ready": self.execution_ready,
            "live_promotion_authorized": self.live_promotion_authorized,
            "schema_version": self.schema_version,
        }

    @property
    def review_decision_id(self) -> str:
        return _sha256_json(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "review_decision_id": self.review_decision_id}


def build_learning_clean_review_decision(
    *,
    review_dossier_path: Path,
    package_root: Path,
    validation_spec_path: Path,
    validation_score_path: Path,
    finalization_path: Path,
    evidence_root: Path,
    reviewer: str,
    reviewed_at_ms: int,
    decision: str,
    rationale: str,
) -> LearningCleanReviewDecision:
    dossier = verify_learning_clean_review_dossier(
        review_dossier_path,
        package_root=package_root,
        validation_spec_path=validation_spec_path,
        validation_score_path=validation_score_path,
        finalization_path=finalization_path,
        evidence_root=evidence_root,
    )
    if reviewed_at_ms < dossier.finalized_at_ms:
        raise LearningCleanReviewDecisionError(
            "LEARNING_CLEAN_REVIEW_DECISION_PREMATURE"
        )
    return LearningCleanReviewDecision(
        candidate_id=dossier.candidate_id,
        candidate_package_id=dossier.candidate_package_id,
        validation_spec_id=dossier.validation_spec_id,
        validation_score_id=dossier.validation_score_id,
        finalization_id=dossier.finalization_id,
        review_dossier_id=dossier.dossier_id,
        reviewer=reviewer,
        reviewed_at_ms=reviewed_at_ms,
        decision=decision,
        rationale=rationale,
        shadow_evaluation_authorized=decision == DECISION_ADVANCE,
    )


def write_learning_clean_review_decision(
    output_root: Path,
    decision: LearningCleanReviewDecision,
) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / "candidate-review-decision.json"
    payload = (_canonical_json(decision.to_dict()) + "\n").encode("utf-8")
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise LearningCleanReviewDecisionError(
                "LEARNING_CLEAN_REVIEW_DECISION_CONFLICT"
            )
        return path
    temporary = output_root / ".candidate-review-decision.json.tmp"
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


def load_learning_clean_review_decision(
    path: Path,
) -> LearningCleanReviewDecision:
    try:
        stored_bytes = path.read_bytes()
        raw = _mapping(json.loads(stored_bytes), "learning clean review decision")
        decision = LearningCleanReviewDecision(
            candidate_id=_string(raw.get("candidate_id"), "candidate_id"),
            candidate_package_id=_string(
                raw.get("candidate_package_id"), "candidate_package_id"
            ),
            validation_spec_id=_string(
                raw.get("validation_spec_id"), "validation_spec_id"
            ),
            validation_score_id=_string(
                raw.get("validation_score_id"), "validation_score_id"
            ),
            finalization_id=_string(raw.get("finalization_id"), "finalization_id"),
            review_dossier_id=_string(
                raw.get("review_dossier_id"), "review_dossier_id"
            ),
            reviewer=_string(raw.get("reviewer"), "reviewer"),
            reviewed_at_ms=_integer(raw.get("reviewed_at_ms"), "reviewed_at_ms"),
            decision=_string(raw.get("decision"), "decision"),
            rationale=_string(raw.get("rationale"), "rationale"),
            shadow_evaluation_authorized=_boolean(
                raw.get("shadow_evaluation_authorized"),
                "shadow_evaluation_authorized",
            ),
            human_review_completed=_boolean(
                raw.get("human_review_completed"), "human_review_completed"
            ),
            paper_only=_boolean(raw.get("paper_only"), "paper_only"),
            research_only=_boolean(raw.get("research_only"), "research_only"),
            promotion_eligible=_boolean(
                raw.get("promotion_eligible"), "promotion_eligible"
            ),
            execution_ready=_boolean(raw.get("execution_ready"), "execution_ready"),
            live_promotion_authorized=_boolean(
                raw.get("live_promotion_authorized"),
                "live_promotion_authorized",
            ),
            schema_version=_integer(raw.get("schema_version"), "schema_version"),
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise LearningCleanReviewDecisionError(
            "LEARNING_CLEAN_REVIEW_DECISION_INVALID"
        ) from exc
    except ValueError as exc:
        raise LearningCleanReviewDecisionError(
            "LEARNING_CLEAN_REVIEW_DECISION_INVALID"
        ) from exc
    if raw.get("review_decision_id") != decision.review_decision_id:
        raise LearningCleanReviewDecisionError(
            "LEARNING_CLEAN_REVIEW_DECISION_ID_MISMATCH"
        )
    canonical = (_canonical_json(decision.to_dict()) + "\n").encode("utf-8")
    if stored_bytes != canonical:
        raise LearningCleanReviewDecisionError(
            "LEARNING_CLEAN_REVIEW_DECISION_NON_CANONICAL"
        )
    return decision


def verify_learning_clean_review_decision(
    path: Path,
    *,
    review_dossier_path: Path,
    package_root: Path,
    validation_spec_path: Path,
    validation_score_path: Path,
    finalization_path: Path,
    evidence_root: Path,
) -> LearningCleanReviewDecision:
    stored = load_learning_clean_review_decision(path)
    expected = build_learning_clean_review_decision(
        review_dossier_path=review_dossier_path,
        package_root=package_root,
        validation_spec_path=validation_spec_path,
        validation_score_path=validation_score_path,
        finalization_path=finalization_path,
        evidence_root=evidence_root,
        reviewer=stored.reviewer,
        reviewed_at_ms=stored.reviewed_at_ms,
        decision=stored.decision,
        rationale=stored.rationale,
    )
    if stored != expected:
        raise LearningCleanReviewDecisionError(
            "LEARNING_CLEAN_REVIEW_DECISION_EVIDENCE_MISMATCH"
        )
    return stored
