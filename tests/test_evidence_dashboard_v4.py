from __future__ import annotations

import runpy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

WORKFLOW = Path(".github/workflows/evidence-dashboard.yml")
BUILDER = Path("scripts/build_evidence_dashboard.py")
VERDICT_APPLIER = Path("scripts/apply_phase9_v4_final_verdict.py")
INTAKE_APPLIER = Path("scripts/apply_v4_intake_diagnostics.py")
SCHEDULER_APPLIER = Path("scripts/apply_v4_scheduler_health.py")


def _read_required(path: Path, label: str) -> str:
    assert path.is_file(), f"{label} must exist"
    return path.read_text(encoding="utf-8")


def _function(path: Path, name: str) -> Any:
    namespace = runpy.run_path(str(path))
    return namespace[name]


def test_dashboard_refresh_tracks_v4_curator_and_one_shot() -> None:
    workflow = _read_required(WORKFLOW, "evidence dashboard workflow")

    assert "Verified V4 Mainnet Evidence Corpus Curator" in workflow
    assert "Phase 9 V4 One-Shot Evaluation" in workflow
    assert "apply_phase9_v4_final_verdict.py" in workflow
    assert "apply_v4_intake_diagnostics.py" in workflow
    assert "apply_v4_scheduler_health.py" in workflow
    assert "issues: write" in workflow
    assert 'DASHBOARD_ISSUE: "82"' in workflow


def test_dashboard_builder_makes_v4_active_and_v3_v2_historical() -> None:
    builder = _read_required(BUILDER, "evidence dashboard builder")

    assert 'label="V4 thesis-expiry"' in builder
    assert "v4-mainnet-corpus" in builder
    assert "Scheduled Genuine Mainnet Evidence Campaign V4" in builder
    assert "Verified V4 Mainnet Evidence Corpus Curator" in builder
    assert "**Active evidence protocol: V4 thesis-expiry**" in builder
    assert "## Active V4 evidence progress" in builder
    assert "Historical V3 accepted cohorts" in builder
    assert "Historical V2 accepted cohorts" in builder
    assert "V4 accepted corpus not established yet" in builder


def test_dashboard_accepts_exact_v4_one_shot_trigger_provenance() -> None:
    builder = _read_required(BUILDER, "evidence dashboard builder")

    assert '"Phase 9 V4 One-Shot Evaluation"' in builder
    assert '".github/workflows/phase9-v4-one-shot.yml"' in builder
    assert "event workflow run provenance is invalid" in builder


def test_dashboard_reads_immutable_v4_one_shot_state_branch() -> None:
    builder = _read_required(BUILDER, "evidence dashboard builder")

    assert 'PHASE9_V4_STATE_BRANCH = "phase9-v4-protocol-state"' in builder
    assert 'PHASE9_V4_FREEZE_FILE = "phase9-v4-freeze.json"' in builder
    assert 'PHASE9_V4_FINAL_FILE = "phase9-v4-final.json"' in builder
    assert "_phase9_v4_state" in builder
    assert "final state freeze id mismatch" in builder


def test_v4_state_summary_does_not_render_interim_performance() -> None:
    builder = _read_required(BUILDER, "evidence dashboard builder")

    start = builder.index("def _phase9_v4_state_summary")
    end = builder.index("def _body", start)
    section = builder[start:end].lower()
    forbidden = (
        "mean_net_r",
        "bootstrap",
        "realized_pnl",
        "unrealized_pnl",
        "profit_factor",
        "win_rate",
    )
    assert all(field not in section for field in forbidden)


def test_v4_final_verdict_stays_unmeasured_until_durable_final() -> None:
    verdict = _function(VERDICT_APPLIER, "_phase9_v4_final_verdict")

    assert verdict({"freeze": None, "final": None}) == "Not measured yet"
    assert verdict({"freeze": {"freeze_id": "abc"}, "final": None}) == (
        "Not measured yet"
    )


def test_v4_final_verdict_accepts_only_v4_evaluation_identity() -> None:
    verdict = _function(VERDICT_APPLIER, "_phase9_v4_final_verdict")
    state = {
        "freeze": {"freeze_id": "abc", "snapshot_id": "snap"},
        "final": {
            "protocol_state": "evaluated",
            "final_type": "evaluation",
            "economic_claim": "phase9_baseline_edge_assessment",
            "freeze_id": "abc",
            "terminal": None,
            "evaluation": {
                "evaluation_name": "v4-phase9-evaluation",
                "edge_status": "candidate_edge",
                "economic_claim": "phase9_baseline_edge_assessment",
                "one_shot_oos": True,
                "snapshot_id": "snap",
                "network_access": False,
                "live_orders": False,
            },
        },
    }

    assert verdict(state) == "CANDIDATE_EDGE"


def test_v4_intake_summary_is_performance_blind() -> None:
    summary = _function(INTAKE_APPLIER, "_intake_summary")
    report = {
        "schema_version": 1,
        "protocol": "v4-thesis-expiry-mainnet",
        "source_run_id": 456,
        "source_conclusion": "success",
        "source_verified": True,
        "corpus_mutated": True,
        "economic_claim": "none",
        "live_orders": False,
    }

    assert summary(report) == "accepted into V4 corpus"
    script = _read_required(INTAKE_APPLIER, "V4 intake diagnostics").lower()
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


def test_v4_scheduler_health_uses_exact_v4_campaign() -> None:
    health = _function(SCHEDULER_APPLIER, "_scheduler_health")
    now = datetime(2026, 8, 28, 21, 0, tzinfo=UTC)
    workflow_updated = datetime(2026, 8, 28, 14, 0, tzinfo=UTC)
    latest_scheduled = {"created_at": "2026-08-28T19:52:00Z"}

    assert health(now, latest_scheduled, workflow_updated) == (
        "healthy — latest configured slot observed"
    )
    script = _read_required(SCHEDULER_APPLIER, "V4 scheduler health")
    assert "Scheduled Genuine Mainnet Evidence Campaign V4" in script
    assert ".github/workflows/evidence-campaign-v4-scheduled.yml" in script
