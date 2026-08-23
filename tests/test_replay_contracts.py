from pathlib import PurePosixPath

import pytest

from cocomelon.domain.replay import (
    EvidenceClass,
    ReplayInputFile,
    ReplayManifest,
    SourceCoordinate,
)


def test_source_coordinates_sort_by_path_segment_and_line() -> None:
    rows = [
        SourceCoordinate("events/2026-08-23/trade/SOL/segment-000002.jsonl", 2, 1),
        SourceCoordinate("events/2026-08-23/trade/SOL/segment-000001.jsonl", 1, 9),
        SourceCoordinate("events/2026-08-23/l2_book/SOL/segment-000001.jsonl", 1, 2),
    ]

    assert sorted(rows) == [rows[2], rows[1], rows[0]]


def test_replay_manifest_run_id_is_stable_across_input_enumeration_order() -> None:
    files = (
        ReplayInputFile("events/a/segment-000001.jsonl", 10, "a" * 64, 1),
        ReplayInputFile("events/b/segment-000001.jsonl", 20, "b" * 64, 1),
    )
    first = ReplayManifest.create(
        code_version="abc123",
        python_version="3.12.14",
        config_sha256="c" * 64,
        strategy_version="phase5-v1",
        risk_version="phase6-v1",
        execution_version="phase7-v1",
        journal_schema_version=1,
        replay_engine_version="phase8-v1",
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        inputs=files,
        start_receive_ms=1_000,
        end_receive_ms=2_000,
    )
    second = ReplayManifest.create(
        code_version="abc123",
        python_version="3.12.14",
        config_sha256="c" * 64,
        strategy_version="phase5-v1",
        risk_version="phase6-v1",
        execution_version="phase7-v1",
        journal_schema_version=1,
        replay_engine_version="phase8-v1",
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        inputs=tuple(reversed(files)),
        start_receive_ms=1_000,
        end_receive_ms=2_000,
    )

    assert first.run_id == second.run_id
    assert first.inputs == second.inputs


def test_replay_manifest_changes_identity_when_evidence_class_changes() -> None:
    common = dict(
        code_version="abc123",
        python_version="3.12.14",
        config_sha256="c" * 64,
        strategy_version="phase5-v1",
        risk_version="phase6-v1",
        execution_version="phase7-v1",
        journal_schema_version=1,
        replay_engine_version="phase8-v1",
        inputs=(ReplayInputFile("events/a/segment-000001.jsonl", 10, "a" * 64, 1),),
        start_receive_ms=1_000,
        end_receive_ms=2_000,
    )

    candle = ReplayManifest.create(evidence_class=EvidenceClass.CANDLE_CONTEXT, **common)
    micro = ReplayManifest.create(evidence_class=EvidenceClass.MICROSTRUCTURE, **common)

    assert candle.run_id != micro.run_id


def test_replay_input_file_rejects_absolute_or_parent_paths() -> None:
    with pytest.raises(ValueError, match="relative"):
        ReplayInputFile("/tmp/segment-000001.jsonl", 10, "a" * 64, 1)
    with pytest.raises(ValueError, match="parent"):
        ReplayInputFile("../segment-000001.jsonl", 10, "a" * 64, 1)
    assert PurePosixPath("events/a/segment-000001.jsonl").is_absolute() is False


def test_replay_manifest_rejects_inverted_receive_window() -> None:
    with pytest.raises(ValueError, match="end_receive_ms"):
        ReplayManifest.create(
            code_version="abc123",
            python_version="3.12.14",
            config_sha256="c" * 64,
            strategy_version="phase5-v1",
            risk_version="phase6-v1",
            execution_version="phase7-v1",
            journal_schema_version=1,
            replay_engine_version="phase8-v1",
            evidence_class=EvidenceClass.CANDLE_CONTEXT,
            inputs=(ReplayInputFile("events/a/segment-000001.jsonl", 10, "a" * 64, 1),),
            start_receive_ms=2_000,
            end_receive_ms=1_000,
        )
