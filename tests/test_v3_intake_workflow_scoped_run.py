from __future__ import annotations

import runpy
from pathlib import Path
from typing import Any

APPLIER = Path("scripts/apply_v3_intake_diagnostics.py")


def _namespace() -> dict[str, Any]:
    return runpy.run_path(str(APPLIER))


def test_latest_curator_run_queries_exact_v3_curator_workflow() -> None:
    namespace = _namespace()
    latest_curator = namespace["_latest_curator_run"]
    calls: list[str] = []

    def fake_gh_json(repo: str, endpoint: str) -> dict[str, object]:
        assert repo == "Dtwosam/Cocomelon"
        calls.append(endpoint)
        return {"workflow_runs": []}

    latest_curator.__globals__["_gh_json"] = fake_gh_json
    assert latest_curator("Dtwosam/Cocomelon") is None
    assert calls == [
        "actions/workflows/evidence-corpus-curator-v3.yml/runs?per_page=100"
    ]
