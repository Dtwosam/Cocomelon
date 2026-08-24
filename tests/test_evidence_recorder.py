from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from importlib import import_module
from pathlib import Path

import pytest

from cocomelon.domain.market import (
    Candle,
    FundingRate,
    MarketId,
    PerpMarketContext,
    PerpMarketMeta,
    PerpMarketSnapshot,
)
from cocomelon.domain.replay import EvidenceClass, ReplayManifest
from cocomelon.recorder import DurableRecorder
from cocomelon.replay.source import (
    JsonlReplaySource,
    RecordingValidationError,
    validate_recording,
)

MARKET = MarketId("", "BTC")
RECEIVED_MS = 1_787_573_000_123
RECEIVED = datetime.fromtimestamp(RECEIVED_MS / 1000, tz=UTC)


def _snapshot() -> PerpMarketSnapshot:
    return PerpMarketSnapshot(
        meta=PerpMarketMeta(
            market=MARKET,
            wire_name="BTC",
            sz_decimals=5,
            max_leverage=40,
            margin_table_id=7,
            only_isolated=False,
            is_delisted=False,
            margin_mode=None,
        ),
        context=PerpMarketContext(
            market=MARKET,
            mark_px=Decimal("64000.25"),
            mid_px=Decimal("64000.50"),
            oracle_px=Decimal("63998.75"),
            funding=Decimal("0.0000125"),
            open_interest=Decimal("12345.678"),
            day_ntl_vlm=Decimal("987654321.25"),
            premium=Decimal("0.00002"),
            prev_day_px=Decimal("63000"),
        ),
        source="hyperliquid-mainnet-info",
        received_at_ms=RECEIVED_MS,
        schema_version=1,
    )


def _funding() -> FundingRate:
    return FundingRate(
        market=MARKET,
        time_ms=RECEIVED_MS - 3_600_000,
        funding_rate=Decimal("0.0000125"),
        premium=Decimal("0.00002"),
        source="hyperliquid-mainnet-info",
        received_at_ms=RECEIVED_MS,
        schema_version=1,
    )


def _candle() -> Candle:
    start_ms = RECEIVED_MS - 86_400_000
    return Candle(
        market=MARKET,
        interval="15m",
        start_ms=start_ms,
        end_ms=start_ms + 900_000,
        open_px=Decimal("62000"),
        high_px=Decimal("62500"),
        low_px=Decimal("61800"),
        close_px=Decimal("62300"),
        volume=Decimal("123.45"),
        trade_count=4321,
        source="hyperliquid-mainnet-info",
        received_at_ms=RECEIVED_MS,
        schema_version=1,
    )


def _manifest(root: Path) -> ReplayManifest:
    return ReplayManifest(
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        start_ms=RECEIVED_MS - 1,
        end_ms=RECEIVED_MS + 1,
        segments=validate_recording(root),
        gap_refs=(),
        code_revision="phase9-evidence-test",
        config_digest="c" * 64,
        feature_version="phase4-v1",
        strategy_version="phase5-v1",
        risk_version="phase6-v1",
        execution_config_version="phase7-v1",
        fee_schedule_id="fees-v1",
        replay_engine_version="phase8-v1",
        dataset_manifest_id=None,
    )


def _recording_module():
    return import_module("cocomelon.evidence.recording")


def test_rest_codecs_preserve_exact_payload_and_receive_provenance() -> None:
    recording = _recording_module()

    snapshot_event = recording.market_snapshot_record_event(_snapshot())
    funding_event = recording.funding_rate_record_event(_funding())
    candle_event = recording.candle_record_event(_candle())

    assert snapshot_event.kind == "market_snapshot"
    assert snapshot_event.market == MARKET
    assert snapshot_event.receive_time == RECEIVED
    assert snapshot_event.exchange_time_ms is None
    assert snapshot_event.payload["meta"] == {
        "wire_name": "BTC",
        "sz_decimals": 5,
        "max_leverage": 40,
        "margin_table_id": 7,
        "only_isolated": False,
        "is_delisted": False,
        "margin_mode": None,
    }
    assert snapshot_event.payload["context"] == {
        "mark_px": Decimal("64000.25"),
        "mid_px": Decimal("64000.50"),
        "oracle_px": Decimal("63998.75"),
        "funding": Decimal("0.0000125"),
        "open_interest": Decimal("12345.678"),
        "day_ntl_vlm": Decimal("987654321.25"),
        "premium": Decimal("0.00002"),
        "prev_day_px": Decimal("63000"),
    }

    assert funding_event.kind == "funding_rate"
    assert funding_event.exchange_time_ms == _funding().time_ms
    assert funding_event.receive_time == RECEIVED
    assert funding_event.payload == {
        "time_ms": _funding().time_ms,
        "funding_rate": Decimal("0.0000125"),
        "premium": Decimal("0.00002"),
    }

    assert candle_event.kind == "candle"
    assert candle_event.exchange_time_ms == _candle().start_ms
    assert candle_event.receive_time == RECEIVED
    assert candle_event.receive_time.timestamp() * 1000 == pytest.approx(RECEIVED_MS)
    assert candle_event.payload["end_ms"] == _candle().end_ms
    assert candle_event.payload["interval"] == "15m"


def test_durable_recorder_appends_rest_rows_that_phase8_validator_replays(tmp_path: Path) -> None:
    recorder = DurableRecorder(tmp_path, max_records=1)

    snapshot_path = recorder.append_market_snapshot(_snapshot())
    funding_path = recorder.append_funding_rate(_funding())
    candle_path = recorder.append_candle(_candle())

    assert "market_snapshot" in snapshot_path.as_posix()
    assert "funding_rate" in funding_path.as_posix()
    assert "/candle/" in candle_path.as_posix()

    segments = validate_recording(tmp_path)
    assert len(segments) == 3
    records = tuple(JsonlReplaySource(tmp_path).iter_records(_manifest(tmp_path)))
    assert {record.event_kind for record in records} == {
        "market_snapshot",
        "funding_rate",
        "candle",
    }
    assert all(record.available_at_ms == RECEIVED_MS for record in records)

    candle_row = json.loads(candle_path.read_text(encoding="utf-8"))
    assert candle_row["receive_time"] == RECEIVED.isoformat().replace("+00:00", "Z")
    assert candle_row["exchange_time_ms"] == _candle().start_ms
    assert candle_row["payload"]["open_px"] == "62000"


def test_duplicate_rest_funding_receive_provenance_is_detected(tmp_path: Path) -> None:
    recorder = DurableRecorder(tmp_path, max_records=1)
    recorder.append_funding_rate(_funding())
    recorder.append_funding_rate(_funding())

    with pytest.raises(RecordingValidationError, match="duplicate event_key"):
        validate_recording(tmp_path)
