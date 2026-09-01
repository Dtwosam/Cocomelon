from __future__ import annotations

from datetime import UTC, datetime
from importlib import import_module, util
from pathlib import Path

import pytest

from cocomelon.evidence.recording import load_recording_session
from cocomelon.replay.source import validate_recording
from cocomelon.research.registry import ResearchRegistry, ResearchRegistryError
from tests.test_evidence_bridge_pipeline import _recording


def _sync_module() -> object:
    spec = util.find_spec("cocomelon.research.v4_sync")
    assert spec is not None, "cocomelon.research.v4_sync must exist"
    return import_module("cocomelon.research.v4_sync")


def _finished_at(value_ms: int) -> str:
    return datetime.fromtimestamp(value_ms / 1000, tz=UTC).isoformat().replace("+00:00", "Z")


def _acquisition_artifact(tmp_path: Path) -> tuple[Path, int, int]:
    root = tmp_path / "v4-acquisition"
    recording_root = root / "recording"
    output_root = root / "output"
    diagnostics_root = root / "diagnostics"
    _recording(recording_root)
    output_root.mkdir(parents=True)
    diagnostics_root.mkdir(parents=True)
    session = load_recording_session(recording_root)
    assert session is not None
    segments = validate_recording(recording_root)
    finish_ms = max(item.last_available_at_ms for item in segments) + 1_000
    (output_root / "finished-at-utc.txt").write_text(
        _finished_at(finish_ms) + "\n",
        encoding="utf-8",
    )
    (diagnostics_root / "recorder-exit-status.txt").write_text("143\n", encoding="utf-8")
    return root, session.started_at_ms, finish_ms


def test_failed_v4_capture_records_actual_session_interval_without_economics(
    tmp_path: Path,
) -> None:
    sync = _sync_module()
    artifact_root, expected_start, expected_end = _acquisition_artifact(tmp_path)
    run = sync.V4AuthorityRun(
        run_id="33369130434",
        run_attempt=1,
        status="completed",
        conclusion="failure",
        run_started_at_ms=expected_start - 5_000,
        capture_step_conclusion="failure",
        artifact_root=artifact_root,
    )
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    observed_at_ms = expected_end + 5_000
    try:
        through_ms = sync.apply_v4_authority_inventory(
            registry,
            runs=(run,),
            observed_at_ms=observed_at_ms,
        )
        interval = registry.connection.execute(
            "SELECT run_id, start_ms, end_ms, disposition FROM research_v4_intervals"
        ).fetchone()
        state = registry.connection.execute(
            "SELECT complete_through_ms, source_id FROM research_v4_registry_state"
        ).fetchone()
    finally:
        registry.close()

    assert interval is not None
    assert str(interval["run_id"]) == "github-v4-33369130434-attempt-1"
    assert int(interval["start_ms"]) == expected_start
    assert int(interval["end_ms"]) == expected_end
    assert str(interval["disposition"]) == "workflow_failure"
    assert through_ms == observed_at_ms
    assert state is not None
    assert int(state["complete_through_ms"]) == observed_at_ms
    assert str(state["source_id"]) == sync.V4_AUTHORITY_SOURCE_ID


def test_in_progress_v4_run_is_a_completeness_barrier_not_a_nominal_interval(
    tmp_path: Path,
) -> None:
    sync = _sync_module()
    artifact_root, start_ms, end_ms = _acquisition_artifact(tmp_path)
    completed = sync.V4AuthorityRun(
        run_id="completed",
        run_attempt=1,
        status="completed",
        conclusion="success",
        run_started_at_ms=start_ms - 5_000,
        capture_step_conclusion="success",
        artifact_root=artifact_root,
    )
    barrier_ms = end_ms + 10_000
    in_progress = sync.V4AuthorityRun(
        run_id="in-progress",
        run_attempt=1,
        status="in_progress",
        conclusion=None,
        run_started_at_ms=barrier_ms,
        capture_step_conclusion=None,
        artifact_root=None,
    )
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    try:
        through_ms = sync.apply_v4_authority_inventory(
            registry,
            runs=(completed, in_progress),
            observed_at_ms=barrier_ms + 50_000,
        )
        rows = registry.connection.execute(
            "SELECT run_id FROM research_v4_intervals ORDER BY run_id"
        ).fetchall()
    finally:
        registry.close()

    assert through_ms == barrier_ms
    assert [str(row["run_id"]) for row in rows] == ["github-v4-completed-attempt-1"]


def test_completed_run_without_artifact_only_advances_when_capture_was_proven_skipped(
    tmp_path: Path,
) -> None:
    sync = _sync_module()
    ambiguous = sync.V4AuthorityRun(
        run_id="ambiguous",
        run_attempt=1,
        status="completed",
        conclusion="failure",
        run_started_at_ms=10_000,
        capture_step_conclusion="failure",
        artifact_root=None,
    )
    registry = ResearchRegistry(tmp_path / "ambiguous.sqlite3")
    try:
        with pytest.raises(ResearchRegistryError, match="capture evidence"):
            sync.apply_v4_authority_inventory(
                registry,
                runs=(ambiguous,),
                observed_at_ms=20_000,
            )
    finally:
        registry.close()

    skipped = sync.V4AuthorityRun(
        run_id="skipped",
        run_attempt=1,
        status="completed",
        conclusion="failure",
        run_started_at_ms=10_000,
        capture_step_conclusion="skipped",
        artifact_root=None,
    )
    registry = ResearchRegistry(tmp_path / "skipped.sqlite3")
    try:
        through_ms = sync.apply_v4_authority_inventory(
            registry,
            runs=(skipped,),
            observed_at_ms=20_000,
        )
        count = registry.connection.execute(
            "SELECT COUNT(*) FROM research_v4_intervals"
        ).fetchone()[0]
    finally:
        registry.close()

    assert through_ms == 20_000
    assert count == 0


def test_v4_authority_rejects_source_events_outside_declared_session_finish(
    tmp_path: Path,
) -> None:
    sync = _sync_module()
    artifact_root, _, _ = _acquisition_artifact(tmp_path)
    segments = validate_recording(artifact_root / "recording")
    too_early_finish = max(item.last_available_at_ms for item in segments) - 1
    (artifact_root / "output" / "finished-at-utc.txt").write_text(
        _finished_at(too_early_finish) + "\n",
        encoding="utf-8",
    )
    run = sync.V4AuthorityRun(
        run_id="bad-finish",
        run_attempt=1,
        status="completed",
        conclusion="failure",
        run_started_at_ms=1,
        capture_step_conclusion="failure",
        artifact_root=artifact_root,
    )
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    try:
        with pytest.raises(ResearchRegistryError, match="outside acquisition session"):
            sync.apply_v4_authority_inventory(
                registry,
                runs=(run,),
                observed_at_ms=too_early_finish + 5_000,
            )
    finally:
        registry.close()
