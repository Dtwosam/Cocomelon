from __future__ import annotations

import json
import sqlite3

from cocomelon.research.contracts import ResearchCandidateState
from cocomelon.research.registry import ResearchRegistry, ResearchRegistryError
from cocomelon.research.report_auth import assert_checkpoint_report_backed_by_observations

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


def commit_checkpoint_report_and_state(
    registry: ResearchRegistry,
    *,
    candidate_id: str,
    state: ResearchCandidateState,
    report_id: str,
    payload: dict[str, object],
) -> None:
    registry._begin_immediate()
    try:
        current = registry.load_candidate(candidate_id)
        _validate_transition(current.state, state)
        canonical_payload = _canonical_payload(registry, payload)
        _require_attested_batch_provenance(canonical_payload)
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
        _persist_report_uncommitted(
            registry,
            candidate_id=candidate_id,
            report_id=report_id,
            payload=canonical_payload,
        )
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
        registry.connection.commit()
    except (ResearchRegistryError, sqlite3.Error):
        registry.connection.rollback()
        raise
    except Exception:
        registry.connection.rollback()
        raise
