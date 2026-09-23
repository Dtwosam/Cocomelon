from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum

HOUR_MS = 3_600_000
MINUTE_MS = 60_000
DEFAULT_PROTECTED_CAPTURE_MINUTE_UTC = 3
DEFAULT_MAX_ENTRY_CANDLE_AGE_MS = 15 * MINUTE_MS
DEFAULT_QUEUE_DEPTH = 4


class ProspectiveDispatchQueueError(RuntimeError):
    pass


class ProspectiveCaptureWindow(StrEnum):
    EARLY = "early"
    READY = "ready"
    STALE = "stale"


@dataclass(frozen=True, slots=True)
class ProspectiveDispatchRun:
    run_id: int
    display_title: str
    event: str
    head_branch: str
    status: str
    conclusion: str | None

    def __post_init__(self) -> None:
        if self.run_id <= 0:
            raise ValueError("run_id must be positive")
        if not self.display_title.strip():
            raise ValueError("display_title must not be empty")
        if not self.event.strip():
            raise ValueError("event must not be empty")
        if not self.head_branch.strip():
            raise ValueError("head_branch must not be empty")
        if not self.status.strip():
            raise ValueError("status must not be empty")

    @property
    def can_cover_target(self) -> bool:
        if self.status != "completed":
            return True
        return self.conclusion == "success"


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProspectiveDispatchQueueError(f"{field}_INVALID")
    return value


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProspectiveDispatchQueueError(f"{field}_INVALID")
    return value


def normalize_dispatch_runs(
    raw_runs: Iterable[Mapping[str, object]],
) -> tuple[ProspectiveDispatchRun, ...]:
    runs: list[ProspectiveDispatchRun] = []
    for raw in raw_runs:
        conclusion_raw = raw.get("conclusion")
        if conclusion_raw is not None and not isinstance(conclusion_raw, str):
            raise ProspectiveDispatchQueueError("RUN_CONCLUSION_INVALID")
        runs.append(
            ProspectiveDispatchRun(
                run_id=_integer(raw.get("id"), "RUN_ID"),
                display_title=_text(raw.get("display_title"), "RUN_DISPLAY_TITLE"),
                event=_text(raw.get("event"), "RUN_EVENT"),
                head_branch=_text(raw.get("head_branch"), "RUN_HEAD_BRANCH"),
                status=_text(raw.get("status"), "RUN_STATUS"),
                conclusion=conclusion_raw,
            )
        )
    return tuple(runs)


def validate_protected_capture_target(
    target_capture_ms: int,
    *,
    protected_minute_utc: int = DEFAULT_PROTECTED_CAPTURE_MINUTE_UTC,
) -> None:
    if target_capture_ms < 0:
        raise ValueError("target_capture_ms must be non-negative")
    if not 0 <= protected_minute_utc < 60:
        raise ValueError("protected_minute_utc must be within [0, 59]")
    required_offset = protected_minute_utc * MINUTE_MS
    if target_capture_ms % HOUR_MS != required_offset:
        raise ValueError("target_capture_ms is off the protected hourly phase")


def next_protected_capture_ms(
    now_ms: int,
    *,
    protected_minute_utc: int = DEFAULT_PROTECTED_CAPTURE_MINUTE_UTC,
) -> int:
    if now_ms < 0:
        raise ValueError("now_ms must be non-negative")
    if not 0 <= protected_minute_utc < 60:
        raise ValueError("protected_minute_utc must be within [0, 59]")
    hour_start_ms = (now_ms // HOUR_MS) * HOUR_MS
    candidate = hour_start_ms + protected_minute_utc * MINUTE_MS
    if candidate <= now_ms:
        candidate += HOUR_MS
    return candidate


def target_anchor_end_ms(
    target_capture_ms: int,
    *,
    protected_minute_utc: int = DEFAULT_PROTECTED_CAPTURE_MINUTE_UTC,
) -> int:
    validate_protected_capture_target(
        target_capture_ms,
        protected_minute_utc=protected_minute_utc,
    )
    protected_offset_ms = protected_minute_utc * MINUTE_MS
    if target_capture_ms <= protected_offset_ms:
        raise ValueError("target_capture_ms must follow a complete hourly anchor")
    return target_capture_ms - protected_offset_ms - 1


def capture_window(
    *,
    target_capture_ms: int,
    now_ms: int,
    protected_minute_utc: int = DEFAULT_PROTECTED_CAPTURE_MINUTE_UTC,
    max_entry_candle_age_ms: int = DEFAULT_MAX_ENTRY_CANDLE_AGE_MS,
) -> ProspectiveCaptureWindow:
    if now_ms < 0:
        raise ValueError("now_ms must be non-negative")
    if max_entry_candle_age_ms <= 0:
        raise ValueError("max_entry_candle_age_ms must be positive")
    anchor_end_ms = target_anchor_end_ms(
        target_capture_ms,
        protected_minute_utc=protected_minute_utc,
    )
    if now_ms < target_capture_ms:
        return ProspectiveCaptureWindow.EARLY
    if now_ms - anchor_end_ms <= max_entry_candle_age_ms:
        return ProspectiveCaptureWindow.READY
    return ProspectiveCaptureWindow.STALE


def future_capture_targets(
    target_capture_ms: int,
    *,
    depth: int = DEFAULT_QUEUE_DEPTH,
    protected_minute_utc: int = DEFAULT_PROTECTED_CAPTURE_MINUTE_UTC,
) -> tuple[int, ...]:
    validate_protected_capture_target(
        target_capture_ms,
        protected_minute_utc=protected_minute_utc,
    )
    if depth <= 0:
        raise ValueError("depth must be positive")
    return tuple(
        target_capture_ms + index * HOUR_MS
        for index in range(1, depth + 1)
    )


def dispatch_run_title(prefix: str, target_capture_ms: int) -> str:
    normalized = prefix.strip()
    if not normalized:
        raise ValueError("prefix must not be empty")
    validate_protected_capture_target(target_capture_ms)
    return f"{normalized} {target_capture_ms}"


def _eligible_for_title(
    run: ProspectiveDispatchRun,
    *,
    title: str,
    event: str,
    head_branch: str,
) -> bool:
    return (
        run.display_title == title
        and run.event == event
        and run.head_branch == head_branch
        and run.can_cover_target
    )


def elect_dispatch_leader(
    runs: Iterable[ProspectiveDispatchRun],
    *,
    title: str,
    current_run_id: int,
    event: str = "workflow_dispatch",
    head_branch: str = "main",
) -> bool:
    if current_run_id <= 0:
        raise ValueError("current_run_id must be positive")
    matching = tuple(
        run
        for run in runs
        if _eligible_for_title(
            run,
            title=title,
            event=event,
            head_branch=head_branch,
        )
    )
    if not matching:
        raise ProspectiveDispatchQueueError("DISPATCH_LEADER_NOT_FOUND")
    leader = min(matching, key=lambda item: item.run_id)
    return leader.run_id == current_run_id


def target_has_covering_run(
    runs: Iterable[ProspectiveDispatchRun],
    *,
    title: str,
    event: str = "workflow_dispatch",
    head_branch: str = "main",
) -> bool:
    return any(
        _eligible_for_title(
            run,
            title=title,
            event=event,
            head_branch=head_branch,
        )
        for run in runs
    )


def missing_future_targets(
    runs: Iterable[ProspectiveDispatchRun],
    *,
    prefix: str,
    target_capture_ms: int,
    depth: int = DEFAULT_QUEUE_DEPTH,
) -> tuple[int, ...]:
    resolved_runs = tuple(runs)
    missing: list[int] = []
    for target in future_capture_targets(target_capture_ms, depth=depth):
        title = dispatch_run_title(prefix, target)
        if not target_has_covering_run(resolved_runs, title=title):
            missing.append(target)
    return tuple(missing)
