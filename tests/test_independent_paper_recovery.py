"""Regression coverage for independent, fail-closed paper continuity rescue."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from scripts.rescue_continuous_paper import (
    PaperRescueError,
    choose_exact_source,
    find_new_exact_successor,
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
    measured: bool = False,
    fast_packed: bool = False,
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
                "name": "Measure durable continuous paper state",
                "status": "completed" if measured else "pending",
                "conclusion": "success" if measured else None,
            },
            {
                "name": "Pack fast continuous paper resume state",
                "status": "completed" if fast_packed else "pending",
                "conclusion": "success" if fast_packed else None,
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
        "size_in_bytes": 1_000_000,
        "digest": "sha256:" + "a" * 64,
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


def test_failed_trader_terminal_fast_snapshot_can_attempt_exact_restore() -> None:
    # Observed October 13 run: trader step failed, but it stopped, local
    # state was measured and packed, and the exact fast archive was uploaded.
    assert choose(
        [
            run(
                38473612016, event="workflow_dispatch",
                status="completed", conclusion="success",
            ),
            run(38432977298),
            run(38431384464, status="completed", conclusion="success"),
        ],
        jobs_by_run={
            38473612016: paper_job(
                "completed", "skipped", skipped_checkout=True,
            ),
            38432977298: paper_job(
                "completed", "failure", measured=True, fast_packed=True,
            ),
        },
        artifacts_by_run={38432977298: exact_artifact(38432977298)},
    ) == ("ready", (38432977298, 1))


@pytest.mark.parametrize(
    ("measured", "packed", "uploaded", "expired"),
    [
        (False, True, True, False),
        (True, False, True, False),
        (True, True, False, False),
        (True, True, True, True),
    ],
)
def test_failed_trader_with_incomplete_or_expired_terminal_fast_state_blocks(
    measured: bool, packed: bool, uploaded: bool, expired: bool,
) -> None:
    artifacts = exact_artifact(13)
    artifacts[0]["expired"] = expired
    assert choose(
        [run(13), run(12)],
        jobs_by_run={
            13: paper_job(
                "completed", "failure", measured=measured,
                fast_packed=packed, fast_uploaded=uploaded,
            ),
            12: paper_job("completed", "success"),
        },
        artifacts_by_run={13: artifacts, 12: exact_artifact(12)},
    ) == ("blocked", None)


def test_failed_trader_still_running_cannot_be_rescued() -> None:
    assert choose(
        [run(13)],
        jobs_by_run={
            13: paper_job(
                "in_progress", None, measured=True, fast_packed=True,
            ),
        },
        artifacts_by_run={13: exact_artifact(13)},
    ) == ("active", (13, 1))


@pytest.mark.parametrize("trader_outcome", ["success", "failure"])
def test_cancelled_after_terminal_archive_is_safe_exact_resume(
    trader_outcome: str,
) -> None:
    # Real worker #38432977298 completed its paper trader and packed
    # 11852078410 before cancellation of its deferred research tail.
    assert choose(
        [
            run(38473612016, event="workflow_dispatch",
                status="completed", conclusion="success"),
            run(38432977298, event="workflow_dispatch",
                status="completed", conclusion="cancelled"),
            run(38431384464, status="completed", conclusion="failure"),
        ],
        jobs_by_run={
            38473612016: paper_job(
                "completed", "skipped", skipped_checkout=True,
            ),
            38432977298: paper_job(
                "completed", trader_outcome, measured=True, fast_packed=True,
            ),
        },
        artifacts_by_run={
            38432977298: exact_artifact(38432977298),
        },
    ) == ("ready", (38432977298, 1))


@pytest.mark.parametrize("defect", [
    "missing_measurement", "missing_pack", "missing_upload", "expired",
    "no_digest", "malformed_digest", "zero_size", "duplicate", "wrong_attempt",
    "durable_only",
])
def test_cancelled_archive_requires_exact_post_exit_custody(defect: str) -> None:
    job = paper_job(
        "completed", "failure", measured=True, fast_packed=True,
    )
    artifacts = exact_artifact(13)
    if defect == "missing_measurement":
        job[0]["steps"][2]["conclusion"] = "failure"
    elif defect == "missing_pack":
        job[0]["steps"][3]["conclusion"] = "failure"
    elif defect == "missing_upload":
        job[0]["steps"][4]["conclusion"] = "failure"
    elif defect == "expired":
        artifacts[0]["expired"] = True
    elif defect == "no_digest":
        del artifacts[0]["digest"]
    elif defect == "malformed_digest":
        artifacts[0]["digest"] = "sha256:" + "x" * 64
    elif defect == "zero_size":
        artifacts[0]["size_in_bytes"] = 0
    elif defect == "duplicate":
        artifacts.append(dict(artifacts[0]))
        artifacts[-1]["digest"] = "sha256:" + "x" * 64
    elif defect == "wrong_attempt":
        artifacts[0]["name"] = "continuous-paper-resume-13-2"
    elif defect == "durable_only":
        artifacts[0]["name"] = "continuous-paper-state-13-1"
    assert choose(
        [run(13, status="completed", conclusion="cancelled"), run(12)],
        jobs_by_run={
            13: job, 12: paper_job("completed", "success"),
        },
        artifacts_by_run={
            13: artifacts, 12: exact_artifact(12),
        },
    ) == ("blocked", None)


def test_cancelled_while_trader_is_active_never_dispatches_overlap() -> None:
    assert choose(
        [run(13, status="completed", conclusion="cancelled")],
        jobs_by_run={
            13: paper_job("in_progress", None, measured=True, fast_packed=True),
        },
        artifacts_by_run={13: exact_artifact(13)},
    ) == ("active", (13, 1))


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
    assert "issues: read" in watchdog
    assert "  schedule:" not in paper
    assert "cancel-in-progress: false" in watchdog



def test_exact_active_worker_fresh_heartbeat_and_15min_boundary() -> None:
    now = datetime(2026, 10, 9, 21, 30, tzinfo=UTC)
    template = (
        "## Continuous paper runtime live status\n"
        "Updated: {updated}\n"
        "Worker run: 555999\n"
    )
    for minutes, accepted in ((0, True), (14, True), (15, True), (16, False)):
        body = template.format(
            updated=(now - timedelta(minutes=minutes)).isoformat()
        )
        if accepted:
            assert verify_active_heartbeat(
                body, active_run_id=555999,
                run_started_at=(now - timedelta(minutes=30)).isoformat(),
                now=now,
            ) == "fresh"
        else:
            with pytest.raises(PaperRescueError, match="stale"):
                verify_active_heartbeat(
                    body, active_run_id=555999,
                    run_started_at=(now - timedelta(minutes=30)).isoformat(),
                    now=now,
                )


def test_stale_or_future_workflow_heartbeat_fails_without_rescue_lease() -> None:
    now = datetime(2026, 10, 9, 21, 30, tzinfo=UTC)
    old = "Updated: 2026-10-09T19:29:00+00:00\nWorker run: 100\n"
    assert verify_active_heartbeat(
        old, active_run_id=101,
        run_started_at=(now - timedelta(minutes=4)).isoformat(),
        now=now,
    ) == "startup_grace"
    with pytest.raises(PaperRescueError, match="no current heartbeat"):
        verify_active_heartbeat(
            old, active_run_id=101,
            run_started_at=(now - timedelta(minutes=18)).isoformat(),
            now=now,
        )
    with pytest.raises(PaperRescueError, match="future-dated"):
        verify_active_heartbeat(
            old.replace("19:29:00", "21:35:00").replace("run: 100", "run: 101"),
            active_run_id=101,
            run_started_at=(now - timedelta(minutes=20)).isoformat(),
            now=now,
        )


def test_heartbeat_cannot_predate_claimed_worker_start() -> None:
    now = datetime(2026, 10, 9, 21, 30, tzinfo=UTC)
    with pytest.raises(PaperRescueError, match="stale"):
        verify_active_heartbeat(
            "Worker run: 101\nUpdated: 2026-10-09T21:20:00Z\n",
            active_run_id=101, run_started_at="2026-10-09T21:26:00Z",
            now=now,
        )


@pytest.mark.parametrize(
    ("body", "start"),
    (
        (None, "2026-10-09T21:20:00Z"),
        (42, "2026-10-09T21:20:00Z"),
        ("Worker run: 101\n", None),
        ("Worker run: 101\n", "no date"),
        ("Worker run: 101\n", "2026-10-09T21:20:00"),
        ("Worker run: 101\n", "2026-10-09T21:40:00Z"),
        ("Worker run: 101\nUpdated: not-iso\n", "2026-10-09T21:20:00Z"),
        ("Worker run: 101\nUpdated: 2026-10-09T21:28:00\n", "2026-10-09T21:20:00Z"),
    ),
)
def test_missing_corrupt_and_future_active_heartbeat_data_fail_closed(
    body: object, start: object,
) -> None:
    with pytest.raises(PaperRescueError):
        verify_active_heartbeat(
            body, active_run_id=101, run_started_at=start,
            now=datetime(2026, 10, 9, 21, 30, tzinfo=UTC),
        )


def test_active_worker_identity_cannot_be_boolean() -> None:
    with pytest.raises(PaperRescueError, match="identity invalid"):
        verify_active_heartbeat(
            "Updated: 2026-10-09T21:29:00Z\nWorker run: 1\n",
            active_run_id=True,  # type: ignore[arg-type]
            run_started_at="2026-10-09T21:20:00Z",
            now=datetime(2026, 10, 9, 21, 30, tzinfo=UTC),
        )


def test_exact_successor_receipt_must_be_new_and_from_correct_predecessor() -> None:
    candidate = run(101, event="workflow_dispatch", status="queued")
    candidate["display_title"] = "Continuous Paper · 100"
    assert find_new_exact_successor(
        [candidate], repository=REPOSITORY, source_run_id=100,
        previously_seen_ids=frozenset(),
    ) == 101
    assert find_new_exact_successor(
        [candidate], repository=REPOSITORY, source_run_id=100,
        previously_seen_ids=frozenset({101}),
    ) is None
    wrong_predecessor = dict(candidate)
    wrong_predecessor["display_title"] = "Continuous Paper · 99"
    assert find_new_exact_successor(
        [wrong_predecessor], repository=REPOSITORY, source_run_id=100,
        previously_seen_ids=frozenset(),
    ) is None


@pytest.mark.parametrize("tamper", [
    "wrong_repository", "wrong_branch", "push", "wrong_workflow",
    "older_run", "fake_run_id",
])
def test_fake_materialized_successor_cannot_certify_dispatch(
    tamper: str,
) -> None:
    candidate = run(101, event="workflow_dispatch")
    candidate["display_title"] = "Continuous Paper · 100"
    if tamper == "wrong_repository":
        candidate["head_repository"] = {"full_name": "other/trader"}
    elif tamper == "wrong_branch":
        candidate["head_branch"] = "research-branch"
    elif tamper == "push":
        candidate["event"] = "push"
    elif tamper == "wrong_workflow":
        candidate["path"] = ".github/workflows/other.yml"
    elif tamper == "older_run":
        candidate["id"] = 100
    else:
        candidate["id"] = True
    if tamper in {"older_run", "fake_run_id"}:
        with pytest.raises(PaperRescueError, match="invalid"):
            find_new_exact_successor(
                [candidate], repository=REPOSITORY, source_run_id=100,
                previously_seen_ids=frozenset(),
            )
    else:
        assert find_new_exact_successor(
            [candidate], repository=REPOSITORY, source_run_id=100,
            previously_seen_ids=frozenset(),
        ) is None


def test_duplicate_new_exact_dispatch_is_not_a_success_receipt() -> None:
    first = run(101, event="workflow_dispatch")
    first["display_title"] = "Continuous Paper · 100"
    second = run(102, event="workflow_dispatch")
    second["display_title"] = "Continuous Paper · 100"
    with pytest.raises(PaperRescueError, match="multiple"):
        find_new_exact_successor(
            [first, second], repository=REPOSITORY,
            source_run_id=100, previously_seen_ids=frozenset(),
        )


def test_recovery_runs_on_every_main_merge_but_keeps_exclusive_lease() -> None:
    from pathlib import Path

    watchdog = Path(".github/workflows/independent-paper-recovery.yml").read_text()
    script = Path("scripts/rescue_continuous_paper.py").read_text()
    push = watchdog.split("  push:", 1)[1].split("  workflow_dispatch:", 1)[0]
    assert "branches: [main]" in push
    assert "paths:" not in push
    assert "group: independent-paper-rescue" in watchdog
    assert "COCOMELON_EXECUTION_MODE: paper" in watchdog
    assert "gh\", \"workflow\", \"run\"" in script
    assert "latest_status != \"ready\" or latest_source != source" in script
    assert 'latest_status in {"active", "queued_exact"}' in script
    assert "PAPER lease changed to unverifiable exact state" in script
    assert "previously_seen_ids=prior_ids" in script
    assert "no NEW successor run" in script




def test_speculative_guard_pending_trader_is_not_an_active_paper_worker() -> None:
    # Observed Oct 17: main push #39072496525 was stuck on the startup
    # guard while restored exact #39071958397 genuinely ran the trader.
    # A "pending" future trader step does not have a running lease.
    speculative = paper_job("pending", None)
    speculative[0]["steps"][0]["status"] = "pending"
    assert choose(
        [run(15, event="push", status="in_progress"), run(12)],
        jobs_by_run={
            15: speculative,
            12: paper_job("in_progress", None),
        },
    ) == ("blocked", None)


def test_unstarted_exact_handoff_is_held_without_claiming_a_trader() -> None:
    # No second dispatch may overlap the exact predecessor's pending
    # restoration, but no authenticated PAPER heartbeat is yet possible.
    pending = paper_job("pending", None)
    pending[0]["steps"][0]["status"] = "pending"
    assert choose(
        [run(15, event="workflow_dispatch", status="in_progress"), run(12)],
        jobs_by_run={
            15: pending,
            12: paper_job("completed", "success"),
        },
        artifacts_by_run={12: exact_artifact(12)},
    ) == ("queued_exact", None)


def test_actual_trader_step_in_progress_still_requires_active_heartbeat() -> None:
    # The only active classification is the trader step itself in progress,
    # not the GitHub job being in progress in another earlier step.
    assert choose(
        [run(15, event="workflow_dispatch", status="in_progress")],
        jobs_by_run={15: paper_job("in_progress", None)},
    ) == ("active", (15, 1))


def test_completed_unstarted_guard_does_not_borrow_old_paper_state() -> None:
    assert choose(
        [
            run(15, event="push", status="completed", conclusion="failure"),
            run(12, event="workflow_dispatch", status="in_progress"),
        ],
        jobs_by_run={
            15: paper_job("pending", None),
            12: paper_job("in_progress", None),
        },
    ) == ("blocked", None)
