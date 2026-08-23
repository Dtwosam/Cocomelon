import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass, ReplayManifest, SourceRecordKind
from cocomelon.domain.stream import DataGap, StreamEvent, StreamKind
from cocomelon.recorder import DurableRecorder
from cocomelon.replay.source import JsonlReplaySource, RecordingValidationError, validate_recording

RECEIVED = datetime(2026, 8, 23, 14, 30, tzinfo=UTC)
RECEIVED_MS = int(RECEIVED.timestamp() * 1000)
MARKET = MarketId("", "SOL")


def stream_event(kind: StreamKind, key: str, *, receive_time: datetime = RECEIVED) -> StreamEvent:
    if kind is StreamKind.CANDLE:
        payload: dict[str, object] = {
            "start_ms": RECEIVED_MS - 60_000,
            "end_ms": RECEIVED_MS,
            "interval": "1m",
            "open_px": Decimal("100"),
            "close_px": Decimal("101"),
            "high_px": Decimal("102"),
            "low_px": Decimal("99"),
            "volume": Decimal("10"),
            "trade_count": 4,
        }
    elif kind is StreamKind.L2_BOOK:
        payload = {
            "bids": ({"px": Decimal("100"), "sz": Decimal("2"), "n": 1},),
            "asks": ({"px": Decimal("101"), "sz": Decimal("2"), "n": 1},),
        }
    elif kind is StreamKind.ACTIVE_ASSET_CTX:
        payload = {
            "mark_px": Decimal("100.5"),
            "mid_px": Decimal("100.5"),
            "oracle_px": Decimal("100.4"),
            "funding": Decimal("0.00001"),
            "open_interest": Decimal("1000"),
        }
    else:
        payload = {"mid_px": Decimal("100.5")}
    return StreamEvent(
        kind=kind,
        market=MARKET,
        exchange_time_ms=None if kind in {StreamKind.ALL_MIDS, StreamKind.ACTIVE_ASSET_CTX} else RECEIVED_MS,
        receive_time=receive_time,
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key=key,
        payload=payload,
    )


def valid_recording(root: Path) -> None:
    recorder = DurableRecorder(root, max_records=1)
    recorder.append_event(stream_event(StreamKind.CANDLE, "candle:SOL:1"))
    recorder.append_event(stream_event(StreamKind.L2_BOOK, "l2:SOL:1"))
    recorder.append_event(stream_event(StreamKind.ACTIVE_ASSET_CTX, "ctx:SOL:1"))
    recorder.append_gap(
        DataGap(
            stream_id="l2Book:SOL",
            started_ms=RECEIVED_MS,
            ended_ms=RECEIVED_MS + 100,
            reason="disconnect",
        )
    )


def replay_manifest(root: Path, evidence_class: EvidenceClass) -> ReplayManifest:
    return ReplayManifest(
        evidence_class=evidence_class,
        start_ms=RECEIVED_MS - 1,
        end_ms=RECEIVED_MS + 1_000,
        segments=validate_recording(root),
        gap_refs=(),
        code_revision="phase8-test",
        config_digest="c" * 64,
        feature_version="phase4-v1",
        strategy_version="phase5-v1",
        risk_version="phase6-v1",
        execution_config_version=("phase7-v1" if evidence_class is EvidenceClass.MICROSTRUCTURE else None),
        fee_schedule_id=("fees-v1" if evidence_class is EvidenceClass.MICROSTRUCTURE else None),
        replay_engine_version="phase8-v1",
        dataset_manifest_id=None,
    )


def test_validator_hashes_exact_bytes_and_checks_metadata(tmp_path: Path) -> None:
    valid_recording(tmp_path)

    segments = validate_recording(tmp_path)

    assert len(segments) == 4
    for segment in segments:
        raw = (tmp_path / segment.relative_path).read_bytes()
        assert segment.sha256 == hashlib.sha256(raw).hexdigest()
        assert segment.byte_count == len(raw)
        assert segment.row_count == 1
        assert segment.first_available_at_ms <= segment.last_available_at_ms


def test_validator_rejects_truncated_jsonl(tmp_path: Path) -> None:
    valid_recording(tmp_path)
    path = next(tmp_path.glob("events/**/*.jsonl"))
    path.write_bytes(path.read_bytes()[:-2])

    with pytest.raises(RecordingValidationError, match="newline|JSON"):
        validate_recording(tmp_path)


def test_validator_rejects_partition_identity_mismatch(tmp_path: Path) -> None:
    valid_recording(tmp_path)
    path = next(tmp_path.glob("events/**/candle/SOL/*.jsonl"))
    row = json.loads(path.read_text(encoding="utf-8"))
    row["kind"] = "trade"
    path.write_text(json.dumps(row, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(RecordingValidationError, match="partition"):
        validate_recording(tmp_path)


def test_validator_rejects_unsupported_schema_and_duplicate_event_key(tmp_path: Path) -> None:
    recorder = DurableRecorder(tmp_path, max_records=1)
    recorder.append_event(stream_event(StreamKind.CANDLE, "same-key"))
    second = recorder.append_event(stream_event(StreamKind.CANDLE, "same-key"))

    with pytest.raises(RecordingValidationError, match="duplicate event_key"):
        validate_recording(tmp_path)

    row = json.loads(second.read_text(encoding="utf-8"))
    row["event_key"] = "different-key"
    row["schema_version"] = 999
    second.write_text(json.dumps(row, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(RecordingValidationError, match="schema_version"):
        validate_recording(tmp_path)


def test_jsonl_source_rehashes_manifest_segments_before_replay(tmp_path: Path) -> None:
    valid_recording(tmp_path)
    manifest = replay_manifest(tmp_path, EvidenceClass.MICROSTRUCTURE)
    source = JsonlReplaySource(tmp_path)
    first = tmp_path / manifest.segments[0].relative_path
    first.write_bytes(first.read_bytes() + b"\n")

    with pytest.raises(RecordingValidationError, match="sha256"):
        tuple(source.iter_records(manifest))


def test_evidence_class_filters_microstructure_without_fabrication(tmp_path: Path) -> None:
    valid_recording(tmp_path)
    candle_records = tuple(
        JsonlReplaySource(tmp_path).iter_records(
            replay_manifest(tmp_path, EvidenceClass.CANDLE_CONTEXT)
        )
    )
    micro_records = tuple(
        JsonlReplaySource(tmp_path).iter_records(
            replay_manifest(tmp_path, EvidenceClass.MICROSTRUCTURE)
        )
    )

    assert any(item.event_kind == StreamKind.CANDLE.value for item in candle_records)
    assert any(item.event_kind == StreamKind.ACTIVE_ASSET_CTX.value for item in candle_records)
    assert not any(item.event_kind == StreamKind.L2_BOOK.value for item in candle_records)
    assert any(item.event_kind == StreamKind.L2_BOOK.value for item in micro_records)
    assert any(item.record_kind is SourceRecordKind.DATA_GAP for item in micro_records)
    assert all(item.available_at_ms >= RECEIVED_MS for item in micro_records)
