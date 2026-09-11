from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/research-campaign-scheduled.yml")


def _source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _job(source: str, name: str, next_name: str | None) -> str:
    block = source.split(f"\n  {name}:\n", 1)[1]
    if next_name is not None:
        block = block.split(f"\n  {next_name}:\n", 1)[0]
    return block


def test_research_fanout_reuses_exactly_one_authenticated_capture() -> None:
    source = _source()
    capture = _job(source, "capture-control", "candidate-decisions")

    assert source.count("record-mainnet-evidence") == 1
    assert "RESEARCH_CHALLENGER_CANDIDATE_ID" in source
    assert "candidate_matrix: ${{ steps.candidates.outputs.matrix }}" in source
    assert "resolve_research_fanout" in source
    assert "prepare_research_capture_source" in capture
    assert "prepare_research_cohort_source" not in capture
    assert "capture-source.json" in capture
    assert source.count("acquisition-attempt.txt") == 1


def test_candidate_build_and_decisions_are_fanned_out_but_isolated() -> None:
    source = _source()
    candidate = _job(source, "candidate-build", "capture-control")
    decisions = _job(source, "candidate-decisions", "refresh-authority")
    matrix = "matrix: ${{ fromJSON(needs.prepare-control.outputs.candidate_matrix) }}"
    candidate_stage = (
        "research-candidate-stage-${{ matrix.artifact_key }}-"
        "${{ github.run_id }}-${{ github.run_attempt }}"
    )
    decision_stage = (
        "research-decision-stage-${{ matrix.artifact_key }}-"
        "${{ github.run_id }}-${{ github.run_attempt }}"
    )

    for block in (candidate, decisions):
        assert matrix in block
        assert "continue-on-error: ${{ !matrix.required }}" in block
        assert "candidate_id" in block
        assert "research.sqlite3" not in block
        assert "GH_TOKEN:" not in block

    assert candidate_stage in candidate
    assert "ref: ${{ matrix.code_revision }}" in candidate
    assert decision_stage in decisions
    assert "materialize_research_candidate_source" in decisions
    assert "--network none" in decisions
    assert "docker load" in decisions


def test_candidate_evaluation_serializes_registry_updates_and_contains_optional_failure() -> None:
    source = _source()
    evaluation = _job(source, "evaluate-research", "finalize-publish")
    header = evaluation.split("steps:", 1)[0]

    assert "matrix:" not in header
    assert "research-authoritative-registry-publisher" in evaluation
    assert "Download all candidate decision stages" in evaluation
    assert "research-decision-stage-*-${{ github.run_id }}-${{ github.run_attempt }}" in evaluation
    assert "for candidate in fanout" in evaluation
    assert "candidate.required" in evaluation
    assert "candidate.attempt_id" in evaluation
    assert "candidate.candidate_id" in evaluation
    assert "candidate.batch_id" in evaluation
    assert "candidate.source_id" in evaluation
    assert "assert_batch_disjoint_from_v4" in evaluation
    assert "record_touched_interval" in evaluation
    assert "finish_runner_attempt" in evaluation
    assert "ResearchRunnerAttemptStatus.FAILED" in evaluation
    assert "str(output_root)" in evaluation
    assert "research-authoritative-registry" in evaluation


def test_shared_capture_interval_is_bound_to_every_fanout_attempt() -> None:
    source = _source()
    capture = _job(source, "capture-control", "candidate-decisions")
    refresh = _job(source, "refresh-authority", "evaluate-research")

    assert "bind_runner_attempt_source_interval" in capture
    assert "capture-source.json" in capture
    assert "for candidate in fanout" in capture
    assert "capture-source.json" in refresh
    assert "assert_batch_disjoint_from_v4" in refresh
    assert "record_touched_interval" not in refresh


def test_finalizer_verifies_two_candidate_rollout_contract() -> None:
    source = _source()
    finalizer = _job(source, "finalize-publish", "dispatch-dashboard")

    assert "Verify root+challenger rollout contract" in finalizer
    assert "research-fanout.json" in finalizer
    assert "rollout_verifier" in finalizer
    assert "PYTHONPATH" in finalizer
