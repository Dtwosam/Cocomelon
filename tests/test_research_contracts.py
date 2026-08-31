from __future__ import annotations

from pytest import raises

from cocomelon.research.contracts import (
    SIX_HOURS_MS,
    ResearchCandidateManifest,
    ResearchCandidateState,
    TimeInterval,
    intervals_overlap,
    normalize_intervals,
    validation_cutover_allowed,
)


def test_normalize_intervals_merges_overlapping_and_touching_ranges() -> None:
    intervals = (
        TimeInterval(30, 40),
        TimeInterval(10, 20),
        TimeInterval(18, 25),
        TimeInterval(25, 30),
    )

    assert normalize_intervals(intervals) == (TimeInterval(10, 40),)


def test_half_open_intervals_do_not_overlap_when_only_touching() -> None:
    assert intervals_overlap(TimeInterval(10, 20), TimeInterval(20, 30)) is False
    assert intervals_overlap(TimeInterval(10, 21), TimeInterval(20, 30)) is True


def test_candidate_root_and_child_lineage_are_explicit() -> None:
    root = ResearchCandidateManifest(
        candidate_id="research-r1-root",
        family_id="family-a",
        parent_candidate_id=None,
        ancestor_candidate_ids=(),
        config_digest="a" * 64,
        code_revision="1" * 40,
        state=ResearchCandidateState.DRAFT,
    )
    child = ResearchCandidateManifest(
        candidate_id="research-r2-child",
        family_id=root.family_id,
        parent_candidate_id=root.candidate_id,
        ancestor_candidate_ids=(root.candidate_id,),
        config_digest="b" * 64,
        code_revision="2" * 40,
        state=ResearchCandidateState.DRAFT,
    )

    assert child.parent_candidate_id == root.candidate_id
    assert child.ancestor_candidate_ids == (root.candidate_id,)


def test_candidate_rejects_duplicate_or_self_ancestor() -> None:
    with raises(ValueError, match="ancestor"):
        ResearchCandidateManifest(
            candidate_id="research-r2-child",
            family_id="family-a",
            parent_candidate_id="research-r1-root",
            ancestor_candidate_ids=("research-r1-root", "research-r1-root"),
            config_digest="b" * 64,
            code_revision="2" * 40,
            state=ResearchCandidateState.DRAFT,
        )

    with raises(ValueError, match="ancestor"):
        ResearchCandidateManifest(
            candidate_id="research-r2-child",
            family_id="family-a",
            parent_candidate_id="research-r1-root",
            ancestor_candidate_ids=("research-r1-root", "research-r2-child"),
            config_digest="b" * 64,
            code_revision="2" * 40,
            state=ResearchCandidateState.DRAFT,
        )


def test_validation_cutover_requires_freeze_and_six_hour_embargo() -> None:
    touched = (TimeInterval(1_000, 2_000), TimeInterval(3_000, 4_000))
    freeze_ms = 5_000

    assert validation_cutover_allowed(
        validation_start_ms=4_000 + SIX_HOURS_MS - 1,
        freeze_ms=freeze_ms,
        effective_touched_intervals=touched,
    ) is False
    assert validation_cutover_allowed(
        validation_start_ms=freeze_ms - 1,
        freeze_ms=freeze_ms,
        effective_touched_intervals=touched,
    ) is False
    assert validation_cutover_allowed(
        validation_start_ms=max(freeze_ms, 4_000 + SIX_HOURS_MS),
        freeze_ms=freeze_ms,
        effective_touched_intervals=touched,
    ) is True
