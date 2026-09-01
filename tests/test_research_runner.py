from __future__ import annotations

from decimal import Decimal
from importlib import import_module
from pathlib import Path

import pytest

from cocomelon.research.contracts import (
    ResearchCandidateManifest,
    ResearchCandidateState,
    TimeInterval,
)
from cocomelon.research.registry import (
    ResearchContaminationError,
    ResearchRegistry,
    ResearchRegistryError,
)
from cocomelon.research.runner_history import (
    ResearchRunnerAttemptStatus,
    load_runner_attempts,
)
from tests.research_artifact_support import (
    CODE_REVISION,
    CONFIG_DIGEST,
    ArtifactTradeSpec,
    write_research_artifact,
)

runner_module = import_module("cocomelon.research.runner")
ResearchRunnerRequest = runner_module.ResearchRunnerRequest
run_research_artifact_attempt = runner_module.run_research_artifact_attempt


def _candidate(candidate_id: str = "runner-candidate") -> ResearchCandidateManifest:
    return ResearchCandidateManifest(
        candidate_id=candidate_id,
        family_id="runner-family",
        parent_candidate_id=None,
        ancestor_candidate_ids=(),
        config_digest=CONFIG_DIGEST,
        code_revision=CODE_REVISION,
        execution_config_json='{"mode":"paper","slippage_model":"recorded"}',
        risk_config_json='{"risk_per_trade":"0.0025","stops_required":true}',
        state=ResearchCandidateState.DRAFT,
        first_observation_ms=None,
        last_observation_ms=None,
        source_provenance_ids=(),
        local_touched_intervals=(),
        effective_touched_intervals=(),
        performance_report_ids=(),
    )


def _artifact(tmp_path: Path, *, batch_id: str = "runner-batch"):
    return write_research_artifact(
        tmp_path / batch_id,
        batch_id=batch_id,
        source_id=f"source-{batch_id}",
        replay_run_id=f"replay-{batch_id}",
        start_ms=1_000,
        end_ms=3_000,
        trades=(ArtifactTradeSpec(closed_at_ms=2_500, net_r=Decimal("0.25")),),
    )


def _request(artifact, *, attempt_id: str = "attempt-1"):
    return ResearchRunnerRequest(
        attempt_id=attempt_id,
        candidate_id="runner-candidate",
        batch_id=artifact.batch_id,
        source_id=artifact.source_id,
        artifact_root=artifact.artifact_root,
    )


def test_successful_runner_attempt_uses_artifact_interval_and_persists_report(
    tmp_path: Path,
) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    try:
        registry.create_candidate(_candidate())
        registry.mark_v4_registry_complete_through(
            through_ms=3_000,
            source_id="authoritative-v4-inventory",
        )
        artifact = _artifact(tmp_path)

        result = run_research_artifact_attempt(registry, _request(artifact))
        attempts = load_runner_attempts(registry.connection)
    finally:
        registry.close()

    assert result.attempt_id == "attempt-1"
    assert result.start_ms == 1_000
    assert result.end_ms == 3_000
    assert result.report_id
    assert len(attempts) == 1
    assert attempts[0].status is ResearchRunnerAttemptStatus.SUCCEEDED
    assert attempts[0].start_ms == 1_000
    assert attempts[0].end_ms == 3_000
    assert attempts[0].report_id == result.report_id


def test_runner_fails_closed_when_v4_registry_is_incomplete_through_actual_interval(
    tmp_path: Path,
) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    try:
        registry.create_candidate(_candidate())
        registry.mark_v4_registry_complete_through(
            through_ms=2_999,
            source_id="authoritative-v4-inventory",
        )
        artifact = _artifact(tmp_path)

        with pytest.raises(ResearchRegistryError, match="completeness"):
            run_research_artifact_attempt(registry, _request(artifact))
        attempts = load_runner_attempts(registry.connection)
    finally:
        registry.close()

    assert attempts[0].status is ResearchRunnerAttemptStatus.FAILED
    assert attempts[0].start_ms == 1_000
    assert attempts[0].end_ms == 3_000
    assert attempts[0].report_id is None


def test_runner_marks_actual_interval_overlap_contaminated_and_rejects_candidate(
    tmp_path: Path,
) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    try:
        registry.create_candidate(_candidate())
        registry.record_v4_interval(
            run_id="v4-overlap",
            interval=TimeInterval(1_500, 2_000),
            disposition="accepted",
        )
        registry.mark_v4_registry_complete_through(
            through_ms=3_000,
            source_id="authoritative-v4-inventory",
        )
        artifact = _artifact(tmp_path)

        with pytest.raises(ResearchContaminationError, match="v4-overlap"):
            run_research_artifact_attempt(registry, _request(artifact))
        attempts = load_runner_attempts(registry.connection)
        candidate = registry.load_candidate("runner-candidate")
    finally:
        registry.close()

    assert attempts[0].status is ResearchRunnerAttemptStatus.CONTAMINATED
    assert attempts[0].start_ms == 1_000
    assert attempts[0].end_ms == 3_000
    assert candidate.state is ResearchCandidateState.REJECTED_CONTAMINATION


def test_runner_rejects_candidate_code_or_config_mismatch_before_checkpoint(
    tmp_path: Path,
) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    try:
        registry.create_candidate(_candidate())
        registry.mark_v4_registry_complete_through(
            through_ms=3_000,
            source_id="authoritative-v4-inventory",
        )
        artifact = write_research_artifact(
            tmp_path / "mismatch",
            batch_id="mismatch-batch",
            source_id="mismatch-source",
            replay_run_id="mismatch-replay",
            start_ms=1_000,
            end_ms=3_000,
            code_revision="2" * 40,
            config_digest=CONFIG_DIGEST,
        )
        request = ResearchRunnerRequest(
            attempt_id="attempt-mismatch",
            candidate_id="runner-candidate",
            batch_id=artifact.batch_id,
            source_id=artifact.source_id,
            artifact_root=artifact.artifact_root,
        )

        with pytest.raises(ResearchRegistryError, match="code revision"):
            run_research_artifact_attempt(registry, request)
        attempts = load_runner_attempts(registry.connection)
        candidate = registry.load_candidate("runner-candidate")
    finally:
        registry.close()

    assert attempts[0].status is ResearchRunnerAttemptStatus.FAILED
    assert attempts[0].start_ms == 1_000
    assert attempts[0].end_ms == 3_000
    assert candidate.performance_report_ids == ()
    assert candidate.local_touched_intervals == ()


def test_runner_persists_evaluator_failure_and_reraises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    try:
        registry.create_candidate(_candidate())
        registry.mark_v4_registry_complete_through(
            through_ms=3_000,
            source_id="authoritative-v4-inventory",
        )
        artifact = _artifact(tmp_path)

        def fail_evaluator(**_kwargs: object) -> None:
            raise RuntimeError("synthetic evaluator failure")

        monkeypatch.setattr(runner_module, "evaluate_research_checkpoint", fail_evaluator)
        with pytest.raises(RuntimeError, match="synthetic evaluator failure"):
            run_research_artifact_attempt(registry, _request(artifact))
        attempts = load_runner_attempts(registry.connection)
    finally:
        registry.close()

    assert attempts[0].status is ResearchRunnerAttemptStatus.FAILED
    assert attempts[0].error_type == "RuntimeError"
    assert attempts[0].error_message == "synthetic evaluator failure"


def test_interrupted_evaluation_cannot_be_reclaimed_by_same_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    calls = 0
    try:
        registry.create_candidate(_candidate())
        registry.mark_v4_registry_complete_through(
            through_ms=3_000,
            source_id="authoritative-v4-inventory",
        )
        artifact = _artifact(tmp_path)
        request = _request(artifact, attempt_id="attempt-interrupted")

        def interrupt_evaluator(**_kwargs: object) -> None:
            nonlocal calls
            calls += 1
            raise KeyboardInterrupt("synthetic interruption after evaluation claim")

        monkeypatch.setattr(runner_module, "evaluate_research_checkpoint", interrupt_evaluator)
        with pytest.raises(KeyboardInterrupt, match="synthetic interruption"):
            run_research_artifact_attempt(registry, request)

        with pytest.raises(ResearchRegistryError, match="evaluation"):
            run_research_artifact_attempt(registry, request)
        attempts = load_runner_attempts(registry.connection)
    finally:
        registry.close()

    assert calls == 1
    assert len(attempts) == 1
    assert attempts[0].status is ResearchRunnerAttemptStatus.EVALUATING


def test_terminal_attempt_cannot_be_rerun_after_outcome_is_known(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    try:
        registry.create_candidate(_candidate())
        registry.mark_v4_registry_complete_through(
            through_ms=3_000,
            source_id="authoritative-v4-inventory",
        )
        artifact = _artifact(tmp_path)
        request = _request(artifact)
        run_research_artifact_attempt(registry, request)

        with pytest.raises(ResearchRegistryError, match="terminal"):
            run_research_artifact_attempt(registry, request)
        attempts = load_runner_attempts(registry.connection)
    finally:
        registry.close()

    assert len(attempts) == 1
    assert attempts[0].status is ResearchRunnerAttemptStatus.SUCCEEDED
