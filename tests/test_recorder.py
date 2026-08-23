import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from cocomelon.domain.market import MarketId
from cocomelon.domain.stream import DataGap, StreamEvent, StreamKind
from cocomelon.recorder import DurableRecorder

RECEIVED = datetime(2026, 8, 23, 14, 30, tzinfo=UTC)


def event(*, market: str = "xyz:NVDA", key: str = "trade:1") -> StreamEvent:
    if ":" in market:
        dex = market.split(":", 1)[0]
        market_id = MarketId.from_wire_name(dex, market)
    else:
        market_id = MarketId.from_wire_name("", market)
    return StreamEvent(
        kind=StreamKind.TRADE,
        market=market_id,
        exchange_time_ms=1_787_500_000_000,
        receive_time=RECEIVED,
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key=key,
        payload={
            "price": Decimal("100.50"),
            "observed_at": RECEIVED,
            "levels": ({"px": Decimal("99.90")},),
        },
    )


def test_append_event_persists_deterministic_windows_safe_partition(tmp_path) -> None:
    recorder = DurableRecorder(tmp_path)

    path = recorder.append_event(event())

    assert path.relative_to(tmp_path).as_posix() == (
        "events/2026-08-23/trade/xyz%3ANVDA/segment-000001.jsonl"
    )
    rows = path.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1
    row = json.loads(rows[0])
    assert row["record_type"] == "normalized_event"
    assert row["market"] == "xyz:NVDA"
    assert row["receive_time"] == "2026-08-23T14:30:00Z"
    assert row["payload"]["price"] == "100.50"
    assert row["payload"]["observed_at"] == "2026-08-23T14:30:00Z"
    assert row["payload"]["levels"] == [{"px": "99.90"}]


def test_rotation_by_record_count_is_deterministic(tmp_path) -> None:
    recorder = DurableRecorder(tmp_path, max_records=1)

    first = recorder.append_event(event(key="trade:1"))
    second = recorder.append_event(event(key="trade:2"))

    assert first.name == "segment-000001.jsonl"
    assert second.name == "segment-000002.jsonl"
    assert first.read_text(encoding="utf-8").count("\n") == 1
    assert second.read_text(encoding="utf-8").count("\n") == 1


def test_rotation_by_max_bytes_never_splits_a_record(tmp_path) -> None:
    recorder = DurableRecorder(tmp_path, max_bytes=1)

    first = recorder.append_event(event(key="trade:1"))
    second = recorder.append_event(event(key="trade:2"))

    assert first.name == "segment-000001.jsonl"
    assert second.name == "segment-000002.jsonl"


def test_reopen_advances_to_next_safe_segment_without_truncating(tmp_path) -> None:
    first_recorder = DurableRecorder(tmp_path)
    first = first_recorder.append_event(event(key="trade:1"))
    before = first.read_bytes()

    second_recorder = DurableRecorder(tmp_path)
    second = second_recorder.append_event(event(key="trade:2"))

    assert second.name == "segment-000002.jsonl"
    assert first.read_bytes() == before
    assert json.loads(first.read_text(encoding="utf-8"))["event_key"] == "trade:1"
    assert json.loads(second.read_text(encoding="utf-8"))["event_key"] == "trade:2"


def test_gap_records_are_separate_and_preserve_provenance(tmp_path) -> None:
    recorder = DurableRecorder(tmp_path)
    started = int(datetime(2026, 8, 23, 14, 0, tzinfo=UTC).timestamp() * 1000)

    path = recorder.append_gap(
        DataGap(
            stream_id="trades:BTC",
            started_ms=started,
            ended_ms=started + 2000,
            reason="disconnect",
        )
    )

    assert path.relative_to(tmp_path).as_posix() == "gaps/2026-08-23/segment-000001.jsonl"
    row = json.loads(path.read_text(encoding="utf-8"))
    assert row == {
        "ended_ms": started + 2000,
        "reason": "disconnect",
        "record_type": "data_gap",
        "schema_version": 1,
        "source": "hyperliquid-mainnet-ws",
        "started_ms": started,
        "stream_id": "trades:BTC",
    }


def test_manifest_is_replaced_atomically_and_tracks_segment_state(tmp_path) -> None:
    recorder = DurableRecorder(tmp_path)
    recorder.append_event(event())

    manifest = tmp_path / "manifest.json"
    temp_manifest = tmp_path / "manifest.json.tmp"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    partition = payload["partitions"]["events/2026-08-23/trade/xyz%3ANVDA"]

    assert temp_manifest.exists() is False
    assert payload["schema_version"] == 1
    assert partition["segment"] == 1
    assert partition["records"] == 1
    assert partition["bytes"] > 0


def test_write_failure_is_surfaced(tmp_path) -> None:
    recorder = DurableRecorder(tmp_path)
    (tmp_path / "events").write_text("blocks directory creation", encoding="utf-8")

    with pytest.raises(OSError):
        recorder.append_event(event())
