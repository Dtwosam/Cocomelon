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


def test_observer_rechecks_for_newer_protected_v4_before_safe_gap_dispatch() -> None:
    text = OBSERVER.read_text(encoding="utf-8")
    dispatch = text.split("dispatch_safe_gap() {", 1)[1].split("\n          }", 1)[0]

    assert "protected V4 acquisition already exists; safe-gap wakeup skipped" in dispatch
    assert "/actions/workflows/evidence-campaign-v4-scheduled.yml/runs?per_page=100" in dispatch
    assert "/attempts/$CANDIDATE_RUN_ATTEMPT/jobs?per_page=100" in dispatch
    assert 'select(.status != "completed")' in dispatch
    assert "CANDIDATE_ACQUIRE_STATUS" in dispatch
    assert 'if [ "$CANDIDATE_ACQUIRE_STATUS" != "completed" ]; then' in dispatch
    assert dispatch.index("protected V4 acquisition already exists") < dispatch.index(
        "/actions/workflows/research-daily-gap-dispatcher.yml/dispatches"
    )


def test_push_bootstrap_does_not_attach_when_workflow_run_observer_is_active() -> None:
    text = OBSERVER.read_text(encoding="utf-8")
    push = text.split('if [ "$GITHUB_EVENT_NAME" = "push" ]; then', 1)[1].split(
        '          fi\n\n          if [ -z "${RUN_ID:-}" ]',
        1,
    )[0]

    assert "/actions/workflows/research-v4-acquisition-gap-observer.yml/runs?per_page=100" in push
    assert 'select(.event == "workflow_run")' in push
    assert 'select(.status != "completed")' in push
    assert "active workflow-run observer already exists; bootstrap attachment skipped" in push
    assert push.index("active workflow-run observer already exists") < push.index(
        "/actions/workflows/evidence-campaign-v4-scheduled.yml/runs?per_page=100"
    )
