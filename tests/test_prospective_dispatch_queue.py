from __future__ import annotations

import pytest

from cocomelon.research.prospective_dispatch_queue import (
    HOUR_MS,
    ProspectiveCaptureWindow,
    ProspectiveDispatchQueueError,
    ProspectiveDispatchRun,
    capture_window,
    dispatch_run_title,
    elect_dispatch_leader,
    future_capture_targets,
    missing_future_targets,
    next_protected_capture_ms,
    normalize_dispatch_runs,
    target_anchor_end_ms,
    target_has_covering_run,
    validate_protected_capture_target,
)

MINUTE_MS = 60_000


def _run(
    run_id: int,
    title: str,
    *,
    status: str = "queued",
    conclusion: str | None = None,
    event: str = "workflow_dispatch",
    branch: str = "main",
) -> ProspectiveDispatchRun:
    return ProspectiveDispatchRun(
        run_id=run_id,
        display_title=title,
        event=event,
        head_branch=branch,
        status=status,
        conclusion=conclusion,
    )


def test_next_protected_capture_uses_next_minute_three_boundary() -> None:
    hour = 1_800_000_000_000
    hour -= hour % HOUR_MS

    assert next_protected_capture_ms(hour) == hour + 3 * MINUTE_MS
    assert next_protected_capture_ms(hour + 2 * MINUTE_MS) == hour + 3 * MINUTE_MS
    assert (
        next_protected_capture_ms(hour + 3 * MINUTE_MS)
        == hour + HOUR_MS + 3 * MINUTE_MS
    )


def test_target_phase_and_anchor_identity_are_exact() -> None:
    target = 1_800_000_000_000
    target -= target % HOUR_MS
    target += 3 * MINUTE_MS

    validate_protected_capture_target(target)
    assert target_anchor_end_ms(target) == target - 3 * MINUTE_MS - 1

    with pytest.raises(ValueError, match="off the protected hourly phase"):
        validate_protected_capture_target(target + 1)


def test_capture_window_matches_fifteen_minute_anchor_freshness() -> None:
    target = 1_800_000_000_000
    target -= target % HOUR_MS
    target += 3 * MINUTE_MS
    anchor = target_anchor_end_ms(target)

    assert capture_window(target_capture_ms=target, now_ms=target - 1) is (
        ProspectiveCaptureWindow.EARLY
    )
    assert capture_window(target_capture_ms=target, now_ms=target) is (
        ProspectiveCaptureWindow.READY
    )
    assert capture_window(
        target_capture_ms=target,
        now_ms=anchor + 15 * MINUTE_MS,
    ) is ProspectiveCaptureWindow.READY
    assert capture_window(
        target_capture_ms=target,
        now_ms=anchor + 15 * MINUTE_MS + 1,
    ) is ProspectiveCaptureWindow.STALE


def test_future_queue_targets_are_hourly_and_bounded() -> None:
    target = 1_800_000_000_000
    target -= target % HOUR_MS
    target += 3 * MINUTE_MS

    assert future_capture_targets(target, depth=4) == (
        target + HOUR_MS,
        target + 2 * HOUR_MS,
        target + 3 * HOUR_MS,
        target + 4 * HOUR_MS,
    )


def test_leader_election_ignores_failed_prior_attempts() -> None:
    target = 1_800_000_000_000
    target -= target % HOUR_MS
    target += 3 * MINUTE_MS
    title = dispatch_run_title("Prospective HYPE V3 capture", target)
    runs = (
        _run(10, title, status="completed", conclusion="failure"),
        _run(11, title, status="in_progress"),
        _run(12, title, status="queued"),
    )

    assert elect_dispatch_leader(runs, title=title, current_run_id=11) is True
    assert elect_dispatch_leader(runs, title=title, current_run_id=12) is False


def test_prior_success_suppresses_ambiguous_duplicate() -> None:
    target = 1_800_000_000_000
    target -= target % HOUR_MS
    target += 3 * MINUTE_MS
    title = dispatch_run_title("Prospective HYPE V3 capture", target)
    runs = (
        _run(20, title, status="completed", conclusion="success"),
        _run(21, title, status="in_progress"),
    )

    assert elect_dispatch_leader(runs, title=title, current_run_id=21) is False


def test_queue_fill_treats_failed_runs_as_missing_but_active_and_success_as_covered() -> None:
    target = 1_800_000_000_000
    target -= target % HOUR_MS
    target += 3 * MINUTE_MS
    prefix = "Prospective HYPE V3 capture"
    future = future_capture_targets(target, depth=4)
    runs = (
        _run(
            30,
            dispatch_run_title(prefix, future[0]),
            status="completed",
            conclusion="success",
        ),
        _run(31, dispatch_run_title(prefix, future[1]), status="queued"),
        _run(
            32,
            dispatch_run_title(prefix, future[2]),
            status="completed",
            conclusion="failure",
        ),
    )

    assert target_has_covering_run(
        runs,
        title=dispatch_run_title(prefix, future[0]),
    )
    assert missing_future_targets(
        runs,
        prefix=prefix,
        target_capture_ms=target,
        depth=4,
    ) == (future[2], future[3])


def test_normalization_fails_closed_on_malformed_api_payload() -> None:
    with pytest.raises(ProspectiveDispatchQueueError, match="RUN_ID_INVALID"):
        normalize_dispatch_runs(
            (
                {
                    "id": "not-an-int",
                    "display_title": "capture",
                    "event": "workflow_dispatch",
                    "head_branch": "main",
                    "status": "queued",
                    "conclusion": None,
                },
            )
        )


def test_wrong_event_or_branch_never_covers_target() -> None:
    target = 1_800_000_000_000
    target -= target % HOUR_MS
    target += 3 * MINUTE_MS
    title = dispatch_run_title("Prospective HYPE V3 capture", target)
    runs = (
        _run(40, title, event="push"),
        _run(41, title, branch="feature"),
    )

    assert target_has_covering_run(runs, title=title) is False
    with pytest.raises(ProspectiveDispatchQueueError, match="DISPATCH_LEADER_NOT_FOUND"):
        elect_dispatch_leader(runs, title=title, current_run_id=40)
