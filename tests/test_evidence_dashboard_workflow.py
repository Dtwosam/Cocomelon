from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/evidence-dashboard.yml")
BUILDER = Path("scripts/build_evidence_dashboard.py")


def _read_required(path: Path, label: str) -> str:
    assert path.is_file(), f"{label} must exist"
    return path.read_text(encoding="utf-8")


def test_dashboard_refresh_is_event_driven_and_writable() -> None:
    workflow = _read_required(WORKFLOW, "evidence dashboard workflow")

    assert "Verified V2 Mainnet Evidence Corpus Curator" in workflow
    assert "workflow_run:" in workflow
    assert "workflow_dispatch:" in workflow
    assert "issues: write" in workflow
    assert 'DASHBOARD_ISSUE: "82"' in workflow
    assert "github.event.workflow_run.id" in workflow


def test_dashboard_uses_verified_corpus_progress_and_live_run_status() -> None:
    workflow = _read_required(WORKFLOW, "evidence dashboard workflow")
    builder = _read_required(BUILDER, "evidence dashboard builder")

    assert "scripts/build_evidence_dashboard.py" in workflow
    assert "v2-mainnet-corpus" in builder
    assert "progress.json" in builder
    assert "corpus-index.json" in builder
    assert "Scheduled Genuine Mainnet Evidence Campaign V2" in builder
    assert "Verified V2 Mainnet Evidence Corpus Curator" in builder
    assert "gh api --method PATCH" in workflow
