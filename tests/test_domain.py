from decimal import Decimal

import pytest

from cocomelon.domain.execution import OrderIntent, OrderSide, OrderType
from cocomelon.domain.market import (
    MarketId,
    PerpMarketContext,
    PerpMarketMeta,
    PerpMarketSnapshot,
)
from cocomelon.domain.strategy import Direction, StrategyRole, StrategySignal


def test_market_id_canonicalizes_default_and_named_dex() -> None:
    assert MarketId(dex="", coin="BTC").canonical == "BTC"
    assert MarketId(dex="xyz", coin="XYZ100").canonical == "xyz:XYZ100"


def test_market_id_from_wire_name_strips_matching_hip3_prefix() -> None:
    market = MarketId.from_wire_name("xyz", "xyz:NVDA")
    assert market == MarketId(dex="xyz", coin="NVDA")
    assert market.canonical == "xyz:NVDA"


def test_market_id_from_wire_name_rejects_mismatched_prefix() -> None:
    with pytest.raises(ValueError, match="prefix"):
        MarketId.from_wire_name("xyz", "hyna:AAPL")


def test_perp_snapshot_uses_decimal_financial_values() -> None:
    market = MarketId(dex="", coin="BTC")
    snapshot = PerpMarketSnapshot(
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
            mark_px=Decimal("65000.5"),
            mid_px=Decimal("65000.0"),
            oracle_px=Decimal("64999.5"),
            funding=Decimal("0.0000125"),
            open_interest=Decimal("1234.5"),
            day_ntl_vlm=Decimal("987654321.1"),
            premium=Decimal("0.0001"),
            prev_day_px=Decimal("64000"),
        ),
        source="hyperliquid-mainnet-info",
        received_at_ms=123456789,
        schema_version=1,
    )
    assert snapshot.context.mark_px == Decimal("65000.5")
    assert isinstance(snapshot.context.open_interest, Decimal)


def test_strategy_score_is_bounded() -> None:
    market = MarketId(dex="", coin="SOL")
    with pytest.raises(ValueError, match="score"):
        StrategySignal(
            strategy="trend",
            role=StrategyRole.PRIMARY,
            market=market,
            direction=Direction.LONG,
            score=Decimal("101"),
            timestamp_ms=1,
            reason_codes=("example",),
            feature_snapshot_id="feature-1",
            invalidation_price=Decimal("100"),
            veto_directions=(),
        )


def test_no_trade_does_not_require_invalidation() -> None:
    signal = StrategySignal(
        strategy="trend",
        role=StrategyRole.PRIMARY,
        market=MarketId(dex="", coin="ETH"),
        direction=Direction.NO_TRADE,
        score=Decimal("40"),
        timestamp_ms=1,
        reason_codes=("insufficient_edge",),
        feature_snapshot_id="feature-1",
        invalidation_price=None,
        veto_directions=(),
    )
    assert signal.direction is Direction.NO_TRADE


def test_opening_order_requires_positive_quantity() -> None:
    with pytest.raises(ValueError, match="quantity"):
        OrderIntent(
            intent_id="intent-1",
            market=MarketId(dex="", coin="BTC"),
            side=OrderSide.BUY,
            quantity=0.0,
            order_type=OrderType.MARKETABLE_IOC,
            reduce_only=False,
            limit_price=None,
            created_at_ms=1,
        )
