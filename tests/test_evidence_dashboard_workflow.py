from pathlib import Path


WORKFLOW = Path(".github/workflows/evidence-dashboard.yml")


def _workflow_text() -> str:
    assert WORKFLOW.is_file(), "evidence dashboard workflow must exist"
    return WORKFLOW.read_text(encoding="utf-8")


def test_dashboard_refresh_is_event_driven_and_writable() -> None:
    text = _workflow_text()

    assert "Verified V2 Mainnet Evidence Corpus Curator" in text
    assert "workflow_run:" in text
    assert "workflow_dispatch:" in text
    assert "issues: write" in text
    assert 'DASHBOARD_ISSUE: "82"' in text


def test_dashboard_uses_verified_corpus_progress_and_live_run_status() -> None:
    text = _workflow_text()

    assert "v2-mainnet-corpus" in text
    assert "progress.json" in text
    assert "corpus-index.json" in text
    assert "Scheduled Genuine Mainnet Evidence Campaign V2" in text
    assert "github.event.workflow_run.id" in text
    assert "gh api --method PATCH" in text
