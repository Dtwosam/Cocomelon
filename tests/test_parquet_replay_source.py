from __future__ import annotations

import json
from pathlib import Path

import pytest

from cocomelon.domain.execution import PaperExecutionConfig
from cocomelon.domain.replay import EvidenceClass
from cocomelon.replay.clock import canonical_record_order
from cocomelon.replay.compaction import compact_recording
from cocomelon.replay.manifest import build_replay_manifest
from cocomelon.replay.parquet_source import ParquetReplayError, ParquetReplaySource
from cocomelon.replay.source import JsonlReplaySource, validate_recording


def _write_event(
    root: Path,
    *,
    kind: str,
    event_key: str,
    receive_time: str,
    payload: dict[str, object],
    market: str = "SOL",
    exchange_time_ms: int | None = 1_000,
) -> None:
    path = root / f"events/2026-08-23/{kind}/{market}/segment-000001.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "record_type": "normalized_event",
        "schema_version": 1,
        "source": "hyperliquid-mainnet-ws",
        "kind": kind,
        "market": market,
        "exchange_time_ms": exchange_time_ms,
        "receive_time": receive_time,
        "event_key": event_key,
        "payload": payload,
    }
    path.write_text(
        json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _fixture(tmp_path: Path):
    root = tmp_path / "recordings"
    _write_event(
        root,
        kind="candle",
        event_key="candle:SOL:1m:1000:a",
        receive_time="2026-08-23T00:00:01Z",
        payload={
            "start_ms": 1_000,
            "end_ms": 1_999,
            "interval": "1m",
            "open_px": "100",
            "close_px": "101",
            "high_px": "102",
            "low_px": "99",
            "volume": "5",
            "trade_count": 10,
        },
    )
    _write_event(
        root,
        kind="active_asset_ctx",
        event_key="activeAssetCtx:SOL:a",
        receive_time="2026-08-23T00:00:02Z",
        exchange_time_ms=None,
        payload={
            "mark_px": "101",
            "mid_px": "100.9",
            "oracle_px": "100.8",
            "funding": "0.00001",
            "open_interest": "1000",
        },
    )
    _write_event(
        root,
        kind="l2_book",
        event_key="l2Book:SOL:3000:a",
        receive_time="2026-08-23T00:00:03Z",
        exchange_time_ms=3_000,
        payload={
            "bids": [{"px": "100.9", "sz": "5", "n": 1}],
            "asks": [{"px": "101.1", "sz": "4", "n": 1}],
        },
    )
    _write_event(
        root,
        kind="trade",
        event_key="trades:SOL:4000:1",
        receive_time="2026-08-23T00:00:04Z",
        exchange_time_ms=4_000,
        payload={"side": "B", "price": "101.1", "size": "1", "tid": 1},
    )
    segments = validate_recording(root)
    compaction = compact_recording(root, tmp_path / "datasets", segments)
    replay_manifest = build_replay_manifest(
        segments,
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        start_ms=1_787_443_201_000,
        end_ms=1_787_443_204_000,
        code_revision="phase8-test",
        config_snapshot={"mode": "paper"},
        feature_version="phase4-v1",
        strategy_version="phase5-v1",
        risk_version="phase6-v1",
        execution_config=PaperExecutionConfig(),
        dataset_manifest_id=compaction.dataset_id,
    )
    return root, compaction, replay_manifest


def test_parquet_replay_matches_authoritative_jsonl_canonical_sequence(tmp_path: Path) -> None:
    pytest.importorskip("pyarrow.parquet")
    root, compaction, replay_manifest = _fixture(tmp_path)

    expected = canonical_record_order(tuple(JsonlReplaySource(root).iter_records(replay_manifest)))
    actual = tuple(ParquetReplaySource(compaction.dataset_root, compaction).iter_records(replay_manifest))

    assert actual == expected


def test_parquet_replay_rejects_mutated_output_before_yielding_rows(tmp_path: Path) -> None:
    pytest.importorskip("pyarrow.parquet")
    _, compaction, replay_manifest = _fixture(tmp_path)
    output = compaction.dataset_root / compaction.output_files[0].relative_path
    output.write_bytes(output.read_bytes() + b"corruption")

    source = ParquetReplaySource(compaction.dataset_root, compaction)
    with pytest.raises(ParquetReplayError, match="sha256"):
        tuple(source.iter_records(replay_manifest))


def test_parquet_replay_rejects_wrong_dataset_manifest_identity(tmp_path: Path) -> None:
    pytest.importorskip("pyarrow.parquet")
    _, compaction, replay_manifest = _fixture(tmp_path)
    wrong = build_replay_manifest(
        replay_manifest.segments,
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        start_ms=replay_manifest.start_ms,
        end_ms=replay_manifest.end_ms,
        code_revision="phase8-test",
        config_snapshot={"mode": "paper"},
        feature_version="phase4-v1",
        strategy_version="phase5-v1",
        risk_version="phase6-v1",
        execution_config=PaperExecutionConfig(),
        dataset_manifest_id="different-dataset",
    )

    source = ParquetReplaySource(compaction.dataset_root, compaction)
    with pytest.raises(ParquetReplayError, match="dataset manifest"):
        tuple(source.iter_records(wrong))
