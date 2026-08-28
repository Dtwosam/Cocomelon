from __future__ import annotations

import runpy
from pathlib import Path
from typing import Any

WORKFLOW = Path(".github/workflows/evidence-dashboard.yml")
BUILDER = Path("scripts/build_evidence_dashboard.py")
VERDICT_APPLIER = Path("scripts/apply_phase9_v3_final_verdict.py")


def _read_required(path: Path, label: str) -> str:
    assert path.is_file(), f"{label} must exist"
    return path.read_text(encoding="utf-8")


def _verdict_function(name: str) -> Any:
    namespace = runpy.run_path(str(VERDICT_APPLIER))
    return namespace[name]


def test_dashboard_refresh_tracks_v2_v3_curators_and_v3_one_shot() -> None:
    workflow = _read_required(WORKFLOW, "evidence dashboard workflow")

    assert "Verified V2 Mainnet Evidence Corpus Curator" in workflow
    assert "Verified V3 Mainnet Evidence Corpus Curator" in workflow
    assert "Phase 9 V3 One-Shot Evaluation" in workflow
    assert "workflow_run:" in workflow
    assert "workflow_dispatch:" in workflow
    assert "issues: write" in workflow
    assert 'DASHBOARD_ISSUE: "82"' in workflow
    assert "github.event.workflow_run.id" in workflow
    assert "EVENT_WORKFLOW_RUN_ID" in workflow
    assert "apply_phase9_v3_final_verdict.py" in workflow


def test_dashboard_builder_prefers_v3_but_preserves_v2_history() -> None:
    workflow = _read_required(WORKFLOW, "evidence dashboard workflow")
    builder = _read_required(BUILDER, "evidence dashboard builder")

    assert "scripts/build_evidence_dashboard.py" in workflow
    assert "v3-mainnet-corpus" in builder
    assert "v2-mainnet-corpus" in builder
    assert "progress.json" in builder
    assert "corpus-index.json" in builder
    assert "Scheduled Genuine Mainnet Evidence Campaign V3" in builder
    assert "Verified V3 Mainnet Evidence Corpus Curator" in builder
    assert "Verified V2 Mainnet Evidence Corpus Curator" in builder
    assert "gh api --method PATCH" in workflow


def test_dashboard_does_not_count_v2_history_as_v3_progress() -> None:
    builder = _read_required(BUILDER, "evidence dashboard builder")

    assert "Active evidence protocol" in builder
    assert "V3 lifecycle-aware" in builder
    assert "Historical V2 accepted cohorts" in builder
    assert "V3 accepted corpus not established yet" in builder
    assert "active_progress" in builder
    assert "historical_v2_progress" in builder


def test_dashboard_accepts_only_exact_trusted_curator_paths() -> None:
    builder = _read_required(BUILDER, "evidence dashboard builder")

    assert '.github/workflows/evidence-corpus-curator-v3.yml' in builder
    assert '.github/workflows/evidence-corpus-curator.yml' in builder
    assert "curator run provenance is invalid" in builder


def test_dashboard_accepts_exact_v3_one_shot_trigger_provenance() -> None:
    builder = _read_required(BUILDER, "evidence dashboard builder")

    assert '"Phase 9 V3 One-Shot Evaluation"' in builder
    assert '".github/workflows/phase9-v3-one-shot.yml"' in builder
    assert "event workflow run provenance is invalid" in builder


def test_dashboard_reads_immutable_v3_one_shot_state_branch() -> None:
    builder = _read_required(BUILDER, "evidence dashboard builder")

    assert 'PHASE9_V3_STATE_BRANCH = "phase9-v3-protocol-state"' in builder
    assert 'PHASE9_V3_FREEZE_FILE = "phase9-v3-freeze.json"' in builder
    assert 'PHASE9_V3_FINAL_FILE = "phase9-v3-final.json"' in builder
    assert "durable_freeze_exists" in builder
    assert "durable_final_exists" in builder
    assert "freeze_id" in builder
    assert "final_id" in builder
    assert "V3 final state freeze id mismatch" in builder


def test_dashboard_shows_non_performance_leaking_one_shot_status() -> None:
    builder = _read_required(BUILDER, "evidence dashboard builder")

    assert "V3 one-shot state" in builder
    assert "waiting for finalizable snapshot" in builder
    assert "frozen; finalization pending" in builder
    assert "terminal insufficient evidence" in builder
    assert "evaluated" in builder
    assert "Frozen evaluator revision" in builder
    assert "Freeze ID" in builder
    assert "source curator run" in builder.lower()
    assert "corpus artifact ID" in builder


def test_dashboard_state_summary_does_not_render_pre_final_performance_fields() -> None:
    builder = _read_required(BUILDER, "evidence dashboard builder")

    state_section_start = builder.index("def _phase9_v3_state_summary")
    state_section_end = builder.index("def _body", state_section_start)
    state_section = builder[state_section_start:state_section_end]
    assert "mean_net_r" not in state_section
    assert "bootstrap" not in state_section
    assert "pnl" not in state_section.lower()
    assert "evaluation" not in state_section.lower()


def test_dashboard_keeps_edge_unmeasured_until_durable_final_exists() -> None:
    verdict = _verdict_function("_phase9_v3_final_verdict")

    assert verdict({"freeze": None, "final": None}) == "Not measured yet"
    assert verdict({"freeze": {"freeze_id": "abc"}, "final": None}) == "Not measured yet"


def test_dashboard_reports_terminal_insufficient_only_from_durable_final() -> None:
    verdict = _verdict_function("_phase9_v3_final_verdict")
    state = {
        "freeze": {"freeze_id": "abc", "snapshot_id": "snap"},
        "final": {
            "protocol_state": "insufficient_evidence",
            "final_type": "terminal_insufficient",
            "economic_claim": "phase9_readiness_only",
            "freeze_id": "abc",
            "terminal": {
                "edge_status": "insufficient_evidence",
                "economic_claim": "phase9_readiness_only",
                "one_shot_oos": True,
                "snapshot_id": "snap",
                "network_access": False,
                "live_orders": False,
            },
            "evaluation": None,
        },
    }

    assert verdict(state) == "INSUFFICIENT_EVIDENCE (readiness-only terminal)"


def test_dashboard_reports_evaluated_edge_status_only_from_durable_final() -> None:
    verdict = _verdict_function("_phase9_v3_final_verdict")
    state = {
        "freeze": {"freeze_id": "abc", "snapshot_id": "snap"},
        "final": {
            "protocol_state": "evaluated",
            "final_type": "evaluation",
            "economic_claim": "phase9_baseline_edge_assessment",
            "freeze_id": "abc",
            "terminal": None,
            "evaluation": {
                "evaluation_name": "v3-phase9-evaluation",
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


def test_dashboard_rejects_invalid_final_verdict_identity() -> None:
    verdict = _verdict_function("_phase9_v3_final_verdict")
    state = {
        "freeze": {"freeze_id": "abc", "snapshot_id": "snap"},
        "final": {
            "protocol_state": "evaluated",
            "final_type": "evaluation",
            "economic_claim": "phase9_baseline_edge_assessment",
            "freeze_id": "abc",
            "terminal": None,
            "evaluation": {
                "evaluation_name": "unexpected-evaluation",
                "edge_status": "candidate_edge",
                "economic_claim": "phase9_baseline_edge_assessment",
                "one_shot_oos": True,
                "snapshot_id": "snap",
                "network_access": False,
                "live_orders": False,
            },
        },
    }

    try:
        verdict(state)
    except RuntimeError as exc:
        assert "evaluation identity" in str(exc)
    else:
        raise AssertionError("invalid evaluated verdict must fail closed")
