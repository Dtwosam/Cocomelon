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
    assert "env -u GITHUB_TOKEN cocomelon record-mainnet-evidence" in acquire
    assert "scripts/research_v4_active_acquisition.sh" in acquire
    assert "v4-became-active.txt" in acquire
    assert 'kill "$RECORDER_PID"' in acquire
    assert "--seconds 1800" in acquire


def test_capture_rechecks_v4_synchronously_before_starting_recorder() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    capture = _job(source, "capture-control", "candidate-decisions")
    acquire = capture.split("- name: Acquire one public mainnet research cohort", 1)[1].split(
        "- name: Prepare trusted frozen research source",
        1,
    )[0]
    before_recorder = acquire.split("env -u GITHUB_TOKEN cocomelon record-mainnet-evidence", 1)[0]

    assert 'PRE_CAPTURE_ACTIVE_ROWS="$(' in before_recorder
    assert "scripts/research_v4_active_acquisition.sh" in before_recorder
    assert "v4-active-before-recorder.txt" in before_recorder
    assert (
        "protected V4 acquisition is active immediately before research capture"
        in before_recorder
    )
    assert "exit 76" in before_recorder


def test_midcapture_guard_fails_closed_when_actions_metadata_is_unavailable() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    capture = _job(source, "capture-control", "candidate-decisions")
    acquire = capture.split("- name: Acquire one public mainnet research cohort", 1)[1].split(
        "- name: Prepare trusted frozen research source",
        1,
    )[0]

    assert 'if ! ACTIVE_ROWS="$(' in acquire
    assert "v4-watch-failed.txt" in acquire
    assert "Actions metadata watch failed during research capture" in acquire
    assert 'kill "$RECORDER_PID"' in acquire


def test_midcapture_guard_does_not_modify_frozen_v4_workflow() -> None:
    v4 = V4_WORKFLOW.read_text(encoding="utf-8")

    assert 'cron: "37 1,7,13,19 * * *"' in v4
    assert "COHORT_CODE_REVISION: 0c14c9cfa37c80babc65d050fed6d4465dcb9032" in v4
    assert "CAPTURE_WINDOW_SECONDS: 18900" in v4
    assert "MAX_POSITION_AGE_SECONDS: 14400" in v4
    assert "research-campaign" not in v4
