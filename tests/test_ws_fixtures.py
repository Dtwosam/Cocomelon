from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from cocomelon.domain.stream import StreamKind
from cocomelon.hyperliquid.ws_protocol import normalize_ws_message

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "hyperliquid_ws"
RECEIVED = datetime(2026, 8, 23, 16, 10, tzinfo=UTC)
EXPECTED_SHA256 = {
    "all_mids_hip3.json": "e461134887e4eddca47723c53448e965cf7f09045eea25baf6688444369550f6",
    "all_mids_native.json": "2cbef45a82ce2bc9ddeb2eb5aaf0b1a8e048cef872a57429d85f2c510098bd8f",
    "candle_btc_1m.json": "f20e41b78781eaa36c6cf929da58c511951f40b5e83a3a31c8ab9248a5c56873",
    "l2_book_btc.json": "3b4d7c2093438f40725b59f58128339568564ed1c668ad24950850fd9ac8e2ad",
    "l2_book_hip3.json": "31bad51e19de6f2ef06f2137f3947faa73bf49d5a05a2bd35afa6b9afd2e6be7",
    "trades_btc.json": "e669d90d3469f5b5b0431b3e5efdd836b45529b72fa4352a463eaa588373df0f",
}


def fixture(name: str) -> object:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_public_mainnet_fixture_bytes_match_capture_artifact() -> None:
    actual = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in FIXTURE_DIR.glob("*.json")
    }
    assert actual == EXPECTED_SHA256


def test_native_all_mids_fixture_normalizes_btc_and_exotic_market_names() -> None:
    events = normalize_ws_message(fixture("all_mids_native.json"), receive_time=RECEIVED)
    markets = {event.market.canonical for event in events}

    assert events
    assert all(event.kind is StreamKind.ALL_MIDS for event in events)
    assert "BTC" in markets
    assert "PURR/USDC" in markets
    assert any(name.startswith("@") for name in markets)
    assert any(name.startswith("#") for name in markets)


def test_hip3_all_mids_fixture_preserves_dex_identity() -> None:
    raw = fixture("all_mids_hip3.json")
    assert isinstance(raw, dict)
    data = raw["data"]
    assert isinstance(data, dict)
    assert data["dex"] == "xyz"

    events = normalize_ws_message(raw, receive_time=RECEIVED)

    assert events
    assert all(event.kind is StreamKind.ALL_MIDS for event in events)
    assert all(event.market.dex == "xyz" for event in events)
    assert any(event.market.canonical == "xyz:NVDA" for event in events)


def test_btc_l2_fixture_normalizes_full_snapshot() -> None:
    events = normalize_ws_message(fixture("l2_book_btc.json"), receive_time=RECEIVED)

    assert len(events) == 1
    event = events[0]
    assert event.kind is StreamKind.L2_BOOK
    assert event.market.canonical == "BTC"
    assert event.exchange_time_ms is not None
    assert event.payload["bids"]
    assert event.payload["asks"]


def test_hip3_l2_fixture_preserves_prefixed_market() -> None:
    events = normalize_ws_message(fixture("l2_book_hip3.json"), receive_time=RECEIVED)

    assert len(events) == 1
    assert events[0].kind is StreamKind.L2_BOOK
    assert events[0].market.canonical == "xyz:XYZ100"
    assert events[0].market.dex == "xyz"


def test_btc_trade_fixture_splits_batch_and_preserves_unique_keys() -> None:
    raw = fixture("trades_btc.json")
    assert isinstance(raw, dict)
    rows = raw["data"]
    assert isinstance(rows, list)

    events = normalize_ws_message(raw, receive_time=RECEIVED)
    keys = [event.event_key for event in events]

    assert len(events) == len(rows) == 30
    assert all(event.kind is StreamKind.TRADE for event in events)
    assert all(event.market.canonical == "BTC" for event in events)
    assert len(keys) == len(set(keys))


def test_btc_candle_fixture_preserves_interval_and_exchange_time() -> None:
    events = normalize_ws_message(fixture("candle_btc_1m.json"), receive_time=RECEIVED)

    assert len(events) == 1
    event = events[0]
    assert event.kind is StreamKind.CANDLE
    assert event.market.canonical == "BTC"
    assert event.exchange_time_ms == event.payload["start_ms"]
    assert event.payload["interval"] == "1m"
