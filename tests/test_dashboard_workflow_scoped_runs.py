from __future__ import annotations

import runpy
from pathlib import Path
from typing import Any

BUILDER = Path("scripts/build_evidence_dashboard.py")
SCHEDULER = Path("scripts/apply_v3_scheduler_health.py")


def _namespace(path: Path) -> dict[str, Any]:
    return runpy.run_path(str(path))


def test_dashboard_queries_v3_campaign_runs_from_exact_workflow() -> None:
    namespace = _namespace(BUILDER)
    workflow_runs = namespace.get("_workflow_runs")
    assert callable(workflow_runs)

    calls: list[str] = []

    def fake_gh_json(repo: str, endpoint: str) -> dict[str, object]:
        assert repo == "Dtwosam/Cocomelon"
        calls.append(endpoint)
        return {"workflow_runs": [{"id": 123}]}

    workflow_runs.__globals__["_gh_json"] = fake_gh_json
    assert workflow_runs(
        "Dtwosam/Cocomelon",
        ".github/workflows/evidence-campaign-scheduled.yml",
    ) == [{"id": 123}]
    assert calls == [
        "actions/workflows/evidence-campaign-scheduled.yml/runs?per_page=100"
    ]


def test_scheduler_health_queries_only_v3_campaign_schedule_runs() -> None:
    namespace = _namespace(SCHEDULER)
    latest_scheduled = namespace["_latest_scheduled_run"]
    calls: list[str] = []

    def fake_gh_value(repo: str, endpoint: str) -> object:
        assert repo == "Dtwosam/Cocomelon"
        calls.append(endpoint)
        return {"workflow_runs": []}

    latest_scheduled.__globals__["_gh_value"] = fake_gh_value
    assert latest_scheduled("Dtwosam/Cocomelon") is None
    assert calls == [
        "actions/workflows/evidence-campaign-scheduled.yml/runs?event=schedule&per_page=100"
    ]
