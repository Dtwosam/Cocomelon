"""Regression coverage for independent, fail-closed paper continuity rescue."""

from __future__ import annotations

import pytest
from datetime import UTC, datetime, timedelta

from scripts.rescue_continuous_paper import (
    PaperRescueError,
    choose_exact_source,
    verify_active_heartbeat,
)

REPOSITORY = "Dtwosam/Cocomelon"
OLD_RUN = 37768727228


def run(
    run_id: int,
    *,
    event: str = "push",
    status: str = "in_progress",
    conclusion: str | None = None,
) -> dict[str, object]:
    return {
        "id": run_id,
        "event": event,
        "status": status,
        "conclusion": conclusion,
        "path": ".github/workflows/continuous-paper.yml",
        "head_branch": "main",
        "head_repository": {"full_name": REPOSITORY},
        "run_attempt": 1,
    }


def paper_job(
    trader_status: str,
    trader_conclusion: str | None,
    *,
    fast_uploaded: bool = True,
    skipped_checkout: bool = False,
) -> list[dict[str, object]]:
    return [{
        "name": "paper",
        "steps": [
            {
                "name": "Run actions/checkout@v7",
                "status": "completed",
                "conclusion": "skipped" if skipped_checkout else "success",
            },
            {
                "name": "Run continuous paper trader",
                "status": trader_status,
                "conclusion": trader_conclusion,
            },
            {
                "name": "Upload fast continuous paper resume state",
                "status": "completed" if fast_uploaded else "pending",
                "conclusion": "success" if fast_uploaded else None,
            },
        ],
    }]


def exact_artifact(run_id: int) -> list[dict[str, object]]:
    return [{
        "name": f"continuous-paper-resume-{run_id}-1",
        "expired": False,
    }]


def choose(
    runs: list[dict[str, object]],
    *,
    jobs_by_run: dict[int, list[dict[str, object]]],
    artifacts_by_run: dict[int, list[dict[str, object]]] | None = None,
) -> tuple[str, tuple[int, int] | None]:
    return choose_exact_source(
        runs,
        repository=REPOSITORY,
        get_jobs=lambda run_id: jobs_by_run[run_id],
        get_artifacts=lambda run_id: (artifacts_by_run or {}).get(run_id, []),
    )


def test_exact_archived_worker_beats_queued_nontrading_push_and_green_skipped_successor() -> None:
    assert choose(
        [
            run(37771010416, status="pending"),
            run(
                37770542228,
                event="workflow_dispatch",
                status="completed",
                conclusion="success",
            ),
            run(OLD_RUN),
        ],
        jobs_by_run={
            37770542228: paper_job(
                "completed", "skipped", skipped_checkout=True
            ),
            OLD_RUN: paper_job("completed", "success"),
        },
        artifacts_by_run={OLD_RUN: exact_artifact(OLD_RUN)},
    ) == ("ready", (OLD_RUN, 1))


def test_running_real_trader_blocks_any_replacement() -> None:
    assert choose(
        [run(12)],
        jobs_by_run={12: paper_job("in_progress", None)},
    ) == ("active", (12, 1))


def test_pending_exact_successor_blocks_duplicate_dispatch() -> None:
    assert choose(
        [
            run(13, event="workflow_dispatch", status="queued"),
            run(12),
        ],
        jobs_by_run={12: paper_job("completed", "success")},
        artifacts_by_run={12: exact_artifact(12)},
    ) == ("queued_exact", None)


def test_unarchived_latest_finished_worker_does_not_roll_back_to_old_state() -> None:
    assert choose(
        [run(13), run(12)],
        jobs_by_run={
            13: paper_job("completed", "success"),
            12: paper_job("completed", "success"),
        },
        artifacts_by_run={12: exact_artifact(12)},
    ) == ("blocked", None)


def test_failed_worker_cannot_be_replaced_from_old_archives() -> None:
    assert choose(
        [run(13), run(12)],
        jobs_by_run={
            13: paper_job("completed", "failure"),
            12: paper_job("completed", "success"),
        },
        artifacts_by_run={
            13: exact_artifact(13), 12: exact_artifact(12)
        },
    ) == ("blocked", None)


def test_skipped_guard_does_not_claim_live_trader_or_evidence() -> None:
    assert choose(
        [run(13, status="completed", conclusion="success")],
        jobs_by_run={
            13: paper_job("completed", "skipped", skipped_checkout=True)
        },
    ) == ("no_source", None)


def test_missing_or_expired_exact_artifact_fails_closed() -> None:
    assert choose(
        [run(12)],
        jobs_by_run={12: paper_job("completed", "success")},
        artifacts_by_run={
            12: [{"name": "continuous-paper-resume-12-1", "expired": True}]
        },
    ) == ("blocked", None)


def test_cancelled_and_failed_pushes_without_jobs_do_not_block_archive() -> None:
    # Actual production runs had no job at all: 37771010416
    # (cancelled), 37770349229 (cancelled), and 37769990622
    # (failed admission). They cannot own or mutate a paper account.
    assert choose(
        [
            run(37771010416, status="completed", conclusion="cancelled"),
            run(37770349229, status="completed", conclusion="cancelled"),
            run(37769990622, status="completed", conclusion="failure"),
            run(OLD_RUN),
        ],
        jobs_by_run={
            37771010416: [],
            37770349229: [],
            37769990622: [],
            OLD_RUN: paper_job("completed", "success"),
        },
        artifacts_by_run={OLD_RUN: exact_artifact(OLD_RUN)},
    ) == ("ready", (OLD_RUN, 1))


def test_cancelled_worker_with_materialized_paper_job_still_blocks() -> None:
    assert choose(
        [run(13, status="completed", conclusion="cancelled"), run(12)],
        jobs_by_run={
            13: paper_job("completed", "failure"),
            12: paper_job("completed", "success"),
        },
        artifacts_by_run={12: exact_artifact(12)},
    ) == ("blocked", None)


def test_cancelled_exact_dispatch_without_jobs_still_blocks() -> None:
    assert choose(
        [
            run(
                13,
                event="workflow_dispatch",
                status="completed",
                conclusion="cancelled",
            ),
            run(12),
        ],
        jobs_by_run={13: [], 12: paper_job("completed", "success")},
        artifacts_by_run={12: exact_artifact(12)},
    ) == ("blocked", None)


def test_missing_paper_job_fails_closed() -> None:
    assert choose(
        [run(12)],
        jobs_by_run={12: []},
    ) == ("blocked", None)


def test_wrong_repository_run_is_ignored() -> None:
    foreign = run(13)
    foreign["head_repository"] = {"full_name": "other/repo"}
    assert choose(
        [foreign, run(12)],
        jobs_by_run={12: paper_job("completed", "success")},
        artifacts_by_run={12: exact_artifact(12)},
    ) == ("ready", (12, 1))


def test_corrupt_run_attempt_rejected() -> None:
    bad = run(13)
    bad["run_attempt"] = True
    with pytest.raises(PaperRescueError, match="run attempt"):
        choose(
            [bad],
            jobs_by_run={13: paper_job("completed", "success")},
        )



def test_active_worker_heartbeat_must_match_run_and_be_recent() -> None:
    now = datetime(2026, 10, 8, 12, 30, tzinfo=UTC)
    issue = (
        "## Continuous paper runtime live status\\n"
        "Updated: 2026-10-08T12:29:24+00:00\\n"
        "Worker run: 37776929867\\n"
    )
    assert verify_active_heartbeat(
        issue,
        active_run_id=37776929867,
        run_started_at="2026-10-08T12:26:00Z",
        now=now,
    ) == "fresh"
    with pytest.raises(PaperRescueError, match="stale"):
        verify_active_heartbeat(
            issue.replace("12:29:24", "11:29:24"),
            active_run_id=37776929867,
            run_started_at="2026-10-08T12:26:00Z",
            now=now,
        )
    with pytest.raises(PaperRescueError, match="future-dated"):
        verify_active_heartbeat(
            issue.replace("12:29:24", "12:40:24"),
            active_run_id=37776929867,
            run_started_at="2026-10-08T12:26:00Z",
            now=now,
        )


def test_heartbeat_startup_grace_never_claims_old_worker_is_current() -> None:
    now = datetime(2026, 10, 8, 12, 30, tzinfo=UTC)
    old_issue = (
        "Updated: 2026-10-08T11:29:24+00:00\\n"
        "Worker run: 37768727228\\n"
    )
    assert verify_active_heartbeat(
        old_issue,
        active_run_id=37776929867,
        run_started_at="2026-10-08T12:27:00Z",
        now=now,
    ) == "startup_grace"
    with pytest.raises(PaperRescueError, match="no current heartbeat"):
        verify_active_heartbeat(
            old_issue,
            active_run_id=37776929867,
            run_started_at=(now - timedelta(minutes=18)).isoformat(),
            now=now,
        )


def test_corrupt_heartbeat_and_missing_run_start_fail_closed() -> None:
    now = datetime(2026, 10, 8, 12, 30, tzinfo=UTC)
    for invalid in (None, 42, ""):
        with pytest.raises(PaperRescueError):
            verify_active_heartbeat(
                invalid,
                active_run_id=12,
                run_started_at=now.isoformat(),
                now=now,
            )
    with pytest.raises(PaperRescueError, match="start timestamp"):
        verify_active_heartbeat(
            "Worker run: 12\\n",
            active_run_id=12,
            run_started_at=None,
            now=now,
        )


def test_independent_workflow_has_unshared_concurrency_and_no_live_orders() -> None:
    from pathlib import Path

    watchdog = Path(".github/workflows/independent-paper-recovery.yml").read_text(
        encoding="utf-8"
    )
    paper = Path(".github/workflows/continuous-paper.yml").read_text(
        encoding="utf-8"
    )
    assert '- cron: "3,13,23,33,43,53 * * * *"' in watchdog
    assert "group: independent-paper-rescue" in watchdog
    assert "python scripts/rescue_continuous_paper.py" in watchdog
    assert "COCOMELON_EXECUTION_MODE: paper" in watchdog
    assert "  schedule:" not in paper
    assert "cancel-in-progress: false" in watchdog
