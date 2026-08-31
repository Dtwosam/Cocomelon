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


def _manifest(
    *,
    candidate_id: str,
    family_id: str = "family-a",
    parent_candidate_id: str | None = None,
    ancestor_candidate_ids: tuple[str, ...] = (),
    digest_char: str = "a",
    code_revision: str = "1" * 40,
    state: ResearchCandidateState = ResearchCandidateState.DRAFT,
    first_observation_ms: int | None = None,
    last_observation_ms: int | None = None,
    source_provenance_ids: tuple[str, ...] = (),
    local_touched_intervals: tuple[TimeInterval, ...] = (),
    effective_touched_intervals: tuple[TimeInterval, ...] = (),
    performance_report_ids: tuple[str, ...] = (),
) -> ResearchCandidateManifest:
    return ResearchCandidateManifest(
        candidate_id=candidate_id,
        family_id=family_id,
        parent_candidate_id=parent_candidate_id,
        ancestor_candidate_ids=ancestor_candidate_ids,
        config_digest=digest_char * 64,
        code_revision=code_revision,
        execution_config_json='{"mode":"paper","slippage_model":"recorded"}',
        risk_config_json='{"max_position_r":"1","stops_required":true}',
        state=state,
        first_observation_ms=first_observation_ms,
        last_observation_ms=last_observation_ms,
        source_provenance_ids=source_provenance_ids,
        local_touched_intervals=local_touched_intervals,
        effective_touched_intervals=effective_touched_intervals,
        performance_report_ids=performance_report_ids,
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
    root = _manifest(candidate_id="research-r1-root")
    child = _manifest(
        candidate_id="research-r2-child",
        family_id=root.family_id,
        parent_candidate_id=root.candidate_id,
        ancestor_candidate_ids=(root.candidate_id,),
        digest_char="b",
        code_revision="2" * 40,
    )

    assert child.parent_candidate_id == root.candidate_id
    assert child.ancestor_candidate_ids == (root.candidate_id,)
    assert child.execution_config_json == (
        '{"mode":"paper","slippage_model":"recorded"}'
    )
    assert child.risk_config_json == (
        '{"max_position_r":"1","stops_required":true}'
    )


def test_candidate_rejects_duplicate_or_self_ancestor() -> None:
    with raises(ValueError, match="ancestor"):
        _manifest(
            candidate_id="research-r2-child",
            parent_candidate_id="research-r1-root",
            ancestor_candidate_ids=("research-r1-root", "research-r1-root"),
            digest_char="b",
            code_revision="2" * 40,
        )

    with raises(ValueError, match="ancestor"):
        _manifest(
            candidate_id="research-r2-child",
            parent_candidate_id="research-r1-root",
            ancestor_candidate_ids=("research-r1-root", "research-r2-child"),
            digest_char="b",
            code_revision="2" * 40,
        )


def test_candidate_manifest_requires_consistent_observation_provenance() -> None:
    touched = (TimeInterval(1_000, 2_000), TimeInterval(3_000, 4_000))
    manifest = _manifest(
        candidate_id="research-r1-root",
        first_observation_ms=1_000,
        last_observation_ms=4_000,
        source_provenance_ids=("source-b", "source-a"),
        local_touched_intervals=touched,
        effective_touched_intervals=touched,
        performance_report_ids=("report-b", "report-a"),
    )

    assert manifest.source_provenance_ids == ("source-a", "source-b")
    assert manifest.performance_report_ids == ("report-a", "report-b")

    with raises(ValueError, match="observation"):
        _manifest(
            candidate_id="research-r2-bad-observation",
            first_observation_ms=1_000,
            last_observation_ms=None,
        )

    with raises(ValueError, match="effective touched"):
        _manifest(
            candidate_id="research-r3-bad-touched",
            first_observation_ms=1_000,
            last_observation_ms=2_000,
            source_provenance_ids=("source-a",),
            local_touched_intervals=(TimeInterval(1_000, 2_000),),
            effective_touched_intervals=(),
        )


def test_validation_cutover_requires_strict_freeze_and_six_hour_embargo() -> None:
    touched = (TimeInterval(1_000, 2_000), TimeInterval(3_000, 4_000))
    embargo_cutoff = 4_000 + SIX_HOURS_MS
    early_freeze_ms = 5_000

    assert validation_cutover_allowed(
        validation_start_ms=embargo_cutoff - 1,
        freeze_ms=early_freeze_ms,
        effective_touched_intervals=touched,
    ) is False
    assert validation_cutover_allowed(
        validation_start_ms=embargo_cutoff,
        freeze_ms=early_freeze_ms,
        effective_touched_intervals=touched,
    ) is True

    late_freeze_ms = embargo_cutoff + 10_000
    assert validation_cutover_allowed(
        validation_start_ms=late_freeze_ms,
        freeze_ms=late_freeze_ms,
        effective_touched_intervals=touched,
    ) is False
    assert validation_cutover_allowed(
        validation_start_ms=late_freeze_ms + 1,
        freeze_ms=late_freeze_ms,
        effective_touched_intervals=touched,
    ) is True
