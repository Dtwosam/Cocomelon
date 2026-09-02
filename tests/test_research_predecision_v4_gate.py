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


def test_known_active_v4_is_rejected_before_candidate_build_or_capture() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    prepare = _job(source, "prepare-control", "candidate-build")
    marker = "Refuse research capture while V4 acquisition is active"

    assert marker in prepare
    preflight = prepare.split(f"- name: {marker}", 1)[1].split(
        "- name: Upload prepared research control state",
        1,
    )[0]
    assert "GH_TOKEN: ${{ github.token }}" in preflight
    assert "evidence-campaign-v4-scheduled.yml/runs?per_page=100" in preflight
    assert '.head_branch == "main"' in preflight
    assert '.event == "schedule" or .event == "workflow_dispatch"' in preflight
    assert '.status != "completed"' in preflight
    assert "v4-active-run" in preflight

    for forbidden in (
        "net_pnl",
        "mean_net_r",
        "posterior_probability",
        "profit_factor",
        "final_equity",
        "phase9_v4_one_shot",
    ):
        assert forbidden not in preflight.lower()

    assert prepare.index("Persist acquisition attempt before candidate setup") < prepare.index(
        marker
    )
    assert prepare.index(marker) < prepare.index("Upload prepared research control state")
    assert source.index(marker) < source.index("Checkout candidate code revision")
    assert source.index(marker) < source.index("record-mainnet-evidence")
