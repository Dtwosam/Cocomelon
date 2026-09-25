from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from cocomelon.research.learning_candidate_package import (
    verify_learning_candidate_package,
)
from cocomelon.research.learning_clean_evidence import LearningCleanEvidenceStore
from cocomelon.research.learning_clean_finalization import (
    VERDICT_ELIGIBLE,
    VERDICT_FAILED,
    verify_learning_clean_finalization,
)
from cocomelon.research.learning_clean_state import verify_learning_clean_state
from cocomelon.research.learning_clean_validation_score import (
    verify_learning_clean_validation_score,
)
from cocomelon.research.learning_clean_validation_spec import (
    verify_learning_clean_validation_spec,
)


class LearningCleanReviewQueueError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class LearningCleanReviewItem:
    candidate_id: str
    candidate_package_id: str
    validation_spec_id: str
    model_family: str
    validation_start_ms: int
    state_as_of_ms: int
    lifecycle_status: str
    settled_trade_count: int
    target_settled_trades: int
    finalization_id: str | None
    finalized_at_ms: int | None
    eligible_for_candidate_review: bool | None
    verdict: str | None
    research_only: bool = True
    promotion_eligible: bool = False
    execution_ready: bool = False

    def __post_init__(self) -> None:
        for field in (
            "candidate_id",
            "candidate_package_id",
            "validation_spec_id",
        ):
            value = getattr(self, field)
            if (
                len(value) != 64
                or any(char not in "0123456789abcdef" for char in value)
            ):
                raise ValueError(f"{field} must be a lowercase SHA-256 identity")
        if not self.model_family.strip():
            raise ValueError("model_family must not be empty")
        if self.validation_start_ms < 0 or self.state_as_of_ms < 0:
            raise ValueError("review queue timestamps must be non-negative")
        if self.settled_trade_count < 0 or self.target_settled_trades <= 0:
            raise ValueError("review queue trade counts are invalid")
        if self.settled_trade_count > self.target_settled_trades:
            raise ValueError("settled trade count cannot exceed frozen target")
        if self.lifecycle_status not in {
            "waiting_for_validation_start",
            "collecting",
            "ready_to_finalize",
            "review_ready",
            "validation_failed",
        }:
            raise ValueError("unsupported clean review lifecycle status")
        if self.finalization_id is None:
            if (
                self.finalized_at_ms is not None
                or self.eligible_for_candidate_review is not None
                or self.verdict is not None
            ):
                raise ValueError("non-finalized review item cannot carry finalization")
        else:
            if (
                len(self.finalization_id) != 64
                or any(
                    char not in "0123456789abcdef"
                    for char in self.finalization_id
                )
            ):
                raise ValueError("finalization_id must be a SHA-256 identity")
            if self.finalized_at_ms is None or self.finalized_at_ms < 0:
                raise ValueError("finalized review item requires finalized_at_ms")
            if self.eligible_for_candidate_review is None or self.verdict is None:
                raise ValueError("finalized review item requires terminal verdict")
            if self.verdict not in {VERDICT_ELIGIBLE, VERDICT_FAILED}:
                raise ValueError("unsupported clean finalization verdict")
            expected_status = (
                "review_ready"
                if self.eligible_for_candidate_review
                else "validation_failed"
            )
            if self.lifecycle_status != expected_status:
                raise ValueError("review lifecycle must match finalization")
        if not self.research_only:
            raise ValueError("clean review queue must remain research-only")
        if self.promotion_eligible:
            raise ValueError("clean review queue cannot authorize promotion")
        if self.execution_ready:
            raise ValueError("clean review queue cannot authorize execution")

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "candidate_package_id": self.candidate_package_id,
            "validation_spec_id": self.validation_spec_id,
            "model_family": self.model_family,
            "validation_start_ms": self.validation_start_ms,
            "state_as_of_ms": self.state_as_of_ms,
            "lifecycle_status": self.lifecycle_status,
            "settled_trade_count": self.settled_trade_count,
            "target_settled_trades": self.target_settled_trades,
            "finalization_id": self.finalization_id,
            "finalized_at_ms": self.finalized_at_ms,
            "eligible_for_candidate_review": self.eligible_for_candidate_review,
            "verdict": self.verdict,
            "research_only": self.research_only,
            "promotion_eligible": self.promotion_eligible,
            "execution_ready": self.execution_ready,
        }


def _item_from_candidate_root(candidate_root: Path) -> LearningCleanReviewItem:
    package_root = candidate_root / "package"
    spec_path = candidate_root / "candidate-validation-spec.json"
    evidence_root = candidate_root / "evidence"
    state_path = candidate_root / "state.json"

    package = verify_learning_candidate_package(package_root)
    spec = verify_learning_clean_validation_spec(
        spec_path,
        package_root=package_root,
    )
    evidence = LearningCleanEvidenceStore(evidence_root, spec=spec)
    evidence.verify()
    state = verify_learning_clean_state(
        state_path,
        package_root=package_root,
        validation_spec_path=spec_path,
        evidence_root=evidence_root,
    )
    if (
        package.candidate_id != spec.candidate_id
        or package.candidate_id != state.candidate_id
        or package.package_id != spec.candidate_package_id
        or package.package_id != state.candidate_package_id
        or spec.spec_id != state.validation_spec_id
    ):
        raise LearningCleanReviewQueueError("CLEAN_REVIEW_LINEAGE_MISMATCH")
    if state.promotion_eligible or state.execution_ready:
        raise LearningCleanReviewQueueError("CLEAN_REVIEW_AUTHORITY_INVALID")

    score_path = candidate_root / "score" / "candidate-validation-score.json"
    finalization_path = (
        candidate_root / "finalization" / "candidate-finalization.json"
    )
    finalization = None
    if finalization_path.is_file():
        if not score_path.is_file():
            raise LearningCleanReviewQueueError(
                "CLEAN_REVIEW_FINALIZATION_WITHOUT_SCORE"
            )
        verify_learning_clean_validation_score(
            score_path,
            evidence_root=evidence_root,
            package_root=package_root,
            validation_spec_path=spec_path,
        )
        finalization = verify_learning_clean_finalization(
            finalization_path,
            package_root=package_root,
            validation_spec_path=spec_path,
            validation_score_path=score_path,
            evidence_root=evidence_root,
        )
        if finalization.promotion_eligible or finalization.execution_ready:
            raise LearningCleanReviewQueueError(
                "CLEAN_REVIEW_FINALIZATION_AUTHORITY_INVALID"
            )

    if finalization is not None:
        lifecycle_status = (
            "review_ready"
            if finalization.eligible_for_candidate_review
            else "validation_failed"
        )
        finalization_id = finalization.finalization_id
        finalized_at_ms = finalization.finalized_at_ms
        eligible = finalization.eligible_for_candidate_review
        verdict = finalization.verdict
    elif state.status == "waiting_for_validation_start":
        lifecycle_status = "waiting_for_validation_start"
        finalization_id = None
        finalized_at_ms = None
        eligible = None
        verdict = None
    elif state.status == "collecting":
        lifecycle_status = "collecting"
        finalization_id = None
        finalized_at_ms = None
        eligible = None
        verdict = None
    elif state.status == "ready_to_score":
        lifecycle_status = "ready_to_finalize"
        finalization_id = None
        finalized_at_ms = None
        eligible = None
        verdict = None
    else:
        raise LearningCleanReviewQueueError("CLEAN_REVIEW_STATE_INVALID")

    return LearningCleanReviewItem(
        candidate_id=state.candidate_id,
        candidate_package_id=state.candidate_package_id,
        validation_spec_id=state.validation_spec_id,
        model_family=state.model_family,
        validation_start_ms=state.validation_start_ms,
        state_as_of_ms=state.as_of_ms,
        lifecycle_status=lifecycle_status,
        settled_trade_count=min(
            state.settled_outcome_count,
            state.target_settled_trades,
        ),
        target_settled_trades=state.target_settled_trades,
        finalization_id=finalization_id,
        finalized_at_ms=finalized_at_ms,
        eligible_for_candidate_review=eligible,
        verdict=verdict,
    )


def _merge_duplicate(
    existing: LearningCleanReviewItem,
    incoming: LearningCleanReviewItem,
) -> LearningCleanReviewItem:
    if (
        existing.candidate_package_id != incoming.candidate_package_id
        or existing.validation_spec_id != incoming.validation_spec_id
        or existing.model_family != incoming.model_family
        or existing.validation_start_ms != incoming.validation_start_ms
        or existing.target_settled_trades != incoming.target_settled_trades
    ):
        raise LearningCleanReviewQueueError("CLEAN_REVIEW_DUPLICATE_LINEAGE_CONFLICT")

    if (
        existing.finalization_id is not None
        and incoming.finalization_id is not None
        and existing.finalization_id != incoming.finalization_id
    ):
        raise LearningCleanReviewQueueError(
            "CLEAN_REVIEW_DUPLICATE_FINALIZATION_CONFLICT"
        )
    if existing.state_as_of_ms == incoming.state_as_of_ms and existing != incoming:
        raise LearningCleanReviewQueueError("CLEAN_REVIEW_DUPLICATE_STATE_CONFLICT")

    if existing.finalization_id is not None and incoming.finalization_id is None:
        return existing
    if incoming.finalization_id is not None and existing.finalization_id is None:
        return incoming
    return incoming if incoming.state_as_of_ms > existing.state_as_of_ms else existing


def build_learning_clean_review_queue(
    state_roots: Iterable[str | Path],
) -> dict[str, object]:
    by_candidate: dict[str, LearningCleanReviewItem] = {}

    for raw_root in state_roots:
        state_root = Path(raw_root)
        candidates_root = state_root / "candidates"
        if not candidates_root.is_dir():
            raise LearningCleanReviewQueueError("CLEAN_REVIEW_CANDIDATES_MISSING")
        candidate_roots = sorted(
            path for path in candidates_root.iterdir() if path.is_dir()
        )
        for candidate_root in candidate_roots:
            item = _item_from_candidate_root(candidate_root)
            existing = by_candidate.get(item.candidate_id)
            by_candidate[item.candidate_id] = (
                item if existing is None else _merge_duplicate(existing, item)
            )

    items = tuple(
        sorted(
            by_candidate.values(),
            key=lambda item: (
                0 if item.lifecycle_status == "review_ready" else 1,
                item.lifecycle_status,
                item.candidate_id,
            ),
        )
    )
    counts = {
        status: sum(item.lifecycle_status == status for item in items)
        for status in (
            "waiting_for_validation_start",
            "collecting",
            "ready_to_finalize",
            "review_ready",
            "validation_failed",
        )
    }
    return {
        "candidate_count": len(items),
        "waiting_for_validation_start_count": counts[
            "waiting_for_validation_start"
        ],
        "collecting_count": counts["collecting"],
        "ready_to_finalize_count": counts["ready_to_finalize"],
        "review_ready_count": counts["review_ready"],
        "validation_failed_count": counts["validation_failed"],
        "candidates": tuple(item.to_dict() for item in items),
        "research_only": True,
        "promotion_eligible": False,
        "execution_ready": False,
    }


def render_learning_clean_review_markdown(queue: dict[str, object]) -> str:
    candidates = queue.get("candidates")
    if not isinstance(candidates, (tuple, list)):
        raise LearningCleanReviewQueueError("CLEAN_REVIEW_QUEUE_INVALID")

    lines = [
        "## Learned Clean Candidate Review Queue",
        "",
        "**RESEARCH ONLY / HUMAN REVIEW REQUIRED / NO EXECUTION**",
        "",
        f"- Clean candidates: {queue['candidate_count']}",
        f"- Waiting for validation start: {queue['waiting_for_validation_start_count']}",
        f"- Collecting clean evidence: {queue['collecting_count']}",
        f"- Ready to finalize: {queue['ready_to_finalize_count']}",
        f"- Ready for candidate review: {queue['review_ready_count']}",
        f"- Validation failed: {queue['validation_failed_count']}",
    ]
    for raw in candidates:
        if not isinstance(raw, dict):
            raise LearningCleanReviewQueueError("CLEAN_REVIEW_ITEM_INVALID")
        status = raw.get("lifecycle_status")
        candidate_id = raw.get("candidate_id")
        model_family = raw.get("model_family")
        settled = raw.get("settled_trade_count")
        target = raw.get("target_settled_trades")
        if (
            not isinstance(status, str)
            or not isinstance(candidate_id, str)
            or not isinstance(model_family, str)
            or isinstance(settled, bool)
            or not isinstance(settled, int)
            or isinstance(target, bool)
            or not isinstance(target, int)
        ):
            raise LearningCleanReviewQueueError("CLEAN_REVIEW_ITEM_INVALID")
        if status == "review_ready":
            lines.append(
                f"- **REVIEW READY** {candidate_id} ({model_family}); "
                f"clean settled sample {settled}/{target}"
            )
        elif status == "ready_to_finalize":
            lines.append(
                f"- **FINALIZATION PENDING** {candidate_id} ({model_family}); "
                f"clean settled sample {settled}/{target}"
            )

    lines.extend(
        [
            "",
            (
                "This queue exposes lifecycle provenance and terminal review "
                "readiness only. It contains no PnL, net-R, prediction values, "
                "model ranking, promotion authority, or execution authority."
            ),
            "",
        ]
    )
    return "\n".join(lines)
