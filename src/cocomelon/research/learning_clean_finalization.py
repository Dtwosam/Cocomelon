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
from cocomelon.research.learning_clean_validation_score import (
    verify_learning_clean_validation_score,
)
from cocomelon.research.learning_clean_validation_spec import (
    verify_learning_clean_validation_spec,
)

LEARNING_CLEAN_FINALIZATION_SCHEMA_VERSION = 1
VERDICT_ELIGIBLE = "eligible_for_candidate_review"
VERDICT_FAILED = "validation_failed"


class LearningCleanFinalizationError(RuntimeError):
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
        raise LearningCleanFinalizationError(f"{field} must be a JSON object")
    return cast(dict[str, object], value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LearningCleanFinalizationError(
            f"{field} must be a non-empty string"
        )
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LearningCleanFinalizationError(
            f"{field} must be a non-negative integer"
        )
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise LearningCleanFinalizationError(f"{field} must be boolean")
    return value


@dataclass(frozen=True, slots=True)
class LearningCleanFinalization:
    candidate_id: str
    candidate_package_id: str
    validation_spec_id: str
    validation_score_id: str
    validation_score_as_of_ms: int
    selected_evidence_digest: str
    settled_trade_count: int
    target_settled_trades: int
    finalized_at_ms: int
    verdict: str
    eligible_for_candidate_review: bool
    reason_codes: tuple[str, ...]
    paper_only: bool = True
    prospective_only: bool = True
    research_only: bool = True
    promotion_eligible: bool = False
    execution_ready: bool = False
    schema_version: int = LEARNING_CLEAN_FINALIZATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in (
            "candidate_id",
            "candidate_package_id",
            "validation_spec_id",
            "validation_score_id",
            "selected_evidence_digest",
        ):
            _require_sha256(getattr(self, field), field)
        if self.validation_score_as_of_ms < 0 or self.finalized_at_ms < 0:
            raise ValueError("clean finalization timestamps must be non-negative")
        if self.finalized_at_ms < self.validation_score_as_of_ms:
            raise ValueError("finalization cannot precede frozen validation score")
        if self.settled_trade_count <= 0 or self.target_settled_trades <= 0:
            raise ValueError("clean finalization trade counts must be positive")
        if self.settled_trade_count != self.target_settled_trades:
            raise ValueError("clean finalization requires the frozen target sample")
        if tuple(sorted(set(self.reason_codes))) != self.reason_codes:
            raise ValueError("reason_codes must be sorted unique")
        expected_eligible = not self.reason_codes
        if self.eligible_for_candidate_review != expected_eligible:
            raise ValueError("candidate review eligibility must match reason codes")
        expected_verdict = VERDICT_ELIGIBLE if expected_eligible else VERDICT_FAILED
        if self.verdict != expected_verdict:
            raise ValueError("clean finalization verdict must match reason codes")
        if not self.paper_only or not self.prospective_only or not self.research_only:
            raise ValueError("clean finalization must remain prospective paper research")
        if self.promotion_eligible:
            raise ValueError("clean finalization cannot authorize promotion")
        if self.execution_ready:
            raise ValueError("clean finalization cannot authorize execution")
        if self.schema_version != LEARNING_CLEAN_FINALIZATION_SCHEMA_VERSION:
            raise ValueError("unsupported learning clean finalization schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "candidate_package_id": self.candidate_package_id,
            "validation_spec_id": self.validation_spec_id,
            "validation_score_id": self.validation_score_id,
            "validation_score_as_of_ms": self.validation_score_as_of_ms,
            "selected_evidence_digest": self.selected_evidence_digest,
            "settled_trade_count": self.settled_trade_count,
            "target_settled_trades": self.target_settled_trades,
            "finalized_at_ms": self.finalized_at_ms,
            "verdict": self.verdict,
            "eligible_for_candidate_review": self.eligible_for_candidate_review,
            "reason_codes": self.reason_codes,
            "paper_only": self.paper_only,
            "prospective_only": self.prospective_only,
            "research_only": self.research_only,
            "promotion_eligible": self.promotion_eligible,
            "execution_ready": self.execution_ready,
            "schema_version": self.schema_version,
        }

    @property
    def finalization_id(self) -> str:
        return _sha256_json(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "finalization_id": self.finalization_id}


def build_learning_clean_finalization(
    *,
    package_root: Path,
    validation_spec_path: Path,
    validation_score_path: Path,
    evidence_root: Path,
    finalized_at_ms: int,
) -> LearningCleanFinalization:
    if finalized_at_ms < 0:
        raise ValueError("finalized_at_ms must be non-negative")

    package = verify_learning_candidate_package(package_root)
    spec = verify_learning_clean_validation_spec(
        validation_spec_path,
        package_root=package_root,
    )
    score = verify_learning_clean_validation_score(
        validation_score_path,
        evidence_root=evidence_root,
        package_root=package_root,
        validation_spec_path=validation_spec_path,
    )
    if score.status != "complete" or score.qualifies_clean_validation is None:
        raise LearningCleanFinalizationError(
            "LEARNING_CLEAN_FINALIZATION_SCORE_INCOMPLETE"
        )
    if (
        score.candidate_id != package.candidate_id
        or score.candidate_id != spec.candidate_id
        or score.candidate_package_id != package.package_id
        or score.candidate_package_id != spec.candidate_package_id
        or score.validation_spec_id != spec.spec_id
    ):
        raise LearningCleanFinalizationError(
            "LEARNING_CLEAN_FINALIZATION_LINEAGE_MISMATCH"
        )
    if finalized_at_ms < score.as_of_ms:
        raise LearningCleanFinalizationError(
            "LEARNING_CLEAN_FINALIZATION_PREMATURE"
        )

    reasons = (
        ()
        if score.qualifies_clean_validation
        else ("clean_validation_gate_failed",)
    )
    eligible = not reasons
    return LearningCleanFinalization(
        candidate_id=score.candidate_id,
        candidate_package_id=score.candidate_package_id,
        validation_spec_id=score.validation_spec_id,
        validation_score_id=score.score_id,
        validation_score_as_of_ms=score.as_of_ms,
        selected_evidence_digest=score.selected_evidence_digest,
        settled_trade_count=score.selected_settled_trade_count,
        target_settled_trades=score.target_settled_trades,
        finalized_at_ms=finalized_at_ms,
        verdict=VERDICT_ELIGIBLE if eligible else VERDICT_FAILED,
        eligible_for_candidate_review=eligible,
        reason_codes=reasons,
    )


def write_learning_clean_finalization(
    output_root: Path,
    finalization: LearningCleanFinalization,
) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / "candidate-finalization.json"
    payload = (_canonical_json(finalization.to_dict()) + "\n").encode("utf-8")
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise LearningCleanFinalizationError(
                "LEARNING_CLEAN_FINALIZATION_CONFLICT"
            )
        return path
    temporary = output_root / ".candidate-finalization.json.tmp"
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


def _finalization_from_payload(
    raw: dict[str, object],
) -> LearningCleanFinalization:
    reason_codes = raw.get("reason_codes")
    if not isinstance(reason_codes, list) or not all(
        isinstance(item, str) for item in reason_codes
    ):
        raise LearningCleanFinalizationError(
            "LEARNING_CLEAN_FINALIZATION_REASON_CODES_INVALID"
        )
    try:
        finalization = LearningCleanFinalization(
            candidate_id=_string(raw.get("candidate_id"), "candidate_id"),
            candidate_package_id=_string(
                raw.get("candidate_package_id"),
                "candidate_package_id",
            ),
            validation_spec_id=_string(
                raw.get("validation_spec_id"),
                "validation_spec_id",
            ),
            validation_score_id=_string(
                raw.get("validation_score_id"),
                "validation_score_id",
            ),
            validation_score_as_of_ms=_integer(
                raw.get("validation_score_as_of_ms"),
                "validation_score_as_of_ms",
            ),
            selected_evidence_digest=_string(
                raw.get("selected_evidence_digest"),
                "selected_evidence_digest",
            ),
            settled_trade_count=_integer(
                raw.get("settled_trade_count"),
                "settled_trade_count",
            ),
            target_settled_trades=_integer(
                raw.get("target_settled_trades"),
                "target_settled_trades",
            ),
            finalized_at_ms=_integer(
                raw.get("finalized_at_ms"),
                "finalized_at_ms",
            ),
            verdict=_string(raw.get("verdict"), "verdict"),
            eligible_for_candidate_review=_boolean(
                raw.get("eligible_for_candidate_review"),
                "eligible_for_candidate_review",
            ),
            reason_codes=tuple(reason_codes),
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
        raise LearningCleanFinalizationError(
            "LEARNING_CLEAN_FINALIZATION_INVALID"
        ) from exc
    if raw.get("finalization_id") != finalization.finalization_id:
        raise LearningCleanFinalizationError(
            "LEARNING_CLEAN_FINALIZATION_ID_MISMATCH"
        )
    return finalization


def load_learning_clean_finalization(path: Path) -> LearningCleanFinalization:
    try:
        stored_bytes = path.read_bytes()
        raw = _mapping(
            json.loads(stored_bytes),
            "learning clean finalization",
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise LearningCleanFinalizationError(
            "LEARNING_CLEAN_FINALIZATION_INVALID"
        ) from exc
    finalization = _finalization_from_payload(raw)
    canonical = (_canonical_json(finalization.to_dict()) + "\n").encode("utf-8")
    if stored_bytes != canonical:
        raise LearningCleanFinalizationError(
            "LEARNING_CLEAN_FINALIZATION_NON_CANONICAL"
        )
    return finalization


def verify_learning_clean_finalization(
    path: Path,
    *,
    package_root: Path,
    validation_spec_path: Path,
    validation_score_path: Path,
    evidence_root: Path,
) -> LearningCleanFinalization:
    stored = load_learning_clean_finalization(path)
    expected = build_learning_clean_finalization(
        package_root=package_root,
        validation_spec_path=validation_spec_path,
        validation_score_path=validation_score_path,
        evidence_root=evidence_root,
        finalized_at_ms=stored.finalized_at_ms,
    )
    if stored != expected:
        raise LearningCleanFinalizationError(
            "LEARNING_CLEAN_FINALIZATION_EVIDENCE_MISMATCH"
        )
    return stored
