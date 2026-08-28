from __future__ import annotations

import runpy
from pathlib import Path
from typing import Any

WORKFLOW = Path(".github/workflows/evidence-dashboard.yml")
BUILDER = Path("scripts/build_evidence_dashboard.py")
VERDICT_APPLIER = Path("scripts/apply_phase9_v4_final_verdict.py")
INTAKE_APPLIER = Path("scripts/apply_v4_intake_diagnostics.py")


def _read_required(path: Path, label: str) -> str:
    assert path.is_file(), f"{label} must exist"
    return path.read_text(encoding="utf-8")


def _verdict_function(name: str) -> Any:
    namespace = runpy.run_path(str(VERDICT_APPLIER))
    return namespace[name]


def _intake_function(name: str) -> Any:
    namespace = runpy.run_path(str(INTAKE_APPLIER))
    return namespace[name]


def test_dashboard_refresh_tracks_v2_v3_v4_and_v4_one_shot() -> None:
    workflow = _read_required(WORKFLOW, "evidence dashboard workflow")

    assert "Verified V2 Mainnet Evidence Corpus Curator" in workflow
    assert "Verified V3 Mainnet Evidence Corpus Curator" in workflow
    assert "Verified V4 Mainnet Evidence Corpus Curator" in workflow
    assert "Phase 9 V4 One-Shot Evaluation" in workflow
    assert "workflow_run:" in workflow
    assert "workflow_dispatch:" in workflow
    assert "issues: write" in workflow
    assert 'DASHBOARD_ISSUE: "82"' in workflow
    assert "github.event.workflow_run.id" in workflow
    assert "EVENT_WORKFLOW_RUN_ID" in workflow
    assert "apply_phase9_v4_final_verdict.py" in workflow
    assert "apply_v4_intake_diagnostics.py" in workflow


def test_dashboard_builder_prefers_v4_but_preserves_v3_v2_history() -> None:
    workflow = _read_required(WORKFLOW, "evidence dashboard workflow")
    builder = _read_required(BUILDER, "evidence dashboard builder")

    assert "scripts/build_evidence_dashboard.py" in workflow
    assert "v4-mainnet-corpus" in builder
    assert "v3-mainnet-corpus" in builder
    assert "v2-mainnet-corpus" in builder
    assert "progress.json" in builder
    assert "corpus-index.json" in builder
    assert "Scheduled Genuine Mainnet Evidence Campaign V4" in builder
    assert "Verified V4 Mainnet Evidence Corpus Curator" in builder
    assert "Verified V3 Mainnet Evidence Corpus Curator" in builder
    assert "Verified V2 Mainnet Evidence Corpus Curator" in builder
    assert "gh api --method PATCH" in workflow


def test_dashboard_does_not_count_v3_v2_history_as_v4_progress() -> None:
    builder = _read_required(BUILDER, "evidence dashboard builder")

    assert "Active evidence protocol" in builder
    assert "V4 thesis-expiry" in builder
    assert "Historical V3 accepted cohorts" in builder
    assert "Historical V2 accepted cohorts" in builder
    assert "V4 accepted corpus not established yet" in builder
    assert "active_progress" in builder
    assert "historical_v3_progress" in builder
    assert "historical_v2_progress" in builder


def test_dashboard_accepts_only_exact_trusted_curator_paths() -> None:
    builder = _read_required(BUILDER, "evidence dashboard builder")

    assert '.github/workflows/evidence-corpus-curator-v4.yml' in builder
    assert '.github/workflows/evidence-corpus-curator-v3.yml' in builder
    assert '.github/workflows/evidence-corpus-curator.yml' in builder
    assert "curator run provenance is invalid" in builder


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
    assert "durable_freeze_exists" in builder
    assert "durable_final_exists" in builder
    assert "freeze_id" in builder
    assert "final_id" in builder
    assert "final state freeze id mismatch" in builder


def test_dashboard_preserves_historical_v3_one_shot_state_reader() -> None:
    builder = _read_required(BUILDER, "evidence dashboard builder")

    assert 'PHASE9_V3_STATE_BRANCH = "phase9-v3-protocol-state"' in builder
    assert 'PHASE9_V3_FREEZE_FILE = "phase9-v3-freeze.json"' in builder
    assert 'PHASE9_V3_FINAL_FILE = "phase9-v3-final.json"' in builder
    assert "_phase9_v3_state" in builder


def test_dashboard_shows_non_performance_leaking_v4_one_shot_status() -> None:
    builder = _read_required(BUILDER, "evidence dashboard builder")

    assert "V4 one-shot integrity state" in builder
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

    state_section_start = builder.index("def _phase9_v4_state_summary")
    state_section_end = builder.index("def _body", state_section_start)
    state_section = builder[state_section_start:state_section_end]
    assert "mean_net_r" not in state_section
    assert "bootstrap" not in state_section
    assert "pnl" not in state_section.lower()


def test_dashboard_keeps_edge_unmeasured_until_durable_final_exists() -> None:
    verdict = _verdict_function("_phase9_v4_final_verdict")

    assert verdict({"freeze": None, "final": None}) == "Not measured yet"
    assert verdict({"freeze": {"freeze_id": "abc"}, "final": None}) == (
        "Not measured yet"
    )


def test_dashboard_reports_terminal_insufficient_only_from_durable_final() -> None:
    verdict = _verdict_function("_phase9_v4_final_verdict")
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
    verdict = _verdict_function("_phase9_v4_final_verdict")
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


def test_dashboard_rejects_invalid_final_verdict_identity() -> None:
    verdict = _verdict_function("_phase9_v4_final_verdict")
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


def test_dashboard_formats_failed_v4_intake_without_performance_metrics() -> None:
    summary = _intake_function("_intake_summary")
    report = {
        "schema_version": 1,
        "protocol": "v4-thesis-expiry-mainnet",
        "source_run_id": 123,
        "source_conclusion": "failure",
        "source_verified": False,
        "corpus_mutated": False,
        "reason": "source_workflow_not_successful",
        "diagnostic_status": "eligibility_probe",
        "economic_ineligibility_reasons": ["open_exposure"],
        "replay_data_complete": True,
        "dataset_data_complete": True,
        "dataset_gap_refs_empty": True,
        "flat_replay": False,
        "economic_claim": "none",
        "network_access": False,
        "live_orders": False,
    }

    assert summary(report) == "rejected — open_exposure"


def test_dashboard_formats_successful_v4_intake_as_accepted() -> None:
    summary = _intake_function("_intake_summary")
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


def test_dashboard_handles_pre_diagnostic_failed_v4_intake() -> None:
    summary = _intake_function("_intake_summary")
    report = {
        "schema_version": 1,
        "protocol": "v4-thesis-expiry-mainnet",
        "source_run_id": 789,
        "source_conclusion": "failure",
        "source_verified": False,
        "corpus_mutated": False,
        "reason": "source_workflow_not_successful",
        "economic_claim": "none",
        "live_orders": False,
    }

    assert summary(report) == "rejected — diagnostic detail unavailable"


def test_dashboard_intake_applier_does_not_render_economic_metrics() -> None:
    script = _read_required(INTAKE_APPLIER, "V4 intake dashboard applier").lower()
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
