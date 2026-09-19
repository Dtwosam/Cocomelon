from __future__ import annotations

from pathlib import Path


V4_WORKFLOW = Path(".github/workflows/evidence-campaign-v4-scheduled.yml")


def test_failed_touched_v4_candidate_has_no_future_economic_cron() -> None:
    source = V4_WORKFLOW.read_text(encoding="utf-8")

    assert "\n  schedule:" not in source
    assert "cron:" not in source
    assert "workflow_dispatch:" in source
