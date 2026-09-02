from pathlib import Path

WORKFLOW = Path(".github/workflows/research-campaign-scheduled.yml")


def _job(source: str, name: str, next_name: str | None) -> str:
    block = source.split(f"\n  {name}:\n", 1)[1]
    if next_name is not None:
        block = block.split(f"\n  {next_name}:\n", 1)[0]
    return block


def test_v4_authority_is_verified_before_candidate_observes_capture() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    capture = _job(source, "capture-control", "candidate-decisions")
    decisions = _job(source, "candidate-decisions", "refresh-authority")
    refresh = _job(source, "refresh-authority", "evaluate-research")
    evaluation = _job(source, "evaluate-research", "finalize-publish")

    assert "record_touched_interval" not in capture
    assert "refresh-authority" in decisions.split("steps:", 1)[0]
    assert "candidate-decisions" not in refresh.split("steps:", 1)[0]
    assert "Download candidate research stage" not in refresh
    assert "assert_batch_disjoint_from_v4" in refresh
    assert "record_touched_interval" in refresh
    assert refresh.index("assert_batch_disjoint_from_v4") < refresh.index("record_touched_interval")
    assert "candidate-decisions" in evaluation.split("steps:", 1)[0]
    assert "Download candidate research stage" in evaluation

    assert "Authorize candidate observation and record research touch" in refresh
    assert "refresh-authority" in decisions.split("steps:", 1)[0]
