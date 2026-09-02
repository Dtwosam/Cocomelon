from __future__ import annotations

from pathlib import Path

CAMPAIGN = Path(".github/workflows/research-campaign-scheduled.yml")
DISPATCHER = Path(".github/workflows/research-daily-gap-dispatcher.yml")


def test_gap_dispatcher_uses_actual_run_state_and_caps_daily_success() -> None:
    assert DISPATCHER.exists(), "daily research gap dispatcher workflow is missing"
    source = DISPATCHER.read_text(encoding="utf-8")
    lowered = source.lower()

    assert "name: Research Daily Gap Dispatcher" in source
    assert "workflow_run:" in source
    assert "Scheduled Genuine Mainnet Evidence Campaign V4" in source
    assert "types: [completed]" in source
    assert "workflow_dispatch:" in source
    assert "actions: write" in source
    assert "contents: read" in source

    assert "evidence-campaign-v4-scheduled.yml/runs?per_page=100" in source
    assert '.head_branch == "main"' in source
    assert '.event == "schedule" or .event == "workflow_dispatch"' in source
    assert '.status != "completed"' in source

    assert "research-campaign-scheduled.yml" in source
    assert 'date -u +%Y-%m-%dT00:00:00Z' in source
    assert '.conclusion == "success"' in source
    assert "ACTIVE_RESEARCH_ROWS" in source
    assert "SUCCESS_TODAY_ROWS" in source
    assert "--method POST" in source
    assert "actions/workflows/research-campaign-scheduled.yml/dispatches" in source
    assert "-f ref=main" in source

    for forbidden in (
        "net_pnl",
        "mean_net_r",
        "posterior_probability",
        "profit_factor",
        "final_equity",
        "candidate_edge",
        "v4-mainnet-corpus",
        "phase9_v4_one_shot",
    ):
        assert forbidden not in lowered


def test_campaign_refuses_second_successful_cohort_in_same_utc_day_before_attempt() -> None:
    source = CAMPAIGN.read_text(encoding="utf-8")
    prepare = source.split("\n  prepare-control:\n", 1)[1].split("\n  candidate-build:\n", 1)[0]
    marker = "Refuse duplicate successful research cohort for current UTC day"

    assert marker in prepare
    guard = prepare.split(f"- name: {marker}", 1)[1].split(
        "- name: Persist acquisition attempt before candidate setup",
        1,
    )[0]
    assert "GH_TOKEN: ${{ github.token }}" in guard
    assert 'date -u +%Y-%m-%dT00:00:00Z' in guard
    assert "research-campaign-scheduled.yml" in guard
    assert '.head_branch == "main"' in guard
    assert '.conclusion == "success"' in guard
    assert '.event == "schedule" or .event == "workflow_dispatch"' in guard
    assert "GITHUB_RUN_ID" in guard
    assert source.index(marker) < source.index("Persist acquisition attempt before candidate setup")
    assert source.index(marker) < source.index("Checkout candidate code revision")
    assert source.index(marker) < source.index("record-mainnet-evidence")

    for forbidden in (
        "net_pnl",
        "mean_net_r",
        "posterior_probability",
        "profit_factor",
        "final_equity",
    ):
        assert forbidden not in guard.lower()
