from __future__ import annotations

from pathlib import Path

import pytest

from cocomelon.research.contracts import (
    ResearchCandidateManifest,
    ResearchCandidateState,
    TimeInterval,
)
from cocomelon.research.registry import ResearchRegistry, ResearchRegistryError
from cocomelon.research.runner_history import (
    ResearchRunnerAttemptStatus,
    load_runner_attempts,
    record_runner_attempt_started,
)
from cocomelon.research.v4_authority import merge_v4_authority_snapshot


def _candidate(candidate_id: str = "candidate-a") -> ResearchCandidateManifest:
    return ResearchCandidateManifest(
        candidate_id=candidate_id,
        family_id="family-a",
        parent_candidate_id=None,
        ancestor_candidate_ids=(),
        config_digest="a" * 64,
        code_revision="b" * 40,
        execution_config_json='{"mode":"paper"}',
        risk_config_json='{"risk_per_trade":"0.0025"}',
        state=ResearchCandidateState.DRAFT,
        first_observation_ms=None,
        last_observation_ms=None,
        source_provenance_ids=(),
        local_touched_intervals=(),
        effective_touched_intervals=(),
        performance_report_ids=(),
    )


def _v4_rows(registry: ResearchRegistry) -> list[tuple[str, int, int, str]]:
    rows = registry.connection.execute(
        """
        SELECT run_id, start_ms, end_ms, disposition
        FROM research_v4_intervals
        ORDER BY run_id
        """
    ).fetchall()
    return [
        (
            str(row["run_id"]),
            int(row["start_ms"]),
            int(row["end_ms"]),
            str(row["disposition"]),
        )
        for row in rows
    ]


def test_refresh_merges_only_v4_authority_and_preserves_local_research_state(
    tmp_path: Path,
) -> None:
    local = ResearchRegistry(tmp_path / "local.sqlite3")
    authority = ResearchRegistry(tmp_path / "authority.sqlite3")
    try:
        local.create_candidate(_candidate())
        record_runner_attempt_started(
            local.connection,
            attempt_id="attempt-a",
            candidate_id="candidate-a",
            batch_id="batch-a",
            source_id="source-a",
            artifact_root="artifact-a",
        )
        authority.record_v4_interval(
            run_id="v4-failed-run",
            interval=TimeInterval(2_000, 2_500),
            disposition="failed_transport",
        )
        authority.mark_v4_registry_complete_through(
            through_ms=4_000,
            source_id="authoritative-v4-inventory",
        )

        merge_v4_authority_snapshot(local, authority.path)

        candidate = local.load_candidate("candidate-a")
        attempts = load_runner_attempts(local.connection)
        completeness = local.connection.execute(
            """
            SELECT complete_through_ms, source_id
            FROM research_v4_registry_state
            WHERE singleton = 1
            """
        ).fetchone()
    finally:
        authority.close()
        local.close()

    assert candidate.state is ResearchCandidateState.DRAFT
    assert candidate.performance_report_ids == ()
    assert len(attempts) == 1
    assert attempts[0].attempt_id == "attempt-a"
    assert attempts[0].status is ResearchRunnerAttemptStatus.RUNNING
    assert completeness is not None
    assert int(completeness["complete_through_ms"]) == 4_000
    assert str(completeness["source_id"]) == "authoritative-v4-inventory"


def test_refresh_retroactively_contaminates_overlapping_research_batch(tmp_path: Path) -> None:
    local = ResearchRegistry(tmp_path / "local.sqlite3")
    authority = ResearchRegistry(tmp_path / "authority.sqlite3")
    try:
        local.create_candidate(_candidate())
        local.mark_v4_registry_complete_through(
            through_ms=5_000,
            source_id="authoritative-v4-inventory",
        )
        local.record_batch(
            candidate_id="candidate-a",
            batch_id="batch-a",
            source_id="source-a",
            replay_run_id="replay-a",
            interval=TimeInterval(2_000, 3_000),
        )
        authority.record_v4_interval(
            run_id="v4-late-overlap",
            interval=TimeInterval(2_500, 2_750),
            disposition="failed_transport",
        )
        authority.mark_v4_registry_complete_through(
            through_ms=6_000,
            source_id="authoritative-v4-inventory",
        )

        merge_v4_authority_snapshot(local, authority.path)

        candidate = local.load_candidate("candidate-a")
        batch = local.connection.execute(
            """
            SELECT status, contamination_v4_run_id
            FROM research_batches
            WHERE batch_id = 'batch-a'
            """
        ).fetchone()
    finally:
        authority.close()
        local.close()

    assert candidate.state is ResearchCandidateState.REJECTED_CONTAMINATION
    assert batch is not None
    assert str(batch["status"]) == "rejected_contamination"
    assert str(batch["contamination_v4_run_id"]) == "v4-late-overlap"


def test_refresh_rolls_back_all_v4_updates_on_conflicting_snapshot(tmp_path: Path) -> None:
    local = ResearchRegistry(tmp_path / "local.sqlite3")
    authority = ResearchRegistry(tmp_path / "authority.sqlite3")
    try:
        local.record_v4_interval(
            run_id="v4-conflict",
            interval=TimeInterval(1_000, 1_500),
            disposition="accepted",
        )
        local.mark_v4_registry_complete_through(
            through_ms=2_000,
            source_id="authoritative-v4-inventory",
        )
        authority.record_v4_interval(
            run_id="v4-before-conflict",
            interval=TimeInterval(2_100, 2_200),
            disposition="failed_transport",
        )
        authority.record_v4_interval(
            run_id="v4-conflict",
            interval=TimeInterval(1_050, 1_550),
            disposition="accepted",
        )
        authority.mark_v4_registry_complete_through(
            through_ms=3_000,
            source_id="authoritative-v4-inventory",
        )

        with pytest.raises(ResearchRegistryError, match="different data"):
            merge_v4_authority_snapshot(local, authority.path)

        rows = _v4_rows(local)
        completeness = local.connection.execute(
            "SELECT complete_through_ms FROM research_v4_registry_state WHERE singleton = 1"
        ).fetchone()
    finally:
        authority.close()
        local.close()

    assert rows == [("v4-conflict", 1_000, 1_500, "accepted")]
    assert completeness is not None
    assert int(completeness["complete_through_ms"]) == 2_000
