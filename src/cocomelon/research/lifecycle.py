from __future__ import annotations

from cocomelon.research.contracts import ResearchCandidateState, validation_cutover_allowed
from cocomelon.research.registry import ResearchRegistry, ResearchRegistryError


def activate_validation_cutover(
    registry: ResearchRegistry,
    candidate_id: str,
    *,
    validation_start_ms: int,
) -> None:
    if validation_start_ms < 0:
        raise ResearchRegistryError("validation_start_ms must be non-negative")
    registry._begin_immediate()
    try:
        row = registry.connection.execute(
            """
            SELECT state, freeze_ms
            FROM research_candidates
            WHERE candidate_id = ?
            """,
            (candidate_id,),
        ).fetchone()
        if row is None:
            raise ResearchRegistryError(f"candidate not found: {candidate_id}")
        if str(row["state"]) != ResearchCandidateState.FROZEN_CHALLENGER.value:
            raise ResearchRegistryError(
                "candidate must remain frozen and uncontaminated for validation cutover"
            )
        if row["freeze_ms"] is None:
            raise ResearchRegistryError("candidate freeze timestamp is missing")
        if not validation_cutover_allowed(
            validation_start_ms=validation_start_ms,
            freeze_ms=int(row["freeze_ms"]),
            effective_touched_intervals=registry.effective_touched_intervals(candidate_id),
        ):
            raise ResearchRegistryError(
                "validation cutover violates freeze or touched-data embargo"
            )
        cursor = registry.connection.execute(
            """
            UPDATE research_candidates
            SET state = ?
            WHERE candidate_id = ? AND state = ?
            """,
            (
                ResearchCandidateState.VALIDATING.value,
                candidate_id,
                ResearchCandidateState.FROZEN_CHALLENGER.value,
            ),
        )
        if cursor.rowcount != 1:
            raise ResearchRegistryError("candidate validation state changed concurrently")
        registry.connection.execute(
            """
            INSERT INTO research_candidate_state_events (candidate_id, state, reason)
            VALUES (?, ?, ?)
            """,
            (
                candidate_id,
                ResearchCandidateState.VALIDATING.value,
                f"validation_cutover:{validation_start_ms}",
            ),
        )
        registry.connection.commit()
    except Exception:
        registry.connection.rollback()
        raise
