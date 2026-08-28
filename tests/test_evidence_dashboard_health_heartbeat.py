from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/evidence-dashboard.yml")


def test_dashboard_refreshes_hourly_for_time_based_health_state() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "schedule:" in workflow
    assert 'cron: "17 * * * *"' in workflow
    scheduled_section = workflow.split("schedule:", 1)[1]
    assert "Scheduled Genuine Mainnet Evidence Campaign V3" not in scheduled_section
