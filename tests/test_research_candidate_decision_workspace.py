from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/research-campaign-scheduled.yml")


def test_candidate_decisions_creates_diagnostics_before_policy_write() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    step = source.split(
        "- name: Run candidate strategy against trusted contexts",
        1,
    )[1].split("- name: Upload candidate decision stage", 1)[0]

    mkdir = 'mkdir -p "$GITHUB_WORKSPACE/research-campaign/diagnostics"'
    policy = (
        '> "$GITHUB_WORKSPACE/research-campaign/diagnostics/'
        'candidate-sandbox-policy.txt"'
    )

    assert mkdir in step
    assert policy in step
    assert step.index(mkdir) < step.index(policy)
