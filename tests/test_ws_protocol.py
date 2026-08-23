from datetime import UTC, datetime
from decimal import Decimal

import pytest

from cocomelon.domain.stream import StreamKind
from cocomelon.hyperliquid.ws_protocol import (
    WsProtocolError,
    normalize_ws_message,
    subscribe_message,
    subscription_id,
    unsubscribe_message,
)

RECEIVED = datetime(2026, 8, 23, 15, 30, tzinfo=UTC)


def test_public_subscription_ids_are_canonical() -> None:
    assert subscription_id({"type": "allMids"}) == "allMids"
    assert subscription_id({"type": "allMids", "dex": "xyz"}) == "allMids:xyz"
    assert subscription_id({"type": "l2Book", "coin": "xyz:NVDA"}) == "l2Book:xyz:NVDA"
    assert subscription_id({"type": "trades", "coin": "BTC"}) == "trades:BTC"
    assert (
        subscription_id({"type": "candle", "coin": "BTC", "interval": "15m"})
        == "candle:BTC:15m"
    )


def test_subscribe_and_unsubscribe_preserve_exact_subscription() -> None:
    subscription: dict[str, object] = {"type": "l2Book", "coin": "BTC"}

    assert subscribe_message(subscription) == {
        "method": "subscribe",
        "subscription": subscription,
    }
    assert unsubscribe_message(subscription) == {
        "method": "unsubscribe",
        "subscription": subscription,
    }


def test_user_specific_subscription_is_rejected_in_phase_3() -> None:
    with pytest.raises(WsProtocolError, match="public subscription"):
        subscription_id({"type": "userFills", "user": "0xabc"})


def test_all_mids_normalizes_native_and_hip3_markets() -> None:
    events = normalize_ws_message(
        {"channel": "allMids", "data": {"mids": {"BTC": "100.5", "xyz:NVDA": "55.25"}}},
        receive_time=RECEIVED,
    )

    assert [event.market.canonical for event in events] == ["BTC", "xyz:NVDA"]
    assert all(event.kind is StreamKind.ALL_MIDS for event in events)
    assert events[0].exchange_time_ms is None
    assert events[0].payload["mid_px"] == Decimal("100.5")
    assert events[1].payload["mid_px"] == Decimal("55.25")


def test_l2_book_normalizes_full_snapshot() -> None:
    events = normalize_ws_message(
        {
            "channel": "l2Book",
            "data": {
                "coin": "BTC",
                "time": 1_787_500_000_000,
                "levels": [
                    [{"px": "100", "sz": "2.5", "n": 3}],
                    [{"px": "101", "sz": "1.25", "n": 2}],
                ],
            },
        },
        receive_time=RECEIVED,
    )

    assert len(events) == 1
    event = events[0]
    assert event.kind is StreamKind.L2_BOOK
    assert event.market.canonical == "BTC"
    assert event.exchange_time_ms == 1_787_500_000_000
    bids = event.payload["bids"]
    asks = event.payload["asks"]
    assert bids == ({"px": Decimal("100"), "sz": Decimal("2.5"), "n": 3},)
    assert asks == ({"px": Decimal("101"), "sz": Decimal("1.25"), "n": 2},)


def test_trades_split_into_one_event_per_trade_and_use_documented_unique_key() -> None:
    events = normalize_ws_message(
        {
            "channel": "trades",
            "data": [
                {
                    "coin": "xyz:NVDA",
                    "side": "B",
                    "px": "55.5",
                    "sz": "10",
                    "hash": "0xabc",
                    "time": 1_787_500_000_001,
                    "tid": 12345,
                    "users": ["0xbuyer", "0xseller"],
                }
            ],
        },
        receive_time=RECEIVED,
    )

    assert len(events) == 1
    event = events[0]
    assert event.kind is StreamKind.TRADE
    assert event.market.canonical == "xyz:NVDA"
    assert event.event_key == "trades:xyz:NVDA:1787500000001:12345"
    assert event.payload["price"] == Decimal("55.5")
    assert event.payload["size"] == Decimal("10")
    assert event.payload["users"] == ("0xbuyer", "0xseller")


def test_candle_updates_include_content_in_event_key_so_mutations_are_not_duplicates() -> None:
    first = {
        "channel": "candle",
        "data": {
            "t": 1_000,
            "T": 1_999,
            "s": "BTC",
            "i": "1m",
            "o": "100",
            "c": "101",
            "h": "102",
            "l": "99",
            "v": "5",
            "n": 10,
        },
    }
    second = {"channel": "candle", "data": {**first["data"], "c": "101.5", "n": 11}}

    event_a = normalize_ws_message(first, receive_time=RECEIVED)[0]
    event_b = normalize_ws_message(second, receive_time=RECEIVED)[0]

    assert event_a.kind is StreamKind.CANDLE
    assert event_a.payload["close_px"] == Decimal("101")
    assert event_b.payload["close_px"] == Decimal("101.5")
    assert event_a.event_key != event_b.event_key


def test_control_messages_do_not_become_market_events() -> None:
    assert normalize_ws_message({"channel": "pong"}, receive_time=RECEIVED) == []
    assert (
        normalize_ws_message(
            {
                "channel": "subscriptionResponse",
                "data": {"method": "subscribe", "subscription": {"type": "trades", "coin": "BTC"}},
            },
            receive_time=RECEIVED,
        )
        == []
    )


def test_non_finite_numeric_value_is_rejected() -> None:
    with pytest.raises(WsProtocolError, match="finite"):
        normalize_ws_message(
            {"channel": "allMids", "data": {"mids": {"BTC": "NaN"}}},
            receive_time=RECEIVED,
        )


def test_unknown_channel_is_explicit_protocol_error() -> None:
    with pytest.raises(WsProtocolError, match="unsupported channel"):
        normalize_ws_message({"channel": "mystery", "data": {}}, receive_time=RECEIVED)
