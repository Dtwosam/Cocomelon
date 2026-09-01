from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from importlib import import_module
from pathlib import Path

import pytest

from cocomelon.evaluation.mainnet_evidence import verify_mainnet_evidence_cohort_payload
from cocomelon.evidence.bundle import resolve_code_revision
from cocomelon.evidence.recording import load_recording_session
from cocomelon.replay.source import validate_recording
from cocomelon.research.artifact import verify_research_batch_artifact
from tests.test_evidence_bridge_pipeline import _recording

cohort_module = import_module("cocomelon.research.cohort")
build_research_cohort = cohort_module.build_research_cohort


def _rewrite_session_revision(root: Path) -> object:
    session = load_recording_session(root)
    assert session is not None
    revision = resolve_code_revision(None, cwd=Path.cwd())
    revised = replace(session, recorder_code_revision=revision)
    payload = {
        "api_url": revised.api_url,
        "recorder_code_revision": revised.recorder_code_revision,
        "recording_config_digest": revised.recording_config_digest,
        "schema_version": revised.schema_version,
        "selected": [
            {
                "feature_snapshot_id": item.feature_snapshot_id,
                "market": item.market.canonical,
                "rank": item.rank,
                "score": str(item.score),
            }
            for item in revised.selected
        ],
        "selection_policy_id": revised.selection_policy_id,
        "session_id": revised.session_id,
        "started_at_ms": revised.started_at_ms,
        "ws_url": revised.ws_url,
    }
    (root / "recording-session.json").write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return revised


def _cohort_roots(tmp_path: Path) -> tuple[Path, Path, object]:
    root = tmp_path / "cohort"
    recording_root = root / "recording"
    output_root = root / "output"
    _recording(recording_root)
    session = _rewrite_session_revision(recording_root)
    output_root.mkdir(parents=True)
    segments = validate_recording(recording_root)
    event_count = sum(segment.row_count for segment in segments)
    transport = {
        "anomaly_count": 0,
        "duplicate_count": 0,
        "duration_seconds": 3_600,
        "event_count": event_count,
        "gap_count": 0,
        "live_orders": False,
        "network_access": True,
        "reconnect_count": 0,
        "root": str(recording_root),
        "selected_markets": [item.market.canonical for item in session.selected],
        "session_id": session.session_id,
    }
    (output_root / "record-transport.json").write_text(
        json.dumps(transport, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return recording_root, output_root, session


def test_builder_emits_verified_genuine_mainnet_research_cohort(tmp_path: Path) -> None:
    recording_root, output_root, _ = _cohort_roots(tmp_path)
    segments = validate_recording(recording_root)
    expected_start = min(item.first_available_at_ms for item in segments)
    expected_end = max(item.last_available_at_ms for item in segments)

    result = build_research_cohort(
        recording_root,
        output_root,
        Decimal("10000"),
        trigger_head_sha="f" * 40,
    )
    mainnet = verify_mainnet_evidence_cohort_payload(output_root)
    research = verify_research_batch_artifact(
        output_root,
        batch_id="research-cohort-batch",
        source_id="research-cohort-source",
    )
    replay = json.loads((output_root / "replay.json").read_text(encoding="utf-8"))

    assert result.output_root == output_root
    assert result.replay_run_id == mainnet["run_id"] == research.replay_run_id
    assert result.start_ms == mainnet["start_ms"] == research.interval.start_ms == expected_start
    assert result.end_ms == mainnet["end_ms"] == research.interval.end_ms == expected_end
    assert replay["network_access"] is False
    assert replay["live_orders"] is False
    assert mainnet["network_access"] is False
    assert mainnet["live_orders"] is False


def test_builder_requires_authenticated_transport_summary(tmp_path: Path) -> None:
    recording_root, output_root, _ = _cohort_roots(tmp_path)
    (output_root / "record-transport.json").unlink()

    with pytest.raises(ValueError, match="transport"):
        build_research_cohort(
            recording_root,
            output_root,
            Decimal("10000"),
            trigger_head_sha="f" * 40,
        )


def test_builder_fails_closed_when_offline_replay_is_not_flat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recording_root, output_root, _ = _cohort_roots(tmp_path)
    real_runner = cohort_module.run_baseline_replay_payload

    def non_flat_runner(*args: object, **kwargs: object) -> dict[str, object]:
        payload = dict(real_runner(*args, **kwargs))
        payload["opened_positions"] = int(payload["closed_positions"]) + 1
        return payload

    monkeypatch.setattr(cohort_module, "run_baseline_replay_payload", non_flat_runner)

    with pytest.raises(ValueError, match="flat"):
        build_research_cohort(
            recording_root,
            output_root,
            Decimal("10000"),
            trigger_head_sha="f" * 40,
        )


def test_builder_fails_closed_when_offline_replay_is_incomplete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recording_root, output_root, _ = _cohort_roots(tmp_path)
    real_runner = cohort_module.run_baseline_replay_payload

    def incomplete_runner(*args: object, **kwargs: object) -> dict[str, object]:
        payload = dict(real_runner(*args, **kwargs))
        payload["data_complete"] = False
        return payload

    monkeypatch.setattr(cohort_module, "run_baseline_replay_payload", incomplete_runner)

    with pytest.raises(ValueError, match="complete"):
        build_research_cohort(
            recording_root,
            output_root,
            Decimal("10000"),
            trigger_head_sha="f" * 40,
        )
