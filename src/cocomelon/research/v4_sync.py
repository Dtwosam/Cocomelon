from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from cocomelon.evidence.recording import load_recording_session
from cocomelon.replay.source import validate_recording
from cocomelon.research.contracts import TimeInterval
from cocomelon.research.registry import ResearchRegistry, ResearchRegistryError

V4_AUTHORITY_SOURCE_ID = "github-actions-v4-acquisition-authority-v1"


@dataclass(frozen=True, slots=True)
class V4AuthorityRun:
    run_id: str
    run_attempt: int
    status: str
    conclusion: str | None
    run_started_at_ms: int
    capture_step_conclusion: str | None
    artifact_root: Path | None


def _require_text(value: str, field: str) -> str:
    resolved = value.strip()
    if not resolved:
        raise ResearchRegistryError(f"V4 authority {field} must not be empty")
    return resolved


def _parse_finish(path: Path) -> tuple[int, bool]:
    if not path.is_file():
        raise ResearchRegistryError("V4 capture evidence is missing finished-at-utc.txt")
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        raise ResearchRegistryError("V4 capture evidence has an empty finished-at-utc.txt")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ResearchRegistryError(
            "V4 capture evidence finished-at-utc.txt must be ISO-8601"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ResearchRegistryError(
            "V4 capture evidence finished-at-utc.txt must be timezone-aware"
        )
    finish_ms = int(parsed.astimezone(UTC).timestamp() * 1_000)
    time_text = raw.split("T", 1)[-1]
    has_fraction = "." in time_text.split("Z", 1)[0].split("+", 1)[0]
    return finish_ms, has_fraction


def _artifact_interval(root: Path) -> TimeInterval:
    recording_root = root / "recording"
    session = load_recording_session(recording_root)
    if session is None:
        raise ResearchRegistryError("V4 capture evidence is missing recording-session.json")
    try:
        segments = validate_recording(recording_root)
    except ValueError as exc:
        raise ResearchRegistryError(f"V4 capture evidence recording is invalid: {exc}") from exc
    if not segments:
        raise ResearchRegistryError("V4 capture evidence contains no validated recording segments")

    declared_finish_ms, finish_has_fraction = _parse_finish(root / "output" / "finished-at-utc.txt")
    first_source_ms = min(item.first_available_at_ms for item in segments)
    last_source_ms = max(item.last_available_at_ms for item in segments)
    start_ms = session.started_at_ms
    if first_source_ms < start_ms:
        raise ResearchRegistryError("V4 source event is outside acquisition session start")

    finish_ms = declared_finish_ms
    if last_source_ms > declared_finish_ms:
        coarse_overrun_ms = last_source_ms - declared_finish_ms
        if finish_has_fraction or coarse_overrun_ms >= 1_000:
            raise ResearchRegistryError("V4 source event is outside acquisition session finish")
        # The production workflow writes the finish marker at second precision. Preserve
        # every actually observed source event rather than pretending the coarse marker
        # ended up to 999 ms earlier than it did.
        finish_ms = last_source_ms + 1
    if finish_ms <= start_ms:
        raise ResearchRegistryError("V4 acquisition session interval is invalid")
    return TimeInterval(start_ms=start_ms, end_ms=finish_ms)


def _canonical_run_id(run: V4AuthorityRun) -> str:
    return f"github-v4-{_require_text(run.run_id, 'run_id')}-attempt-{run.run_attempt}"


def _validate_run(run: V4AuthorityRun) -> None:
    _require_text(run.run_id, "run_id")
    if run.run_attempt <= 0:
        raise ResearchRegistryError("V4 authority run_attempt must be positive")
    if run.run_started_at_ms < 0:
        raise ResearchRegistryError("V4 authority run_started_at_ms must be non-negative")
    status = _require_text(run.status, "status")
    if status == "completed" and not (run.conclusion or "").strip():
        raise ResearchRegistryError("completed V4 authority run requires a conclusion")


def _completed_interval(run: V4AuthorityRun) -> tuple[TimeInterval, str] | None:
    capture = (run.capture_step_conclusion or "").strip()
    if run.artifact_root is None:
        if capture == "skipped":
            return None
        raise ResearchRegistryError(
            "completed V4 run lacks authoritative capture evidence"
        )
    interval = _artifact_interval(run.artifact_root)
    disposition = (
        "accepted"
        if run.conclusion == "success" and capture == "success"
        else "workflow_failure"
    )
    return interval, disposition


def apply_v4_authority_inventory(
    registry: ResearchRegistry,
    *,
    runs: tuple[V4AuthorityRun, ...],
    observed_at_ms: int,
) -> int:
    if observed_at_ms < 0:
        raise ResearchRegistryError("V4 authority observation timestamp must be non-negative")

    barriers: list[int] = []
    completed: list[tuple[V4AuthorityRun, TimeInterval, str]] = []
    seen: set[tuple[str, int]] = set()
    for run in runs:
        _validate_run(run)
        identity = (run.run_id, run.run_attempt)
        if identity in seen:
            raise ResearchRegistryError("V4 authority inventory contains a duplicate run attempt")
        seen.add(identity)
        if run.status != "completed":
            barriers.append(run.run_started_at_ms)
            continue
        resolved = _completed_interval(run)
        if resolved is None:
            continue
        interval, disposition = resolved
        completed.append((run, interval, disposition))

    for run, interval, disposition in completed:
        registry.record_v4_interval(
            run_id=_canonical_run_id(run),
            interval=interval,
            disposition=disposition,
        )

    through_ms = min((observed_at_ms, *barriers)) if barriers else observed_at_ms
    registry.mark_v4_registry_complete_through(
        through_ms=through_ms,
        source_id=V4_AUTHORITY_SOURCE_ID,
    )
    return through_ms
