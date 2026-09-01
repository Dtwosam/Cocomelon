from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from cocomelon.research.contracts import ResearchCandidateState


@dataclass(frozen=True, slots=True)
class AuthenticatedCheckpointCommit:
    commit_index: int
    report_id: str
    candidate_id: str
    state: ResearchCandidateState


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def record_authenticated_checkpoint_commit(
    connection: sqlite3.Connection,
    *,
    candidate_id: str,
    report_id: str,
    state: ResearchCandidateState,
) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS research_checkpoint_commits (
            commit_index INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id TEXT NOT NULL UNIQUE,
            candidate_id TEXT NOT NULL,
            candidate_state TEXT NOT NULL,
            FOREIGN KEY(report_id) REFERENCES research_performance_reports(report_id),
            FOREIGN KEY(candidate_id) REFERENCES research_candidates(candidate_id)
        )
        """
    )
    existing = connection.execute(
        """
        SELECT candidate_id, candidate_state
        FROM research_checkpoint_commits
        WHERE report_id = ?
        """,
        (report_id,),
    ).fetchone()
    if existing is not None:
        stored = (str(existing["candidate_id"]), str(existing["candidate_state"]))
        incoming = (candidate_id, state.value)
        if stored != incoming:
            raise ValueError(
                f"authenticated checkpoint commit already exists with different data: {report_id}"
            )
        return
    connection.execute(
        """
        INSERT INTO research_checkpoint_commits (
            report_id, candidate_id, candidate_state
        ) VALUES (?, ?, ?)
        """,
        (report_id, candidate_id, state.value),
    )


def load_authenticated_checkpoint_commits(
    connection: sqlite3.Connection,
    *,
    candidate_id: str,
) -> tuple[AuthenticatedCheckpointCommit, ...]:
    if not _table_exists(connection, "research_checkpoint_commits"):
        return ()
    rows = connection.execute(
        """
        SELECT commit_index, report_id, candidate_id, candidate_state
        FROM research_checkpoint_commits
        WHERE candidate_id = ?
        ORDER BY commit_index
        """,
        (candidate_id,),
    ).fetchall()
    result: list[AuthenticatedCheckpointCommit] = []
    for row in rows:
        try:
            state = ResearchCandidateState(str(row["candidate_state"]))
        except ValueError as exc:
            raise ValueError("stored checkpoint commit state is invalid") from exc
        result.append(
            AuthenticatedCheckpointCommit(
                commit_index=int(row["commit_index"]),
                report_id=str(row["report_id"]),
                candidate_id=str(row["candidate_id"]),
                state=state,
            )
        )
    return tuple(result)
