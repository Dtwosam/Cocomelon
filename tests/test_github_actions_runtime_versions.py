from __future__ import annotations

from pathlib import Path

WORKFLOWS = Path(".github/workflows")


def test_workflows_do_not_use_deprecated_node20_action_majors() -> None:
    offenders: list[str] = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        source = path.read_text(encoding="utf-8")
        for deprecated in ("actions/checkout@v4", "actions/setup-python@v5"):
            if deprecated in source:
                offenders.append(f"{path}:{deprecated}")
    assert offenders == []
