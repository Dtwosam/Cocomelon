from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/research-campaign-scheduled.yml")
V4_WORKFLOW = Path(".github/workflows/evidence-campaign-v4-scheduled.yml")


def _job(source: str, name: str, next_name: str) -> str:
    return source.split(f"\n  {name}:\n", 1)[1].split(f"\n  {next_name}:\n", 1)[0]


def test_research_capture_aborts_when_v4_becomes_active_after_preflight() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    capture = _job(source, "capture-control", "candidate-decisions")
    acquire = capture.split("- name: Acquire one public mainnet research cohort", 1)[1].split(
        "- name: Prepare trusted frozen research source",
        1,
    )[0]

    assert "actions: read" in capture.split("steps:", 1)[0]
    assert "GITHUB_TOKEN: ${{ github.token }}" in acquire
    assert "evidence-campaign-v4-scheduled.yml/runs?per_page=100" in acquire
    assert "v4-became-active.txt" in acquire
    assert 'kill "$RECORDER_PID"' in acquire
    assert "--seconds 1800" in acquire


def test_midcapture_guard_does_not_modify_frozen_v4_workflow() -> None:
    v4 = V4_WORKFLOW.read_text(encoding="utf-8")

    assert 'cron: "37 1,7,13,19 * * *"' in v4
    assert "COHORT_CODE_REVISION: 0c14c9cfa37c80babc65d050fed6d4465dcb9032" in v4
    assert "CAPTURE_WINDOW_SECONDS: 18900" in v4
    assert "MAX_POSITION_AGE_SECONDS: 14400" in v4
    assert "research-campaign" not in v4
