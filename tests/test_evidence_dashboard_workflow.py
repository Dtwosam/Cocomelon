from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/evidence-dashboard.yml")
BUILDER = Path("scripts/build_evidence_dashboard.py")


def _read_required(path: Path, label: str) -> str:
    assert path.is_file(), f"{label} must exist"
    return path.read_text(encoding="utf-8")


def test_dashboard_refresh_tracks_v2_and_v3_curators() -> None:
    workflow = _read_required(WORKFLOW, "evidence dashboard workflow")

    assert "Verified V2 Mainnet Evidence Corpus Curator" in workflow
    assert "Verified V3 Mainnet Evidence Corpus Curator" in workflow
    assert "workflow_run:" in workflow
    assert "workflow_dispatch:" in workflow
    assert "issues: write" in workflow
    assert 'DASHBOARD_ISSUE: "82"' in workflow
    assert "github.event.workflow_run.id" in workflow


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
