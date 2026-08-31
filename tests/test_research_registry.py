from __future__ import annotations

from pathlib import Path

from pytest import raises

from cocomelon.research.contracts import (
    SIX_HOURS_MS,
    ResearchCandidateManifest,
    ResearchCandidateState,
    TimeInterval,
)
from cocomelon.research.registry import (
    ResearchContaminationError,
    ResearchRegistry,
    ResearchRegistryError,
)


def _candidate(
    candidate_id: str,
    *,
    family_id: str = "family-a",
    parent_candidate_id: str | None = None,
    ancestor_candidate_ids: tuple[str, ...] = (),
    digest_char: str = "a",
) -> ResearchCandidateManifest:
    return ResearchCandidateManifest(
        candidate_id=candidate_id,
        family_id=family_id,
        parent_candidate_id=parent_candidate_id,
        ancestor_candidate_ids=ancestor_candidate_ids,
        config_digest=digest_char * 64,
        code_revision="1" * 40,
        state=ResearchCandidateState.DRAFT,
    )


def test_registry_persists_lineage_and_inherits_ancestor_touched_intervals(
    tmp_path: Path,
) -> None:
    path = tmp_path / "research.sqlite3"
    registry = ResearchRegistry(path)
    root = _candidate("r1", digest_char="a")
    child = _candidate(
        "r2",
        parent_candidate_id="r1",
        ancestor_candidate_ids=("r1",),
        digest_char="b",
    )
    grandchild = _candidate(
        "r3",
        parent_candidate_id="r2",
        ancestor_candidate_ids=("r1", "r2"),
        digest_char="c",
    )

    registry.create_candidate(root)
    registry.record_touched_interval("r1", TimeInterval(10, 20), source_id="root-source")
    registry.create_candidate(child)
    registry.record_touched_interval("r2", TimeInterval(30, 40), source_id="child-source")
    registry.create_candidate(grandchild)
    registry.record_touched_interval("r3", TimeInterval(19, 31), source_id="grandchild-source")
    registry.close()

    reopened = ResearchRegistry(path)
    assert reopened.effective_touched_intervals("r3") == (TimeInterval(10, 40),)
    assert reopened.load_candidate("r3") == grandchild
    reopened.close()


def test_registry_rejects_cross_family_or_inexact_parent_lineage(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    registry.create_candidate(_candidate("r1", family_id="family-a"))

    with raises(ResearchRegistryError, match="family"):
        registry.create_candidate(
            _candidate(
                "r2",
                family_id="family-b",
                parent_candidate_id="r1",
                ancestor_candidate_ids=("r1",),
                digest_char="b",
            )
        )

    with raises(ResearchRegistryError, match="ancestor"):
        registry.create_candidate(
            _candidate(
                "r3",
                family_id="family-a",
                parent_candidate_id="r1",
                ancestor_candidate_ids=("missing", "r1"),
                digest_char="c",
            )
        )
    registry.close()


def test_any_registered_v4_interval_blocks_overlapping_research_source(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    registry.record_v4_interval(
        run_id="v4-failed-run",
        interval=TimeInterval(1_000, 2_000),
        disposition="diagnostic_failure",
    )

    with raises(ResearchContaminationError, match="v4-failed-run"):
        registry.assert_batch_disjoint_from_v4(TimeInterval(1_999, 2_500))

    registry.assert_batch_disjoint_from_v4(TimeInterval(2_000, 2_500))
    registry.close()


def test_terminal_candidate_state_cannot_return_to_researching(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    registry.create_candidate(_candidate("r1"))
    registry.transition_candidate("r1", ResearchCandidateState.RESEARCHING, reason="started")
    registry.transition_candidate("r1", ResearchCandidateState.REJECTED_FUTILITY, reason="futile")

    with raises(ResearchRegistryError, match="terminal"):
        registry.transition_candidate("r1", ResearchCandidateState.RESEARCHING, reason="resume")
    registry.close()


def test_frozen_candidate_cutover_uses_inherited_touched_history(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    registry.create_candidate(_candidate("r1"))
    registry.record_touched_interval("r1", TimeInterval(10_000, 20_000), source_id="source")
    child = _candidate(
        "r2",
        parent_candidate_id="r1",
        ancestor_candidate_ids=("r1",),
        digest_char="b",
    )
    registry.create_candidate(child)
    registry.transition_candidate("r2", ResearchCandidateState.RESEARCHING, reason="started")
    registry.transition_candidate("r2", ResearchCandidateState.RESEARCH_PROMISING, reason="promising")
    registry.freeze_candidate("r2", freeze_ms=25_000)

    with raises(ResearchRegistryError, match="embargo"):
        registry.assert_validation_cutover(
            "r2",
            validation_start_ms=20_000 + SIX_HOURS_MS - 1,
        )

    registry.assert_validation_cutover(
        "r2",
        validation_start_ms=max(25_000, 20_000 + SIX_HOURS_MS),
    )
    registry.close()
