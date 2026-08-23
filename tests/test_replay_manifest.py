import json
from pathlib import Path

import pytest
from cocomelon.replay.manifest import (
    ReplayInputMismatchError,
    build_replay_manifest,
    verify_replay_inputs,
)

from cocomelon.domain.replay import EvidenceClass
from cocomelon.replay.jsonl import validate_jsonl_segment


def write_event(path: Path, *, event_key: str, receive_time: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "record_type": "normalized_event",
        "schema_version": 1,
        "source": "hyperliquid-mainnet-ws",
        "kind": "trade",
        "market": "SOL",
        "exchange_time_ms": 1_000,
        "receive_time": receive_time,
        "event_key": event_key,
        "payload": {"price": "100", "size": "1"},
    }
    path.write_text(json.dumps(row, separators=(",", ":")) + "\n", encoding="utf-8")


def validated_pair(tmp_path: Path):
    root = tmp_path / "recordings"
    first_path = root / "events/a/segment-000001.jsonl"
    second_path = root / "events/b/segment-000002.jsonl"
    write_event(first_path, event_key="trade:1", receive_time="2026-08-23T00:00:01Z")
    write_event(second_path, event_key="trade:2", receive_time="2026-08-23T00:00:02Z")
    first = validate_jsonl_segment(
        first_path,
        root=root,
        evidence_class=EvidenceClass.MICROSTRUCTURE,
    )
    second = validate_jsonl_segment(
        second_path,
        root=root,
        evidence_class=EvidenceClass.MICROSTRUCTURE,
    )
    return root, first, second


def manifest_for(segments):
    return build_replay_manifest(
        segments,
        code_version="abc123",
        python_version="3.12.14",
        config_sha256="c" * 64,
        strategy_version="phase5-v1",
        risk_version="phase6-v1",
        execution_version="phase7-v1",
        journal_schema_version=1,
        replay_engine_version="phase8-v1",
        evidence_class=EvidenceClass.MICROSTRUCTURE,
    )


def test_manifest_identity_is_stable_across_segment_enumeration_order(tmp_path: Path) -> None:
    _, first, second = validated_pair(tmp_path)

    forward = manifest_for([first, second])
    reverse = manifest_for([second, first])

    assert forward.run_id == reverse.run_id
    assert forward.inputs == reverse.inputs
    assert forward.start_receive_ms == 1_787_443_201_000
    assert forward.end_receive_ms == 1_787_443_202_000


def test_manifest_identity_changes_when_code_or_config_changes(tmp_path: Path) -> None:
    _, first, second = validated_pair(tmp_path)
    base = manifest_for([first, second])
    code_changed = build_replay_manifest(
        [first, second],
        code_version="def456",
        python_version="3.12.14",
        config_sha256="c" * 64,
        strategy_version="phase5-v1",
        risk_version="phase6-v1",
        execution_version="phase7-v1",
        journal_schema_version=1,
        replay_engine_version="phase8-v1",
        evidence_class=EvidenceClass.MICROSTRUCTURE,
    )
    config_changed = build_replay_manifest(
        [first, second],
        code_version="abc123",
        python_version="3.12.14",
        config_sha256="d" * 64,
        strategy_version="phase5-v1",
        risk_version="phase6-v1",
        execution_version="phase7-v1",
        journal_schema_version=1,
        replay_engine_version="phase8-v1",
        evidence_class=EvidenceClass.MICROSTRUCTURE,
    )

    assert base.run_id != code_changed.run_id
    assert base.run_id != config_changed.run_id


def test_verify_replay_inputs_rejects_mutated_segment_before_replay(tmp_path: Path) -> None:
    root, first, second = validated_pair(tmp_path)
    manifest = manifest_for([first, second])
    second.path.write_text(second.path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(ReplayInputMismatchError, match="size|sha256"):
        verify_replay_inputs(manifest, root=root)


def test_verify_replay_inputs_returns_validated_segments_in_manifest_order(tmp_path: Path) -> None:
    root, first, second = validated_pair(tmp_path)
    manifest = manifest_for([second, first])

    verified = verify_replay_inputs(manifest, root=root)

    assert tuple(item.input_file for item in verified) == manifest.inputs
    assert all(item.evidence_class is EvidenceClass.MICROSTRUCTURE for item in verified)


def test_manifest_requires_at_least_one_evidence_row(tmp_path: Path) -> None:
    root = tmp_path / "recordings"
    empty_path = root / "events/a/segment-000001.jsonl"
    empty_path.parent.mkdir(parents=True, exist_ok=True)
    empty_path.write_text("", encoding="utf-8")
    empty = validate_jsonl_segment(
        empty_path,
        root=root,
        evidence_class=EvidenceClass.MICROSTRUCTURE,
    )

    with pytest.raises(ValueError, match="evidence row"):
        manifest_for([empty])
