from __future__ import annotations

from pathlib import Path

from pytest import raises

from cocomelon.research.contracts import (
    ResearchCandidateManifest,
    ResearchCandidateState,
    TimeInterval,
)
from cocomelon.research.registry import ResearchRegistry, ResearchRegistryError

EXECUTION_CONFIG = '{"mode":"paper","slippage_model":"recorded"}'
RISK_CONFIG = '{"max_position_r":"1","stops_required":true}'


def _candidate() -> ResearchCandidateManifest:
    return ResearchCandidateManifest(
        candidate_id="safety-r1",
        family_id="safety-family",
        parent_candidate_id=None,
        ancestor_candidate_ids=(),
        config_digest="a" * 64,
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


def test_research_source_fails_closed_without_authoritative_v4_completeness(
    tmp_path: Path,
) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")

    with raises(ResearchRegistryError, match="V4 registry completeness"):
        registry.assert_batch_disjoint_from_v4(TimeInterval(1_000, 2_000))

    registry.close()


def test_v4_completeness_must_cover_entire_research_interval(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    registry.mark_v4_registry_complete_through(
        through_ms=1_999,
        source_id="authoritative-v4-inventory",
    )

    with raises(ResearchRegistryError, match="V4 registry completeness"):
        registry.assert_batch_disjoint_from_v4(TimeInterval(1_000, 2_000))

    registry.mark_v4_registry_complete_through(
        through_ms=2_000,
        source_id="authoritative-v4-inventory",
    )
    registry.assert_batch_disjoint_from_v4(TimeInterval(1_000, 2_000))
    registry.close()


def test_v4_completeness_watermark_is_monotonic_and_source_bound(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    registry.mark_v4_registry_complete_through(
        through_ms=5_000,
        source_id="authoritative-v4-inventory",
    )
    registry.mark_v4_registry_complete_through(
        through_ms=5_000,
        source_id="authoritative-v4-inventory",
    )

    with raises(ResearchRegistryError, match="cannot move backwards"):
        registry.mark_v4_registry_complete_through(
            through_ms=4_999,
            source_id="authoritative-v4-inventory",
        )
    with raises(ResearchRegistryError, match="source"):
        registry.mark_v4_registry_complete_through(
            through_ms=6_000,
            source_id="different-inventory",
        )
    registry.close()


def test_record_batch_locks_before_v4_completeness_and_overlap_scan(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    registry.create_candidate(_candidate())
    registry.mark_v4_registry_complete_through(
        through_ms=10_000,
        source_id="authoritative-v4-inventory",
    )
    trace: list[str] = []
    registry.connection.set_trace_callback(trace.append)

    registry.record_batch(
        candidate_id="safety-r1",
        batch_id="safe-batch",
        source_id="safe-source",
        replay_run_id="safe-replay",
        interval=TimeInterval(1_000, 2_000),
    )

    upper = [statement.upper() for statement in trace]
    begin_index = next(
        index for index, statement in enumerate(upper) if statement.startswith("BEGIN IMMEDIATE")
    )
    v4_scan_index = next(
        index
        for index, statement in enumerate(upper)
        if "FROM RESEARCH_V4_INTERVALS" in statement
    )
    insert_index = next(
        index
        for index, statement in enumerate(upper)
        if "INSERT INTO RESEARCH_BATCHES" in statement
    )
    assert begin_index < v4_scan_index < insert_index
    registry.close()


def test_record_v4_interval_locks_before_overlapping_batch_scan(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    trace: list[str] = []
    registry.connection.set_trace_callback(trace.append)

    registry.record_v4_interval(
        run_id="v4-run",
        interval=TimeInterval(3_000, 4_000),
        disposition="diagnostic_failure",
    )

    upper = [statement.upper() for statement in trace]
    begin_index = next(
        index for index, statement in enumerate(upper) if statement.startswith("BEGIN IMMEDIATE")
    )
    batch_scan_index = next(
        index
        for index, statement in enumerate(upper)
        if "FROM RESEARCH_BATCHES" in statement
    )
    insert_index = next(
        index
        for index, statement in enumerate(upper)
        if "INSERT INTO RESEARCH_V4_INTERVALS" in statement
    )
    assert begin_index < batch_scan_index < insert_index
    registry.close()
