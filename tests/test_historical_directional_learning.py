from __future__ import annotations

from decimal import Decimal

import pytest

from cocomelon.research.historical_learning import (
    HistoricalLearningError,
    build_directional_outcomes,
    plan_candle_windows,
)
from cocomelon.domain.market import Candle, MarketId

MARKET = MarketId(dex="", coin="ETH")
FIVE_MINUTES_MS = 300_000


def _candle(*, end_ms: int, close: str, market: MarketId = MARKET) -> Candle:
    return Candle(
        market=market,
        interval="5m",
        start_ms=end_ms - FIVE_MINUTES_MS,
        end_ms=end_ms,
        open_px=Decimal(close),
        high_px=Decimal(close),
        low_px=Decimal(close),
        close_px=Decimal(close),
        volume=Decimal("1"),
        trade_count=1,
        source="historical-test",
        received_at_ms=end_ms,
        schema_version=1,
    )


def test_plan_candle_windows_partitions_large_history_without_overlap() -> None:
    end_ms = 9_999 * FIVE_MINUTES_MS

    windows = plan_candle_windows(
        interval="5m",
        start_ms=0,
        end_ms=end_ms,
        max_candles=5_000,
    )

    assert [(item.start_ms, item.end_ms) for item in windows] == [
        (0, 4_999 * FIVE_MINUTES_MS),
        (5_000 * FIVE_MINUTES_MS, end_ms),
    ]
    assert all(item.candle_capacity <= 5_000 for item in windows)


def test_plan_candle_windows_rejects_unknown_interval_and_invalid_bounds() -> None:
    with pytest.raises(ValueError, match="unsupported candle interval"):
        plan_candle_windows(interval="7m", start_ms=0, end_ms=1_000)
    with pytest.raises(ValueError, match="end_ms must be >= start_ms"):
        plan_candle_windows(interval="5m", start_ms=2_000, end_ms=1_000)
    with pytest.raises(ValueError, match="max_candles must be positive"):
        plan_candle_windows(interval="5m", start_ms=0, end_ms=1_000, max_candles=0)


def test_directional_outcomes_label_both_long_and_short_from_future_close() -> None:
    candles = (
        _candle(end_ms=FIVE_MINUTES_MS, close="100"),
        _candle(end_ms=2 * FIVE_MINUTES_MS, close="110"),
        _candle(end_ms=3 * FIVE_MINUTES_MS, close="99"),
    )

    outcomes = build_directional_outcomes(
        candles,
        horizons_ms=(FIVE_MINUTES_MS, 2 * FIVE_MINUTES_MS),
    )

    keyed = {(item.anchor_end_ms, item.horizon_ms): item for item in outcomes}
    first = keyed[(FIVE_MINUTES_MS, FIVE_MINUTES_MS)]
    assert first.entry_px == Decimal("100")
    assert first.exit_px == Decimal("110")
    assert first.long_gross_return == Decimal("0.1")
    assert first.short_gross_return == Decimal("-0.1")

    second = keyed[(2 * FIVE_MINUTES_MS, FIVE_MINUTES_MS)]
    assert second.long_gross_return == Decimal("-0.1")
    assert second.short_gross_return == Decimal("0.1")

    two_step = keyed[(FIVE_MINUTES_MS, 2 * FIVE_MINUTES_MS)]
    assert two_step.long_gross_return == Decimal("-0.01")
    assert two_step.short_gross_return == Decimal("0.01")


def test_directional_outcomes_never_approximate_across_a_missing_target_candle() -> None:
    candles = (
        _candle(end_ms=FIVE_MINUTES_MS, close="100"),
        _candle(end_ms=3 * FIVE_MINUTES_MS, close="120"),
    )

    outcomes = build_directional_outcomes(candles, horizons_ms=(FIVE_MINUTES_MS,))

    assert outcomes == ()


def test_directional_outcomes_are_deterministic_for_out_of_order_input() -> None:
    chronological = (
        _candle(end_ms=FIVE_MINUTES_MS, close="100"),
        _candle(end_ms=2 * FIVE_MINUTES_MS, close="105"),
        _candle(end_ms=3 * FIVE_MINUTES_MS, close="103"),
    )

    expected = build_directional_outcomes(
        chronological,
        horizons_ms=(FIVE_MINUTES_MS,),
    )
    actual = build_directional_outcomes(
        tuple(reversed(chronological)),
        horizons_ms=(FIVE_MINUTES_MS,),
    )

    assert actual == expected


def test_directional_outcomes_reject_mixed_markets_duplicate_timestamps_and_bad_prices() -> None:
    btc = MarketId(dex="", coin="BTC")
    with pytest.raises(HistoricalLearningError, match="MIXED_MARKETS"):
        build_directional_outcomes(
            (
                _candle(end_ms=FIVE_MINUTES_MS, close="100"),
                _candle(end_ms=2 * FIVE_MINUTES_MS, close="101", market=btc),
            ),
            horizons_ms=(FIVE_MINUTES_MS,),
        )

    duplicate = _candle(end_ms=FIVE_MINUTES_MS, close="100")
    with pytest.raises(HistoricalLearningError, match="DUPLICATE_CANDLE_END"):
        build_directional_outcomes(
            (duplicate, duplicate),
            horizons_ms=(FIVE_MINUTES_MS,),
        )

    with pytest.raises(HistoricalLearningError, match="NON_POSITIVE_CLOSE"):
        build_directional_outcomes(
            (
                _candle(end_ms=FIVE_MINUTES_MS, close="0"),
                _candle(end_ms=2 * FIVE_MINUTES_MS, close="1"),
            ),
            horizons_ms=(FIVE_MINUTES_MS,),
        )


def test_directional_outcomes_require_positive_unique_horizons() -> None:
    candles = (
        _candle(end_ms=FIVE_MINUTES_MS, close="100"),
        _candle(end_ms=2 * FIVE_MINUTES_MS, close="101"),
    )

    with pytest.raises(ValueError, match="horizons_ms values must be positive"):
        build_directional_outcomes(candles, horizons_ms=(0,))
    with pytest.raises(ValueError, match="horizons_ms values must be unique"):
        build_directional_outcomes(
            candles,
            horizons_ms=(FIVE_MINUTES_MS, FIVE_MINUTES_MS),
        )
