from pathlib import Path

WORKFLOW = Path(".github/workflows/research-campaign-scheduled.yml")


def test_research_capture_runs_recorder_from_trusted_checkout() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    capture = source.split("\n  capture-control:\n", 1)[1].split(
        "\n  candidate-decisions:\n",
        1,
    )[0]
    acquire = capture.split("- name: Acquire one public mainnet research cohort", 1)[1].split(
        "- name: Prepare trusted frozen research source",
        1,
    )[0]

    assert "cd control-src" in acquire
    assert acquire.index("cd control-src") < acquire.index("cocomelon record-mainnet-evidence")
    assert '--root "$GITHUB_WORKSPACE/research-campaign/recording"' in acquire
    assert '> "$GITHUB_WORKSPACE/research-campaign/output/record-transport.json"' in acquire
