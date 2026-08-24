from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
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
from cocomelon.domain.replay import ReplayRecord, SourceRecordKind
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.evidence.baseline import (
    RecordedStateBook,
    replay_record_candle,
    replay_record_funding_rate,
    replay_record_market_snapshot,
    replay_record_stream_event,
)
from cocomelon.evidence.bundle import freeze_baseline_replay_bundle
from cocomelon.evidence.contracts import (
    BaselineReplayConfig,
    EvidenceRecordingConfig,
    EvidenceRecordingSession,
    SelectedEvidenceMarket,
)
from cocomelon.evidence.recording import write_recording_session
from cocomelon.recorder import DurableRecorder
from cocomelon.replay.clock import canonical_record_order
from cocomelon.replay.source import JsonlReplaySource

MARKET = MarketId("", "SOL")
RECEIVE_TIME = datetime(2026, 8, 24, 14, 30, tzinfo=UTC)
RECEIVE_MS = int(RECEIVE_TIME.timestamp() * 1000)


def _snapshot(received_at_ms: int = RECEIVE_MS) -> PerpMarketSnapshot:
    return PerpMarketSnapshot(
        meta=PerpMarketMeta(
            market=MARKET,
            wire_name="SOL",
            sz_decimals=3,
            max_leverage=20,
            margin_table_id=None,
            only_isolated=False,
            is_delisted=False,
            margin_mode=None,
        ),
        context=PerpMarketContext(
            market=MARKET,
            mark_px=Decimal("180"),
            mid_px=Decimal("180.1"),
            oracle_px=Decimal("179.9"),
            funding=Decimal("0.00001"),
            open_interest=Decimal("100000"),
            day_ntl_vlm=Decimal("500000000"),
            premium=Decimal("0.0002"),
            prev_day_px=Decimal("178"),
        ),
        source="hyperliquid-mainnet-info",
        received_at_ms=received_at_ms,
        schema_version=1,
    )


def _candle(received_at_ms: int = RECEIVE_MS + 10) -> Candle:
    return Candle(
        market=MARKET,
        interval="15m",
        start_ms=RECEIVE_MS - 900_000,
        end_ms=RECEIVE_MS,
        open_px=Decimal("178"),
        high_px=Decimal("181"),
        low_px=Decimal("177"),
        close_px=Decimal("180"),
        volume=Decimal("12345.6"),
        trade_count=4321,
        source="hyperliquid-mainnet-info",
        received_at_ms=received_at_ms,
        schema_version=1,
    )


def _funding(received_at_ms: int = RECEIVE_MS + 20) -> FundingRate:
    return FundingRate(
        market=MARKET,
        time_ms=RECEIVE_MS - 3_600_000,
        funding_rate=Decimal("0.0000125"),
        premium=Decimal("0.0001"),
        source="hyperliquid-mainnet-info",
        received_at_ms=received_at_ms,
        schema_version=1,
    )


def _session(root: Path) -> EvidenceRecordingSession:
    config = EvidenceRecordingConfig(duration_seconds=3_600, deep_limit=1)
    session = EvidenceRecordingSession(
        started_at_ms=RECEIVE_MS - 60_000,
        recorder_code_revision="a" * 40,
        selected=(
            SelectedEvidenceMarket(
                market=MARKET,
                rank=1,
                feature_snapshot_id="feature-sol",
                score=Decimal("75"),
            ),
        ),
        recording_config_digest=config.config_digest,
        api_url=config.api_url,
        ws_url=config.ws_url,
        selection_policy_id=config.selection_policy_id,
    )
    write_recording_session(root, session)
    return session


def test_decoders_round_trip_recorder_rows_with_exact_receive_availability(
    tmp_path: Path,
) -> None:
    root = tmp_path / "recording"
    _session(root)
    recorder = DurableRecorder(root)
    snapshot = _snapshot()
    candle = _candle()
    funding = _funding()
    book = StreamEvent(
        kind=StreamKind.L2_BOOK,
        market=MARKET,
        exchange_time_ms=RECEIVE_MS - 5,
        receive_time=datetime.fromtimestamp((RECEIVE_MS + 30) / 1000, tz=UTC),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key="book-sol-1",
        payload={
            "bids": ({"px": Decimal("179.5"), "sz": Decimal("10"), "n": 3},),
            "asks": ({"px": Decimal("180.5"), "sz": Decimal("11"), "n": 4},),
        },
    )
    active_ctx = StreamEvent(
        kind=StreamKind.ACTIVE_ASSET_CTX,
        market=MARKET,
        exchange_time_ms=None,
        receive_time=datetime.fromtimestamp((RECEIVE_MS + 40) / 1000, tz=UTC),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key="ctx-sol-1",
        payload={
            "mark_px": Decimal("180.2"),
            "mid_px": Decimal("180.25"),
            "oracle_px": Decimal("180.1"),
            "funding": Decimal("0.00002"),
            "open_interest": Decimal("100100"),
        },
    )

    recorder.append_market_snapshot(snapshot)
    recorder.append_candle(candle)
    recorder.append_funding_rate(funding)
    recorder.append_event(book)
    recorder.append_event(active_ctx)
    bundle = freeze_baseline_replay_bundle(
        root,
        replay_config=BaselineReplayConfig(),
        code_revision="b" * 40,
    )
    records = canonical_record_order(tuple(JsonlReplaySource(root).iter_records(bundle.manifest)))
    by_kind = {record.event_kind: record for record in records if record.event_kind is not None}

    assert replay_record_market_snapshot(by_kind["market_snapshot"]) == snapshot
    assert replay_record_candle(by_kind["candle"]) == candle
    assert replay_record_funding_rate(by_kind["funding_rate"]) == funding
    assert replay_record_stream_event(by_kind["l2_book"]) == book
    assert replay_record_stream_event(by_kind["active_asset_ctx"]) == active_ctx
    assert by_kind["market_snapshot"].available_at_ms == snapshot.received_at_ms
    assert by_kind["candle"].available_at_ms == candle.received_at_ms
    assert by_kind["funding_rate"].available_at_ms == funding.received_at_ms


def _record(
    *,
    kind: str,
    available_at_ms: int,
    payload: dict[str, object],
    exchange_time_ms: int | None = None,
    key: str | None = None,
) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=available_at_ms,
        source=(
            "hyperliquid-mainnet-info"
            if kind in {"market_snapshot", "funding_rate"}
            else "hyperliquid-mainnet-ws"
        ),
        schema_version=1,
        market="SOL",
        exchange_time_ms=exchange_time_ms,
        event_key=key or f"{kind}:{available_at_ms}",
        payload_json=json.dumps(payload),
        event_kind=kind,
    )


def _candle_record(available_at_ms: int, close_px: str) -> ReplayRecord:
    return _record(
        kind="candle",
        available_at_ms=available_at_ms,
        exchange_time_ms=0,
        payload={
            "start_ms": 0,
            "end_ms": 900_000,
            "interval": "15m",
            "open_px": "100",
            "high_px": "102",
            "low_px": "98",
            "close_px": close_px,
            "volume": "1000",
            "trade_count": 100,
        },
    )


def _snapshot_record(available_at_ms: int) -> ReplayRecord:
    return _record(
        kind="market_snapshot",
        available_at_ms=available_at_ms,
        payload={
            "meta": {
                "wire_name": "SOL",
                "sz_decimals": 3,
                "max_leverage": 20,
                "margin_table_id": None,
                "only_isolated": False,
                "is_delisted": False,
                "margin_mode": None,
            },
            "context": {
                "mark_px": "100",
                "mid_px": "100.1",
                "oracle_px": "99.9",
                "funding": "0.00001",
                "open_interest": "100000",
                "day_ntl_vlm": "500000000",
                "premium": "0.0001",
                "prev_day_px": "98",
            },
        },
    )


def test_state_replaces_only_with_later_evidence_and_does_not_fabricate_full_context() -> None:
    book = RecordedStateBook(microstructure_window_ms=60_000)
    book.apply(_candle_record(1_000, "100"), now_ms=1_000)
    book.apply(_candle_record(2_000, "101"), now_ms=2_000)
    book.apply(_candle_record(1_500, "99"), now_ms=2_500)
    book.apply(_snapshot_record(3_000), now_ms=3_000)
    book.apply(
        _record(
            kind="active_asset_ctx",
            available_at_ms=4_000,
            payload={
                "mark_px": "110",
                "mid_px": "110.1",
                "oracle_px": "109.9",
                "funding": "0.00002",
                "open_interest": "110000",
            },
        ),
        now_ms=4_000,
    )

    state = book.state(MARKET)
    assert state.candles_15m[0].close_px == Decimal("101")
    assert state.latest_snapshot is not None
    assert state.latest_snapshot.context.mark_px == Decimal("100")
    assert state.latest_snapshot.context.day_ntl_vlm == Decimal("500000000")
    assert state.latest_snapshot.context.prev_day_px == Decimal("98")
    assert state.latest_asset_ctx is not None
    assert state.latest_asset_ctx.payload["mark_px"] == Decimal("110")


def test_state_rejects_future_evidence_and_prunes_micro_events_by_replay_clock() -> None:
    book = RecordedStateBook(microstructure_window_ms=60_000)
    first_trade = _record(
        kind="trade",
        available_at_ms=1_000,
        exchange_time_ms=900,
        payload={
            "side": "B",
            "price": "100",
            "size": "1",
            "hash": "0x1",
            "tid": 1,
            "users": ["0xa", "0xb"],
        },
    )
    l2 = _record(
        kind="l2_book",
        available_at_ms=30_000,
        exchange_time_ms=29_900,
        payload={
            "bids": [{"px": "99", "sz": "2", "n": 1}],
            "asks": [{"px": "101", "sz": "2", "n": 1}],
        },
    )
    latest_trade = _record(
        kind="trade",
        available_at_ms=70_000,
        exchange_time_ms=69_900,
        payload={
            "side": "A",
            "price": "101",
            "size": "1.5",
            "hash": "0x2",
            "tid": 2,
            "users": ["0xc", "0xd"],
        },
    )

    with pytest.raises(ValueError, match="future"):
        book.apply(first_trade, now_ms=999)

    book.apply(first_trade, now_ms=1_000)
    book.apply(l2, now_ms=30_000)
    book.apply(latest_trade, now_ms=70_000)

    state = book.state(MARKET)
    assert tuple(event.event_key for event in state.micro_events) == (
        l2.event_key,
        latest_trade.event_key,
    )
    assert state.latest_book is not None
    assert state.latest_book.event_key == l2.event_key
