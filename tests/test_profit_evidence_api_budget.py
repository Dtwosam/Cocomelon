"""Keep economically relevant research evidence available under GitHub API quotas.

These are fallback polls, not the source event triggers; a minute-based cron
is an avoidable contributor to a shared installation's API quota exhaustion.
"""
from __future__ import annotations

import re
from pathlib import Path


def _workflow(name: str) -> str:
    return Path(".github/workflows", name).read_text(encoding="utf-8")


def test_research_fallback_polling_budget_is_three_runs_per_hour() -> None:
    # Before this change there were 12 + 4 + 4 = 20 fallback runs/hour.
    # These workflows can make many additional gh API calls in each run.
    # The branch changes only their redundant cron wakeups.
    schedules = {
        "research-dashboard-catchup.yml": "13 * * * *",
        "continuous-paper-decision-learning-catchup.yml": "17 * * * *",
        "prospective-cadence-actual-trade-overlap.yml": "41 * * * *",
    }
    assert len(set(schedules.values())) == 3
    for workflow, cron in schedules.items():
        source = _workflow(workflow)
        assert re.findall(r'^\s+- cron: "([^"]+)"$', source, re.MULTILINE) == [
            cron
        ]
        assert "workflow_dispatch:" in source


def test_normal_profit_evidence_arrival_events_remain_enabled() -> None:
    decision = _workflow("continuous-paper-decision-learning-catchup.yml")
    overlap = _workflow("prospective-cadence-actual-trade-overlap.yml")
    assert "workflow_run:" in decision
    assert '"Continuous Mainnet Paper Trader"' in decision
    assert '"Continuous Paper Decision Learning Evidence"' in decision
    assert "workflow_run:" in overlap
    assert '"Continuous Mainnet Paper Trader"' in overlap
    assert '"Prospective Cadence Prediction Ledger"' in overlap
    assert "cancel-in-progress: false" in decision
    assert "cancel-in-progress: false" in overlap


def test_no_new_trading_authority_or_shortcuts_in_fallbacks() -> None:
    for filename in (
        "research-dashboard-catchup.yml",
        "continuous-paper-decision-learning-catchup.yml",
        "prospective-cadence-actual-trade-overlap.yml",
    ):
        source = _workflow(filename).lower()
        for forbidden in (
            "live_order",
            "send_order",
            "withdraw",
            "wallet_private",
            "ignore_source_gap",
            "skip_risk_evaluation",
        ):
            assert forbidden not in source
