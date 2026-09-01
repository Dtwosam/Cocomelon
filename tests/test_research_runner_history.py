from __future__ import annotations

from pathlib import Path

import pytest

from cocomelon.research.registry import ResearchRegistry, ResearchRegistryError
from cocomelon.research.runner_history import (
    ResearchRunnerAttemptStatus,
    bind_runner_attempt_source_interval,
    finish_runner_attempt,
    load_runner_attempts,
    record_runner_attempt_started,
)


def test_runner_attempt_lifecycle_is_append_only_and_auditable(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    try:
        record_runner_attempt_started(
            registry.connection,
            attempt_id="attempt-1",
            candidate_id="candidate-1",
            batch_id="batch-1",
            source_id="source-1",
            artifact_root="/artifacts/attempt-1/output",
        )
        finish_runner_attempt(
            registry.connection,
            attempt_id="attempt-1",
            status=ResearchRunnerAttemptStatus.FAILED,
            start_ms=1_000,
            end_ms=2_000,
            report_id=None,
            error_type="RuntimeError",
            error_message="transport failed",
        )

        attempts = load_runner_attempts(registry.connection)
    finally:
        registry.close()

    assert len(attempts) == 1
    attempt = attempts[0]
    assert attempt.attempt_id == "attempt-1"
    assert attempt.candidate_id == "candidate-1"
    assert attempt.batch_id == "batch-1"
    assert attempt.source_id == "source-1"
    assert attempt.artifact_root == "/artifacts/attempt-1/output"
    assert attempt.status is ResearchRunnerAttemptStatus.FAILED
    assert attempt.start_ms == 1_000
    assert attempt.end_ms == 2_000
    assert attempt.report_id is None
    assert attempt.error_type == "RuntimeError"
    assert attempt.error_message == "transport failed"


def test_bound_source_interval_survives_later_failure_without_derived_interval(
    tmp_path: Path,
) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    try:
        record_runner_attempt_started(
            registry.connection,
            attempt_id="attempt-bound",
            candidate_id="candidate-1",
            batch_id="batch-bound",
            source_id="source-bound",
            artifact_root="/artifacts/attempt-bound/output",
        )
        bind_runner_attempt_source_interval(
            registry.connection,
            attempt_id="attempt-bound",
            start_ms=10_000,
            end_ms=20_000,
        )
        finish_runner_attempt(
            registry.connection,
            attempt_id="attempt-bound",
            status=ResearchRunnerAttemptStatus.FAILED,
            start_ms=None,
            end_ms=None,
            report_id=None,
            error_type="ValueError",
            error_message="artifact verification failed",
        )
        attempt = load_runner_attempts(registry.connection)[0]
    finally:
        registry.close()

    assert attempt.status is ResearchRunnerAttemptStatus.FAILED
    assert attempt.start_ms == 10_000
    assert attempt.end_ms == 20_000


def test_runner_attempt_identity_is_idempotent_but_cannot_be_rewritten(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    try:
        kwargs = {
            "attempt_id": "attempt-1",
            "candidate_id": "candidate-1",
            "batch_id": "batch-1",
            "source_id": "source-1",
            "artifact_root": "/artifacts/attempt-1/output",
        }
        record_runner_attempt_started(registry.connection, **kwargs)
        record_runner_attempt_started(registry.connection, **kwargs)

        with pytest.raises(ResearchRegistryError, match="different identity"):
            record_runner_attempt_started(
                registry.connection,
                attempt_id="attempt-1",
                candidate_id="candidate-1",
                batch_id="batch-different",
                source_id="source-1",
                artifact_root="/artifacts/attempt-1/output",
            )
    finally:
        registry.close()


def test_terminal_attempt_cannot_change_outcome(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    try:
        record_runner_attempt_started(
            registry.connection,
            attempt_id="attempt-1",
            candidate_id="candidate-1",
            batch_id="batch-1",
            source_id="source-1",
            artifact_root="/artifacts/attempt-1/output",
        )
        finish_runner_attempt(
            registry.connection,
            attempt_id="attempt-1",
            status=ResearchRunnerAttemptStatus.FAILED,
            start_ms=None,
            end_ms=None,
            report_id=None,
            error_type="OSError",
            error_message="disk failure",
        )

        with pytest.raises(ResearchRegistryError, match="terminal"):
            finish_runner_attempt(
                registry.connection,
                attempt_id="attempt-1",
                status=ResearchRunnerAttemptStatus.SUCCEEDED,
                start_ms=1_000,
                end_ms=2_000,
                report_id="a" * 64,
                error_type=None,
                error_message=None,
            )
    finally:
        registry.close()


def test_retry_requires_new_attempt_and_batch_identity(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    try:
        record_runner_attempt_started(
            registry.connection,
            attempt_id="attempt-1",
            candidate_id="candidate-1",
            batch_id="batch-1",
            source_id="source-1",
            artifact_root="/artifacts/attempt-1/output",
        )
        finish_runner_attempt(
            registry.connection,
            attempt_id="attempt-1",
            status=ResearchRunnerAttemptStatus.FAILED,
            start_ms=None,
            end_ms=None,
            report_id=None,
            error_type="TimeoutError",
            error_message="capture timeout",
        )

        with pytest.raises(ResearchRegistryError, match="batch"):
            record_runner_attempt_started(
                registry.connection,
                attempt_id="attempt-2",
                candidate_id="candidate-1",
                batch_id="batch-1",
                source_id="source-2",
                artifact_root="/artifacts/attempt-2/output",
            )

        record_runner_attempt_started(
            registry.connection,
            attempt_id="attempt-2",
            candidate_id="candidate-1",
            batch_id="batch-2",
            source_id="source-2",
            artifact_root="/artifacts/attempt-2/output",
        )
        attempts = load_runner_attempts(registry.connection)
    finally:
        registry.close()

    assert [item.attempt_id for item in attempts] == ["attempt-1", "attempt-2"]
    assert [item.batch_id for item in attempts] == ["batch-1", "batch-2"]
