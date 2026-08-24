from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.stream import DataGap, StreamEvent, StreamKind
from cocomelon.evidence.bundle import (
    freeze_baseline_replay_bundle,
    load_baseline_replay_bundle,
    resolve_code_revision,
    write_baseline_replay_bundle,
)
from cocomelon.evidence.contracts import (
    BaselineReplayConfig,
    EvidenceRecordingConfig,
    EvidenceRecordingSession,
    SelectedEvidenceMarket,
    baseline_manifest_config_digest,
)
from cocomelon.evidence.recording import write_recording_session
from cocomelon.recorder import DurableRecorder
from cocomelon.replay.source import validate_recording

MARKET = MarketId("", "SOL")
RECEIVE_TIME = datetime(2026, 8, 24, 14, 30, tzinfo=UTC)
RECEIVE_MS = int(RECEIVE_TIME.timestamp() * 1000)


def _source_set_digest(root: Path) -> str:
    segments = validate_recording(root)
    encoded = json.dumps(
        [segment.canonical_payload() for segment in segments],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _recording(
    root: Path,
    *,
    session_revision: str = "a" * 40,
    bid_px: str = "179.5",
) -> EvidenceRecordingSession:
    recording_config = EvidenceRecordingConfig(duration_seconds=3_600, deep_limit=1)
    session = EvidenceRecordingSession(
        started_at_ms=RECEIVE_MS - 60_000,
        recorder_code_revision=session_revision,
        selected=(
            SelectedEvidenceMarket(
                market=MARKET,
                rank=1,
                feature_snapshot_id="feature-sol",
                score=Decimal("75"),
            ),
        ),
        recording_config_digest=recording_config.config_digest,
        api_url=recording_config.api_url,
        ws_url=recording_config.ws_url,
        selection_policy_id=recording_config.selection_policy_id,
    )
    write_recording_session(root, session)
    recorder = DurableRecorder(root)
    recorder.append_event(
        StreamEvent(
            kind=StreamKind.L2_BOOK,
            market=MARKET,
            exchange_time_ms=RECEIVE_MS - 10,
            receive_time=RECEIVE_TIME,
            schema_version=1,
            source="hyperliquid-mainnet-ws",
            event_key=f"l2:SOL:{bid_px}",
            payload={
                "levels": [
                    [{"px": bid_px, "sz": "10", "n": 3}],
                    [{"px": "180.5", "sz": "11", "n": 4}],
                ]
            },
        )
    )
    recorder.append_gap(
        DataGap(
            stream_id="l2Book:SOL",
            started_ms=RECEIVE_MS + 1_000,
            ended_ms=RECEIVE_MS + 2_000,
            reason="disconnect",
        )
    )
    return session


def test_freeze_binds_all_sources_session_config_and_real_gap_refs(tmp_path: Path) -> None:
    root = tmp_path / "recording"
    session = _recording(root)
    replay_config = BaselineReplayConfig()

    bundle = freeze_baseline_replay_bundle(
        root,
        replay_config=replay_config,
        code_revision="b" * 40,
    )

    segments = validate_recording(root)
    assert bundle.manifest.evidence_class is EvidenceClass.MICROSTRUCTURE
    assert bundle.manifest.segments == segments
    assert bundle.source_set_digest == _source_set_digest(root)
    assert bundle.recording_session_digest == session.session_id
    assert bundle.manifest.config_digest == baseline_manifest_config_digest(
        replay_config,
        session.session_id,
    )
    assert bundle.manifest.execution_config_version == replay_config.execution.config_version
    assert bundle.manifest.fee_schedule_id == replay_config.execution.fee_schedule_id
    assert bundle.manifest.start_ms == min(item.first_available_at_ms for item in segments)
    assert bundle.manifest.end_ms == max(item.last_available_at_ms for item in segments)
    assert bundle.manifest.gap_refs == (
        f"gap:l2Book:SOL:{RECEIVE_MS + 1_000}:{RECEIVE_MS + 2_000}:disconnect",
    )


def test_bundle_atomic_round_trip_rejects_serialized_tampering(tmp_path: Path) -> None:
    root = tmp_path / "recording"
    _recording(root)
    bundle = freeze_baseline_replay_bundle(
        root,
        replay_config=BaselineReplayConfig(),
        code_revision="b" * 40,
    )
    path = tmp_path / "bundle.json"

    write_baseline_replay_bundle(path, bundle)
    assert load_baseline_replay_bundle(path) == bundle

    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["source_set_digest"] = "f" * 64
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="bundle_id"):
        load_baseline_replay_bundle(path)


def test_bundle_identity_changes_with_source_session_or_replay_config(tmp_path: Path) -> None:
    first_root = tmp_path / "first"
    first_session = _recording(first_root, bid_px="179.5")
    base_config = BaselineReplayConfig()
    first = freeze_baseline_replay_bundle(
        first_root,
        replay_config=base_config,
        code_revision="b" * 40,
    )

    changed_source_root = tmp_path / "changed-source"
    _recording(changed_source_root, bid_px="179.4")
    changed_source = freeze_baseline_replay_bundle(
        changed_source_root,
        replay_config=base_config,
        code_revision="b" * 40,
    )

    changed_session_root = tmp_path / "changed-session"
    changed_session_meta = _recording(
        changed_session_root,
        session_revision="c" * 40,
        bid_px="179.5",
    )
    changed_session = freeze_baseline_replay_bundle(
        changed_session_root,
        replay_config=base_config,
        code_revision="b" * 40,
    )

    changed_config = freeze_baseline_replay_bundle(
        first_root,
        replay_config=replace(base_config, decision_grace_ms=31_000),
        code_revision="b" * 40,
    )

    assert changed_source.source_set_digest != first.source_set_digest
    assert changed_source.bundle_id != first.bundle_id
    assert changed_session_meta.session_id != first_session.session_id
    assert changed_session.bundle_id != first.bundle_id
    assert changed_config.manifest.config_digest != first.manifest.config_digest
    assert changed_config.bundle_id != first.bundle_id


def test_resolve_code_revision_prefers_explicit_and_fails_without_git(tmp_path: Path) -> None:
    assert resolve_code_revision("d" * 40, cwd=tmp_path) == "d" * 40
    with pytest.raises(RuntimeError, match="code revision"):
        resolve_code_revision(None, cwd=tmp_path)
