from __future__ import annotations

import json
import runpy
from pathlib import Path

V4 = Path(".github/workflows/evidence-campaign-v4-scheduled.yml")
REGISTER = Path(".github/workflows/research-candidate-register.yml")
CAMPAIGN = Path(".github/workflows/research-campaign-scheduled.yml")
SYNC = Path(".github/workflows/research-v4-registry-sync.yml")
DASHBOARD = Path(".github/workflows/research-dashboard.yml")
SCHEDULER = Path("scripts/apply_v4_scheduler_health.py")
R2_SPEC = Path("docs/research-r2-short-trend-quality-v1.json")
DECISIONS = Path("docs/DECISIONS.md")
STATUS = Path("docs/STATUS.md")
OLD_PLAN = Path("docs/superpowers/plans/2026-09-14-research-natural-rollout-validation.md")
NEW_PLAN = Path("docs/superpowers/plans/2026-09-20-r2-short-trend-quality-validation.md")

R2 = "research-r2-short-trend-quality-v1"
R2_REVISION = "2ce088d69df01f044b0650b811b51015a5edda51"


def test_failed_touched_v4_has_no_future_automatic_acquisition_schedule() -> None:
    workflow = V4.read_text(encoding="utf-8")
    assert "\n  schedule:\n" not in workflow
    assert '37 1,7,13,19 * * *' not in workflow
    assert "workflow_dispatch:" in workflow
    assert 'if [ "$GITHUB_EVENT_NAME" != "schedule" ]; then' in workflow


def test_r2_candidate_spec_is_immutable_and_keeps_root_execution_horizon() -> None:
    payload = json.loads(R2_SPEC.read_text(encoding="utf-8"))
    assert payload == {
        "candidate_id": R2,
        "parent_candidate_id": "scheduled-research-root",
        "code_revision": R2_REVISION,
        "execution_config": {
            "config_version": "research-paper-20m-expiry-v1",
            "max_position_age_ms": 1_200_000,
            "starting_cash": "10000",
        },
    }


def test_r2_registration_is_main_push_trusted_without_market_acquisition() -> None:
    register = REGISTER.read_text(encoding="utf-8")
    assert "push:" in register
    assert "branches: [main]" in register
    assert "docs/research-r2-short-trend-quality-v1.json" in register
    assert "--spec docs/research-r2-short-trend-quality-v1.json" in register
    assert "record-mainnet-evidence" not in register
    for path in (REGISTER, CAMPAIGN, SYNC, DASHBOARD):
        workflow = path.read_text(encoding="utf-8")
        assert 'research-candidate-register.yml' in workflow
        assert '.event == "push"' in workflow


def test_research_campaign_targets_r2_and_verifies_it_before_publication() -> None:
    workflow = CAMPAIGN.read_text(encoding="utf-8")
    assert f"RESEARCH_CHALLENGER_CANDIDATE_ID: {R2}" in workflow
    assert '{"scheduled-research-root", "research-r1-exit-15m-v1"}' not in workflow
    verifier_arg = '--challenger-candidate-id "$RESEARCH_CHALLENGER_CANDIDATE_ID"'
    assert workflow.count(verifier_arg) >= 2


def test_v4_scheduler_health_reports_retired_when_schedule_is_removed() -> None:
    namespace = runpy.run_path(str(SCHEDULER))
    assert namespace["_campaign_schedule_enabled"]() is False
    assert namespace["RETIRED_SUMMARY"] == (
        "retired — no future V4 acquisition schedule configured"
    )


def test_source_of_truth_records_touched_v4_retirement_and_r2_plan() -> None:
    decisions = DECISIONS.read_text(encoding="utf-8")
    status = STATUS.read_text(encoding="utf-8")
    old_plan = OLD_PLAN.read_text(encoding="utf-8")
    new_plan = NEW_PLAN.read_text(encoding="utf-8")
    assert "D-024" in decisions
    assert "TOUCHED" in status
    assert R2 in status
    assert "**Status:** completed" in old_plan
    assert "**Status:** active" in new_plan
    assert R2 in new_plan
    assert "LIVE TRADING: DISABLED" in status
