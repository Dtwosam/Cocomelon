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


def test_remaining_recovery_pollers_are_hourly_and_collision_staggered() -> None:
    # Before this change, these 3 source/campaign recovery safety nets
    # started 4 + 6 + 6 = 16 jobs/hour. Already-throttled workflows add 3.
    # No ordinary event-following workflow_run input is removed here.
    schedules = {
        "continuous-paper-learning-catchup.yml": "7 * * * *",
        "research-dashboard-catchup.yml": "13 * * * *",
        "continuous-paper-decision-learning-catchup.yml": "17 * * * *",
        "research-learning-catchup.yml": "27 * * * *",
        "prospective-cadence-actual-trade-overlap.yml": "41 * * * *",
        "research-learning-clean-catchup.yml": "47 * * * *",
    }
    assert len(schedules) == len(set(schedules.values())) == 6
    for filename, expected in schedules.items():
        source = _workflow(filename)
        assert re.findall(
            r'^\s+- cron: "([^"]+)"$', source, re.MULTILINE
        ) == [expected]
        assert "workflow_dispatch:" in source
    for filename, expected_producers in {
        "continuous-paper-learning-catchup.yml": (
            "Continuous Mainnet Paper Trader",
            "Continuous Paper Learning Evidence Sync",
        ),
        "research-learning-catchup.yml": (
            "Scheduled Research Mainnet Replay Campaign",
            "Research Learning Evidence Sync",
        ),
        "research-learning-clean-catchup.yml": (
            "Research Learning Clean State Bootstrap",
            "Research Learning Clean State Campaign Follower",
        ),
    }.items():
        source = _workflow(filename)
        assert "workflow_run:" in source
        assert "types: [completed]" in source
        assert "cancel-in-progress: false" in source
        for producer in expected_producers:
            assert producer in source


def test_no_source_admission_relaxation_in_remaining_api_fallbacks() -> None:
    for filename in (
        "continuous-paper-learning-catchup.yml",
        "research-learning-catchup.yml",
        "research-learning-clean-catchup.yml",
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
