from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cocomelon.research.artifact import verify_research_batch_artifact
from cocomelon.research.contracts import ResearchCandidateState
from cocomelon.research.evaluator import (
    ResearchArtifactBatch,
    evaluate_research_checkpoint,
)
from cocomelon.research.registry import (
    ResearchContaminationError,
    ResearchRegistry,
    ResearchRegistryError,
)
from cocomelon.research.runner_history import (
    ResearchRunnerAttemptStatus,
    claim_runner_attempt_evaluation,
    finish_runner_attempt,
    record_runner_attempt_started,
)


@dataclass(frozen=True, slots=True)
class ResearchRunnerRequest:
    attempt_id: str
    candidate_id: str
    batch_id: str
    source_id: str
    artifact_root: Path


@dataclass(frozen=True, slots=True)
class ResearchRunnerResult:
    attempt_id: str
    start_ms: int
    end_ms: int
    report_id: str


def _finish_failure(
    registry: ResearchRegistry,
    *,
    request: ResearchRunnerRequest,
    status: ResearchRunnerAttemptStatus,
    start_ms: int | None,
    end_ms: int | None,
    exc: Exception,
) -> None:
    finish_runner_attempt(
        registry.connection,
        attempt_id=request.attempt_id,
        status=status,
        start_ms=start_ms,
        end_ms=end_ms,
        report_id=None,
        error_type=type(exc).__name__,
        error_message=str(exc),
    )


def _assert_candidate_matches_artifact(
    registry: ResearchRegistry,
    *,
    request: ResearchRunnerRequest,
    code_revision: str,
    config_digest: str,
) -> None:
    candidate = registry.load_candidate(request.candidate_id)
    if candidate.code_revision != code_revision:
        raise ResearchRegistryError(
            "research runner artifact code revision does not match candidate"
        )
    if candidate.config_digest != config_digest:
        raise ResearchRegistryError(
            "research runner artifact config digest does not match candidate"
        )


def _reject_contamination(
    registry: ResearchRegistry,
    *,
    request: ResearchRunnerRequest,
    start_ms: int | None,
    end_ms: int | None,
    exc: ResearchContaminationError,
) -> None:
    candidate = registry.load_candidate(request.candidate_id)
    if candidate.state is not ResearchCandidateState.REJECTED_CONTAMINATION:
        registry.transition_candidate(
            request.candidate_id,
            ResearchCandidateState.REJECTED_CONTAMINATION,
            reason="v4_source_interval_overlap",
        )
    _finish_failure(
        registry,
        request=request,
        status=ResearchRunnerAttemptStatus.CONTAMINATED,
        start_ms=start_ms,
        end_ms=end_ms,
        exc=exc,
    )


def run_research_artifact_attempt(
    registry: ResearchRegistry,
    request: ResearchRunnerRequest,
) -> ResearchRunnerResult:
    record_runner_attempt_started(
        registry.connection,
        attempt_id=request.attempt_id,
        candidate_id=request.candidate_id,
        batch_id=request.batch_id,
        source_id=request.source_id,
        artifact_root=str(request.artifact_root),
    )

    start_ms: int | None = None
    end_ms: int | None = None
    try:
        verified = verify_research_batch_artifact(
            request.artifact_root,
            batch_id=request.batch_id,
            source_id=request.source_id,
        )
        start_ms = verified.interval.start_ms
        end_ms = verified.interval.end_ms
        _assert_candidate_matches_artifact(
            registry,
            request=request,
            code_revision=verified.code_revision,
            config_digest=verified.config_digest,
        )
        registry.assert_batch_disjoint_from_v4(verified.interval)
    except ResearchContaminationError as exc:
        _reject_contamination(
            registry,
            request=request,
            start_ms=start_ms,
            end_ms=end_ms,
            exc=exc,
        )
        raise
    except Exception as exc:
        _finish_failure(
            registry,
            request=request,
            status=ResearchRunnerAttemptStatus.FAILED,
            start_ms=start_ms,
            end_ms=end_ms,
            exc=exc,
        )
        raise

    claim_runner_attempt_evaluation(
        registry.connection,
        attempt_id=request.attempt_id,
    )
    try:
        report = evaluate_research_checkpoint(
            registry=registry,
            candidate_id=request.candidate_id,
            artifact_batches=(
                ResearchArtifactBatch(
                    artifact_root=request.artifact_root,
                    batch_id=request.batch_id,
                    source_id=request.source_id,
                ),
            ),
        )
    except ResearchContaminationError as exc:
        _reject_contamination(
            registry,
            request=request,
            start_ms=start_ms,
            end_ms=end_ms,
            exc=exc,
        )
        raise
    except Exception as exc:
        _finish_failure(
            registry,
            request=request,
            status=ResearchRunnerAttemptStatus.FAILED,
            start_ms=start_ms,
            end_ms=end_ms,
            exc=exc,
        )
        raise

    finish_runner_attempt(
        registry.connection,
        attempt_id=request.attempt_id,
        status=ResearchRunnerAttemptStatus.SUCCEEDED,
        start_ms=start_ms,
        end_ms=end_ms,
        report_id=report.report_id,
        error_type=None,
        error_message=None,
    )
    return ResearchRunnerResult(
        attempt_id=request.attempt_id,
        start_ms=start_ms,
        end_ms=end_ms,
        report_id=report.report_id,
    )
