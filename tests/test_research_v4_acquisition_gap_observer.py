from pathlib import Path

OBSERVER = Path(".github/workflows/research-v4-acquisition-gap-observer.yml")


def test_v4_acquisition_gap_observer_wakes_existing_safe_gap_dispatcher() -> None:
    text = OBSERVER.read_text(encoding="utf-8")

    assert "name: Research V4 Acquisition Gap Observer" in text
    assert "Scheduled Genuine Mainnet Evidence Campaign V4" in text
    assert "types: [in_progress]" in text
    assert "push:" in text
    assert "branches: [main]" in text
    assert ".github/workflows/research-v4-acquisition-gap-observer.yml" in text
    assert "github.event.workflow_run.head_branch == 'main'" in text
    assert "github.event.workflow_run.event == 'schedule'" in text
    assert "github.event_name == 'push'" in text
    assert "actions: write" in text
    assert "actions/checkout" not in text
    assert "timeout-minutes: 340" in text
    assert "/actions/workflows/evidence-campaign-v4-scheduled.yml/runs?per_page=100" in text
    assert "bootstrap V4 workflow metadata is ambiguous" in text
    assert "bootstrap found no active scheduled V4 acquisition" in text
    assert "/attempts/$RUN_ATTEMPT/jobs?per_page=100" in text
    assert '.name == \"acquire-evidence\"' in text
    assert "acquire-evidence job metadata is ambiguous" in text
    assert 'if [ "$ACQUIRE_STATUS" = "completed" ]; then' in text
    assert "sleep 60" in text
    assert (
        "/actions/workflows/research-daily-gap-dispatcher.yml/dispatches" in text
    )
    assert "/actions/workflows/research-campaign-scheduled.yml/dispatches" not in text
