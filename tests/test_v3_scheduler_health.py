from __future__ import annotations

import runpy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

WORKFLOW = Path(".github/workflows/evidence-dashboard.yml")
APPLIER = Path("scripts/apply_v3_scheduler_health.py")


def _function(name: str) -> Any:
    namespace = runpy.run_path(str(APPLIER))
    return namespace[name]


def test_scheduler_health_marks_recent_activation_pending() -> None:
    health = _function("_scheduler_health")
    now = datetime(2026, 8, 28, 15, 30, tzinfo=UTC)
    workflow_updated = datetime(2026, 8, 28, 14, 0, tzinfo=UTC)
    latest_scheduled = {"created_at": "2026-08-28T01:05:56Z"}

    assert health(now, latest_scheduled, workflow_updated) == (
        "activation pending — next configured slot 19:37 UTC"
    )


def test_scheduler_health_marks_missed_slot_stale_after_grace() -> None:
    health = _function("_scheduler_health")
    now = datetime(2026, 8, 28, 22, 0, tzinfo=UTC)
    workflow_updated = datetime(2026, 8, 28, 14, 0, tzinfo=UTC)
    latest_scheduled = {"created_at": "2026-08-28T01:05:56Z"}

    assert health(now, latest_scheduled, workflow_updated) == (
        "stale — configured 19:37 UTC slot not observed"
    )


def test_scheduler_health_marks_observed_slot_healthy() -> None:
    health = _function("_scheduler_health")
    now = datetime(2026, 8, 28, 21, 0, tzinfo=UTC)
    workflow_updated = datetime(2026, 8, 28, 14, 0, tzinfo=UTC)
    latest_scheduled = {"created_at": "2026-08-28T19:52:00Z"}

    assert health(now, latest_scheduled, workflow_updated) == (
        "healthy — latest configured slot observed"
    )


def test_historical_v3_scheduler_remains_performance_blind_but_not_active() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    script = APPLIER.read_text(encoding="utf-8").lower()

    assert "apply_v3_scheduler_health.py" not in workflow
    assert "apply_v4_scheduler_health.py" in workflow
    assert "scheduler health" in script
    forbidden = (
        "final_equity",
        "realized_pnl",
        "unrealized_pnl",
        "profit_factor",
        "mean_net_r",
        "win_rate",
        "bootstrap",
    )
    assert all(field not in script for field in forbidden)
