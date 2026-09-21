from __future__ import annotations

from decimal import Decimal

import pytest

from cocomelon.domain.features import TrendRegime
from cocomelon.domain.market import Candle, FundingRate, MarketId
from cocomelon.research.historical_features import (
    HistoricalFeatureError,
    build_historical_feature_rows,
    build_historical_feature_rows_15m,
    join_features_to_outcomes,
)
from cocomelon.research.historical_learning import build_directional_outcomes

MARKET = MarketId(dex="", coin="ETH")
FIVE = 300_000
FIFTEEN = 900_000
HOUR = 3_600_000


def _candle(
    *,
    interval: str,
    start_ms: int,
    close: str,
    volume: str = "100",
    open_px: str | None = None,
    received_at_ms: int = 99_000_000,
    market: MarketId = MARKET,
) -> Candle:
    width = FIVE if interval == "5m" else FIFTEEN
    resolved_open = Decimal(open_px) if open_px is not None else Decimal(close) - Decimal("1")
    close_px = Decimal(close)
    return Candle(
        market=market,
        interval=interval,
        start_ms=start_ms,
        end_ms=start_ms + width - 1,
        open_px=resolved_open,
        high_px=max(resolved_open, close_px) + Decimal("1"),
        low_px=min(resolved_open, close_px) - Decimal("1"),
        close_px=close_px,
        volume=Decimal(volume),
        trade_count=10,
        source="hyperliquid-mainnet-info",
        received_at_ms=received_at_ms,
        schema_version=1,
    )


def _funding(
    time_ms: int,
    *,
    rate: str,
    premium: str = "0.0002",
    received_at_ms: int = 99_000_000,
) -> FundingRate:
    return FundingRate(
        market=MARKET,
        time_ms=time_ms,
        funding_rate=Decimal(rate),
        premium=Decimal(premium),
        source="hyperliquid-mainnet-info",
        received_at_ms=received_at_ms,
        schema_version=1,
    )


def test_historical_features_use_exchange_availability_not_late_retrieval_time() -> None:
    candles_5m = (
        _candle(interval="5m", start_ms=0, close="100"),
        _candle(interval="5m", start_ms=FIVE, close="110"),
    )

    rows = build_historical_feature_rows(
        candles_5m=candles_5m,
        candles_15m=(),
        funding_rates=(),
        source_manifest_ids=("candle-manifest",),
    )

    assert len(rows) == 2
    latest = rows[-1]
    assert latest.anchor_end_ms == 2 * FIVE - 1
    assert latest.return_5m == Decimal("0.1")
    assert latest.retrieved_after_anchor is True
    assert latest.availability_basis == "exchange_timestamp"


def test_historical_features_match_live_candle_math_when_history_is_contiguous() -> None:
    candles_5m = tuple(
        _candle(interval="5m", start_ms=index * FIVE, close=str(100 + index))
        for index in range(63)
    )
    candles_15m = tuple(
        _candle(
            interval="15m",
            start_ms=index * FIFTEEN,
            close=str(100 + index),
            volume=str(100 + index),
            open_px=str(99 + index),
        )
        for index in range(21)
    )

    rows = build_historical_feature_rows(
        candles_5m=candles_5m,
        candles_15m=candles_15m,
        funding_rates=(),
        source_manifest_ids=("5m-manifest", "15m-manifest"),
    )

    latest = rows[-1]
    assert latest.return_5m == Decimal("162") / Decimal("161") - Decimal("1")
    assert latest.return_15m == Decimal("120") / Decimal("119") - Decimal("1")
    assert latest.return_1h == Decimal("120") / Decimal("116") - Decimal("1")
    assert latest.return_4h == Decimal("120") / Decimal("104") - Decimal("1")
    assert latest.trend_regime is TrendRegime.UP


def test_historical_feature_provenance_covers_all_lookback_inputs() -> None:
    candles_5m = tuple(
        _candle(interval="5m", start_ms=index * FIVE, close=str(100 + index))
        for index in range(63)
    )
    candles_15m = tuple(
        _candle(
            interval="15m",
            start_ms=index * FIFTEEN,
            close=str(100 + index),
            volume=str(100 + index),
            received_at_ms=(
                123_000_000
                if index == 5
                else 99_000_000
            ),
        )
        for index in range(21)
    )

    rows = build_historical_feature_rows(
        candles_5m=candles_5m,
        candles_15m=candles_15m,
        funding_rates=(),
        source_manifest_ids=("5m-manifest", "15m-manifest"),
    )

    latest = rows[-1]
    assert latest.realized_vol_15m is not None
    assert latest.source_retrieved_at_ms == 123_000_000
    assert latest.retrieved_after_anchor is True


def test_historical_features_do_not_bridge_missing_candle_gaps() -> None:
    candles_5m = tuple(
        _candle(interval="5m", start_ms=index * FIVE, close=str(100 + index))
        for index in range(63)
    )
    candles_15m = tuple(
        _candle(interval="15m", start_ms=index * FIFTEEN, close=str(100 + index))
        for index in range(21)
        if index != 19
    )

    rows = build_historical_feature_rows(
        candles_5m=candles_5m,
        candles_15m=candles_15m,
        funding_rates=(),
        source_manifest_ids=("source-a",),
    )

    latest = rows[-1]
    assert latest.return_5m == Decimal("162") / Decimal("161") - Decimal("1")
    assert latest.return_15m is None
    assert latest.realized_vol_15m is None
    assert latest.range_expansion_15m is None
    assert latest.relative_volume_15m is None


def test_historical_features_align_latest_known_funding_without_lookahead() -> None:
    candles_5m = tuple(
        _candle(interval="5m", start_ms=index * FIVE, close=str(100 + index))
        for index in range(14)
    )
    funding = (
        _funding(0, rate="0.0001", premium="0.0002"),
        _funding(HOUR, rate="0.0003", premium="0.0005"),
        _funding(2 * HOUR, rate="0.0099", premium="0.0099"),
    )

    rows = build_historical_feature_rows(
        candles_5m=candles_5m,
        candles_15m=(),
        funding_rates=funding,
        source_manifest_ids=("funding-manifest",),
    )

    anchor = next(row for row in rows if row.anchor_end_ms > HOUR)
    assert anchor.anchor_end_ms < 2 * HOUR
    assert anchor.funding_rate == Decimal("0.0003")
    assert anchor.funding_change == Decimal("0.0002")
    assert anchor.funding_premium == Decimal("0.0005")
    assert anchor.funding_premium_change == Decimal("0.0003")
    assert anchor.funding_age_ms == anchor.anchor_end_ms - HOUR


def test_historical_features_explicitly_mark_unavailable_microstructure_and_oi() -> None:
    rows = build_historical_feature_rows(
        candles_5m=(_candle(interval="5m", start_ms=0, close="100"),),
        candles_15m=(),
        funding_rates=(),
        source_manifest_ids=("source-a",),
    )

    row = rows[0]
    assert "open_interest" in row.unavailable_features
    assert "spread_bps" in row.unavailable_features
    assert "book_imbalance" in row.unavailable_features
    assert "funding_rate" in row.unavailable_features
    assert "return_5m" in row.unavailable_features
    assert row.row_id == build_historical_feature_rows(
        candles_5m=(_candle(interval="5m", start_ms=0, close="100"),),
        candles_15m=(),
        funding_rates=(),
        source_manifest_ids=("source-a",),
    )[0].row_id


def test_historical_feature_construction_is_deterministic_for_reordered_sources() -> None:
    candles_5m = tuple(
        _candle(interval="5m", start_ms=index * FIVE, close=str(100 + index))
        for index in range(3)
    )
    funding = (
        _funding(0, rate="0.0001"),
        _funding(HOUR, rate="0.0002"),
    )

    expected = build_historical_feature_rows(
        candles_5m=candles_5m,
        candles_15m=(),
        funding_rates=funding,
        source_manifest_ids=("b", "a"),
    )
    actual = build_historical_feature_rows(
        candles_5m=tuple(reversed(candles_5m)),
        candles_15m=(),
        funding_rates=tuple(reversed(funding)),
        source_manifest_ids=("a", "b", "a"),
    )

    assert actual == expected


def test_historical_features_fail_closed_on_mixed_markets() -> None:
    btc = MarketId(dex="", coin="BTC")
    with pytest.raises(HistoricalFeatureError, match="MIXED_MARKETS"):
        build_historical_feature_rows(
            candles_5m=(
                _candle(interval="5m", start_ms=0, close="100"),
                _candle(interval="5m", start_ms=FIVE, close="101", market=btc),
            ),
            candles_15m=(),
            funding_rates=(),
            source_manifest_ids=("source-a",),
        )


def test_feature_outcome_join_requires_exact_market_anchor_and_preserves_both_sides() -> None:
    candles_5m = tuple(
        _candle(interval="5m", start_ms=index * FIVE, close=close)
        for index, close in enumerate(("100", "110", "99"))
    )
    features = build_historical_feature_rows(
        candles_5m=candles_5m,
        candles_15m=(),
        funding_rates=(),
        source_manifest_ids=("source-a",),
    )
    outcomes = build_directional_outcomes(
        candles_5m,
        horizons_ms=(FIVE,),
    )

    rows = join_features_to_outcomes(features, outcomes)

    assert len(rows) == 2
    first = rows[0]
    assert first.feature_id == features[0].row_id
    assert first.long_gross_return == Decimal("0.1")
    assert first.short_gross_return == Decimal("-0.1")
    assert first.horizon_ms == FIVE
    assert len(first.training_row_id) == 24



def test_historical_features_compute_funding_change_across_small_timestamp_jitter() -> None:
    candles_5m = tuple(
        _candle(interval="5m", start_ms=index * FIVE, close=str(100 + index))
        for index in range(14)
    )
    funding = (
        _funding(41, rate="0.0001", premium="0.0002"),
        _funding(HOUR + 73, rate="0.0003", premium="0.0005"),
    )

    rows = build_historical_feature_rows(
        candles_5m=candles_5m,
        candles_15m=(),
        funding_rates=funding,
        source_manifest_ids=("funding-manifest",),
    )

    anchor = next(row for row in rows if row.anchor_end_ms > HOUR + 73)
    assert anchor.funding_rate == Decimal("0.0003")
    assert anchor.funding_change == Decimal("0.0002")
    assert anchor.funding_premium_change == Decimal("0.0003")



def test_15m_anchor_features_do_not_invent_5m_return() -> None:
    candles_15m = tuple(
        _candle(
            interval="15m",
            start_ms=index * FIFTEEN,
            close=str(100 + index),
            volume=str(100 + index),
            open_px=str(99 + index),
        )
        for index in range(21)
    )

    rows = build_historical_feature_rows_15m(
        candles_15m=candles_15m,
        funding_rates=(),
        source_manifest_ids=("15m-manifest",),
    )

    latest = rows[-1]
    assert latest.return_5m is None
    assert latest.return_15m == Decimal("120") / Decimal("119") - Decimal("1")
    assert latest.return_1h == Decimal("120") / Decimal("116") - Decimal("1")
    assert latest.return_4h == Decimal("120") / Decimal("104") - Decimal("1")
    assert latest.candle_15m_age_ms == 0
    assert latest.realized_vol_15m is not None
    assert "return_5m" in latest.unavailable_features


def test_15m_anchor_features_do_not_bridge_missing_gap() -> None:
    candles_15m = tuple(
        _candle(interval="15m", start_ms=index * FIFTEEN, close=str(100 + index))
        for index in range(21)
        if index != 19
    )

    latest = build_historical_feature_rows_15m(
        candles_15m=candles_15m,
        funding_rates=(),
        source_manifest_ids=("15m-manifest",),
    )[-1]

    assert latest.return_15m is None
    assert latest.realized_vol_15m is None
    assert latest.range_expansion_15m is None
    assert latest.relative_volume_15m is None
