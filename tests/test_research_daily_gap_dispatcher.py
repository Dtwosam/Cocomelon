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

    assert "scripts/research_v4_active_acquisition.sh" in source
    assert 'cron: "*/5 * * * *"' in source

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


def test_campaign_cleanly_skips_second_successful_cohort_before_attempt() -> None:
    source = CAMPAIGN.read_text(encoding="utf-8")
    prepare = source.split("\n  prepare-control:\n", 1)[1].split("\n  candidate-build:\n", 1)[0]
    candidate = source.split("\n  candidate-build:\n", 1)[1].split(
        "\n  capture-control:\n",
        1,
    )[0]
    marker = "Refuse duplicate successful research cohort for current UTC day"

    assert marker in prepare
    assert "run_research: ${{ steps.daily_guard.outputs.run_research }}" in prepare
    guard = prepare.split(f"- name: {marker}", 1)[1].split(
        "- name: Persist acquisition attempt before candidate setup",
        1,
    )[0]
    assert "id: daily_guard" in guard
    assert "GH_TOKEN: ${{ github.token }}" in guard
    assert 'date -u +%Y-%m-%dT00:00:00Z' in guard
    assert "research-campaign-scheduled.yml" in guard
    assert '.head_branch == "main"' in guard
    assert '.conclusion == "success"' in guard
    assert '.event == "schedule" or .event == "workflow_dispatch"' in guard
    assert "GITHUB_RUN_ID" in guard
    assert "run_research=false" in guard
    assert "run_research=true" in guard
    assert "exit 77" not in guard

    persist = prepare.split(
        "- name: Persist acquisition attempt before candidate setup",
        1,
    )[1].split("- name: Refuse research capture while V4 acquisition is active", 1)[0]
    v4_guard = prepare.split(
        "- name: Refuse research capture while V4 acquisition is active",
        1,
    )[1].split("- name: Upload prepared research control state", 1)[0]
    gate = "if: ${{ steps.daily_guard.outputs.run_research == 'true' }}"
    assert gate in persist
    assert gate in v4_guard
    assert "if: ${{ needs.prepare-control.outputs.run_research == 'true' }}" in candidate

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
