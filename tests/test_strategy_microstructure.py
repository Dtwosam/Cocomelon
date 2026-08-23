from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from cocomelon.strategies.microstructure import build_microstructure_window

from cocomelon.domain.market import MarketId
from cocomelon.domain.stream import StreamKind
from cocomelon.hyperliquid.ws_protocol import normalize_ws_message

FIXTURES = Path(__file__).parent / "fixtures" / "hyperliquid_ws"
AS_OF_MS = 1_787_501_400_000
RECEIVE_TIME = datetime.fromtimestamp(AS_OF_MS / 1000, tz=UTC)


def _load(name: str) -> object:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _trade_events() -> list[object]:
    return normalize_ws_message(_load("trades_btc.json"), receive_time=RECEIVE_TIME)


def _book_events() -> list[object]:
    return normalize_ws_message(_load("l2_book_btc.json"), receive_time=RECEIVE_TIME)


def test_real_trade_fixture_b_side_counts_as_buy_notional() -> None:
    event = next(
        event for event in _trade_events() if event.payload.get("side") == "B"
    )
    window = build_microstructure_window(
        [event],
        market=MarketId("", "BTC"),
        as_of_ms=AS_OF_MS,
    )
    assert event.kind is StreamKind.TRADE
    assert window.buy_notional == event.payload["price"] * event.payload["size"]
    assert window.sell_notional == Decimal("0")
    assert window.trade_flow_imbalance == Decimal("1")


def test_real_trade_fixture_a_side_counts_as_sell_notional() -> None:
    event = next(
        event for event in _trade_events() if event.payload.get("side") == "A"
    )
    window = build_microstructure_window(
        [event],
        market=MarketId("", "BTC"),
        as_of_ms=AS_OF_MS,
    )
    assert window.buy_notional == Decimal("0")
    assert window.sell_notional == event.payload["price"] * event.payload["size"]
    assert window.trade_flow_imbalance == Decimal("-1")


def test_trade_flow_imbalance_is_decimal_and_input_order_invariant() -> None:
    trades = _trade_events()
    selected = [
        next(event for event in trades if event.payload.get("side") == "B"),
        next(event for event in trades if event.payload.get("side") == "A"),
    ]
    first = build_microstructure_window(
        selected,
        market=MarketId("", "BTC"),
        as_of_ms=AS_OF_MS,
    )
    second = build_microstructure_window(
        list(reversed(selected)),
        market=MarketId("", "BTC"),
        as_of_ms=AS_OF_MS,
    )
    assert isinstance(first.trade_flow_imbalance, Decimal)
    assert first == second


def test_single_real_book_has_latest_imbalance_but_no_change() -> None:
    event = _book_events()[0]
    window = build_microstructure_window(
        [event],
        market=MarketId("", "BTC"),
        as_of_ms=AS_OF_MS,
    )
    assert event.kind is StreamKind.L2_BOOK
    assert window.latest_book_imbalance is not None
    assert Decimal("-1") <= window.latest_book_imbalance <= Decimal("1")
    assert window.book_imbalance_change is None


def test_candle_event_is_rejected_as_microstructure_input() -> None:
    candle = normalize_ws_message(
        _load("candle_btc_1m.json"),
        receive_time=RECEIVE_TIME,
    )[0]
    with pytest.raises(ValueError, match="TRADE|L2_BOOK"):
        build_microstructure_window(
            [candle],
            market=MarketId("", "BTC"),
            as_of_ms=AS_OF_MS,
        )


def test_future_received_event_cannot_enter_window() -> None:
    future_time = RECEIVE_TIME + timedelta(milliseconds=1)
    event = normalize_ws_message(_load("trades_btc.json"), receive_time=future_time)[0]
    window = build_microstructure_window(
        [event],
        market=MarketId("", "BTC"),
        as_of_ms=AS_OF_MS,
    )
    assert window.trade_count == 0
    assert window.trade_flow_imbalance is None
    assert window.latest_event_age_ms is None


def test_window_rejects_non_positive_duration_and_market_mismatch() -> None:
    event = _trade_events()[0]
    with pytest.raises(ValueError, match="window_ms"):
        build_microstructure_window(
            [event],
            market=MarketId("", "BTC"),
            as_of_ms=AS_OF_MS,
            window_ms=0,
        )
    with pytest.raises(ValueError, match="market"):
        build_microstructure_window(
            [event],
            market=MarketId("", "ETH"),
            as_of_ms=AS_OF_MS,
        )
