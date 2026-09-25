from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/ci.yml")


def test_feature_branches_run_ci_once_via_pull_request() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "on:\n  push:\n    branches:\n      - main\n  pull_request:\n" in source
    assert "  push:\n  pull_request:\n" not in source
