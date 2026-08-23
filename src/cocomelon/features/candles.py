from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from cocomelon.domain.market import Candle, MarketId
from cocomelon.features.math import quantile

ONE = Decimal("1")
ZERO = Decimal("0")
MEDIAN = Decimal("0.5")


@dataclass(frozen=True, slots=True)
class CandleFeatureValues:
    source_received_at_ms: int | None
    return_5m: Decimal | None
    return_15m: Decimal | None
    return_1h: Decimal | None
    return_4h: Decimal | None
    realized_vol_15m: Decimal | None
    range_expansion_15m: Decimal | None
    relative_volume_15m: Decimal | None


def _closed_candles(
    market: MarketId,
    candles: Sequence[Candle],
    *,
    interval: str,
    as_of_ms: int,
) -> tuple[Candle, ...]:
    for candle in candles:
        if candle.market != market:
            raise ValueError(f"{interval} candle market does not match requested market")
        if candle.interval != interval:
            raise ValueError(f"expected {interval} candles")
        if candle.received_at_ms > as_of_ms:
            raise ValueError(f"{interval} candle was received after as_of_ms")

    closed = tuple(candle for candle in candles if candle.end_ms <= as_of_ms)
    previous_start: int | None = None
    for candle in closed:
        if previous_start is not None and candle.start_ms <= previous_start:
            raise ValueError(f"closed {interval} candles must be strictly increasing")
        previous_start = candle.start_ms
    return closed


def _simple_return(current: Decimal, previous: Decimal) -> Decimal:
    if not current.is_finite() or not previous.is_finite() or previous <= ZERO:
        raise ValueError("candle closes used for returns must be finite and previous close positive")
    return current / previous - ONE


def _return_apart(candles: Sequence[Candle], bars_apart: int) -> Decimal | None:
    if len(candles) <= bars_apart:
        return None
    return _simple_return(candles[-1].close_px, candles[-1 - bars_apart].close_px)


def _realized_volatility(candles: Sequence[Candle]) -> Decimal | None:
    if len(candles) < 21:
        return None
    sample = candles[-21:]
    returns = tuple(
        _simple_return(sample[index].close_px, sample[index - 1].close_px)
        for index in range(1, len(sample))
    )
    mean = sum(returns, ZERO) / Decimal(len(returns))
    variance = sum(((value - mean) ** 2 for value in returns), ZERO) / Decimal(len(returns))
    return variance.sqrt()


def _relative_volume(candles: Sequence[Candle]) -> Decimal | None:
    if len(candles) < 21:
        return None
    sample = candles[-21:]
    prior = tuple(candle.volume for candle in sample[:-1])
    if any(not value.is_finite() or value < ZERO for value in (*prior, sample[-1].volume)):
        raise ValueError("candle volume must be finite and non-negative")
    baseline = quantile(prior, MEDIAN)
    if baseline <= ZERO:
        return None
    return sample[-1].volume / baseline


def _normalized_range(candle: Candle) -> Decimal:
    values = (candle.open_px, candle.high_px, candle.low_px)
    if any(not value.is_finite() for value in values) or candle.open_px <= ZERO:
        raise ValueError("candle prices used for range must be finite with positive open")
    if candle.high_px < candle.low_px:
        raise ValueError("candle high must be >= low")
    return (candle.high_px - candle.low_px) / candle.open_px


def _range_expansion(candles: Sequence[Candle]) -> Decimal | None:
    if len(candles) < 21:
        return None
    ranges = tuple(_normalized_range(candle) for candle in candles[-21:])
    baseline = quantile(ranges[:-1], MEDIAN)
    if baseline <= ZERO:
        return None
    return ranges[-1] / baseline


def calculate_candle_features(
    market: MarketId,
    *,
    candles_5m: Sequence[Candle] = (),
    candles_15m: Sequence[Candle] = (),
    as_of_ms: int,
) -> CandleFeatureValues:
    if as_of_ms < 0:
        raise ValueError("as_of_ms must be non-negative")

    closed_5m = _closed_candles(market, candles_5m, interval="5m", as_of_ms=as_of_ms)
    closed_15m = _closed_candles(market, candles_15m, interval="15m", as_of_ms=as_of_ms)
    used = (*closed_5m, *closed_15m)
    source_received_at_ms = max((candle.received_at_ms for candle in used), default=None)

    return CandleFeatureValues(
        source_received_at_ms=source_received_at_ms,
        return_5m=_return_apart(closed_5m, 1),
        return_15m=_return_apart(closed_15m, 1),
        return_1h=_return_apart(closed_15m, 4),
        return_4h=_return_apart(closed_15m, 16),
        realized_vol_15m=_realized_volatility(closed_15m),
        range_expansion_15m=_range_expansion(closed_15m),
        relative_volume_15m=_relative_volume(closed_15m),
    )
