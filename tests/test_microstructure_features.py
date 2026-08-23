import importlib
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from cocomelon.domain.market import MarketId
from cocomelon.domain.stream import StreamEvent, StreamKind

microstructure_module = importlib.import_module("cocomelon.features.microstructure")
calculate_microstructure_features = microstructure_module.calculate_microstructure_features

BTC = MarketId("", "BTC")


def _level(px: str, sz: str, n: int = 1) -> dict[str, object]:
    return {"px": Decimal(px), "sz": Decimal(sz), "n": n}


def _event(
    *,
    kind: StreamKind = StreamKind.L2_BOOK,
    exchange_time_ms: int | None = 1_000,
    bids: tuple[dict[str, object], ...] | None = None,
    asks: tuple[dict[str, object], ...] | None = None,
) -> StreamEvent:
    resolved_bids = bids if bids is not None else (_level("100", "2"),)
    resolved_asks = asks if asks is not None else (_level("100.1", "4"),)
    return StreamEvent(
        kind=kind,
        market=BTC,
        exchange_time_ms=exchange_time_ms,
        receive_time=datetime.fromtimestamp(1, tz=UTC),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key="l2Book:BTC:1000:test",
        payload={"bids": resolved_bids, "asks": resolved_asks},
    )


def test_microstructure_features_find_best_levels_independent_of_input_order() -> None:
    event = _event(
        bids=(
            _level("99.7", "100"),
            _level("100", "2"),
            _level("99.8", "3"),
        ),
        asks=(
            _level("100.4", "100"),
            _level("100.3", "5"),
            _level("100.1", "4"),
        ),
    )

    result = calculate_microstructure_features(event, as_of_ms=1_500)

    mid = (Decimal("100") + Decimal("100.1")) / Decimal("2")
    expected_spread_bps = (Decimal("100.1") - Decimal("100")) / mid * Decimal("10000")
    expected_bid_depth = Decimal("100") * Decimal("2") + Decimal("99.8") * Decimal("3")
    expected_ask_depth = Decimal("100.1") * Decimal("4") + Decimal("100.3") * Decimal("5")
    expected_imbalance = (expected_bid_depth - expected_ask_depth) / (
        expected_bid_depth + expected_ask_depth
    )

    assert result.best_bid_px == Decimal("100")
    assert result.best_ask_px == Decimal("100.1")
    assert result.mid_px == mid
    assert result.spread_bps == expected_spread_bps
    assert result.bid_depth_25bps == expected_bid_depth
    assert result.ask_depth_25bps == expected_ask_depth
    assert result.book_imbalance == expected_imbalance
    assert result.book_age_ms == 500


def test_microstructure_features_reject_empty_or_crossed_books() -> None:
    with pytest.raises(ValueError, match="empty"):
        calculate_microstructure_features(_event(bids=()), as_of_ms=1_500)

    with pytest.raises(ValueError, match="crossed"):
        calculate_microstructure_features(
            _event(
                bids=(_level("101", "1"),),
                asks=(_level("100", "1"),),
            ),
            as_of_ms=1_500,
        )


def test_microstructure_features_reject_future_or_missing_exchange_time() -> None:
    with pytest.raises(ValueError, match="future"):
        calculate_microstructure_features(
            _event(exchange_time_ms=1_501),
            as_of_ms=1_500,
        )

    with pytest.raises(ValueError, match="exchange_time_ms"):
        calculate_microstructure_features(
            _event(exchange_time_ms=None),
            as_of_ms=1_500,
        )


def test_microstructure_features_reject_non_l2_events() -> None:
    with pytest.raises(ValueError, match="L2"):
        calculate_microstructure_features(
            _event(kind=StreamKind.TRADE),
            as_of_ms=1_500,
        )
