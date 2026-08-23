import importlib
from decimal import Decimal

import pytest

from cocomelon.domain.market import Candle, MarketId

candle_module = importlib.import_module("cocomelon.features.candles")
calculate_candle_features = candle_module.calculate_candle_features

BTC = MarketId("", "BTC")
FIVE_MINUTES_MS = 300_000
FIFTEEN_MINUTES_MS = 900_000


def _candle(
    *,
    interval: str,
    index: int,
    close: Decimal,
    volume: Decimal = Decimal("100"),
    open_px: Decimal | None = None,
    received_at_ms: int | None = None,
    market: MarketId = BTC,
) -> Candle:
    width = FIVE_MINUTES_MS if interval == "5m" else FIFTEEN_MINUTES_MS
    start = index * width
    resolved_open = open_px if open_px is not None else close - Decimal("1")
    return Candle(
        market=market,
        interval=interval,
        start_ms=start,
        end_ms=start + width,
        open_px=resolved_open,
        high_px=max(resolved_open, close) + Decimal("1"),
        low_px=min(resolved_open, close) - Decimal("1"),
        close_px=close,
        volume=volume,
        trade_count=10,
        source="synthetic-unit-fixture",
        received_at_ms=received_at_ms if received_at_ms is not None else start + width,
        schema_version=1,
    )


def test_candle_features_ignore_open_future_ending_candles() -> None:
    candles = (
        _candle(interval="5m", index=0, close=Decimal("100")),
        _candle(interval="5m", index=1, close=Decimal("110")),
        _candle(interval="5m", index=2, close=Decimal("999"), received_at_ms=600_000),
    )

    result = calculate_candle_features(BTC, candles_5m=candles, as_of_ms=600_000)

    assert result.return_5m == Decimal("0.1")


def test_candle_features_reject_future_received_input_even_if_bar_is_open() -> None:
    candles = (
        _candle(interval="5m", index=0, close=Decimal("100")),
        _candle(interval="5m", index=1, close=Decimal("110")),
        _candle(interval="5m", index=2, close=Decimal("120"), received_at_ms=600_001),
    )

    with pytest.raises(ValueError, match="received after as_of_ms"):
        calculate_candle_features(BTC, candles_5m=candles, as_of_ms=600_000)


def test_candle_features_require_market_interval_and_strict_order() -> None:
    with pytest.raises(ValueError, match="market"):
        calculate_candle_features(
            BTC,
            candles_5m=(
                _candle(interval="5m", index=0, close=Decimal("100"), market=MarketId("", "ETH")),
            ),
            as_of_ms=600_000,
        )

    with pytest.raises(ValueError, match="strictly increasing"):
        calculate_candle_features(
            BTC,
            candles_5m=(
                _candle(interval="5m", index=1, close=Decimal("110")),
                _candle(interval="5m", index=0, close=Decimal("100")),
            ),
            as_of_ms=600_000,
        )


def test_candle_features_calculate_returns_volume_range_and_realized_vol() -> None:
    candles_5m = tuple(
        _candle(interval="5m", index=index, close=Decimal(100 + index))
        for index in range(2)
    )
    candles_15m = tuple(
        _candle(
            interval="15m",
            index=index,
            close=Decimal(100 + index),
            volume=Decimal(100 + index),
            open_px=Decimal(99 + index),
        )
        for index in range(21)
    )
    as_of_ms = 21 * FIFTEEN_MINUTES_MS

    result = calculate_candle_features(
        BTC,
        candles_5m=candles_5m,
        candles_15m=candles_15m,
        as_of_ms=as_of_ms,
    )

    closes = [Decimal(100 + index) for index in range(21)]
    returns = [closes[index] / closes[index - 1] - Decimal("1") for index in range(1, 21)]
    mean = sum(returns, Decimal("0")) / Decimal(len(returns))
    expected_vol = (
        sum(((value - mean) ** 2 for value in returns), Decimal("0"))
        / Decimal(len(returns))
    ).sqrt()
    previous_volumes = tuple(Decimal(100 + index) for index in range(20))
    median_volume = (previous_volumes[9] + previous_volumes[10]) / Decimal("2")
    normalized_ranges = tuple(Decimal("3") / Decimal(99 + index) for index in range(21))
    median_prior_range = (
        sorted(normalized_ranges[:-1])[9] + sorted(normalized_ranges[:-1])[10]
    ) / Decimal("2")

    assert result.return_5m == Decimal("101") / Decimal("100") - Decimal("1")
    assert result.return_15m == Decimal("120") / Decimal("119") - Decimal("1")
    assert result.return_1h == Decimal("120") / Decimal("116") - Decimal("1")
    assert result.return_4h == Decimal("120") / Decimal("104") - Decimal("1")
    assert result.relative_volume_15m == Decimal("120") / median_volume
    assert result.range_expansion_15m == normalized_ranges[-1] / median_prior_range
    assert result.realized_vol_15m == expected_vol
    assert isinstance(result.realized_vol_15m, Decimal)
