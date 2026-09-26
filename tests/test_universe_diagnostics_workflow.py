from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/universe-opportunity-diagnostics.yml")


def test_universe_diagnostics_workflow_is_non_economic_and_publishes_issue() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert 'cron: "17,47 * * * *"' in source
    assert 'COCOMELON_EXECUTION_MODE: paper' in source
    assert 'DIAGNOSTICS_ISSUE: "483"' in source
    assert "cocomelon-universe-diagnostics" in source
    assert 'gh issue edit "$DIAGNOSTICS_ISSUE"' in source
    assert "universe-opportunity-diagnostics.json" in source
    lowered = source.lower()
    assert "private_key" not in lowered
    assert "live_ack" not in lowered
    assert "exchange endpoint" not in lowered
