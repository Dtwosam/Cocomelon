from decimal import Decimal

import pytest
from cocomelon.strategies.candles import closed_candles, reference_price, swing_invalidation

from cocomelon.domain.features import (
    EligibilityDecision,
    FeatureSnapshot,
    TrendRegime,
    VolatilityRegime,
)
from cocomelon.domain.market import (
    Candle,
    MarketId,
    PerpMarketContext,
    PerpMarketMeta,
    PerpMarketSnapshot,
)
from cocomelon.domain.strategy import Direction, StrategyContext


def _market_snapshot(
    *,
    mid_px: Decimal | None = Decimal("100.5"),
    mark_px: Decimal | None = Decimal("100"),
) -> PerpMarketSnapshot:
    market = MarketId("", "BTC")
    return PerpMarketSnapshot(
        meta=PerpMarketMeta(
            market=market,
            wire_name="BTC",
            sz_decimals=5,
            max_leverage=40,
            margin_table_id=1,
            only_isolated=False,
            is_delisted=False,
            margin_mode=None,
        ),
        context=PerpMarketContext(
            market=market,
            mark_px=mark_px,
            mid_px=mid_px,
            oracle_px=Decimal("100"),
            funding=Decimal("0"),
            open_interest=Decimal("1000"),
            day_ntl_vlm=Decimal("1000000"),
            premium=Decimal("0"),
            prev_day_px=Decimal("99"),
        ),
        source="hyperliquid-mainnet-info",
        received_at_ms=900,
        schema_version=1,
    )


def _feature() -> FeatureSnapshot:
    market = MarketId("", "BTC")
    return FeatureSnapshot(
        market=market,
        as_of_ms=10_000,
        source_received_at_ms=9_000,
        schema_version=1,
        day_return=Decimal("0.01"),
        funding=Decimal("0"),
        open_interest=Decimal("1000"),
        day_notional_volume=Decimal("1000000"),
        oi_change_fraction=None,
        funding_change=None,
        mark_oracle_dislocation_bps=None,
        return_5m=None,
        return_15m=None,
        return_1h=None,
        return_4h=None,
        realized_vol_15m=None,
        range_expansion_15m=None,
        relative_volume_15m=None,
        spread_bps=None,
        bid_depth_25bps=None,
        ask_depth_25bps=None,
        book_imbalance=None,
        book_age_ms=None,
        trend_regime=TrendRegime.UNKNOWN,
        volatility_regime=VolatilityRegime.UNKNOWN,
        provenance=("test",),
    )


def _candle(
    *,
    start_ms: int,
    end_ms: int,
    low: str = "98",
    high: str = "102",
    interval: str = "15m",
    received_at_ms: int | None = None,
    market: MarketId | None = None,
) -> Candle:
    selected = MarketId("", "BTC") if market is None else market
    return Candle(
        market=selected,
        interval=interval,
        start_ms=start_ms,
        end_ms=end_ms,
        open_px=Decimal("100"),
        high_px=Decimal(high),
        low_px=Decimal(low),
        close_px=Decimal("101"),
        volume=Decimal("100"),
        trade_count=10,
        source="test",
        received_at_ms=end_ms if received_at_ms is None else received_at_ms,
        schema_version=1,
    )


def _context(
    *,
    candles_5m: tuple[Candle, ...] = (),
    candles_15m: tuple[Candle, ...] = (),
    market_snapshot: PerpMarketSnapshot | None = None,
) -> StrategyContext:
    feature = _feature()
    snapshot = _market_snapshot() if market_snapshot is None else market_snapshot
    return StrategyContext(
        market_snapshot=snapshot,
        feature_snapshot=feature,
        eligibility=EligibilityDecision(
            market=feature.market,
            rankable=True,
            deep_ready=True,
            reasons=(),
        ),
        candles_5m=candles_5m,
        candles_15m=candles_15m,
        microstructure=None,
        as_of_ms=10_000,
    )


def test_closed_candles_filters_future_end_and_future_receive_time() -> None:
    candles = (
        _candle(start_ms=0, end_ms=1_000),
        _candle(start_ms=1_000, end_ms=2_000, received_at_ms=10_001),
        _candle(start_ms=10_000, end_ms=11_000, received_at_ms=9_999),
        _candle(start_ms=2_000, end_ms=3_000),
    )
    result = closed_candles(_context(candles_15m=candles), "15m")
    assert tuple(candle.end_ms for candle in result) == (1_000, 3_000)


def test_closed_candles_rejects_market_or_interval_mismatch() -> None:
    with pytest.raises(ValueError, match="market"):
        closed_candles(
            _context(
                candles_15m=(
                    _candle(start_ms=0, end_ms=1_000, market=MarketId("", "ETH")),
                )
            ),
            "15m",
        )

    with pytest.raises(ValueError, match="interval"):
        closed_candles(
            _context(candles_15m=(_candle(start_ms=0, end_ms=1_000, interval="5m"),)),
            "15m",
        )


def test_reference_price_prefers_positive_mid_then_mark() -> None:
    assert reference_price(_context()) == Decimal("100.5")
    assert (
        reference_price(_context(market_snapshot=_market_snapshot(mid_px=None)))
        == Decimal("100")
    )
    assert (
        reference_price(
            _context(market_snapshot=_market_snapshot(mid_px=Decimal("0"), mark_px=None))
        )
        is None
    )


def test_swing_invalidation_uses_latest_four_closed_15m_candles() -> None:
    candles = (
        _candle(start_ms=0, end_ms=1_000, low="80", high="120"),
        _candle(start_ms=1_000, end_ms=2_000, low="95", high="104"),
        _candle(start_ms=2_000, end_ms=3_000, low="96", high="105"),
        _candle(start_ms=3_000, end_ms=4_000, low="97", high="103"),
        _candle(start_ms=4_000, end_ms=5_000, low="98", high="102"),
    )
    context = _context(candles_15m=candles)
    assert swing_invalidation(context, Direction.LONG) == Decimal("95")
    assert swing_invalidation(context, Direction.SHORT) == Decimal("105")


def test_wrong_side_or_insufficient_swing_invalidation_returns_none() -> None:
    short_candles = (
        _candle(start_ms=0, end_ms=1_000),
        _candle(start_ms=1_000, end_ms=2_000),
        _candle(start_ms=2_000, end_ms=3_000),
    )
    assert swing_invalidation(_context(candles_15m=short_candles), Direction.LONG) is None

    wrong_side = tuple(
        _candle(start_ms=i * 1_000, end_ms=(i + 1) * 1_000, low="101", high="110")
        for i in range(4)
    )
    assert swing_invalidation(_context(candles_15m=wrong_side), Direction.LONG) is None
