from __future__ import annotations

import json
import sqlite3

from cocomelon.research.checkpoint_history import (
    load_authenticated_checkpoint_commits,
    record_authenticated_checkpoint_commit,
)
from cocomelon.research.contracts import ResearchCandidateState
from cocomelon.research.registry import ResearchRegistry, ResearchRegistryError
from cocomelon.research.report_auth import (
    assert_checkpoint_report_backed_by_observations,
    assert_historical_checkpoint_report_backed_by_observations,
)

_TERMINAL_STATES = frozenset(
    {
        ResearchCandidateState.REJECTED_OPERATIONAL,
        ResearchCandidateState.REJECTED_CONTAMINATION,
        ResearchCandidateState.REJECTED_FUTILITY,
        ResearchCandidateState.VALIDATED_EDGE,
        ResearchCandidateState.NO_EDGE,
    }
)
_ALLOWED_CHECKPOINT_STATES = frozenset(
    {
        ResearchCandidateState.RESEARCHING,
        ResearchCandidateState.RESEARCH_PROMISING,
        ResearchCandidateState.REJECTED_FUTILITY,
        ResearchCandidateState.REJECTED_OPERATIONAL,
    }
)


def _validate_transition(
    current: ResearchCandidateState,
    target: ResearchCandidateState,
) -> None:
    if current in _TERMINAL_STATES and target is not current:
        raise ResearchRegistryError(f"candidate is terminal: {current.value}")
    if current is ResearchCandidateState.FROZEN_CHALLENGER:
        raise ResearchRegistryError(
            "candidate is terminal to research checkpoints: frozen_challenger"
        )
    if target not in _ALLOWED_CHECKPOINT_STATES:
        raise ResearchRegistryError(f"checkpoint cannot enter {target.value}")
    if (
        current is ResearchCandidateState.RESEARCH_PROMISING
        and target is ResearchCandidateState.RESEARCHING
    ):
        raise ResearchRegistryError(
            "research-promising candidate cannot return to researching"
        )


def _persist_report_uncommitted(
    registry: ResearchRegistry,
    *,
    candidate_id: str,
    report_id: str,
    payload: dict[str, object],
) -> None:
    if not report_id.strip():
        raise ResearchRegistryError("report_id must not be empty")
    payload_json = registry._canonical_json(payload)
    existing = registry.connection.execute(
        """
        SELECT candidate_id, payload_json
        FROM research_performance_reports
        WHERE report_id = ?
        """,
        (report_id,),
    ).fetchone()
    if existing is not None:
        if (
            str(existing["candidate_id"]) != candidate_id
            or str(existing["payload_json"]) != payload_json
        ):
            raise ResearchRegistryError(
                f"performance report already exists with different content: {report_id}"
            )
        return
    registry.connection.execute(
        """
        INSERT INTO research_performance_reports (report_id, candidate_id, payload_json)
        VALUES (?, ?, ?)
        """,
        (report_id, candidate_id, payload_json),
    )


def _canonical_payload(
    registry: ResearchRegistry,
    payload: dict[str, object],
) -> dict[str, object]:
    decoded = json.loads(registry._canonical_json(payload))
    if not isinstance(decoded, dict) or not all(isinstance(key, str) for key in decoded):
        raise ResearchRegistryError("checkpoint report payload must be an object")
    return decoded


def _require_attested_batch_provenance(payload: dict[str, object]) -> None:
    batch_ids = payload.get("batch_ids")
    if (
        not isinstance(batch_ids, list)
        or not batch_ids
        or not all(isinstance(batch_id, str) and batch_id.strip() for batch_id in batch_ids)
    ):
        raise ResearchRegistryError("checkpoint report requires attested batch provenance")


def _legacy_report_state(payload: dict[str, object]) -> ResearchCandidateState:
    value = payload.get("candidate_state")
    if not isinstance(value, str):
        raise ResearchRegistryError("legacy checkpoint state is invalid")
    try:
        return ResearchCandidateState(value)
    except ValueError as exc:
        raise ResearchRegistryError("legacy checkpoint state is invalid") from exc


def _legacy_batch_ids(payload: dict[str, object]) -> tuple[str, ...]:
    value = payload.get("batch_ids")
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item.strip() for item in value)
    ):
        raise ResearchRegistryError("legacy checkpoint batch provenance is invalid")
    batch_ids = tuple(value)
    if len(set(batch_ids)) != len(batch_ids):
        raise ResearchRegistryError("legacy checkpoint batch provenance is invalid")
    return batch_ids


def _legacy_source_end_ms(
    registry: ResearchRegistry,
    *,
    candidate_id: str,
    batch_ids: tuple[str, ...],
) -> int:
    ends: list[int] = []
    for batch_id in batch_ids:
        row = registry.connection.execute(
            """
            SELECT candidate_id, end_ms, status
            FROM research_batches
            WHERE batch_id = ?
            """,
            (batch_id,),
        ).fetchone()
        if (
            row is None
            or str(row["candidate_id"]) != candidate_id
            or str(row["status"]) != "admitted"
        ):
            raise ResearchRegistryError("legacy checkpoint batch provenance is invalid")
        ends.append(int(row["end_ms"]))
    return max(ends)


def _seal_legacy_checkpoint_prefix(
    registry: ResearchRegistry,
    *,
    candidate_id: str,
) -> None:
    rows = registry.connection.execute(
        """
        SELECT report_id, payload_json
        FROM research_performance_reports
        WHERE candidate_id = ?
        ORDER BY report_id
        """,
        (candidate_id,),
    ).fetchall()
    if not rows:
        return

    reports: dict[str, dict[str, object]] = {}
    for row in rows:
        report_id = str(row["report_id"])
        try:
            payload = json.loads(str(row["payload_json"]))
        except json.JSONDecodeError:
            return
        if not isinstance(payload, dict) or not all(isinstance(key, str) for key in payload):
            return
        reports[report_id] = payload

    commits = load_authenticated_checkpoint_commits(
        registry.connection,
        candidate_id=candidate_id,
    )
    if commits:
        committed_ids = {commit.report_id for commit in commits}
        if committed_ids != set(reports):
            raise ResearchRegistryError(
                "checkpoint history contains unauthenticated performance report"
            )
        return

    legacy: list[
        tuple[int, int, str, ResearchCandidateState, tuple[str, ...]]
    ] = []
    for report_id, payload in reports.items():
        try:
            state = _legacy_report_state(payload)
            assert_historical_checkpoint_report_backed_by_observations(
                registry.connection,
                candidate_id=candidate_id,
                report_id=report_id,
                payload=payload,
                state=state,
            )
            batch_ids = _legacy_batch_ids(payload)
            source_end_ms = _legacy_source_end_ms(
                registry,
                candidate_id=candidate_id,
                batch_ids=batch_ids,
            )
        except (ResearchRegistryError, ValueError):
            return
        legacy.append((source_end_ms, len(batch_ids), report_id, state, batch_ids))

    legacy.sort(key=lambda item: (item[0], item[1], item[2]))
    previous_batch_ids: set[str] = set()
    for _source_end_ms, _batch_count, _report_id, _state, batch_ids in legacy:
        current_batch_ids = set(batch_ids)
        if not previous_batch_ids.issubset(current_batch_ids):
            return
        previous_batch_ids = current_batch_ids

    for _source_end_ms, _batch_count, report_id, state, _batch_ids in legacy:
        try:
            record_authenticated_checkpoint_commit(
                registry.connection,
                candidate_id=candidate_id,
                report_id=report_id,
                state=state,
            )
        except ValueError as exc:
            raise ResearchRegistryError(str(exc)) from exc


def complete_runner_attempt_success_uncommitted(
    connection: sqlite3.Connection,
    *,
    attempt_id: str,
    candidate_id: str,
    start_ms: int,
    end_ms: int,
    report_id: str,
) -> None:
    if not connection.in_transaction:
        raise ResearchRegistryError(
            "runner success must share the authenticated checkpoint transaction"
        )
    resolved_attempt_id = attempt_id.strip()
    resolved_candidate_id = candidate_id.strip()
    resolved_report_id = report_id.strip()
    if not resolved_attempt_id:
        raise ResearchRegistryError("research runner attempt_id must not be empty")
    if not resolved_candidate_id:
        raise ResearchRegistryError("research runner candidate_id must not be empty")
    if not resolved_report_id:
        raise ResearchRegistryError("successful research runner attempt requires report_id")
    if start_ms < 0 or end_ms <= start_ms:
        raise ResearchRegistryError("research runner attempt interval is invalid")

    row = connection.execute(
        """
        SELECT candidate_id, status
        FROM research_runner_attempts
        WHERE attempt_id = ?
        """,
        (resolved_attempt_id,),
    ).fetchone()
    if row is None:
        raise ResearchRegistryError(
            f"research runner attempt not found: {resolved_attempt_id}"
        )
    if str(row["candidate_id"]) != resolved_candidate_id:
        raise ResearchRegistryError(
            "research runner attempt candidate does not match checkpoint candidate"
        )
    if str(row["status"]) != "evaluating":
        raise ResearchRegistryError(
            "successful research runner attempt requires an evaluation claim"
        )

    cursor = connection.execute(
        """
        UPDATE research_runner_attempts
        SET status = 'succeeded', start_ms = ?, end_ms = ?, report_id = ?,
            error_type = NULL, error_message = NULL
        WHERE attempt_id = ? AND candidate_id = ? AND status = 'evaluating'
        """,
        (
            start_ms,
            end_ms,
            resolved_report_id,
            resolved_attempt_id,
            resolved_candidate_id,
        ),
    )
    if cursor.rowcount != 1:
        raise ResearchRegistryError("research runner attempt changed concurrently")


def _validate_runner_commit_context(
    *,
    runner_attempt_id: str | None,
    runner_start_ms: int | None,
    runner_end_ms: int | None,
) -> None:
    values = (runner_attempt_id, runner_start_ms, runner_end_ms)
    if all(value is None for value in values):
        return
    if runner_attempt_id is None or runner_start_ms is None or runner_end_ms is None:
        raise ResearchRegistryError(
            "runner checkpoint commit context must include attempt id and complete interval"
        )


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def _claimed_runner_commit_context(
    connection: sqlite3.Connection,
    *,
    candidate_id: str,
    payload: dict[str, object],
) -> tuple[str, int, int] | None:
    if not _table_exists(connection, "research_runner_attempts"):
        return None
    batch_ids = payload.get("batch_ids")
    if not isinstance(batch_ids, list) or not batch_ids:
        return None
    resolved_batch_ids = tuple(
        str(batch_id) for batch_id in batch_ids if isinstance(batch_id, str) and batch_id.strip()
    )
    if len(resolved_batch_ids) != len(batch_ids):
        raise ResearchRegistryError("checkpoint report batch provenance is invalid")
    placeholders = ",".join("?" for _ in resolved_batch_ids)
    rows = connection.execute(
        f"""
        SELECT attempt_id, batch_id
        FROM research_runner_attempts
        WHERE candidate_id = ? AND status = 'evaluating'
          AND batch_id IN ({placeholders})
        ORDER BY attempt_id
        """,
        (candidate_id, *resolved_batch_ids),
    ).fetchall()
    if not rows:
        return None
    if len(rows) != 1:
        raise ResearchRegistryError(
            "authenticated checkpoint matches multiple evaluating runner attempts"
        )
    attempt_id = str(rows[0]["attempt_id"])
    batch_id = str(rows[0]["batch_id"])
    batch = connection.execute(
        """
        SELECT start_ms, end_ms, status
        FROM research_batches
        WHERE batch_id = ? AND candidate_id = ?
        """,
        (batch_id, candidate_id),
    ).fetchone()
    if batch is None or str(batch["status"]) != "admitted":
        raise ResearchRegistryError(
            "evaluating runner attempt is not backed by an admitted research batch"
        )
    return attempt_id, int(batch["start_ms"]), int(batch["end_ms"])


def commit_checkpoint_report_and_state(
    registry: ResearchRegistry,
    *,
    candidate_id: str,
    state: ResearchCandidateState,
    report_id: str,
    payload: dict[str, object],
    runner_attempt_id: str | None = None,
    runner_start_ms: int | None = None,
    runner_end_ms: int | None = None,
) -> None:
    _validate_runner_commit_context(
        runner_attempt_id=runner_attempt_id,
        runner_start_ms=runner_start_ms,
        runner_end_ms=runner_end_ms,
    )
    registry._begin_immediate()
    try:
        current = registry.load_candidate(candidate_id)
        _validate_transition(current.state, state)
        canonical_payload = _canonical_payload(registry, payload)
        _require_attested_batch_provenance(canonical_payload)
        if runner_attempt_id is None:
            inferred_runner = _claimed_runner_commit_context(
                registry.connection,
                candidate_id=candidate_id,
                payload=canonical_payload,
            )
            if inferred_runner is not None:
                runner_attempt_id, runner_start_ms, runner_end_ms = inferred_runner
        try:
            assert_checkpoint_report_backed_by_observations(
                registry.connection,
                candidate_id=candidate_id,
                report_id=report_id,
                payload=canonical_payload,
                state=state,
            )
        except ValueError as exc:
            raise ResearchRegistryError(str(exc)) from exc
        registry._validate_checkpoint_report_for_state(canonical_payload, state)
        _seal_legacy_checkpoint_prefix(registry, candidate_id=candidate_id)
        _persist_report_uncommitted(
            registry,
            candidate_id=candidate_id,
            report_id=report_id,
            payload=canonical_payload,
        )
        try:
            record_authenticated_checkpoint_commit(
                registry.connection,
                candidate_id=candidate_id,
                report_id=report_id,
                state=state,
            )
        except ValueError as exc:
            raise ResearchRegistryError(str(exc)) from exc
        if current.state is not state:
            cursor = registry.connection.execute(
                """
                UPDATE research_candidates
                SET state = ?
                WHERE candidate_id = ? AND state = ?
                """,
                (state.value, candidate_id, current.state.value),
            )
            if cursor.rowcount != 1:
                raise ResearchRegistryError("candidate state changed concurrently")
            registry.connection.execute(
                """
                INSERT INTO research_candidate_state_events (candidate_id, state, reason)
                VALUES (?, ?, ?)
                """,
                (candidate_id, state.value, f"checkpoint_report:{report_id}"),
            )
        if runner_attempt_id is not None:
            assert runner_start_ms is not None
            assert runner_end_ms is not None
            complete_runner_attempt_success_uncommitted(
                registry.connection,
                attempt_id=runner_attempt_id,
                candidate_id=candidate_id,
                start_ms=runner_start_ms,
                end_ms=runner_end_ms,
                report_id=report_id,
            )
        registry.connection.commit()
    except (ResearchRegistryError, sqlite3.Error):
        registry.connection.rollback()
        raise
    except Exception:
        registry.connection.rollback()
        raise
