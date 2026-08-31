from __future__ import annotations

from pathlib import Path

import pytest

from cocomelon.research.contracts import (
    ResearchCandidateManifest,
    ResearchCandidateState,
    TimeInterval,
)
from cocomelon.research.registry import ResearchRegistry, ResearchRegistryError

EXECUTION_CONFIG = '{"mode":"paper","slippage_model":"recorded"}'
RISK_CONFIG = '{"max_position_r":"1","stops_required":true}'


def _candidate(
    candidate_id: str,
    *,
    parent_candidate_id: str | None = None,
    ancestor_candidate_ids: tuple[str, ...] = (),
    digest_char: str = "a",
) -> ResearchCandidateManifest:
    return ResearchCandidateManifest(
        candidate_id=candidate_id,
        family_id="race-family",
        parent_candidate_id=parent_candidate_id,
        ancestor_candidate_ids=ancestor_candidate_ids,
        config_digest=digest_char * 64,
        code_revision="1" * 40,
        execution_config_json=EXECUTION_CONFIG,
        risk_config_json=RISK_CONFIG,
        state=ResearchCandidateState.DRAFT,
        first_observation_ms=None,
        last_observation_ms=None,
        source_provenance_ids=(),
        local_touched_intervals=(),
        effective_touched_intervals=(),
        performance_report_ids=(),
    )


def test_freeze_cannot_overwrite_late_v4_contamination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry_path = tmp_path / "research.sqlite3"
    registry = ResearchRegistry(registry_path)
    registry.mark_v4_registry_complete_through(
        through_ms=10_000,
        source_id="authoritative-v4-inventory",
    )
    registry.create_candidate(_candidate("freeze-race"))
    registry.record_batch(
        candidate_id="freeze-race",
        batch_id="freeze-race-batch",
        source_id="freeze-race-source",
        replay_run_id="freeze-race-replay",
        interval=TimeInterval(1_000, 2_000),
    )
    registry.connection.execute(
        "UPDATE research_candidates SET state = ? WHERE candidate_id = ?",
        (ResearchCandidateState.RESEARCH_PROMISING.value, "freeze-race"),
    )
    registry.connection.commit()

    original_load = registry.load_candidate
    contaminated = False

    def load_then_contaminate(candidate_id: str) -> ResearchCandidateManifest:
        nonlocal contaminated
        candidate = original_load(candidate_id)
        if candidate_id == "freeze-race" and not contaminated:
            contaminated = True
            late_registry = ResearchRegistry(registry_path)
            try:
                late_registry.record_v4_interval(
                    run_id="late-v4-freeze-race",
                    interval=TimeInterval(1_500, 1_600),
                    disposition="diagnostic_failure",
                )
            finally:
                late_registry.close()
        return candidate

    monkeypatch.setattr(registry, "load_candidate", load_then_contaminate)

    with pytest.raises(ResearchRegistryError, match="changed concurrently"):
        registry.freeze_candidate("freeze-race", freeze_ms=20_000)

    assert original_load("freeze-race").state is ResearchCandidateState.REJECTED_CONTAMINATION
    frozen_events = registry.connection.execute(
        """
        SELECT COUNT(*) AS event_count
        FROM research_candidate_state_events
        WHERE candidate_id = ? AND state = ?
        """,
        ("freeze-race", ResearchCandidateState.FROZEN_CHALLENGER.value),
    ).fetchone()
    assert frozen_events is not None
    assert int(frozen_events["event_count"]) == 0
    registry.close()


def test_child_creation_locks_before_parent_validation_and_insert(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    registry.create_candidate(_candidate("parent"))
    trace: list[str] = []
    registry.connection.set_trace_callback(trace.append)

    registry.create_candidate(
        _candidate(
            "child",
            parent_candidate_id="parent",
            ancestor_candidate_ids=("parent",),
            digest_char="b",
        )
    )

    upper = [statement.upper() for statement in trace]
    begin_index = next(
        index for index, statement in enumerate(upper) if statement.startswith("BEGIN IMMEDIATE")
    )
    parent_read_index = next(
        index
        for index, statement in enumerate(upper)
        if "ANCESTOR_CANDIDATE_IDS_JSON" in statement
        and "FROM RESEARCH_CANDIDATES" in statement
    )
    insert_index = next(
        index
        for index, statement in enumerate(upper)
        if "INSERT INTO RESEARCH_CANDIDATES" in statement
    )
    assert begin_index < parent_read_index < insert_index
    registry.close()
