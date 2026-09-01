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


def test_candidate_package_is_frozen_before_trusted_capture() -> None:
    source = _source()
    candidate = _job(source, "candidate-build", "capture-control")
    capture = _job(source, "capture-control", "candidate-decisions")

    assert "docker build" in candidate
    assert "docker save" in candidate
    assert "record-mainnet-evidence" not in candidate
    assert "research.sqlite3" not in candidate
    assert "recording/" not in candidate
    assert "build_research_cohort" not in candidate

    assert "needs:" in capture
    assert "candidate-build" in capture
    assert "Checkout trusted research capture control revision" in capture
    assert "record-mainnet-evidence" in capture
    assert "prepare_research_cohort_source" in capture
    assert "candidate-src" not in capture


def test_candidate_strategy_only_sees_one_context_in_networkless_container() -> None:
    source = _source()
    decisions = _job(source, "candidate-decisions", "refresh-authority")

    assert "Checkout trusted strategy orchestration revision" in decisions
    assert "docker load" in decisions
    assert "build_candidate_strategy_decisions" in decisions
    assert "--network none" in decisions
    assert "--read-only" in decisions
    assert "--cap-drop ALL" in decisions
    assert "no-new-privileges" in decisions
    assert "research.sqlite3" not in decisions
    assert "cocomelon-research-runner" not in decisions


def test_trusted_evaluation_constructs_economic_artifact_without_candidate_runtime() -> None:
    source = _source()
    evaluation = _job(source, "evaluate-research", "finalize-publish")

    assert "Checkout trusted research runner control revision" in evaluation
    assert "complete_research_cohort" in evaluation
    assert "strategy-decisions.json" in evaluation
    assert "cocomelon-research-runner run-artifact" in evaluation
    assert "candidate-src" not in evaluation
    assert "docker run" not in evaluation


def test_candidate_runtime_never_receives_raw_recording_or_registry() -> None:
    source = _source()
    candidate = _job(source, "candidate-build", "capture-control")
    decisions = _job(source, "candidate-decisions", "refresh-authority")

    for block in (candidate, decisions):
        assert "research.sqlite3" not in block
    assert "record-mainnet-evidence" not in candidate
    assert "research-campaign/recording" not in candidate
    assert "--root research-campaign/recording" not in decisions
