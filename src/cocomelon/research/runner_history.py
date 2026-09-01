from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import StrEnum

from cocomelon.research.registry import ResearchRegistryError


class ResearchRunnerAttemptStatus(StrEnum):
    RUNNING = "running"
    EVALUATING = "evaluating"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CONTAMINATED = "contaminated"


@dataclass(frozen=True, slots=True)
class ResearchRunnerAttempt:
    attempt_index: int
    attempt_id: str
    candidate_id: str
    batch_id: str
    source_id: str
    artifact_root: str
    status: ResearchRunnerAttemptStatus
    start_ms: int | None
    end_ms: int | None
    report_id: str | None
    error_type: str | None
    error_message: str | None


def _ensure_schema(connection: sqlite3.Connection) -> None:
    if connection.in_transaction:
        raise ResearchRegistryError("research runner history transaction is already active")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS research_runner_attempts (
            attempt_index INTEGER PRIMARY KEY AUTOINCREMENT,
            attempt_id TEXT NOT NULL UNIQUE,
            candidate_id TEXT NOT NULL,
            batch_id TEXT NOT NULL UNIQUE,
            source_id TEXT NOT NULL,
            artifact_root TEXT NOT NULL,
            status TEXT NOT NULL,
            start_ms INTEGER,
            end_ms INTEGER,
            report_id TEXT,
            error_type TEXT,
            error_message TEXT
        )
        """
    )
    connection.commit()


def _require_text(value: str, field: str) -> str:
    resolved = value.strip()
    if not resolved:
        raise ResearchRegistryError(f"research runner {field} must not be empty")
    return resolved


def _stored_status(value: object) -> ResearchRunnerAttemptStatus:
    try:
        return ResearchRunnerAttemptStatus(str(value))
    except ValueError as exc:
        raise ResearchRegistryError("stored research runner attempt status is invalid") from exc


def record_runner_attempt_started(
    connection: sqlite3.Connection,
    *,
    attempt_id: str,
    candidate_id: str,
    batch_id: str,
    source_id: str,
    artifact_root: str,
) -> None:
    _ensure_schema(connection)
    identity = (
        _require_text(attempt_id, "attempt_id"),
        _require_text(candidate_id, "candidate_id"),
        _require_text(batch_id, "batch_id"),
        _require_text(source_id, "source_id"),
        _require_text(artifact_root, "artifact_root"),
    )
    connection.execute("BEGIN IMMEDIATE")
    try:
        existing = connection.execute(
            """
            SELECT candidate_id, batch_id, source_id, artifact_root, status
            FROM research_runner_attempts
            WHERE attempt_id = ?
            """,
            (identity[0],),
        ).fetchone()
        if existing is not None:
            stored_identity = (
                identity[0],
                str(existing["candidate_id"]),
                str(existing["batch_id"]),
                str(existing["source_id"]),
                str(existing["artifact_root"]),
            )
            if stored_identity != identity:
                raise ResearchRegistryError(
                    f"research runner attempt already exists with different identity: {identity[0]}"
                )
            status = _stored_status(existing["status"])
            if status is ResearchRunnerAttemptStatus.RUNNING:
                connection.commit()
                return
            if status is ResearchRunnerAttemptStatus.EVALUATING:
                raise ResearchRegistryError(
                    f"research runner attempt evaluation already claimed: {identity[0]}"
                )
            raise ResearchRegistryError(
                f"research runner attempt is terminal: {identity[0]}"
            )

        batch_existing = connection.execute(
            "SELECT attempt_id FROM research_runner_attempts WHERE batch_id = ?",
            (identity[2],),
        ).fetchone()
        if batch_existing is not None:
            raise ResearchRegistryError(
                "research runner batch already belongs to attempt "
                f"{batch_existing['attempt_id']}"
            )
        connection.execute(
            """
            INSERT INTO research_runner_attempts (
                attempt_id, candidate_id, batch_id, source_id, artifact_root, status,
                start_ms, end_ms, report_id, error_type, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL)
            """,
            (*identity, ResearchRunnerAttemptStatus.RUNNING.value),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def bind_runner_attempt_source_interval(
    connection: sqlite3.Connection,
    *,
    attempt_id: str,
    start_ms: int,
    end_ms: int,
) -> None:
    _ensure_schema(connection)
    resolved_attempt_id = _require_text(attempt_id, "attempt_id")
    if start_ms < 0 or end_ms <= start_ms:
        raise ResearchRegistryError("research runner source interval is invalid")

    connection.execute("BEGIN IMMEDIATE")
    try:
        existing = connection.execute(
            """
            SELECT status, start_ms, end_ms
            FROM research_runner_attempts
            WHERE attempt_id = ?
            """,
            (resolved_attempt_id,),
        ).fetchone()
        if existing is None:
            raise ResearchRegistryError(
                f"research runner attempt not found: {resolved_attempt_id}"
            )
        existing_status = _stored_status(existing["status"])
        stored_start = existing["start_ms"]
        stored_end = existing["end_ms"]
        if (stored_start is None) != (stored_end is None):
            raise ResearchRegistryError("stored research runner source interval is incomplete")
        if stored_start is not None and stored_end is not None:
            if (int(stored_start), int(stored_end)) != (start_ms, end_ms):
                raise ResearchRegistryError(
                    "research runner attempt already has a different source interval"
                )
            connection.commit()
            return
        if existing_status is not ResearchRunnerAttemptStatus.RUNNING:
            raise ResearchRegistryError(
                "research runner source interval must be bound before evaluation"
            )
        cursor = connection.execute(
            """
            UPDATE research_runner_attempts
            SET start_ms = ?, end_ms = ?
            WHERE attempt_id = ? AND status = ?
              AND start_ms IS NULL AND end_ms IS NULL
            """,
            (
                start_ms,
                end_ms,
                resolved_attempt_id,
                ResearchRunnerAttemptStatus.RUNNING.value,
            ),
        )
        if cursor.rowcount != 1:
            raise ResearchRegistryError("research runner source interval changed concurrently")
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def claim_runner_attempt_evaluation(
    connection: sqlite3.Connection,
    *,
    attempt_id: str,
) -> None:
    _ensure_schema(connection)
    resolved_attempt_id = _require_text(attempt_id, "attempt_id")
    connection.execute("BEGIN IMMEDIATE")
    try:
        existing = connection.execute(
            "SELECT status FROM research_runner_attempts WHERE attempt_id = ?",
            (resolved_attempt_id,),
        ).fetchone()
        if existing is None:
            raise ResearchRegistryError(
                f"research runner attempt not found: {resolved_attempt_id}"
            )
        existing_status = _stored_status(existing["status"])
        if existing_status is ResearchRunnerAttemptStatus.EVALUATING:
            raise ResearchRegistryError(
                f"research runner attempt evaluation already claimed: {resolved_attempt_id}"
            )
        if existing_status is not ResearchRunnerAttemptStatus.RUNNING:
            raise ResearchRegistryError(
                f"research runner attempt is terminal: {resolved_attempt_id}"
            )
        cursor = connection.execute(
            """
            UPDATE research_runner_attempts
            SET status = ?
            WHERE attempt_id = ? AND status = ?
            """,
            (
                ResearchRunnerAttemptStatus.EVALUATING.value,
                resolved_attempt_id,
                ResearchRunnerAttemptStatus.RUNNING.value,
            ),
        )
        if cursor.rowcount != 1:
            raise ResearchRegistryError("research runner evaluation claim changed concurrently")
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def _validate_finish(
    *,
    status: ResearchRunnerAttemptStatus,
    start_ms: int | None,
    end_ms: int | None,
    report_id: str | None,
    error_type: str | None,
    error_message: str | None,
) -> None:
    if status in (
        ResearchRunnerAttemptStatus.RUNNING,
        ResearchRunnerAttemptStatus.EVALUATING,
    ):
        raise ResearchRegistryError("research runner finish status must be terminal")
    if (start_ms is None) != (end_ms is None):
        raise ResearchRegistryError("research runner attempt interval must be complete or absent")
    if start_ms is not None and end_ms is not None:
        if start_ms < 0 or end_ms <= start_ms:
            raise ResearchRegistryError("research runner attempt interval is invalid")
    if status is ResearchRunnerAttemptStatus.SUCCEEDED:
        if report_id is None or not report_id.strip():
            raise ResearchRegistryError("successful research runner attempt requires report_id")
        if error_type is not None or error_message is not None:
            raise ResearchRegistryError(
                "successful research runner attempt cannot contain an error"
            )
    elif report_id is not None:
        raise ResearchRegistryError("unsuccessful research runner attempt cannot contain report_id")


def finish_runner_attempt_uncommitted(
    connection: sqlite3.Connection,
    *,
    attempt_id: str,
    status: ResearchRunnerAttemptStatus,
    start_ms: int | None,
    end_ms: int | None,
    report_id: str | None,
    error_type: str | None,
    error_message: str | None,
) -> None:
    if not connection.in_transaction:
        raise ResearchRegistryError(
            "uncommitted research runner finish requires an active transaction"
        )
    resolved_attempt_id = _require_text(attempt_id, "attempt_id")
    _validate_finish(
        status=status,
        start_ms=start_ms,
        end_ms=end_ms,
        report_id=report_id,
        error_type=error_type,
        error_message=error_message,
    )
    existing = connection.execute(
        "SELECT status FROM research_runner_attempts WHERE attempt_id = ?",
        (resolved_attempt_id,),
    ).fetchone()
    if existing is None:
        raise ResearchRegistryError(
            f"research runner attempt not found: {resolved_attempt_id}"
        )
    existing_status = _stored_status(existing["status"])
    if existing_status not in (
        ResearchRunnerAttemptStatus.RUNNING,
        ResearchRunnerAttemptStatus.EVALUATING,
    ):
        raise ResearchRegistryError(
            f"research runner attempt is terminal: {resolved_attempt_id}"
        )
    if (
        status is ResearchRunnerAttemptStatus.SUCCEEDED
        and existing_status is not ResearchRunnerAttemptStatus.EVALUATING
    ):
        raise ResearchRegistryError(
            "successful research runner attempt requires an evaluation claim"
        )
    cursor = connection.execute(
        """
        UPDATE research_runner_attempts
        SET status = ?, start_ms = ?, end_ms = ?, report_id = ?,
            error_type = ?, error_message = ?
        WHERE attempt_id = ? AND status = ?
        """,
        (
            status.value,
            start_ms,
            end_ms,
            report_id,
            error_type,
            error_message,
            resolved_attempt_id,
            existing_status.value,
        ),
    )
    if cursor.rowcount != 1:
        raise ResearchRegistryError("research runner attempt changed concurrently")


def finish_runner_attempt(
    connection: sqlite3.Connection,
    *,
    attempt_id: str,
    status: ResearchRunnerAttemptStatus,
    start_ms: int | None,
    end_ms: int | None,
    report_id: str | None,
    error_type: str | None,
    error_message: str | None,
) -> None:
    _ensure_schema(connection)
    connection.execute("BEGIN IMMEDIATE")
    try:
        finish_runner_attempt_uncommitted(
            connection,
            attempt_id=attempt_id,
            status=status,
            start_ms=start_ms,
            end_ms=end_ms,
            report_id=report_id,
            error_type=error_type,
            error_message=error_message,
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def load_runner_attempts(
    connection: sqlite3.Connection,
    *,
    candidate_id: str | None = None,
) -> tuple[ResearchRunnerAttempt, ...]:
    _ensure_schema(connection)
    if candidate_id is None:
        rows = connection.execute(
            """
            SELECT attempt_index, attempt_id, candidate_id, batch_id, source_id,
                   artifact_root, status, start_ms, end_ms, report_id,
                   error_type, error_message
            FROM research_runner_attempts
            ORDER BY attempt_index
            """
        ).fetchall()
    else:
        resolved_candidate_id = _require_text(candidate_id, "candidate_id")
        rows = connection.execute(
            """
            SELECT attempt_index, attempt_id, candidate_id, batch_id, source_id,
                   artifact_root, status, start_ms, end_ms, report_id,
                   error_type, error_message
            FROM research_runner_attempts
            WHERE candidate_id = ?
            ORDER BY attempt_index
            """,
            (resolved_candidate_id,),
        ).fetchall()
    return tuple(
        ResearchRunnerAttempt(
            attempt_index=int(row["attempt_index"]),
            attempt_id=str(row["attempt_id"]),
            candidate_id=str(row["candidate_id"]),
            batch_id=str(row["batch_id"]),
            source_id=str(row["source_id"]),
            artifact_root=str(row["artifact_root"]),
            status=_stored_status(row["status"]),
            start_ms=None if row["start_ms"] is None else int(row["start_ms"]),
            end_ms=None if row["end_ms"] is None else int(row["end_ms"]),
            report_id=None if row["report_id"] is None else str(row["report_id"]),
            error_type=None if row["error_type"] is None else str(row["error_type"]),
            error_message=(
                None if row["error_message"] is None else str(row["error_message"])
            ),
        )
        for row in rows
    )